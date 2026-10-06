"""Host-owned mandatory validation without hidden fixed Jev questions.

The native model can consult its dynamic decision tool before requesting
validation. This terminal boundary executes the existing host checks in their
original order, preserves cancellation, and never authors a question itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, Any

@dataclass(frozen=True, eq=False)
class RequiredCheck:
    """A host-created closure, never a command supplied by Jev or the repository."""

    scope: str
    run: Callable[[], Any] = field(repr=False, compare=False)

    def __post_init__(self):
        if self.scope not in {"targeted", "broad", "policy"}:
            raise ValueError("unsupported validation scope")


def validation_boundary_ready(event: str, checks: tuple[RequiredCheck, ...]) -> bool:
    """Observe the existing host validation boundary without classifying decisions."""
    return (event == "host.validation.ready" and 2 <= len(checks) <= 16
            and {"targeted", "broad"} <= {check.scope for check in checks})


class MilestoneCancelled(Exception):
    """The owning task left validation before a new check could be dispatched."""


def run_validation_milestone(checks, *, options, is_current, emit,
                             decision_factory=None):
    """Execute every existing check once in its original host order.

    The old experiment settings and decision_factory argument remain accepted
    for compatibility. They do not start provider work or reorder checks; a
    contextual question must be authored by the executing native model.
    """
    checks = tuple(checks)
    detected = time.perf_counter()
    eligible = validation_boundary_ready("host.validation.ready", checks)
    record = {
        "schema_version": "quattro-runtime-milestone-v1",
        "milestone": "VALIDATION", "decision_boundary": "host_validation",
        "observed": 1, "eligible": int(eligible), "jev_calls": 0,
        "outcome": "PASSTHROUGH", "reason": "disabled", "execution_changed": False,
        "agent_reasoning_avoided": False, "model_turns_avoided": 0,
        "advisory_context_emitted": False, "context_bytes": 0,
        "uncertain": 0, "timeouts": 0, "cache_hits": 0,
        "timing": {"milestone_detected_ms": 0.0, "decision_applied_ms": None,
                   "execution_resumed_ms": None, "blocking_ms": 0.0,
                   "rtt_ms": None, "queue_ms": None, "validation_ms": None,
                   "useful_overlap_ms": 0.0},
    }
    order = checks
    enabled = (options.get("mode") == "COOPERATIVE"
               and options.get("experimentalValidationOrder") is True)
    was_current = enabled and eligible
    if not eligible:
        record["reason"] = "agent_reasoning"
    elif enabled:
        record["reason"] = "model_decision_required"
    record["static_questionnaire_retired"] = True
    try:
        if was_current and not is_current():
            record["reason"] = "stale_or_cancelled"
            raise MilestoneCancelled()
        resumed = (time.perf_counter() - detected) * 1000
        record["timing"]["milestone_wait_ms"] = resumed
        if not order:
            record["timing"]["execution_resumed_ms"] = resumed
        results = []
        for check in order:
            if was_current and not is_current():
                record["reason"] = "stale_or_cancelled"
                raise MilestoneCancelled()
            if not results:
                record["timing"]["execution_resumed_ms"] = (time.perf_counter() - detected) * 1000
            results.append(check.run())
        return results
    finally:
        # Optional telemetry must not replace the result/exception of a check.
        try:
            emit(record)
        except Exception:
            pass
