"""Metadata-only routing lifecycle and bounded dynamic-provider resources.

Bootstrap features never cross this boundary into provider questions. The
execution model authors every provider decision through DecisionSession.
"""
from __future__ import annotations

from collections import OrderedDict
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import threading
import time
from typing import Any

_EVIDENCE: ContextVar[dict | None] = ContextVar("routing_evidence", default=None)
_CAPACITY = threading.BoundedSemaphore(8)
FAILURES = frozenset({
    "missing_credential", "timeout", "connection", "rate_limited", "authentication",
    "http_error", "response_too_large", "invalid_json", "schema_mismatch", "unknown_choice",
    "catalog_schema", "model_unavailable", "invalid_state", "worker_failure", "cancelled",
})


class FailureCooldown:
    """Bounded process-local provider suppression, isolated by evidence store.

    No timer threads, persistence, retries, credentials or request text. Ordinary
    cancellation and local telemetry failures are not provider health evidence.
    """
    PROVIDER_FAILURES = FAILURES - {"missing_credential", "cancelled"}

    def __init__(self, *, threshold=3, cooldown_seconds=30.0, capacity=128,
                 clock=time.monotonic):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.capacity = capacity
        self.clock = clock
        self.lock = threading.Lock()
        self.states: OrderedDict[Path, tuple[int, float]] = OrderedDict()

    def suppressed(self, database: Path) -> bool:
        with self.lock:
            state = self.states.get(database)
            if state is None:
                return False
            self.states.move_to_end(database)
            failures, until = state
            if until and self.clock() >= until:
                del self.states[database]
                return False
            return failures >= self.threshold

    def observe(self, database: Path, failure: str | None) -> None:
        if failure is not None and failure not in self.PROVIDER_FAILURES:
            return
        with self.lock:
            if failure is None:
                self.states.pop(database, None)
                return
            failures, until = self.states.get(database, (0, 0.0))
            # In-flight failures must not extend an already active cooldown.
            failures = min(self.threshold, failures + 1)
            if failures == self.threshold and not until:
                until = self.clock() + self.cooldown_seconds
            self.states[database] = (failures, until)
            self.states.move_to_end(database)
            while len(self.states) > self.capacity:
                self.states.popitem(last=False)


def take_scope() -> tuple:
    """Compatibility lifecycle projection; no automatic provider child exists."""
    return ()


def lifecycle(function):
    """Isolate content-free evidence and launcher options per call."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        evidence_token = _EVIDENCE.set({})
        # Propagate only validated launcher options to execution adapters. This
        # context survives routing into run_task, but never crosses sessions.
        from .decision_launch import OPTIONS
        options = None
        try:
            owner_config = getattr(args[0], "config", None) if args else None
            config = owner_config() if callable(owner_config) else owner_config
            if isinstance(config, dict):
                options = dict(config.get("routing", {}).get("jev", {}))
        except Exception:
            pass  # Optional tool registration cannot prevent normal execution.
        decision_token = OPTIONS.set(options)
        try:
            return function(*args, **kwargs)
        finally:
            _EVIDENCE.reset(evidence_token)
            OPTIONS.reset(decision_token)
    return wrapped


def current_learned_signal() -> dict[str, Any] | None:
    signal = (_EVIDENCE.get() or {}).get("learned_signal")
    return None if signal and signal.get("error") in {"off", "fast_guard"} else signal


def mark_dispatch() -> None:
    """Record a local dispatch boundary without inventing provider latency."""
    annotate(dispatch_boundary_observed=True)


def current_evidence() -> dict:
    """Content-free snapshot for the existing per-turn routing record."""
    return dict(_EVIDENCE.get() or {})


def annotate(**values) -> None:
    evidence = _EVIDENCE.get()
    if evidence is not None:
        evidence.update(values)
