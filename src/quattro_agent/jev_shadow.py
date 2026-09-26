"""Lifecycle-owned optional evidence; only Quattro fusion can consume signals.

Each harness call owns at most one child and a joined monitor. A short execution
cancels pending shadow work instead of waiting for the provider. SQLite is an
independent projection, never the task store or human-gold label store.
"""
from __future__ import annotations

from contextlib import closing
from contextvars import ContextVar
from functools import wraps
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from typing import Any
import uuid

from .jev import MODEL, SCHEMA_VERSION, JevFailure, decode, serialize_state, validate_response

_SCOPE: ContextVar[list | None] = ContextVar("jev_scope", default=None)
_EVIDENCE: ContextVar[dict | None] = ContextVar("routing_evidence", default=None)
_CAPACITY = threading.BoundedSemaphore(8)
_LOG = logging.getLogger(__name__)
FAILURES = frozenset({
    "missing_credential", "timeout", "connection", "rate_limited", "authentication",
    "http_error", "response_too_large", "invalid_json", "schema_mismatch", "unknown_choice",
    "catalog_schema", "model_unavailable", "invalid_state", "worker_failure", "cancelled",
})


def persist(database: Path, record: dict[str, Any]) -> bool:
    """Bounded contention, private metadata only. Never mutate execution state."""
    try:
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(database, os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with closing(sqlite3.connect(database, timeout=0.02)) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS jev_shadow ("
                               "id TEXT PRIMARY KEY, source_task_id TEXT, record_id TEXT, evidence TEXT NOT NULL)")
            connection.execute("INSERT OR REPLACE INTO jev_shadow VALUES (?, ?, ?, ?)", (
                record["id"], record["source_task_id"], record["record_id"],
                json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False),
            ))
            connection.commit()
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


