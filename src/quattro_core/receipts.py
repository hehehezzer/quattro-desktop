"""Content-free native-client usage receipts, separate from historical telemetry."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid

from .config import Config, safe_path
from .retrieval import private_database, redact


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("invalid native identity")
    if redact(value)[1]:
        raise ValueError("credential-shaped native identity")
    return value


class Receipts:
    """Separate from historical telemetry; no queries, source content or environments."""
    def __init__(self, config: Config):
        self.path = safe_path(config.database_dir / "native-receipts.sqlite3")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_database(self.path)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS native_receipts(
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, host TEXT NOT NULL,
            session_id TEXT NOT NULL, turn_id TEXT NOT NULL, transport TEXT NOT NULL,
            project TEXT, operation TEXT NOT NULL, status TEXT NOT NULL,
            diagnostic INTEGER NOT NULL, metadata_json TEXT NOT NULL,
            delivery TEXT NOT NULL DEFAULT 'unverified', boundary TEXT, delivered_at TEXT)""")
        self.connection.commit()

    def close(self):
        self.connection.close()

    def record(self, host, request, project, operation, status, metadata):
        session = text(request.get("session_id", "unknown"))
        turn = text(request.get("turn_id", ""))
        transport = "herdr" if request.get("transport") == "herdr" else "native"
        diagnostic = request.get("diagnostic", False)
        if type(diagnostic) is not bool:
            raise ValueError("diagnostic must be boolean")
        identifier = "qi-" + uuid.uuid4().hex
        created = utc_now()
        # Metadata is constructed here by the trusted boundary, never client supplied.
        encoded = json.dumps(metadata, allow_nan=False, separators=(",", ":"))
        with self.connection:
            self.connection.execute("INSERT INTO native_receipts(id,created_at,host,session_id,turn_id,transport,project,operation,status,diagnostic,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (identifier,created,host,session,turn,transport,project,operation,status,int(diagnostic),encoded))
            self.connection.execute("DELETE FROM native_receipts WHERE created_at < ?",
                ((dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=90)).isoformat(timespec="milliseconds"),))
        return {"id":identifier,"created_at":created,"host":host,"session_id":session,"transport":transport,
                "project":project,"operation":operation,"status":status,"diagnostic":diagnostic,
                "delivery":"unverified",**metadata}

    def delivered(self, host, request):
        identifier = text(request.get("receipt_id", ""))
        session = text(request.get("session_id", "unknown"))
        boundary = text(request.get("boundary", ""), 80)
        # Only adapters with a subsequent observable host boundary may confirm delivery.
        if boundary not in {"omp_context_messages", "codex_model_input_observed"}:
            raise ValueError("unsupported delivery boundary")
        expected = "omp" if boundary.startswith("omp_") else "codex"
        if host != expected:
            raise ValueError("host and boundary disagree")
        with self.connection:
            changed = self.connection.execute("UPDATE native_receipts SET delivery='confirmed',boundary=?,delivered_at=? WHERE id=? AND host=? AND session_id=? AND status='ready'",
                (boundary,utc_now(),identifier,host,session)).rowcount
        if not changed:
            raise ValueError("matching returned receipt unavailable")
        return {"receipt_id":identifier,"delivery":"confirmed","boundary":boundary,"model_reliance":"unknown"}

    def recent(self, host, request):
        session = request.get("session_id")
        parameters = [host]
        condition = "host=?"
        if session is not None:
            condition += " AND session_id=?"
            parameters.append(text(session))
        rows = self.connection.execute("SELECT * FROM native_receipts WHERE " + condition + " ORDER BY created_at DESC LIMIT 20",parameters)
        output = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            output.append(value)
        return {"receipts":output,"model_reliance":"unknown"}
