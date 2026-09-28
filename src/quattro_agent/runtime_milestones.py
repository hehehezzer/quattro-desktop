"""Host-owned, opt-in milestone experiment; no commands or model authority.

Only ordering of an existing mandatory validation plan is supported. This is a
post-agent boundary, NOT evidence that agent reasoning has been eliminated.
Native item notifications alone cannot authorize execution. Unknown milestones
remain AGENT_REASONING and no category is enabled by default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Callable, Any

from .decision_service import DecisionSession
from .decision_taxonomy import DecisionClass


@dataclass(frozen=True, eq=False)
class RequiredCheck:
    """A host-created closure, never a command supplied by Jev or the repository."""

    scope: str
    run: Callable[[], Any] = field(repr=False, compare=False)

    def __post_init__(self):
        if self.scope not in {"targeted", "broad", "policy"}:
            raise ValueError("unsupported validation scope")


def classify_milestone(event: str, checks: tuple[RequiredCheck, ...]) -> DecisionClass:
    if (event == "host.validation.ready" and 2 <= len(checks) <= 16
            and {"targeted", "broad"} <= {check.scope for check in checks}):
        return DecisionClass.JEV_ELIGIBLE
    return DecisionClass.AGENT_REASONING


class MilestoneCancelled(Exception):
    """The owning task left validation before a new check could be dispatched."""


def run_validation_milestone(checks, *, options, is_current, emit,
                             decision_factory=None):
    """Execute all existing checks once, optionally changing their order.

    Options are host config, not tool arguments. The explicit experiment flag
    is not a promotion to default enablement. No tests are added, skipped,
    retried, parallelized or declared successful by the decision provider.
    Check execution and exceptions retain the caller's existing behavior.
    """
    checks = tuple(checks)
    detected = time.perf_counter()
    eligible = classify_milestone("host.validation.ready", checks) == DecisionClass.JEV_ELIGIBLE
    record = {
        "schema_version": "quattro-runtime-milestone-v1",
        "milestone": "VALIDATION", "decision_type": "validation_strategy",
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
    service = None
    was_current = False
    enabled = (options.get("mode") == "COOPERATIVE"
               and options.get("experimentalValidationOrder") is True)
    try:
        if not eligible:
            record["reason"] = "agent_reasoning"
        elif enabled and is_current():
            was_current = True
            record["outcome"] = "FALLBACK"
            request = {
                "decision_type": "validation_strategy",
                "available_actions": ["targeted_first", "broad_first", "agent"],
                "relevant_context": {"tests_available": True, "verification_required": True},
                "hard_constraints": {"retry_allowed": False, "parallel_allowed": False,
                                     "retrieval_allowed": False},
                "execution_state": {"revision": 0, "phase": "validation", "attempt": 1},
                "previous_result": "success",
            }
            record["context_bytes"] = len(json.dumps(request, sort_keys=True, separators=(",", ":")).encode())
            # Sparse terminal experiment only. Never spend the full general
            # three-second advisory ceiling on automatic interception.
            timeout = options.get("timeoutMs", 1500)
            timeout = min(750, timeout) if type(timeout) is int and timeout >= 100 else 750
            service = (decision_factory or DecisionSession)(mode="COOPERATIVE", timeout_ms=timeout)
            entered_ms = (time.perf_counter() - detected) * 1000
            record["timing"]["request_entered_ms"] = entered_ms
            result = service.decide(request, cancelled=lambda: not is_current())
            snapshot = service.snapshot().get("counts", {})
            record.update(jev_calls=snapshot.get("calls", 0), cache_hits=snapshot.get("cache_hits", 0))
            record["timing"].update(result.get("timing", {}))
            queued_ms = result.get("timing", {}).get("timeline_ms", {}).get("request_queued")
            record["timing"]["request_queued_ms"] = entered_ms + queued_ms if queued_ms is not None else None
            record["reason"] = result.get("evidence", "invalid_decision")
            record["uncertain"] = int(record["reason"] == "uncertain")
            record["timeouts"] = int(record["reason"] == "timeout")
            action = result.get("selected_action")
            # Defense in depth: an injected/defective service still cannot
            # expand the action space or bypass its confidence floor.
            if not is_current():
                record["reason"] = "stale_or_cancelled"
            elif (result.get("fallback_required") is False
                  and type(result.get("confidence")) in (int, float)
                  and DecisionSession.MIN_CONFIDENCE <= result["confidence"] <= 1
                  and action in {"targeted_first", "broad_first"}):
                first = "targeted" if action == "targeted_first" else "broad"
                movable = tuple(check for check in checks if check.scope != "policy")
                selected = tuple(check for check in movable if check.scope == first) + tuple(
                    check for check in movable if check.scope != first)
                if selected == movable:
                    record["reason"] = "unchanged_order"
                else:
                    # A suite may mutate the repository. In particular it must
                    # never hide an agent's read-only-policy violation by repairing
                    # the tree before the snapshot guard runs. Hard guards move
                    # only earlier, never behind a Jev-reordered executable suite.
                    order = tuple(check for check in checks if check.scope == "policy") + selected
                    record["reason"] = "host_order_selected"
            else:
                record["reason"] = result.get("evidence", "invalid_decision")
        elif enabled:
            record["reason"] = "stale_or_cancelled"
    except Exception:
        # This catches optional decision work only, not validation exceptions.
        order = checks
        record["reason"] = "decision_failure"
    finally:
        if service is not None:
            # Non-joining cancellation retains worker ownership with the
            # existing monitor; no new cleanup lock on validation execution.
            service.request_close()
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
            # Count host application only when the first real check is dispatched.
            if not results and order != checks:
                record["outcome"] = "OFFLOADED"
                record["execution_changed"] = True
                record["timing"]["decision_applied_ms"] = (time.perf_counter() - detected) * 1000
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