class ShadowRun:
    def __init__(self, *, database: Path, request: str, decision: str,
                 record_id: str | None, source_task_id: str | None,
                 authoritative_tier: str | None, timeout_ms: int,
                 state_json: str | None = None, popen=subprocess.Popen):
        self.database = database
        self.request = request
        self.state_json = state_json
        self.annotations: dict[str, Any] = {}
        self.started = time.perf_counter()
        self.timeout_ms = timeout_ms
        self.popen = popen
        self.process = None
        self.lock = threading.Lock()
        self.release_lock = threading.Lock()
        self.released = False
        self.cancel = threading.Event()
        self.stop_reason = "cancelled"
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name="jev-shadow", daemon=False)
        self.record = {
            "id": "jev_" + uuid.uuid4().hex,
            "source_task_id": source_task_id, "record_id": record_id,
            "schema_version": SCHEMA_VERSION, "provenance": "jev_shadow_observation",
            "authoritative_quattro_decision": decision,
            "authoritative_tier": authoritative_tier,
            "requested_model": MODEL, "provider": "typesafe", "jev_model": None,
            "timestamp": time.time(), "finished_at": None, "status": "pending",
            "jev_shadow_decision": None, "answers": None, "agreement": None,
            "input_usage": None, "output_usage": None,
            "cost": None, "cost_source": "unavailable",
            "jev_latency_ms": None, "catalog_latency_ms": None,
            "worker_latency_ms": None, "shadow_elapsed_ms": None,
            "serialization_latency_ms": None, "failure_category": None,
            "timeout_count": 0, "dispatch_ms": None,
        }
        self.persistence_ok: bool | None = None

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        started = time.perf_counter()
        try:
            self.persistence_ok = persist(self.database, self.record)
            if not self.persistence_ok:
                # Do not spend provider tokens on evidence we cannot retain.
                self.record["failure_category"] = "telemetry_unavailable"
                return
            if self.cancel.is_set():
                raise JevFailure(self.stop_reason)
            key = os.environ.get("TYPESAFE_API_KEY", "")
            if not key:
                raise JevFailure("missing_credential")
            serialization_started = time.perf_counter()
            state = self.state_json or serialize_state(self.request)
            self.request = ""  # The monitor never needs execution context or raw text again.
            self.record["serialization_latency_ms"] = (time.perf_counter() - serialization_started) * 1000
            payload = json.dumps({"state": state, "key": key,
                                  "timeout_seconds": self.timeout_ms / 1000}).encode()
            # Only the secret required by this provider crosses the anonymous pipe.
            # No native agent credentials, proxy configuration, or arbitrary env.
            env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if name in os.environ}
            with self.lock:
                if self.cancel.is_set():
                    raise JevFailure(self.stop_reason)
                self.process = self.popen(
                    [sys.executable, str(Path(__file__).with_name("jev_worker.py").resolve())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=env, cwd=str(Path(__file__).resolve().parent),
                )
            try:
                remaining = max(0.001, self.timeout_ms / 1000 - (time.perf_counter() - self.started))
                output, _ = self.process.communicate(payload, timeout=remaining)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
                raise JevFailure("timeout") from None
            if self.cancel.is_set():
                raise JevFailure(self.stop_reason)
            if self.process.returncode != 0 or len(output) > 32_768:
                raise JevFailure("worker_failure")
            result = decode(output)
            if not isinstance(result, dict):
                raise JevFailure("worker_failure")
            for name in ("jev_latency_ms", "catalog_latency_ms", "worker_latency_ms"):
                value = result.get(name)
                if type(value) in (int, float) and 0 <= value <= 60_000:
                    self.record[name] = value
            if result.get("failure_category"):
                category = result["failure_category"]
                raise JevFailure(category if category in FAILURES else "worker_failure")
            response = validate_response(result.get("response"))
            self.record.update({
                "jev_model": response["model"], "answers": response["answers"],
                "jev_shadow_decision": response["answers"]["execution"]["choice"],
                "agreement": response["answers"]["execution"]["choice"] == self.record["authoritative_quattro_decision"],
                "input_usage": response["usage"]["input_tokens"],
                "output_usage": response["usage"]["output_tokens"],
            })
        except JevFailure as error:
            self.record["failure_category"] = error.category
        except Exception:
            # Never log arbitrary exception messages or provider output.
            self.record["failure_category"] = "worker_failure"
        finally:
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait()
                for stream in (self.process.stdin, self.process.stdout):
                    if stream is not None:
                        stream.close()
            self.request = ""
            self.record["finished_at"] = time.time()
            self.record["status"] = "failed" if self.record["failure_category"] else "success"
            self.record["timeout_count"] = int(self.record["failure_category"] == "timeout")
            self.record["shadow_elapsed_ms"] = (time.perf_counter() - started) * 1000
            self.persistence_ok = persist(self.database, self.record)
            if not self.persistence_ok:
                _LOG.warning("Jev telemetry unavailable")
            self.done.set()

    def close(self, *, reason: str = "cancelled") -> None:
        if not self.done.is_set():
            with self.lock:
                if self.process is None or self.process.poll() is None:
                    self.stop_reason = reason
                    self.cancel.set()
                    if self.process is not None:
                        self.process.kill()
        self.thread.join()
        if self.annotations:
            self.record.update(self.annotations)
            self.persistence_ok = persist(self.database, self.record)
            if not self.persistence_ok:
                _LOG.warning("Jev telemetry annotations unavailable")

    def finish_owned(self) -> None:
        """Idempotent across native finish/cancel/shutdown callers."""
        with self.release_lock:
            if not self.released:
                try:
                    self.close()
                finally:
                    self.released = True
                    _CAPACITY.release()


def take_scope() -> tuple[ShadowRun, ...]:
    """Transfer ownership to a native Turn that closes on finish/cancel/shutdown."""
    runs = _SCOPE.get()
    owned = tuple(runs or ())
    if runs is not None:
        runs.clear()
    return owned


def lifecycle(function):
    """A request/run owns its shadow scope, including exceptions and cancellation."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        runs: list[ShadowRun] = []
        token = _SCOPE.set(runs)
        evidence_token = _EVIDENCE.set({})
        try:
            return function(*args, **kwargs)
        finally:
            try:
                for run in runs:
                    try:
                        run.finish_owned()
                    except Exception:
                        # Shadow cleanup must not replace the authoritative outcome.
                        pass
            finally:
                _SCOPE.reset(token)
                _EVIDENCE.reset(evidence_token)
    return wrapped


def start_shadow(*, config, database, request, decision, record_id=None,
                 source_task_id=None, authoritative_tier=None, state_json=None) -> ShadowRun | None:
    """Only Quattro fusion consumes signals; execution transport never calls this."""
    runs = _SCOPE.get()
    options = config.get("routing", {}).get("jev", {})
    if options.get("mode", "OFF") not in {"SHADOW", "COOPERATIVE"} or runs is None or runs:
        return
    if not _CAPACITY.acquire(blocking=False):
        _LOG.warning("Jev skipped: shadow capacity unavailable")
        return
    try:
        run = ShadowRun(
            database=database, request=request, decision=decision,
            record_id=record_id, source_task_id=source_task_id,
            authoritative_tier=authoritative_tier, timeout_ms=options.get("timeoutMs", 300),
            state_json=state_json,
        )
        run.start()
        runs.append(run)
        return run
    except Exception:
        _CAPACITY.release()
        _LOG.warning("Jev unavailable: worker startup failed")
    return None


def current_learned_signal() -> dict[str, Any] | None:
    signal = (_EVIDENCE.get() or {}).get("learned_signal")
    return None if signal and signal.get("error") == "off" else signal


def mark_dispatch() -> None:
    """Elapsed request-boundary-to-transport time, not provider execution time."""
    runs = _SCOPE.get()
    if runs and "dispatch_ms" not in runs[0].annotations:
        runs[0].annotations["dispatch_ms"] = (time.perf_counter() - runs[0].started) * 1000


def current_evidence() -> dict:
    """Content-free snapshot for the existing per-turn routing record."""
    return dict(_EVIDENCE.get() or {})


def annotate(**values) -> None:
    """Owner-thread-only annotations; applied after the monitor has been joined."""
    evidence = _EVIDENCE.get()
    if evidence is not None:
        evidence.update(values)
    runs = _SCOPE.get()
    if runs:
        runs[0].annotations.update(values)
