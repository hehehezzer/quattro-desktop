"""Content-free native-client usage receipts, separate from historical telemetry."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import uuid

from .config import Config, safe_path
from .errors import InvalidRequestError, PermissionDeniedError
from .retrieval import private_database, redact


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise InvalidRequestError("invalid native identity")
    if redact(value)[1]:
        raise InvalidRequestError("credential-shaped native identity")
    return value


def source_scope(config, operation, project, arguments):
    """Resolve scope before execution; carry it unchanged through every receipt."""
    if operation == "index_source":
        source = config.source(arguments.get("source_id"))
        return [source.id] if source.intent != "excluded" else []
    if operation not in {"context", "search_knowledge", "get_project_context", "get_index_status"}:
        return []
    sources = [s for s in config.sources if s.project == project]
    selected = arguments.get("source_ids")
    if selected is not None:
        if not isinstance(selected, list) or any(not isinstance(s, str) for s in selected):
            raise InvalidRequestError("invalid source scope")
        if set(selected) - {s.id for s in sources}:
            raise PermissionDeniedError("source scope is not authorized")
        sources = [s for s in sources if s.id in selected]
    return [s.id for s in sources if s.intent != "excluded"]


def scope_allowed(config, project, metadata):
    scope = metadata.get("authorized_scope", [project] if project else [])
    if set(scope) - set(config.projects):
        return False
    registered = {s.id for s in config.sources}
    coverage = {s["source_id"] for s in metadata.get("sources", []) if s.get("source_id")}
    if coverage - registered:
        return False
    allowed = {s.id for s in config.sources if s.intent != "excluded"}
    sources = set(metadata.get("authorized_sources", []))
    sources.update(s["source_id"] for s in metadata.get("selected_results", []) if s.get("source_id"))
    return not (sources - allowed)


class Receipts:
    """Separate from historical telemetry; no queries, source content or environments."""
    def __init__(self, config: Config):
        self.config = config
        self.path = safe_path(config.database_dir / "native-receipts.sqlite3")
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
        if project is not None:
            self.config.authorize(project)
        session = text(request.get("session_id", "unknown"))
        turn = text(request.get("turn_id", ""))
        transport = "herdr" if request.get("transport") == "herdr" else "native"
        diagnostic = request.get("diagnostic", False)
        if type(diagnostic) is not bool:
            raise InvalidRequestError("diagnostic must be boolean")
        identifier = "qi-" + uuid.uuid4().hex
        retrieval = operation in {"context", "search_knowledge", "get_project_context", "recall_memory"}
        metadata = {**metadata, "stages": {
            "request_received":True, "scope_resolved":project is not None or bool(metadata.get("authorized_scope")),
            "retrieval_attempted":retrieval and (project is not None or bool(metadata.get("authorized_scope"))),
            "evidence_found":metadata.get("result_count", 0) > 0,
            "context_selected":status == "ready" and retrieval,
            "client_accepted":"not_observed", "answer_cited":"not_observed",
        }}
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

    def delivered(self, host, request, outcome="confirmed"):
        identifier = text(request.get("receipt_id", ""))
        session = text(request.get("session_id", "unknown"))
        boundary = text(request.get("boundary", ""), 80)
        allowed = {"confirmed":{"omp_context_messages":"omp","codex_model_input_observed":"codex"},
                   "submitted":{"codex_hook_stdout":"codex"}, "failed":{"omp_context_messages":"omp","codex_hook_stdout":"codex"}}
        if outcome not in allowed or allowed[outcome].get(boundary) != host:
            raise InvalidRequestError("unsupported host delivery boundary")
        row = self.connection.execute("SELECT project,metadata_json FROM native_receipts WHERE id=? AND host=? AND session_id=?",
                                      (identifier,host,session)).fetchone()
        if row is None:
            raise InvalidRequestError("matching returned receipt unavailable")
        metadata = json.loads(row["metadata_json"])
        if not scope_allowed(self.config, row["project"], metadata):
            raise PermissionDeniedError("receipt scope is not authorized")
        placeholders = ",".join("?" for _ in self.config.projects)
        with self.connection:
            changed = self.connection.execute(f"""UPDATE native_receipts SET delivery=?,boundary=?,delivered_at=?
                WHERE id=? AND host=? AND session_id=? AND status='ready'
                AND delivery IN ('unverified','submitted')
                AND (project IS NULL OR project IN ({placeholders}))""",
                (outcome,boundary,utc_now(),identifier,host,session,*self.config.projects)).rowcount
        if not changed:
            raise InvalidRequestError("matching returned receipt unavailable")
        return {"receipt_id":identifier,"delivery":outcome,"boundary":boundary,
                "client_accepted":"not_observed","answer_cited":"not_observed","model_reliance":"unknown"}

    def recent(self, host, request):
        session = request.get("session_id")
        parameters = [host, *self.config.projects]
        condition = "host=? AND (project IS NULL OR project IN (" + ",".join("?" for _ in self.config.projects) + "))"
        if session is not None:
            condition += " AND session_id=?"
            parameters.append(text(session))
        rows = self.connection.execute("SELECT * FROM native_receipts WHERE " + condition + " ORDER BY created_at DESC,rowid DESC LIMIT 20",parameters)
        output = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            if not scope_allowed(self.config, value["project"], value["metadata"]):
                continue
            output.append(value)
        return {"receipts":output,"model_reliance":"unknown"}
