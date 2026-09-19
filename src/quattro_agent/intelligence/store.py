"""Private, versioned storage for Quattro Intelligence evidence."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..privacy import redact_secret_text
from .review import (
    BLIND_REVIEW_SCHEMA_VERSION,
    REASON_CATEGORIES,
    RUBRIC_VERSION,
    agreement_metrics,
    deterministic_sample_order,
    public_review_item,
    sampling_bucket,
    sampling_category,
)


SCHEMA_VERSION = 3
REVIEW_SCHEMA_VERSION = 1
DATASET_SCHEMA_VERSION = "direct-delegate-dataset-v10"
FEATURE_SCHEMA_VERSION = "direct-delegate-features-v2"
VERIFIED_LABEL_SOURCES = frozenset({
    "human_verified",
    "reviewed_outcome",
    "curated_benchmark",
    "human_gold",
    "probe_gold",
    "silver",
})
HUMAN_LABEL_SOURCES = frozenset({"human_verified", "reviewed_outcome", "human_gold"})
DECISIONS = frozenset({"DIRECT", "DELEGATE"})
REVIEW_OUTCOMES = frozenset({"DIRECT", "DELEGATE", "EXCLUDE"})


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _probability(value: Any, field: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be a finite probability")
    return number


def _nonnegative_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return number


class IntelligenceStore:
    """Additive ML evidence store separate from Quattro's authoritative task DB."""

    def __init__(self, path: str | os.PathLike[str], *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self._initialize()
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextlib.contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextlib.contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._reader() as connection:
            journal = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(journal).lower() != "wal":
                raise RuntimeError(f"SQLite WAL mode is unavailable for {self.path}")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS intelligence_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS routing_records (
                    record_id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_task_id TEXT UNIQUE,
                    entrypoint TEXT NOT NULL,
                    decision_applied INTEGER NOT NULL CHECK(decision_applied IN (0,1)),
                    request_text TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    group_fingerprint TEXT NOT NULL,
                    request_redacted INTEGER NOT NULL CHECK(request_redacted IN (0,1)),
                    request_length INTEGER NOT NULL,
                    estimated_tokens INTEGER NOT NULL,
                    task_type TEXT NOT NULL,
                    complexity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    repository_present INTEGER NOT NULL CHECK(repository_present IN (0,1)),
                    project_fingerprint TEXT,
                    retrieval_required INTEGER NOT NULL CHECK(retrieval_required IN (0,1)),
                    tool_required INTEGER CHECK(tool_required IN (0,1)),
                    repository_required INTEGER NOT NULL DEFAULT 0
                        CHECK(repository_required IN (0,1)),
                    current_information_required INTEGER NOT NULL DEFAULT 0
                        CHECK(current_information_required IN (0,1)),
                    execution_required INTEGER NOT NULL DEFAULT 0
                        CHECK(execution_required IN (0,1)),
                    modification_required INTEGER NOT NULL DEFAULT 0
                        CHECK(modification_required IN (0,1)),
                    verification_required INTEGER NOT NULL DEFAULT 0
                        CHECK(verification_required IN (0,1)),
                    multi_step_required INTEGER NOT NULL DEFAULT 0
                        CHECK(multi_step_required IN (0,1)),
                    task_category TEXT NOT NULL DEFAULT 'general',
                    split_hint TEXT CHECK(split_hint IN ('train','validation','test')),
                    context_tokens INTEGER NOT NULL DEFAULT 0,
                    production_decision TEXT CHECK(production_decision IN ('DIRECT','DELEGATE')),
                    selected_worker TEXT,
                    selected_model TEXT,
                    selected_provider TEXT,
                    selected_account TEXT,
                    routing_reason TEXT,
                    production_confidence REAL,
                    alternatives_json TEXT NOT NULL DEFAULT '[]',
                    ml_prediction TEXT CHECK(ml_prediction IN ('DIRECT','DELEGATE')),
                    ml_confidence REAL,
                    ml_model_version TEXT,
                    disagreement INTEGER CHECK(disagreement IN (0,1)),
                    inference_latency_ms REAL,
                    inference_error_code TEXT,
                    tools_json TEXT NOT NULL DEFAULT '[]',
                    retrieval_used INTEGER NOT NULL DEFAULT 0 CHECK(retrieval_used IN (0,1)),
                    retrieved_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
                    retries INTEGER NOT NULL DEFAULT 0,
                    fallback_used INTEGER CHECK(fallback_used IN (0,1)),
                    execution_time_ms REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cost REAL,
                    failure_category TEXT,
                    success INTEGER CHECK(success IN (0,1)),
                    validation_status TEXT,
                    test_status TEXT,
                    build_status TEXT,
                    evaluator_result TEXT,
                    retry_outcome TEXT,
                    user_correction INTEGER CHECK(user_correction IN (0,1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS routing_records_created
                    ON routing_records(created_at, record_id);
                CREATE INDEX IF NOT EXISTS routing_records_shadow
                    ON routing_records(ml_model_version, disagreement);

                CREATE TABLE IF NOT EXISTS routing_labels (
                    record_id TEXT PRIMARY KEY REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    label TEXT NOT NULL CHECK(label IN ('DIRECT','DELEGATE')),
                    source TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'verified'
                        CHECK(review_status IN ('verified')),
                    confidence REAL NOT NULL DEFAULT 1.0
                        CHECK(confidence >= 0.0 AND confidence <= 1.0),
                    labeling_method TEXT NOT NULL DEFAULT 'legacy_verified',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS routing_labels_source
                    ON routing_labels(source, label);

                CREATE TABLE IF NOT EXISTS routing_label_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    label TEXT NOT NULL CHECK(label IN ('DIRECT','DELEGATE')),
                    source TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'verified'
                        CHECK(review_status IN ('verified')),
                    confidence REAL NOT NULL DEFAULT 1.0
                        CHECK(confidence >= 0.0 AND confidence <= 1.0),
                    labeling_method TEXT NOT NULL DEFAULT 'legacy_verified',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS routing_label_history_record
                    ON routing_label_history(record_id, history_id);

                CREATE TABLE IF NOT EXISTS routing_reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    outcome TEXT NOT NULL CHECK(outcome IN ('DIRECT','DELEGATE','EXCLUDE')),
                    source TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    review_status TEXT NOT NULL
                        CHECK(review_status IN ('verified','excluded')),
                    notes TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS routing_reviews_record
                    ON routing_reviews(record_id, review_id);
                CREATE INDEX IF NOT EXISTS routing_reviews_outcome
                    ON routing_reviews(outcome, reviewed_at);

                CREATE TABLE IF NOT EXISTS routing_adjudications (
                    adjudication_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    rubric_version TEXT NOT NULL,
                    judge_id TEXT NOT NULL,
                    verdict TEXT NOT NULL CHECK(verdict IN ('DIRECT','DELEGATE','ABSTAIN')),
                    confidence REAL NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(record_id,rubric_version,judge_id)
                );
                CREATE INDEX IF NOT EXISTS routing_adjudications_record
                    ON routing_adjudications(record_id,adjudication_id);

                CREATE TABLE IF NOT EXISTS blind_review_items (
                    item_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    record_id TEXT NOT NULL REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    request_fingerprint TEXT NOT NULL,
                    rubric_version TEXT NOT NULL,
                    sample_category TEXT NOT NULL,
                    sample_bucket TEXT NOT NULL,
                    selection_reason TEXT NOT NULL,
                    assigned_reviewer TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(batch_id,record_id)
                );
                CREATE INDEX IF NOT EXISTS blind_review_items_record
                    ON blind_review_items(record_id,item_id);
                CREATE INDEX IF NOT EXISTS blind_review_items_batch
                    ON blind_review_items(batch_id,item_id);

                CREATE TABLE IF NOT EXISTS blind_review_votes (
                    vote_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL REFERENCES blind_review_items(item_id),
                    record_id TEXT NOT NULL REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    reviewer TEXT NOT NULL,
                    verdict TEXT NOT NULL CHECK(verdict IN ('DIRECT','DELEGATE','UNCERTAIN')),
                    reason_category TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    rubric_version TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    supersedes_vote_id TEXT UNIQUE REFERENCES blind_review_votes(vote_id),
                    correction_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS blind_review_votes_record
                    ON blind_review_votes(record_id,vote_id);
                CREATE INDEX IF NOT EXISTS blind_review_votes_reviewer
                    ON blind_review_votes(reviewer,record_id);

                CREATE TABLE IF NOT EXISTS blind_review_resolution_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL REFERENCES routing_records(record_id) ON DELETE CASCADE,
                    action TEXT NOT NULL CHECK(action IN ('accepted','retracted')),
                    label TEXT CHECK(label IN ('DIRECT','DELEGATE')),
                    rubric_version TEXT NOT NULL,
                    vote_ids_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS blind_review_resolution_record
                    ON blind_review_resolution_events(record_id,event_id);

                CREATE TABLE IF NOT EXISTS dataset_versions (
                    dataset_version TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    feature_version TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_versions (
                    model_version TEXT PRIMARY KEY,
                    algorithm TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    feature_version TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            row = connection.execute(
                "SELECT value FROM intelligence_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO intelligence_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(row[0]) > SCHEMA_VERSION:
                raise RuntimeError(f"unsupported intelligence schema: {row[0]}")
            columns = {
                str(value[1])
                for value in connection.execute("PRAGMA table_info(routing_records)")
            }
            if "tool_required" not in columns:
                connection.execute(
                    "ALTER TABLE routing_records ADD COLUMN "
                    "tool_required INTEGER CHECK(tool_required IN (0,1))"
                )
            additions = {
                "repository_required": (
                    "INTEGER NOT NULL DEFAULT 0 CHECK(repository_required IN (0,1))"
                ),
                "current_information_required": (
                    "INTEGER NOT NULL DEFAULT 0 CHECK(current_information_required IN (0,1))"
                ),
                "execution_required": (
                    "INTEGER NOT NULL DEFAULT 0 CHECK(execution_required IN (0,1))"
                ),
                "modification_required": (
                    "INTEGER NOT NULL DEFAULT 0 CHECK(modification_required IN (0,1))"
                ),
                "verification_required": (
                    "INTEGER NOT NULL DEFAULT 0 CHECK(verification_required IN (0,1))"
                ),
                "multi_step_required": (
                    "INTEGER NOT NULL DEFAULT 0 CHECK(multi_step_required IN (0,1))"
                ),
                "task_category": "TEXT NOT NULL DEFAULT 'general'",
                "split_hint": "TEXT CHECK(split_hint IN ('train','validation','test'))",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE routing_records ADD COLUMN {name} {declaration}"
                    )
            label_columns = {
                str(value[1])
                for value in connection.execute("PRAGMA table_info(routing_labels)")
            }
            if "review_status" not in label_columns:
                connection.execute(
                    "ALTER TABLE routing_labels ADD COLUMN "
                    "review_status TEXT NOT NULL DEFAULT 'verified'"
                )
            if "confidence" not in label_columns:
                connection.execute(
                    "ALTER TABLE routing_labels ADD COLUMN "
                    "confidence REAL NOT NULL DEFAULT 1.0"
                )
            if "labeling_method" not in label_columns:
                connection.execute(
                    "ALTER TABLE routing_labels ADD COLUMN "
                    "labeling_method TEXT NOT NULL DEFAULT 'legacy_verified'"
                )
            history_columns = {
                str(value[1])
                for value in connection.execute(
                    "PRAGMA table_info(routing_label_history)"
                )
            }
            if "review_status" not in history_columns:
                connection.execute(
                    "ALTER TABLE routing_label_history ADD COLUMN "
                    "review_status TEXT NOT NULL DEFAULT 'verified'"
                )
            if "confidence" not in history_columns:
                connection.execute(
                    "ALTER TABLE routing_label_history ADD COLUMN "
                    "confidence REAL NOT NULL DEFAULT 1.0"
                )
            if "labeling_method" not in history_columns:
                connection.execute(
                    "ALTER TABLE routing_label_history ADD COLUMN "
                    "labeling_method TEXT NOT NULL DEFAULT 'legacy_verified'"
                )
            if row is not None and int(row[0]) < SCHEMA_VERSION:
                connection.execute(
                    "UPDATE intelligence_meta SET value = ? WHERE key = 'schema_version'",
                    (str(SCHEMA_VERSION),),
                )
            for table in ("routing_labels", "routing_label_history"):
                connection.execute(
                    f"""UPDATE {table}
                        SET labeling_method = CASE
                            WHEN source IN ('human_verified','reviewed_outcome','human_gold')
                                THEN 'legacy_exposed_review'
                            WHEN source IN ('curated_benchmark','probe_gold')
                                THEN 'probe_contract_v1'
                            WHEN source = 'silver' THEN 'silver_consensus_v1'
                            ELSE labeling_method END
                        WHERE labeling_method = 'legacy_verified'"""
                )
            connection.execute(
                """INSERT INTO intelligence_meta(key,value)
                   VALUES('review_schema_version',?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(REVIEW_SCHEMA_VERSION),),
            )
            connection.execute(
                """INSERT INTO routing_label_history(
                       record_id,label,source,review_status,confidence,labeling_method,
                       notes,created_at
                   )
                   SELECT l.record_id,l.label,l.source,l.review_status,l.confidence,
                          l.labeling_method,l.notes,l.created_at
                   FROM routing_labels l
                   WHERE NOT EXISTS (
                       SELECT 1 FROM routing_label_history h
                       WHERE h.record_id = l.record_id
                   )"""
            )
            connection.execute(
                """INSERT INTO routing_reviews(
                       record_id,outcome,source,reviewer,review_status,notes,
                       reviewed_at,imported_at
                   )
                   SELECT h.record_id,h.label,h.source,'legacy-unattributed',
                          'verified',min(h.notes),min(h.created_at),min(h.created_at)
                   FROM routing_label_history h
                   WHERE NOT EXISTS (
                       SELECT 1 FROM routing_reviews r
                       WHERE r.record_id = h.record_id
                         AND r.outcome = h.label
                         AND r.source = h.source
                   )
                   GROUP BY h.record_id,h.label,h.source"""
            )

    def metadata(self, key: str) -> str | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT value FROM intelligence_meta WHERE key = ?", (key,)
            ).fetchone()
        return str(row[0]) if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO intelligence_meta(key, value) VALUES(?,?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )

    def record_routing(self, payload: Mapping[str, Any]) -> str:
        source_task_id = payload.get("source_task_id")
        existing_id = None
        if source_task_id and not payload.get("record_id"):
            with self._reader() as connection:
                row = connection.execute(
                    "SELECT record_id FROM routing_records WHERE source_task_id = ?",
                    (source_task_id,),
                ).fetchone()
            existing_id = str(row[0]) if row else None
        record_id = str(payload.get("record_id") or existing_id or f"intel_{uuid.uuid4().hex}")
        production = payload.get("production_decision")
        ml_prediction = payload.get("ml_prediction")
        if production is not None and production not in DECISIONS:
            raise ValueError("production decision must be DIRECT or DELEGATE")
        if ml_prediction is not None and ml_prediction not in DECISIONS:
            raise ValueError("ML prediction must be DIRECT or DELEGATE")
        now = utc_now()
        values = {
            "record_id": record_id,
            "source_kind": str(payload.get("source_kind") or "runtime"),
            "source_task_id": source_task_id,
            "entrypoint": str(payload.get("entrypoint") or "unknown")[:100],
            "decision_applied": int(bool(payload.get("decision_applied", True))),
            "request_text": str(payload.get("request_text") or ""),
            "request_fingerprint": str(payload["request_fingerprint"]),
            "group_fingerprint": str(
                payload.get("group_fingerprint") or payload["request_fingerprint"]
            ),
            "request_redacted": int(bool(payload.get("request_redacted"))),
            "request_length": max(0, int(payload.get("request_length", 0))),
            "estimated_tokens": max(0, int(payload.get("estimated_tokens", 0))),
            "task_type": str(payload.get("task_type") or "unknown")[:100],
            "complexity": str(payload.get("complexity") or "unknown")[:40],
            "category": str(payload.get("category") or "general")[:40],
            "repository_present": int(bool(payload.get("repository_present"))),
            "project_fingerprint": payload.get("project_fingerprint"),
            "retrieval_required": int(bool(payload.get("retrieval_required"))),
            "tool_required": (
                None if payload.get("tool_required") is None
                else int(bool(payload.get("tool_required")))
            ),
            "repository_required": int(bool(payload.get("repository_required"))),
            "current_information_required": int(bool(
                payload.get("current_information_required")
            )),
            "execution_required": int(bool(payload.get("execution_required"))),
            "modification_required": int(bool(payload.get("modification_required"))),
            "verification_required": int(bool(payload.get("verification_required"))),
            "multi_step_required": int(bool(payload.get("multi_step_required"))),
            "task_category": str(payload.get("task_category") or "general")[:80],
            "split_hint": payload.get("split_hint"),
            "context_tokens": max(0, int(payload.get("context_tokens", 0))),
            "production_decision": production,
            "selected_worker": payload.get("selected_worker"),
            "selected_model": payload.get("selected_model"),
            "selected_provider": payload.get("selected_provider"),
            "selected_account": payload.get("selected_account"),
            "routing_reason": payload.get("routing_reason"),
            "production_confidence": _probability(
                payload.get("production_confidence"), "production_confidence"
            ),
            "alternatives_json": _json(list(payload.get("alternatives") or ())),
            "ml_prediction": ml_prediction,
            "ml_confidence": _probability(payload.get("ml_confidence"), "ml_confidence"),
            "ml_model_version": payload.get("ml_model_version"),
            "disagreement": (
                int(production != ml_prediction)
                if production is not None and ml_prediction is not None else None
            ),
            "inference_latency_ms": _nonnegative_number(
                payload.get("inference_latency_ms"), "inference_latency_ms"
            ),
            "inference_error_code": payload.get("inference_error_code"),
            "created_at": str(payload.get("created_at") or now),
            "updated_at": now,
        }
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        updates = ",".join(
            f"{name}=excluded.{name}" for name in values
            if name not in {"record_id", "created_at"}
        )
        with self._transaction(immediate=True) as connection:
            connection.execute(
                f"""INSERT INTO routing_records({columns}) VALUES({placeholders})
                    ON CONFLICT(record_id) DO UPDATE SET {updates}""",
                tuple(values.values()),
            )
        return record_id

    def update_execution(self, record_id: str, payload: Mapping[str, Any]) -> None:
        allowed = {
            "selected_worker", "selected_model", "selected_provider", "selected_account",
            "context_tokens", "inference_error_code", "execution_time_ms", "input_tokens",
            "output_tokens", "cost", "failure_category", "validation_status", "test_status",
            "build_status", "evaluator_result", "retry_outcome",
        }
        values: dict[str, Any] = {key: payload[key] for key in allowed if key in payload}
        if values.get("context_tokens") is None:
            values.pop("context_tokens", None)
        for key in ("context_tokens", "input_tokens", "output_tokens"):
            if key in values and values[key] is not None:
                values[key] = max(0, int(values[key]))
        for key in ("execution_time_ms", "cost"):
            if key in values:
                values[key] = _nonnegative_number(values[key], key)
        for key in ("retries",):
            if key in payload:
                values[key] = max(0, int(payload[key]))
        for key in ("retrieval_used", "fallback_used", "success", "user_correction"):
            if key in payload:
                values[key] = None if payload[key] is None else int(bool(payload[key]))
        if "tools" in payload:
            values["tools_json"] = _json(list(payload.get("tools") or ()))
        if "alternatives" in payload:
            values["alternatives_json"] = _json(list(payload.get("alternatives") or ()))
        if "retrieved_chunk_ids" in payload:
            values["retrieved_chunk_ids_json"] = _json(
                list(payload.get("retrieved_chunk_ids") or ())
            )
        if not values:
            return
        values["updated_at"] = utc_now()
        assignments = ",".join(f"{key} = ?" for key in values)
        with self._transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"UPDATE routing_records SET {assignments} WHERE record_id = ?",
                (*values.values(), record_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown intelligence record: {record_id}")

    def record_for_task(self, task_id: str) -> dict[str, Any] | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM routing_records WHERE source_task_id = ?", (task_id,)
            ).fetchone()
        return self._normalize_record(row) if row else None

    def record(self, record_id: str) -> dict[str, Any]:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM routing_records WHERE record_id = ?", (record_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown intelligence record: {record_id}")
        return self._normalize_record(row)

    @staticmethod
    def _normalize_record(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for key in ("alternatives_json", "tools_json", "retrieved_chunk_ids_json"):
            result[key.removesuffix("_json")] = _decode(result.pop(key), [])
        for key in (
            "request_redacted", "repository_present", "retrieval_required", "disagreement",
            "tool_required", "retrieval_used", "fallback_used", "success",
            "user_correction", "decision_applied",
            "repository_required", "current_information_required", "execution_required",
            "modification_required", "verification_required", "multi_step_required",
        ):
            if result.get(key) is not None:
                result[key] = bool(result[key])
        return result

    def list_records(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM routing_records ORDER BY created_at, record_id"
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (max(1, int(limit)),)
        with self._reader() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._normalize_record(row) for row in rows]

    def label_record(
        self,
        record_id: str,
        label: str,
        *,
        source: str,
        notes: str = "",
        reviewer: str | None = None,
        confidence: float | None = None,
        labeling_method: str | None = None,
    ) -> None:
        if label not in DECISIONS:
            raise ValueError("label must be DIRECT or DELEGATE")
        if source not in VERIFIED_LABEL_SOURCES:
            raise ValueError(f"unsupported verified label source: {source}")
        if source in HUMAN_LABEL_SOURCES and not reviewer:
            raise ValueError("human labels require explicit reviewer provenance")
        safe_notes, _redacted = redact_secret_text(notes)
        if len(safe_notes) > 2_000:
            raise ValueError("label notes exceed 2000 characters")
        safe_reviewer, _redacted = redact_secret_text(reviewer or source)
        safe_reviewer = safe_reviewer.strip()[:200]
        if not safe_reviewer:
            raise ValueError("reviewer provenance is required")
        label_confidence = _probability(
            1.0 if confidence is None else confidence, "label confidence"
        )
        method = str(labeling_method or {
            "human_verified": "manual_cli_unblinded",
            "reviewed_outcome": "manual_cli_unblinded",
            "human_gold": "manual_cli_unblinded",
            "curated_benchmark": "legacy_probe_contract",
            "probe_gold": "probe_contract",
            "silver": "silver_consensus",
        }[source])[:100]
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            record = connection.execute(
                "SELECT source_kind,production_decision,decision_applied,"
                "request_fingerprint FROM routing_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if record is None:
                raise KeyError(f"unknown intelligence record: {record_id}")
            prior_review = connection.execute(
                "SELECT outcome FROM routing_reviews WHERE record_id = ? "
                "ORDER BY review_id DESC LIMIT 1",
                (record_id,),
            ).fetchone()
            if prior_review is not None and prior_review["outcome"] == "EXCLUDE":
                raise ValueError(
                    "excluded records require a separate explicit adjudication workflow"
                )
            prior_label = connection.execute(
                "SELECT label,source,confidence,labeling_method FROM routing_labels "
                "WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if (
                prior_label is not None
                and prior_label["source"] in HUMAN_LABEL_SOURCES
            ):
                if (
                    prior_label["label"] == label
                    and prior_label["source"] == source
                    and float(prior_label["confidence"]) == label_confidence
                    and prior_label["labeling_method"] == method
                ):
                    return
                raise ValueError(
                    "human-gold labels are immutable without an explicit correction audit"
                )
            if (
                prior_label is not None
                and source in {"probe_gold", "silver"}
                and (
                    prior_label["label"] != label
                    or prior_label["source"] != source
                )
            ):
                raise ValueError("automated labels cannot rewrite existing labels")
            if source in {"curated_benchmark", "probe_gold"}:
                allowed_kinds = {
                    "curated_benchmark" if source == "curated_benchmark" else "probe_gold"
                }
                if (
                    record["source_kind"] not in allowed_kinds
                    or record["production_decision"] is not None
                    or bool(record["decision_applied"])
                ):
                    raise ValueError(
                        "probe-gold labels require an independent non-production contract record"
                    )
            if source == "silver":
                votes = connection.execute(
                    "SELECT verdict,confidence,request_fingerprint "
                    "FROM routing_adjudications WHERE record_id = ?",
                    (record_id,),
                ).fetchall()
                verdicts = {str(vote["verdict"]) for vote in votes}
                if (
                    len(votes) != 3
                    or verdicts != {label}
                    or min(float(vote["confidence"]) for vote in votes) < 0.90
                    or any(
                        vote["request_fingerprint"] != record["request_fingerprint"]
                        for vote in votes
                    )
                ):
                    raise ValueError(
                        "silver labels require three matching independent persisted votes"
                    )
            connection.execute(
                """INSERT INTO routing_labels(
                       record_id,label,source,review_status,confidence,labeling_method,
                       notes,created_at,updated_at
                   ) VALUES(?,?,?,'verified',?,?,?,?,?)
                   ON CONFLICT(record_id) DO UPDATE SET
                       label=excluded.label, source=excluded.source,
                       review_status='verified', confidence=excluded.confidence,
                       labeling_method=excluded.labeling_method, notes=excluded.notes,
                       updated_at=excluded.updated_at""",
                (
                    record_id, label, source, label_confidence, method,
                    safe_notes, now, now,
                ),
            )
            connection.execute(
                """INSERT INTO routing_label_history(
                       record_id,label,source,review_status,confidence,labeling_method,
                       notes,created_at
                   ) VALUES(?,?,?,'verified',?,?,?,?)""",
                (
                    record_id, label, source, label_confidence, method,
                    safe_notes, now,
                ),
            )
            connection.execute(
                """INSERT INTO routing_reviews(
                       record_id,outcome,source,reviewer,review_status,notes,
                       reviewed_at,imported_at
                   ) VALUES(?,?,?,?, 'verified',?,?,?)""",
                (record_id, label, source, safe_reviewer, safe_notes, now, now),
            )
            connection.execute(
                """UPDATE routing_records
                   SET user_correction = CASE
                       WHEN production_decision IS NULL THEN user_correction
                       WHEN production_decision <> ? THEN 1
                       ELSE 0 END,
                       updated_at = ?
                   WHERE record_id = ?""",
                (label, now, record_id),
            )

    def exclude_record(
        self,
        record_id: str,
        *,
        source: str,
        notes: str,
    ) -> None:
        if source not in {"silver", "probe_gold"}:
            raise ValueError("automated exclusion source must be silver or probe_gold")
        safe_notes, _redacted = redact_secret_text(notes)
        now = utc_now()
        with self._transaction(immediate=True) as connection:
            existing_label = connection.execute(
                "SELECT source FROM routing_labels WHERE record_id = ?", (record_id,)
            ).fetchone()
            if existing_label is not None:
                if existing_label["source"] in HUMAN_LABEL_SOURCES:
                    raise ValueError("human-gold labels cannot be automatically excluded")
                raise ValueError("labeled records cannot be automatically excluded")
            exists = connection.execute(
                "SELECT 1 FROM routing_records WHERE record_id = ?", (record_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(f"unknown intelligence record: {record_id}")
            prior = connection.execute(
                "SELECT outcome FROM routing_reviews WHERE record_id = ? "
                "ORDER BY review_id DESC LIMIT 1",
                (record_id,),
            ).fetchone()
            if prior is not None:
                if prior["outcome"] == "EXCLUDE":
                    return
                raise ValueError("reviewed records cannot be automatically excluded")
            connection.execute(
                """INSERT INTO routing_reviews(
                       record_id,outcome,source,reviewer,review_status,notes,
                       reviewed_at,imported_at
                   ) VALUES(?,'EXCLUDE',?,'automatic-consensus','excluded',?,?,?)""",
                (record_id, source, safe_notes[:2_000], now, now),
            )

    def record_adjudication_votes(
        self,
        record_id: str,
        *,
        rubric_version: str,
        request_fingerprint: str,
        votes: Mapping[str, Mapping[str, Any]],
    ) -> None:
        prepared: list[tuple[str, str, float]] = []
        for judge_id, vote in sorted(votes.items()):
            verdict = str(vote.get("label") or "ABSTAIN")
            confidence = float(vote.get("confidence", 0.0) or 0.0)
            if verdict not in {"DIRECT", "DELEGATE", "ABSTAIN"}:
                raise ValueError("invalid adjudication verdict")
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("invalid adjudication confidence")
            prepared.append((str(judge_id)[:100], verdict, confidence))
        with self._transaction(immediate=True) as connection:
            record = connection.execute(
                "SELECT request_fingerprint FROM routing_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if record is None:
                raise KeyError(f"unknown intelligence record: {record_id}")
            if record["request_fingerprint"] != request_fingerprint:
                raise ValueError("adjudication request fingerprint is stale")
            now = utc_now()
            for judge_id, verdict, confidence in prepared:
                existing = connection.execute(
                    """SELECT verdict,confidence,request_fingerprint
                       FROM routing_adjudications
                       WHERE record_id = ? AND rubric_version = ? AND judge_id = ?""",
                    (record_id, rubric_version, judge_id),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["verdict"] != verdict
                        or float(existing["confidence"]) != confidence
                        or existing["request_fingerprint"] != request_fingerprint
                    ):
                        raise ValueError("adjudication votes are immutable")
                    continue
                connection.execute(
                    """INSERT INTO routing_adjudications(
                           record_id,rubric_version,judge_id,verdict,confidence,
                           request_fingerprint,created_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        record_id, rubric_version, judge_id, verdict, confidence,
                        request_fingerprint, now,
                    ),
                )

    def delete_stale_probe_records(self, keep_record_ids: set[str]) -> int:
        """Remove only obsolete generated probes; human and runtime evidence is untouched."""
        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                "SELECT record_id FROM routing_records WHERE source_kind = 'probe_gold'"
            ).fetchall()
            stale = [str(row["record_id"]) for row in rows if row["record_id"] not in keep_record_ids]
            if not stale:
                return 0
            placeholders = ",".join("?" for _ in stale)
            connection.execute(
                f"DELETE FROM routing_records WHERE record_id IN ({placeholders})",
                tuple(stale),
            )
            return len(stale)

    @staticmethod
    def _active_blind_votes(
        connection: sqlite3.Connection,
        *,
        record_id: str | None = None,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT vote.* FROM blind_review_votes vote
            LEFT JOIN blind_review_votes newer
              ON newer.supersedes_vote_id = vote.vote_id
            WHERE newer.vote_id IS NULL
        """
        parameters: tuple[Any, ...] = ()
        if record_id is not None:
            query += " AND vote.record_id = ?"
            parameters = (record_id,)
        query += " ORDER BY vote.record_id,vote.reviewer,vote.vote_id"
        return connection.execute(query, parameters).fetchall()

    @staticmethod
    def _latest_resolution_event(
        connection: sqlite3.Connection,
        record_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM blind_review_resolution_events "
            "WHERE record_id = ? ORDER BY event_id DESC LIMIT 1",
            (record_id,),
        ).fetchone()

    def _reconcile_blind_resolution(
        self,
        connection: sqlite3.Connection,
        record_id: str,
    ) -> None:
        votes = self._active_blind_votes(connection, record_id=record_id)
        verdicts = [str(vote["verdict"]) for vote in votes]
        reviewer_count = len({str(vote["reviewer"]) for vote in votes})
        binary = {value for value in verdicts if value in DECISIONS}
        accepted_label = (
            next(iter(binary))
            if reviewer_count >= 2
            and len(binary) == 1
            and "UNCERTAIN" not in verdicts
            else None
        )
        latest = self._latest_resolution_event(connection, record_id)
        latest_action = str(latest["action"]) if latest is not None else None
        latest_label = str(latest["label"]) if latest is not None and latest["label"] else None
        vote_ids = [str(vote["vote_id"]) for vote in votes]
        now = utc_now()
        if accepted_label is None:
            if latest_action == "accepted":
                connection.execute(
                    """INSERT INTO blind_review_resolution_events(
                           record_id,action,label,rubric_version,vote_ids_json,reason,created_at
                       ) VALUES(?,'retracted',NULL,?,?,?,?)""",
                    (
                        record_id,
                        RUBRIC_VERSION,
                        _json(vote_ids),
                        "active blind votes no longer provide reliable consensus",
                        now,
                    ),
                )
            return
        if latest_action == "accepted" and latest_label == accepted_label:
            return
        if latest_action == "accepted" and latest_label != accepted_label:
            connection.execute(
                """INSERT INTO blind_review_resolution_events(
                       record_id,action,label,rubric_version,vote_ids_json,reason,created_at
                   ) VALUES(?,'retracted',NULL,?,?,?,?)""",
                (
                    record_id,
                    RUBRIC_VERSION,
                    _json(vote_ids),
                    "a later audited correction changed the consensus label",
                    now,
                ),
            )
        connection.execute(
            """INSERT INTO blind_review_resolution_events(
                   record_id,action,label,rubric_version,vote_ids_json,reason,created_at
               ) VALUES(?,'accepted',?,?,?,?,?)""",
            (
                record_id,
                accepted_label,
                RUBRIC_VERSION,
                _json(vote_ids),
                "two or more independent blind reviewers unanimously agreed",
                now,
            ),
        )

    def create_blind_review_batch(
        self,
        *,
        reviewer: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Create hidden item mappings and return only reviewer-safe fields."""
        safe_reviewer, _redacted = redact_secret_text(str(reviewer).strip())
        if not safe_reviewer or len(safe_reviewer) > 200:
            raise ValueError("blind review queue requires valid reviewer provenance")
        bounded_limit = max(1, min(int(limit), 500))
        batch_id = f"brb_{uuid.uuid4().hex}"
        with self._transaction(immediate=True) as connection:
            active = self._active_blind_votes(connection)
            reviewed_by_reviewer = {
                str(vote["record_id"])
                for vote in active
                if str(vote["reviewer"]) == safe_reviewer
            }
            reviewed_by_others = {
                str(vote["record_id"])
                for vote in active
                if str(vote["reviewer"]) != safe_reviewer
            }
            category_counts = Counter()
            bucket_counts = Counter()
            for vote in active:
                record = connection.execute(
                    "SELECT request_text FROM routing_records WHERE record_id = ?",
                    (vote["record_id"],),
                ).fetchone()
                if record is not None:
                    category_counts[sampling_category(str(record["request_text"]))] += 1
                    bucket_counts[sampling_bucket(str(record["request_text"]))] += 1
            rows = connection.execute(
                """SELECT * FROM routing_records
                   WHERE source_kind NOT IN ('curated_benchmark','probe_gold')
                     AND entrypoint NOT IN ('interactive','resume')
                     AND request_text <> ''
                   ORDER BY created_at,record_id"""
            ).fetchall()
            deduplicated: dict[str, dict[str, Any]] = {}
            for row in rows:
                if str(row["record_id"]) in reviewed_by_reviewer:
                    continue
                deduplicated.setdefault(str(row["request_fingerprint"]), dict(row))
            repeated_candidates = [
                row for row in deduplicated.values()
                if str(row["record_id"]) in reviewed_by_others
            ]
            fresh_candidates = [
                row for row in deduplicated.values()
                if str(row["record_id"]) not in reviewed_by_others
            ]
            repeated_target = min(len(repeated_candidates), max(1, bounded_limit // 2))
            repeated_selected = deterministic_sample_order(
                repeated_candidates,
                seed=f"{RUBRIC_VERSION}:repeat",
                category_counts=category_counts,
                bucket_counts=bucket_counts,
                limit=repeated_target,
            )
            repeated_ids = {str(row["record_id"]) for row in repeated_selected}
            disagreement_candidates = [
                row for row in fresh_candidates
                if row["production_decision"] in DECISIONS
                and row["ml_prediction"] in DECISIONS
                and row["production_decision"] != row["ml_prediction"]
            ]
            disagreement_target = min(
                len(disagreement_candidates),
                max(0, bounded_limit // 4),
            )
            disagreement_selected = deterministic_sample_order(
                disagreement_candidates,
                seed=f"{RUBRIC_VERSION}:disagreement",
                category_counts=category_counts,
                bucket_counts=bucket_counts,
                limit=disagreement_target,
            )
            selected_ids = repeated_ids | {
                str(row["record_id"]) for row in disagreement_selected
            }
            selected = repeated_selected + disagreement_selected
            selected += deterministic_sample_order(
                [
                    row for row in fresh_candidates
                    if str(row["record_id"]) not in selected_ids
                ],
                seed=f"{RUBRIC_VERSION}:fresh",
                category_counts=category_counts,
                bucket_counts=bucket_counts,
                limit=bounded_limit - len(selected),
            )
            selected.sort(key=lambda row: hashlib.sha256(
                f"{batch_id}:display:{row['record_id']}".encode("utf-8")
            ).hexdigest())
            now = utc_now()
            result: list[dict[str, Any]] = []
            for row in selected:
                item_id = f"br_{uuid.uuid4().hex}"
                category = sampling_category(str(row["request_text"]))
                bucket = sampling_bucket(str(row["request_text"]))
                selection_reason = (
                    "deterministic_shadow_disagreement"
                    if row["production_decision"] in DECISIONS
                    and row["ml_prediction"] in DECISIONS
                    and row["production_decision"] != row["ml_prediction"]
                    else f"stratified_{bucket}"
                )
                connection.execute(
                    """INSERT INTO blind_review_items(
                           item_id,batch_id,record_id,request_fingerprint,rubric_version,
                           sample_category,sample_bucket,selection_reason,
                           assigned_reviewer,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item_id,
                        batch_id,
                        row["record_id"],
                        row["request_fingerprint"],
                        RUBRIC_VERSION,
                        category,
                        bucket,
                        selection_reason,
                        safe_reviewer,
                        now,
                    ),
                )
                result.append({
                    "item_id": item_id,
                    "request_text": str(row["request_text"]),
                })
        return result

    def import_blind_review_votes(
        self,
        votes: Sequence[Mapping[str, Any]],
        *,
        reviewer: str,
    ) -> dict[str, int]:
        """Persist immutable blind votes and derive consensus without overwriting history."""
        safe_reviewer, _redacted = redact_secret_text(str(reviewer).strip())
        if not safe_reviewer or len(safe_reviewer) > 200:
            raise ValueError("blind review import requires valid reviewer provenance")
        prepared: list[tuple[
            str, str, str | None, str, str, str, dict[str, bool]
        ]] = []
        for index, vote in enumerate(votes):
            item_id = str(vote.get("item_id") or "")
            verdict = str(vote.get("verdict") or "").upper()
            reason = vote.get("reason_category")
            note, _redacted = redact_secret_text(str(vote.get("note") or ""))
            reviewed_at = str(vote.get("reviewed_at") or "")
            visible_request = str(vote.get("visible_request") or "")
            visible_requirements = vote.get("visible_requirements")
            if not item_id or verdict not in {"DIRECT", "DELEGATE", "UNCERTAIN"}:
                raise ValueError(f"blind review vote {index} is invalid")
            if reason is not None:
                reason = str(reason)
                if reason not in REASON_CATEGORIES:
                    raise ValueError(
                        f"blind review vote {index} has an invalid reason category"
                    )
            if len(note) > 2_000:
                raise ValueError(f"blind review vote {index} note exceeds 2000 characters")
            if not visible_request or not isinstance(visible_requirements, Mapping):
                raise ValueError(
                    f"blind review vote {index} is missing reviewer-visible evidence"
                )
            try:
                parsed = dt.datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"blind review vote {index} timestamp is invalid") from error
            if parsed.tzinfo is None:
                raise ValueError(f"blind review vote {index} timestamp requires a timezone")
            prepared.append((
                item_id,
                verdict,
                reason,
                note,
                parsed.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds"),
                visible_request,
                {str(key): bool(value) for key, value in visible_requirements.items()},
            ))
        imported = 0
        skipped = 0
        affected: set[str] = set()
        with self._transaction(immediate=True) as connection:
            resolved: list[tuple[
                sqlite3.Row,
                tuple[str, str, str | None, str, str, str, dict[str, bool]],
            ]] = []
            pending_reviewer_records: set[tuple[str, str]] = set()
            for index, vote in enumerate(prepared):
                item = connection.execute(
                    "SELECT * FROM blind_review_items WHERE item_id = ?",
                    (vote[0],),
                ).fetchone()
                if item is None:
                    raise KeyError(f"unknown blind review item: {vote[0]}")
                if str(item["assigned_reviewer"]) != safe_reviewer:
                    raise ValueError(f"blind review vote {index} reviewer does not match assignment")
                record = connection.execute(
                    "SELECT request_fingerprint,request_text FROM routing_records "
                    "WHERE record_id = ?",
                    (item["record_id"],),
                ).fetchone()
                if record is None or record["request_fingerprint"] != item["request_fingerprint"]:
                    raise ValueError(f"blind review vote {index} item mapping is stale")
                expected_visible = public_review_item(
                    str(item["item_id"]),
                    str(record["request_text"]),
                )
                if (
                    vote[5] != expected_visible["request"]
                    or vote[6] != expected_visible["requirements"]
                ):
                    raise ValueError(
                        f"blind review vote {index} reviewer-visible evidence was altered"
                    )
                reviewer_record = (safe_reviewer, str(item["record_id"]))
                if reviewer_record in pending_reviewer_records:
                    raise ValueError(
                        "blind review import contains duplicate reviewer votes for one record"
                    )
                existing = connection.execute(
                    """SELECT current.verdict,current.reason_category,current.note,
                              current.reviewed_at
                       FROM blind_review_votes current
                       LEFT JOIN blind_review_votes newer
                         ON newer.supersedes_vote_id = current.vote_id
                       WHERE current.record_id = ? AND current.reviewer = ?
                         AND newer.vote_id IS NULL
                       ORDER BY current.imported_at DESC,current.vote_id DESC LIMIT 1""",
                    (item["record_id"], safe_reviewer),
                ).fetchone()
                if existing is not None:
                    if tuple(existing)[:3] == (vote[1], vote[2], vote[3]):
                        skipped += 1
                        continue
                    raise ValueError("blind review votes are immutable; use correction flow")
                resolved.append((item, vote))
                pending_reviewer_records.add(reviewer_record)
            now = utc_now()
            for item, vote in resolved:
                vote_id = f"brv_{uuid.uuid4().hex}"
                connection.execute(
                    """INSERT INTO blind_review_votes(
                           vote_id,item_id,record_id,reviewer,verdict,reason_category,note,
                           rubric_version,reviewed_at,imported_at,supersedes_vote_id,
                           correction_reason
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL)""",
                    (
                        vote_id,
                        vote[0],
                        item["record_id"],
                        safe_reviewer,
                        vote[1],
                        vote[2],
                        vote[3],
                        item["rubric_version"],
                        vote[4],
                        now,
                    ),
                )
                affected.add(str(item["record_id"]))
                imported += 1
            for record_id in sorted(affected):
                self._reconcile_blind_resolution(connection, record_id)
        return {"imported": imported, "skipped": skipped}

    def correct_blind_review_vote(
        self,
        vote_id: str,
        *,
        reviewer: str,
        verdict: str,
        reason_category: str | None,
        note: str,
        correction_reason: str,
    ) -> str:
        """Append an audited correction; the original vote remains immutable."""
        safe_reviewer, _redacted = redact_secret_text(str(reviewer).strip())
        safe_note, _redacted = redact_secret_text(str(note))
        safe_reason, _redacted = redact_secret_text(str(correction_reason).strip())
        verdict = str(verdict).upper()
        if verdict not in {"DIRECT", "DELEGATE", "UNCERTAIN"}:
            raise ValueError("blind review correction has an invalid verdict")
        if reason_category is not None and reason_category not in REASON_CATEGORIES:
            raise ValueError("blind review correction has an invalid reason category")
        if not safe_reason or len(safe_reason) > 2_000:
            raise ValueError("blind review correction requires a bounded reason")
        with self._transaction(immediate=True) as connection:
            original = connection.execute(
                "SELECT * FROM blind_review_votes WHERE vote_id = ?",
                (vote_id,),
            ).fetchone()
            if original is None:
                raise KeyError(f"unknown blind review vote: {vote_id}")
            if str(original["reviewer"]) != safe_reviewer:
                raise ValueError("only the original reviewer can correct a blind vote")
            if connection.execute(
                "SELECT 1 FROM blind_review_votes WHERE supersedes_vote_id = ?",
                (vote_id,),
            ).fetchone() is not None:
                raise ValueError("blind review vote already has a correction")
            replacement = f"brv_{uuid.uuid4().hex}"
            now = utc_now()
            connection.execute(
                """INSERT INTO blind_review_votes(
                       vote_id,item_id,record_id,reviewer,verdict,reason_category,note,
                       rubric_version,reviewed_at,imported_at,supersedes_vote_id,
                       correction_reason
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    replacement,
                    original["item_id"],
                    original["record_id"],
                    safe_reviewer,
                    verdict,
                    reason_category,
                    safe_note[:2_000],
                    original["rubric_version"],
                    now,
                    now,
                    vote_id,
                    safe_reason,
                ),
            )
            self._reconcile_blind_resolution(connection, str(original["record_id"]))
        return replacement

    def blind_human_resolutions(self) -> dict[str, dict[str, Any]]:
        """Return only currently accepted blind consensus labels."""
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT event.* FROM blind_review_resolution_events event
                   JOIN (
                       SELECT record_id,max(event_id) AS event_id
                       FROM blind_review_resolution_events GROUP BY record_id
                   ) latest USING(record_id,event_id)
                   WHERE event.action = 'accepted'"""
            ).fetchall()
        return {str(row["record_id"]): dict(row) for row in rows}

    def blind_review_audit(self) -> dict[str, Any]:
        with self._reader() as connection:
            votes = [dict(row) for row in self._active_blind_votes(connection)]
            items = connection.execute(
                "SELECT record_id,sample_category,sample_bucket,selection_reason "
                "FROM blind_review_items ORDER BY item_id"
            ).fetchall()
            resolutions = self.blind_human_resolutions()
            legacy_labels = {
                str(row["record_id"]): str(row["label"])
                for row in connection.execute(
                    "SELECT record_id,label FROM routing_labels "
                    "WHERE labeling_method = 'legacy_exposed_review'"
                ).fetchall()
            }
            stale_item_mappings = int(connection.execute(
                """SELECT count(*) FROM blind_review_items item
                   JOIN routing_records record USING(record_id)
                   WHERE item.request_fingerprint <> record.request_fingerprint
                      OR item.rubric_version <> ?""",
                (RUBRIC_VERSION,),
            ).fetchone()[0])
        verdict_balance = Counter(str(vote["verdict"]) for vote in votes)
        reviewer_balance = Counter(str(vote["reviewer"]) for vote in votes)
        category_balance = Counter(str(row["sample_category"]) for row in items)
        selection_balance = Counter(str(row["selection_reason"]) for row in items)
        votes_by_record: dict[str, list[dict[str, Any]]] = {}
        for vote in votes:
            votes_by_record.setdefault(str(vote["record_id"]), []).append(vote)
        active_reviewer_records = Counter(
            (str(vote["record_id"]), str(vote["reviewer"])) for vote in votes
        )
        duplicate_active_reviewer_records = sum(
            count > 1 for count in active_reviewer_records.values()
        )
        invalid_vote_rubrics = sum(
            str(vote["rubric_version"]) != RUBRIC_VERSION for vote in votes
        )
        disagreement_by_category: Counter[str] = Counter()
        boundary_disagreements = 0
        with self._reader() as connection:
            for record_id, record_votes in votes_by_record.items():
                verdicts = {str(vote["verdict"]) for vote in record_votes}
                if len(record_votes) < 2 or len(verdicts) == 1:
                    continue
                record = connection.execute(
                    "SELECT request_text FROM routing_records WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
                if record is None:
                    continue
                category = sampling_category(str(record["request_text"]))
                disagreement_by_category[category] += 1
                if sampling_bucket(str(record["request_text"])) == "boundary":
                    boundary_disagreements += 1
        return {
            "rubricVersion": RUBRIC_VERSION,
            "activeVoteCount": len(votes),
            "reviewedRecordCount": len(votes_by_record),
            "verdictBalance": dict(sorted(verdict_balance.items())),
            "reviewerBalance": dict(sorted(reviewer_balance.items())),
            "acceptedHumanGoldCount": len(resolutions),
            "acceptedHumanGoldClassBalance": dict(sorted(Counter(
                str(value["label"]) for value in resolutions.values()
            ).items())),
            "agreement": agreement_metrics(votes),
            "sampleCategoryBalance": dict(sorted(category_balance.items())),
            "selectionReasonBalance": dict(sorted(selection_balance.items())),
            "disagreementByCategory": dict(sorted(disagreement_by_category.items())),
            "boundaryDisagreementCount": boundary_disagreements,
            "legacyComparison": {
                "comparableCount": sum(
                    record_id in legacy_labels for record_id in resolutions
                ),
                "matchingCount": sum(
                    record_id in legacy_labels
                    and legacy_labels[record_id] == str(value["label"])
                    for record_id, value in resolutions.items()
                ),
                "mismatchingCount": sum(
                    record_id in legacy_labels
                    and legacy_labels[record_id] != str(value["label"])
                    for record_id, value in resolutions.items()
                ),
                "legacyLabelsUsedAsTargets": False,
            },
            "integrity": {
                "passed": not (
                    stale_item_mappings
                    or duplicate_active_reviewer_records
                    or invalid_vote_rubrics
                ),
                "staleItemMappingCount": stale_item_mappings,
                "duplicateActiveReviewerRecordCount": (
                    duplicate_active_reviewer_records
                ),
                "invalidRubricVoteCount": invalid_vote_rubrics,
                "visibleEvidenceBoundAtImport": True,
            },
        }

    def apply_review_labels(self, reviews: list[Mapping[str, Any]]) -> dict[str, int]:
        prepared: list[tuple[str, str, str, str, str, str, str, str]] = []
        for index, review in enumerate(reviews):
            record_id = str(review.get("record_id") or "")
            fingerprint = str(review.get("request_fingerprint") or "")
            outcome = str(review.get("outcome") or review.get("label") or "").upper()
            if outcome in {"AMBIGUOUS", "AMBIGUOUS / EXCLUDE"}:
                outcome = "EXCLUDE"
            source = str(review.get("source") or "")
            reviewer = str(review.get("reviewer") or "").strip()
            reviewed_at = str(review.get("reviewed_at") or "").strip()
            if not record_id or not fingerprint or outcome not in REVIEW_OUTCOMES:
                raise ValueError(f"review {index} has invalid identity or outcome")
            if source not in {"human_verified", "reviewed_outcome"}:
                raise ValueError(f"review {index} has an invalid source")
            if not reviewer or len(reviewer) > 200:
                raise ValueError(f"review {index} is missing valid reviewer provenance")
            try:
                parsed_reviewed_at = dt.datetime.fromisoformat(
                    reviewed_at.replace("Z", "+00:00")
                )
            except ValueError as error:
                raise ValueError(f"review {index} has an invalid review timestamp") from error
            if parsed_reviewed_at.tzinfo is None:
                raise ValueError(f"review {index} review timestamp must include a timezone")
            safe_reviewer, _redacted = redact_secret_text(reviewer)
            safe_notes, _redacted = redact_secret_text(str(review.get("notes") or ""))
            labeling_method = str(
                review.get("labeling_method") or "legacy_exposed_review"
            )[:100]
            if len(safe_notes) > 2_000:
                raise ValueError(f"review {index} notes exceed 2000 characters")
            prepared.append((
                record_id,
                fingerprint,
                outcome,
                source,
                safe_reviewer,
                safe_notes,
                parsed_reviewed_at.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds"),
                labeling_method,
            ))
        now = utc_now()
        imported = 0
        excluded = 0
        skipped = 0
        with self._transaction(immediate=True) as connection:
            pending: list[tuple[str, str, str, str, str, str, str]] = []
            for index, (
                record_id,
                fingerprint,
                outcome,
                source,
                reviewer,
                notes,
                reviewed_at,
                labeling_method,
            ) in enumerate(prepared):
                record = connection.execute(
                    "SELECT request_fingerprint,source_kind FROM routing_records WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
                if record is None:
                    raise KeyError(f"unknown intelligence record: {record_id}")
                if record["source_kind"] == "curated_benchmark":
                    raise ValueError("review-import cannot relabel curated benchmark rows")
                if record["request_fingerprint"] != fingerprint:
                    raise ValueError(f"review {index} request fingerprint is stale or mismatched")
                existing = connection.execute(
                    "SELECT outcome,source,reviewer FROM routing_reviews "
                    "WHERE record_id = ? ORDER BY review_id DESC LIMIT 1",
                    (record_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["outcome"] == outcome
                        and existing["source"] == source
                        and existing["reviewer"] == reviewer
                    ):
                        skipped += 1
                        continue
                    raise ValueError(f"review {index} targets a record that is already reviewed")
                pending.append((
                    record_id, outcome, source, reviewer, notes, reviewed_at,
                    labeling_method,
                ))
            for (
                record_id, outcome, source, reviewer, notes, reviewed_at,
                labeling_method,
            ) in pending:
                review_status = "excluded" if outcome == "EXCLUDE" else "verified"
                connection.execute(
                    """INSERT INTO routing_reviews(
                           record_id,outcome,source,reviewer,review_status,notes,
                           reviewed_at,imported_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        record_id,
                        outcome,
                        source,
                        reviewer,
                        review_status,
                        notes,
                        reviewed_at,
                        now,
                    ),
                )
                if outcome == "EXCLUDE":
                    excluded += 1
                    continue
                connection.execute(
                    """INSERT INTO routing_labels(
                           record_id,label,source,review_status,confidence,labeling_method,
                           notes,created_at,updated_at
                       ) VALUES(?,?,?,'verified',1.0,?,?,?,?)""",
                    (
                        record_id, outcome, source, labeling_method,
                        notes, now, now,
                    ),
                )
                connection.execute(
                    """INSERT INTO routing_label_history(
                           record_id,label,source,review_status,confidence,labeling_method,
                           notes,created_at
                       ) VALUES(?,?,?,'verified',1.0,?,?,?)""",
                    (record_id, outcome, source, labeling_method, notes, now),
                )
                connection.execute(
                    """UPDATE routing_records
                       SET user_correction = CASE
                           WHEN production_decision IS NULL THEN user_correction
                           WHEN production_decision <> ? THEN 1
                           ELSE 0 END,
                           updated_at = ?
                       WHERE record_id = ?""",
                    (outcome, now, record_id),
                )
                imported += 1
        return {"imported": imported, "excluded": excluded, "skipped": skipped}

    def labeled_records(self) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT r.*, l.label AS verified_label, l.source AS label_source,
                          l.review_status AS review_status,
                          l.confidence AS label_confidence,
                          l.labeling_method AS labeling_method,
                          l.notes AS label_notes
                   FROM routing_records r JOIN routing_labels l USING(record_id)
                   ORDER BY r.created_at, r.record_id"""
            ).fetchall()
        return [self._normalize_record(row) for row in rows]

    def record_label(self, record_id: str) -> dict[str, Any] | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT label,source,review_status,confidence,labeling_method,notes,"
                "created_at,updated_at "
                "FROM routing_labels WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        return dict(row) if row else None

    def latest_reviews(self) -> dict[str, dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                """SELECT r.* FROM routing_reviews r
                   JOIN (
                       SELECT record_id,max(review_id) AS review_id
                       FROM routing_reviews GROUP BY record_id
                   ) latest USING(record_id,review_id)"""
            ).fetchall()
        return {str(row["record_id"]): dict(row) for row in rows}

    def review_audit(self) -> dict[str, Any]:
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT record_id,outcome,reviewer,review_status FROM routing_reviews "
                "ORDER BY record_id,review_id"
            ).fetchall()
            eligible = int(connection.execute(
                """SELECT count(*) FROM routing_records r
                   WHERE r.source_kind <> 'curated_benchmark'
                     AND r.production_decision IS NOT NULL
                     AND r.entrypoint NOT IN ('interactive','resume')"""
            ).fetchone()[0])
            finalized_eligible = int(connection.execute(
                """SELECT count(DISTINCT review.record_id)
                   FROM routing_reviews review
                   JOIN routing_records record USING(record_id)
                   WHERE record.source_kind <> 'curated_benchmark'
                     AND record.production_decision IS NOT NULL
                     AND record.entrypoint NOT IN ('interactive','resume')"""
            ).fetchone()[0])
        by_record: dict[str, list[sqlite3.Row]] = {}
        reviewer_balance: dict[str, int] = {}
        for row in rows:
            by_record.setdefault(str(row["record_id"]), []).append(row)
            reviewer = str(row["reviewer"])
            reviewer_balance[reviewer] = reviewer_balance.get(reviewer, 0) + 1
        binary_conflicts = 0
        disagreements = 0
        repeated = 0
        latest_outcomes: dict[str, int] = {}
        for record_reviews in by_record.values():
            outcomes = {str(row["outcome"]) for row in record_reviews}
            binary = outcomes & DECISIONS
            binary_conflicts += len(binary) > 1
            disagreements += len(outcomes) > 1
            repeated += len(record_reviews) > 1
            latest = str(record_reviews[-1]["outcome"])
            latest_outcomes[latest] = latest_outcomes.get(latest, 0) + 1
        return {
            "reviewCount": len(rows),
            "finalizedRecordCount": len(by_record),
            "latestOutcomeBalance": dict(sorted(latest_outcomes.items())),
            "excludedRecordCount": latest_outcomes.get("EXCLUDE", 0),
            "binaryConflictRecordCount": binary_conflicts,
            "reviewerDisagreementRecordCount": disagreements,
            "repeatedReviewRecordCount": repeated,
            "reviewerBalance": dict(sorted(reviewer_balance.items())),
            "missingReviewerProvenanceCount": reviewer_balance.get(
                "legacy-unattributed", 0
            ),
            "timestampedReviewCount": len(rows),
            "eligibleRecordCount": eligible,
            "remainingRecordCount": max(0, eligible - finalized_eligible),
        }

    def review_queue(
        self,
        *,
        limit: int = 50,
        production_decision: str | None = None,
    ) -> list[dict[str, Any]]:
        if production_decision is not None and production_decision not in DECISIONS:
            raise ValueError("production decision must be DIRECT or DELEGATE")
        query = """
            SELECT r.* FROM routing_records r
            LEFT JOIN routing_reviews review USING(record_id)
            WHERE review.record_id IS NULL
              AND r.source_kind <> 'curated_benchmark'
              AND r.production_decision IS NOT NULL
              AND r.entrypoint NOT IN ('interactive', 'resume')
        """
        parameters: list[Any] = []
        if production_decision is not None:
            query += " AND r.production_decision = ?"
            parameters.append(production_decision)
        query += """ ORDER BY
            CASE r.category
                WHEN 'research' THEN 0
                WHEN 'reasoning' THEN 1
                WHEN 'general' THEN 2
                WHEN 'coding' THEN 3
                ELSE 4
            END,
            CASE r.complexity
                WHEN 'low' THEN 0
                WHEN 'medium' THEN 1
                WHEN 'high' THEN 2
                ELSE 3
            END,
            r.retrieval_required DESC,
            r.created_at DESC,
            r.record_id DESC LIMIT ?"""
        parameters.append(max(1, min(int(limit), 500)))
        with self._reader() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._normalize_record(row) for row in rows]

    def save_dataset_manifest(self, version: str, manifest: Mapping[str, Any]) -> None:
        canonical = dict(manifest)
        canonical.pop("datasetPath", None)
        canonical.pop("manifestPath", None)
        canonical.pop("splitManifestPath", None)
        with self._transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT manifest_json FROM dataset_versions WHERE dataset_version = ?",
                (version,),
            ).fetchone()
            if existing is not None:
                prior = _decode(str(existing[0]), {})
                if isinstance(prior, dict):
                    prior.pop("datasetPath", None)
                    prior.pop("manifestPath", None)
                    prior.pop("splitManifestPath", None)
                if prior != canonical:
                    raise ValueError(f"dataset manifest is immutable: {version}")
                return
            connection.execute(
                """INSERT INTO dataset_versions(
                       dataset_version,schema_version,feature_version,manifest_json,created_at
                   ) VALUES(?,?,?,?,?)""",
                (
                    version, DATASET_SCHEMA_VERSION, FEATURE_SCHEMA_VERSION,
                    _json(canonical), utc_now(),
                ),
            )

    def dataset_manifest(self, version: str) -> dict[str, Any]:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT manifest_json FROM dataset_versions WHERE dataset_version = ?",
                (version,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown dataset version: {version}")
        value = _decode(str(row[0]), {})
        if not isinstance(value, dict):
            raise ValueError("stored dataset manifest is invalid")
        return value

    def register_model(
        self,
        *,
        model_version: str,
        algorithm: str,
        dataset_version: str,
        artifact_path: Path,
        metrics: Mapping[str, Any],
        status: str = "offline",
    ) -> None:
        with self._transaction(immediate=True) as connection:
            candidate = (
                algorithm,
                dataset_version,
                FEATURE_SCHEMA_VERSION,
                str(artifact_path),
                _json(dict(metrics)),
                status,
            )
            existing = connection.execute(
                "SELECT algorithm,dataset_version,feature_version,artifact_path,"
                "metrics_json,status FROM model_versions WHERE model_version = ?",
                (model_version,),
            ).fetchone()
            if existing is not None:
                if tuple(existing)[:4] + tuple(existing)[5:] != candidate[:4] + candidate[5:]:
                    raise ValueError(f"model registry entry is immutable: {model_version}")
                return
            connection.execute(
                """INSERT INTO model_versions(
                       model_version,algorithm,dataset_version,feature_version,
                       artifact_path,metrics_json,status,created_at
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (model_version, *candidate, utc_now()),
            )

    def activate_shadow_model(self, model_version: str) -> None:
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT artifact_path FROM model_versions WHERE model_version = ?",
                (model_version,),
            ).fetchone()
            artifact = Path(str(row[0])) if row else None
            if row is None or artifact is None or artifact.is_symlink() or not artifact.is_file():
                raise KeyError(f"model artifact is unavailable: {model_version}")
            connection.execute("UPDATE model_versions SET status = 'offline' WHERE status = 'shadow'")
            connection.execute(
                "UPDATE model_versions SET status = 'shadow' WHERE model_version = ?",
                (model_version,),
            )
            connection.execute(
                """INSERT INTO intelligence_meta(key,value) VALUES('active_shadow_model',?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (model_version,),
            )

    def active_shadow_model(self) -> dict[str, Any] | None:
        version = self.metadata("active_shadow_model")
        if not version:
            return None
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM model_versions WHERE model_version = ?", (version,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metrics"] = _decode(result.pop("metrics_json"), {})
        return result

    def status(self) -> dict[str, Any]:
        with self._reader() as connection:
            record_count = int(connection.execute("SELECT count(*) FROM routing_records").fetchone()[0])
            label_count = int(connection.execute("SELECT count(*) FROM routing_labels").fetchone()[0])
            shadow_count = int(connection.execute(
                "SELECT count(*) FROM routing_records WHERE ml_prediction IS NOT NULL"
            ).fetchone()[0])
            disagreements = int(connection.execute(
                "SELECT count(*) FROM routing_records WHERE disagreement = 1"
            ).fetchone()[0])
            datasets = int(connection.execute("SELECT count(*) FROM dataset_versions").fetchone()[0])
            models = int(connection.execute("SELECT count(*) FROM model_versions").fetchone()[0])
            excluded = int(connection.execute(
                """SELECT count(*) FROM routing_reviews r
                   JOIN (
                       SELECT record_id,max(review_id) AS review_id
                       FROM routing_reviews GROUP BY record_id
                   ) latest USING(record_id,review_id)
                   WHERE r.outcome = 'EXCLUDE'"""
            ).fetchone()[0])
        return {
            "schemaVersion": SCHEMA_VERSION,
            "reviewSchemaVersion": REVIEW_SCHEMA_VERSION,
            "blindReviewSchemaVersion": BLIND_REVIEW_SCHEMA_VERSION,
            "datasetSchemaVersion": DATASET_SCHEMA_VERSION,
            "featureSchemaVersion": FEATURE_SCHEMA_VERSION,
            "records": record_count,
            "verifiedLabels": label_count,
            "excludedReviews": excluded,
            "shadowPredictions": shadow_count,
            "shadowDisagreements": disagreements,
            "datasets": datasets,
            "models": models,
            "activeShadowModel": self.metadata("active_shadow_model"),
        }
