"""Launcher-independent native intelligence boundary.

This module is deliberately smaller than the Quattro orchestration plane.  It
owns only bounded advisory decisions and evidence for direct Codex/Pi native
sessions.  It never selects a model, grants a permission, runs a command, or
changes a host's account/session settings.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from typing import Any, Mapping

from .decision_service import DecisionSession
from .decision_taxonomy import classify_decision, validate_request
from .errors import ConfigError
from .paths import state_root, xdg_config_home
from .provider_access import typesafe_credential_status


NATIVE_SCHEMA_VERSION = 1
NATIVE_CATEGORIES = (
    "context_strategy",
    "execution_strategy",
    "validation_strategy",
    "retry_strategy",
    "progress_strategy",
)
DEFAULT_TIMEOUT_MS = 1_500
MAX_EVENTS = 5_000
RETENTION_DAYS = 30
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_STAGES = {
    "configured", "loaded", "callable", "requested", "provider_response",
    "validated", "accepted", "advice_delivered", "action_applied",
    "retrieval_requested", "retrieval_completed", "sources_selected",
    "result_returned", "context_delivery", "status_checked", "executed",
    "command_result", "index_refresh", "probe", "skipped",
}
_KINDS = {"availability", "jev", "retrieval", "rtk", "instrumentation"}


def native_config_path() -> Path:
    override = os.environ.get("QUATTRO_NATIVE_INTELLIGENCE_CONFIG")
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override))).resolve(strict=False)
    return xdg_config_home() / "quattro/native-intelligence.json"


def native_telemetry_path() -> Path:
    override = os.environ.get("QUATTRO_NATIVE_TELEMETRY_DB")
    if override:
        return Path(os.path.expandvars(os.path.expanduser(override))).resolve(strict=False)
    return state_root() / "private/native-intelligence.sqlite3"


@dataclass(frozen=True, slots=True)
class NativeSettings:
    enabled: bool = True
    categories: tuple[str, ...] = NATIVE_CATEGORIES
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    retrieval_enabled: bool = True
    rtk_enabled: bool = True
    telemetry_enabled: bool = True
    configured: bool = False
    path: Path | None = None


def load_native_settings() -> NativeSettings:
    """Read only the native settings file; never reads provider auth files."""
    path = native_config_path()
    if not path.is_file() or path.is_symlink():
        return NativeSettings(path=path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"malformed native intelligence configuration: {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError(f"native intelligence configuration must be an object: {path}")
    enabled = raw.get("enabled", True)
    if type(enabled) is not bool:
        raise ConfigError("native intelligence enabled must be a boolean")
    categories = raw.get("categories", list(NATIVE_CATEGORIES))
    if (not isinstance(categories, list)
            or any(not isinstance(value, str) for value in categories)):
        raise ConfigError("native intelligence categories must be a string array")
    selected = tuple(dict.fromkeys(value for value in categories if value in NATIVE_CATEGORIES))
    timeout = raw.get("timeoutMs", DEFAULT_TIMEOUT_MS)
    if type(timeout) is not int or not 100 <= timeout <= 3_000:
        raise ConfigError("native intelligence timeoutMs must be between 100 and 3000")
    retrieval = raw.get("retrievalEnabled", True)
    rtk = raw.get("rtkEnabled", True)
    telemetry = raw.get("telemetryEnabled", True)
    if any(type(value) is not bool for value in (retrieval, rtk, telemetry)):
        raise ConfigError("native intelligence feature flags must be booleans")
    return NativeSettings(
        enabled=enabled,
        categories=selected,
        timeout_ms=timeout,
        retrieval_enabled=retrieval,
        rtk_enabled=rtk,
        telemetry_enabled=telemetry,
        configured=True,
        path=path,
    )


def write_native_settings(*, enabled: bool | None = None) -> NativeSettings:
    """Idempotently change the native Jev switch without touching other keys."""
    path = native_config_path()
    current = load_native_settings()
    value: dict[str, Any] = {
        "schemaVersion": NATIVE_SCHEMA_VERSION,
        "enabled": current.enabled if enabled is None else bool(enabled),
        "categories": list(current.categories),
        "timeoutMs": current.timeout_ms,
        "retrievalEnabled": current.retrieval_enabled,
        "rtkEnabled": current.rtk_enabled,
        "telemetryEnabled": current.telemetry_enabled,
    }
    if path.is_file() and not path.is_symlink():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ConfigError(f"malformed native intelligence configuration: {path}: {error}") from error
        if isinstance(existing, dict):
            existing.update(value)
            value = existing
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".native-intelligence-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return load_native_settings()


def _safe_identifier(value: Any, *, default: str = "unknown") -> str:
    if isinstance(value, str) and _IDENTIFIER.fullmatch(value):
        return value
    if value is None:
        return default
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()[:20]


def project_fingerprint(directory: str | os.PathLike[str] | None) -> str | None:
    if not directory:
        return None
    try:
        value = str(Path(directory).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        value = str(directory)
    return "sha256:" + hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class NativeContext:
    host: str = "unknown"
    session_id: str = "unknown"
    project: str | None = None
    turn_id: str | None = None
    request_id: str | None = None
    tool_call_id: str | None = None
    diagnostic: bool = False
    session_enabled: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "NativeContext":
        value = value if isinstance(value, Mapping) else {}
        return cls(
            host=_safe_identifier(value.get("host"), default="unknown"),
            session_id=_safe_identifier(value.get("session_id"), default="unknown"),
            project=str(value.get("project")) if value.get("project") else None,
            turn_id=_safe_identifier(value.get("turn_id"), default="unknown") if value.get("turn_id") is not None else None,
            request_id=_safe_identifier(value.get("request_id"), default="unknown") if value.get("request_id") is not None else None,
            tool_call_id=_safe_identifier(value.get("tool_call_id"), default="unknown") if value.get("tool_call_id") is not None else None,
            diagnostic=bool(value.get("diagnostic", False)),
            session_enabled=value.get("session_enabled", True) is not False,
        )


def split_native_context(arguments: Mapping[str, Any]) -> tuple[dict[str, Any], NativeContext]:
    """Remove private adapter metadata before a decision is validated."""
    clean = dict(arguments) if isinstance(arguments, Mapping) else {}
    raw = clean.pop("__quattro_context", None)
    return clean, NativeContext.from_mapping(raw)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return "[bounded]"
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str):
            return value[:300]
        return value
    if isinstance(value, Mapping):
        return {str(key)[:50]: _json_safe(item, depth=depth + 1)
                for key, item in list(value.items())[:32]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:32]]
    return str(value)[:300]


class NativeTelemetry:
    """Best-effort local evidence store. Telemetry failures never escape."""

    def __init__(self, path: Path | None = None, *, enabled: bool = True):
        self.path = path or native_telemetry_path()
        self.enabled = enabled
        self.last_error: str | None = None

    def _connection(self, *, write: bool) -> sqlite3.Connection:
        if write:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        if write:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=2000")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS native_events (
                    event_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    host TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    request_id TEXT,
                    tool_call_id TEXT,
                    project_hash TEXT,
                    diagnostic INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS native_events_session_idx
                    ON native_events(session_id, created_at);
                CREATE INDEX IF NOT EXISTS native_events_trace_idx
                    ON native_events(trace_id, created_at);
                """
            )
        return connection

    def record(self, *, kind: str, stage: str, status: str,
               context: NativeContext, trace_id: str | None = None,
               metadata: Mapping[str, Any] | None = None) -> str:
        trace_id = _safe_identifier(trace_id, default="trace-" + uuid.uuid4().hex[:20])
        if not self.enabled:
            return trace_id
        if kind not in _KINDS or stage not in _STAGES:
            return trace_id
        event_id = uuid.uuid4().hex
        payload = _json_safe(metadata or {})
        try:
            connection = self._connection(write=True)
            try:
                connection.execute(
                    "INSERT INTO native_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (event_id, trace_id, dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
                     kind, stage, str(status)[:40], context.host, context.session_id,
                     context.turn_id, context.request_id, context.tool_call_id,
                     project_fingerprint(context.project), int(context.diagnostic),
                     json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
                )
                cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)).isoformat()
                connection.execute("DELETE FROM native_events WHERE created_at < ?", (cutoff,))
                connection.execute(
                    "DELETE FROM native_events WHERE event_id IN "
                    "(SELECT event_id FROM native_events ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                    (MAX_EVENTS,),
                )
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            self.last_error = type(error).__name__
        return trace_id

    def _read(self, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if not self.path.is_file() or self.path.is_symlink():
            return []
        try:
            connection = self._connection(write=False)
            connection.row_factory = sqlite3.Row
            try:
                return [dict(row) for row in connection.execute(query, parameters)]
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as error:
            self.last_error = type(error).__name__
            return []

    @staticmethod
    def _decode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            try:
                metadata = json.loads(row.pop("metadata_json", "{}"))
            except json.JSONDecodeError:
                metadata = {"unavailable": True}
            row["metadata"] = metadata
            row["diagnostic"] = bool(row.get("diagnostic"))
            result.append(row)
        return result

    def trace(self, session_id: str, *, limit: int = 100,
              include_diagnostics: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        predicate = "" if include_diagnostics else " AND diagnostic=0"
        rows = self._read(
            "SELECT * FROM native_events WHERE session_id=?" + predicate
            + " ORDER BY created_at DESC LIMIT ?", (_safe_identifier(session_id), limit),
        )
        return list(reversed(self._decode(rows)))

    def sessions(self, *, include_diagnostics: bool = False) -> list[dict[str, Any]]:
        predicate = "" if include_diagnostics else " AND diagnostic=0"
        rows = self._read(
            "SELECT session_id, host, MAX(created_at) AS last_activity, "
            "COUNT(*) AS events, SUM(CASE WHEN kind='jev' THEN 1 ELSE 0 END) AS jev_events, "
            "SUM(CASE WHEN kind='retrieval' THEN 1 ELSE 0 END) AS retrieval_events, "
            "SUM(CASE WHEN kind='rtk' AND stage='executed' THEN 1 ELSE 0 END) AS rtk_calls "
            "FROM native_events WHERE 1=1" + predicate
            + " GROUP BY session_id, host ORDER BY last_activity DESC", (),
        )
        return self._decode(rows)

    def lifetime(self, *, include_diagnostics: bool = False,
                 diagnostics_only: bool = False) -> list[dict[str, Any]]:
        if diagnostics_only:
            predicate = " AND diagnostic=1"
        else:
            predicate = "" if include_diagnostics else " AND diagnostic=0"
        rows = self._read(
            "SELECT kind, stage, status, COUNT(*) AS count FROM native_events "
            "WHERE 1=1" + predicate + " GROUP BY kind, stage, status ORDER BY kind, stage, status",
        )
        return self._decode(rows)

    def exists(self) -> bool:
        return self.path.is_file() and not self.path.is_symlink()


def _trace_metadata(result: Mapping[str, Any]) -> dict[str, Any]:
    timing = result.get("timing") if isinstance(result.get("timing"), Mapping) else {}
    return {
        "selectedAction": result.get("selected_action"),
        "confidence": result.get("confidence"),
        "evidence": result.get("evidence"),
        "fallbackReason": result.get("evidence") if result.get("fallback_required") else None,
        "blockingMs": timing.get("blocking_ms"),
        "providerWaitMs": timing.get("worker_roundtrip_ms"),
        "cache": result.get("cacheHit", False),
    }


def native_jev_advice(request: Mapping[str, Any], *, context: NativeContext | None = None,
                      settings: NativeSettings | None = None,
                      telemetry: NativeTelemetry | None = None,
                      decision_session: DecisionSession | None = None) -> dict[str, Any]:
    """Run one allowlisted native advisory decision, or fail open locally."""
    context = context or NativeContext()
    settings = settings or load_native_settings()
    telemetry = telemetry or NativeTelemetry(enabled=settings.telemetry_enabled)
    trace_id = "jev-" + uuid.uuid4().hex[:20]
    try:
        normalized = validate_request(dict(request))
    except Exception as error:
        reason = getattr(error, "category", "invalid_state")
        telemetry.record(kind="jev", stage="skipped", status="SKIPPED", context=context,
                         trace_id=trace_id, metadata={"reason": reason})
        return {"selected_action": None, "confidence": None, "evidence": reason,
                "fallback_required": True, "traceId": trace_id,
                "usageEvidence": {"requested": False, "providerResponse": "UNKNOWN",
                                   "validated": False, "accepted": False,
                                   "adviceDelivered": "UNVERIFIED", "actionApplied": "UNVERIFIED"}}
    category = normalized["decision_type"]
    if category not in NATIVE_CATEGORIES or classify_decision(category).value != "JEV_ELIGIBLE":
        reason = "unsupported_native_category"
        telemetry.record(kind="jev", stage="skipped", status="SKIPPED", context=context,
                         trace_id=trace_id, metadata={"reason": reason, "category": category})
        return {"selected_action": None, "confidence": None, "evidence": reason,
                "fallback_required": True, "traceId": trace_id,
                "usageEvidence": {"requested": False, "providerResponse": "UNKNOWN",
                                   "validated": False, "accepted": False,
                                   "adviceDelivered": "UNVERIFIED", "actionApplied": "UNVERIFIED"}}
    if (not settings.enabled or category not in settings.categories
            or not context.session_enabled or os.environ.get("QUATTRO_MANAGED_SESSION") == "1"):
        reason = ("disabled" if not settings.enabled else
                  "session_preference_off" if not context.session_enabled else
                  "managed_session" if os.environ.get("QUATTRO_MANAGED_SESSION") == "1" else
                  "category_disabled")
        telemetry.record(kind="jev", stage="skipped", status="SKIPPED", context=context,
                         trace_id=trace_id, metadata={"reason": reason, "category": category})
        return {"selected_action": None, "confidence": None, "evidence": reason,
                "fallback_required": True, "traceId": trace_id,
                "usageEvidence": {"requested": False, "providerResponse": "UNKNOWN",
                                   "validated": False, "accepted": False,
                                   "adviceDelivered": "UNVERIFIED", "actionApplied": "UNVERIFIED"}}
    flags = normalized["relevant_context"]
    meaningful = any(bool(flags.get(name)) for name in (
        "repository_required", "modification_required", "retrieval_required",
        "multi_step_required", "verification_required", "context_missing",
        "independent_steps", "tests_available", "changes_present",
    )) or normalized["previous_result"] != "none" or normalized["execution_state"]["attempt"] > 0
    if not meaningful and not context.diagnostic:
        telemetry.record(kind="jev", stage="skipped", status="SKIPPED", context=context,
                         trace_id=trace_id, metadata={"reason": "trivial", "category": category})
        return {"selected_action": None, "confidence": None, "evidence": "trivial",
                "fallback_required": True, "traceId": trace_id,
                "usageEvidence": {"requested": False, "providerResponse": "NOT_REQUESTED",
                                   "validated": False, "accepted": False,
                                   "adviceDelivered": "NOT_APPLICABLE", "actionApplied": "NOT_APPLICABLE"}}

    telemetry.record(kind="jev", stage="requested", status="REQUESTED", context=context,
                     trace_id=trace_id, metadata={"category": category, "diagnostic": context.diagnostic})
    owned_session = decision_session is None
    before = decision_session or DecisionSession(mode="COOPERATIVE", timeout_ms=settings.timeout_ms)
    try:
        before_counts = before.snapshot().get("counts", {})
        result = before.decide(normalized, cacheable=True)
        after_counts = before.snapshot().get("counts", {})
        provider_attempted = int(after_counts.get("calls", 0)) > int(before_counts.get("calls", 0))
        cache_hit = bool(result.get("cache_hit")) or (
            int(after_counts.get("cache_hits", 0)) > int(before_counts.get("cache_hits", 0))
        )
        response_evidence = result.get("evidence") in {
            "native_choice_probabilities", "hard_policy", "uncertain",
        }
        if cache_hit:
            telemetry.record(kind="jev", stage="provider_response", status="CACHED", context=context,
                             trace_id=trace_id, metadata={"category": category})
            telemetry.record(kind="jev", stage="validated", status="CACHED", context=context,
                             trace_id=trace_id, metadata={"category": category})
        elif provider_attempted and response_evidence:
            telemetry.record(kind="jev", stage="provider_response", status="RECEIVED", context=context,
                             trace_id=trace_id, metadata={"category": category,
                                                           "providerWaitMs": (result.get("timing") or {}).get("worker_roundtrip_ms")})
            telemetry.record(kind="jev", stage="validated", status="VALIDATED", context=context,
                             trace_id=trace_id, metadata={"category": category})
        accepted = not bool(result.get("fallback_required"))
        if accepted:
            telemetry.record(kind="jev", stage="accepted", status="ACCEPTED", context=context,
                             trace_id=trace_id, metadata=_trace_metadata(result))
            telemetry.record(kind="jev", stage="advice_delivered", status="UNVERIFIED", context=context,
                             trace_id=trace_id, metadata={"delivery": "host_boundary_unverified"})
            telemetry.record(kind="jev", stage="action_applied", status="UNVERIFIED", context=context,
                             trace_id=trace_id, metadata={"reason": "native_host_application_not_observable"})
        result = dict(result)
        result["traceId"] = trace_id
        result["usageEvidence"] = {
            "requested": True,
            "providerResponse": "CACHED" if cache_hit else "RECEIVED" if response_evidence else "NOT_RECEIVED",
            "validated": response_evidence or cache_hit,
            "accepted": accepted,
            "adviceDelivered": "UNVERIFIED" if accepted else "NOT_APPLICABLE",
            "actionApplied": "UNVERIFIED" if accepted else "NOT_APPLICABLE",
            "providerAttempted": provider_attempted,
        }
        return result
    finally:
        if owned_session:
            before.close()


def native_event(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Record a host-observable stage from a native adapter."""
    clean, context = split_native_context(arguments)
    kind = clean.get("kind")
    stage = clean.get("stage")
    status = clean.get("status", "UNKNOWN")
    trace_id = clean.get("traceId")
    if kind not in _KINDS or stage not in _STAGES:
        raise ValueError("invalid native evidence event")
    settings = load_native_settings()
    telemetry = NativeTelemetry(enabled=settings.telemetry_enabled)
    trace_id = telemetry.record(kind=kind, stage=stage, status=str(status), context=context,
                                trace_id=trace_id, metadata=clean.get("metadata", {}))
    return {"recorded": telemetry.last_error is None, "traceId": trace_id,
            "telemetryError": telemetry.last_error}


def host_version(binary: str) -> str | None:
    path = shutil.which(binary)
    if not path:
        return None
    try:
        import subprocess
        result = subprocess.run([path, "--version"], capture_output=True, text=True,
                                timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return "installed"
    line = (result.stdout or result.stderr).strip().splitlines()
    return line[0][:120] if line else "installed"


def credential_status() -> str:
    try:
        return typesafe_credential_status()
    except Exception:
        return "unavailable"
