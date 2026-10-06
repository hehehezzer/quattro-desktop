"""Deterministic host guards; substantive decisions belong to the native model.

Risk booleans are security inputs, not Jev decision parameters. These legacy
hooks never manufacture questions, options, or provider requests. A guard can
narrow or deny an operation; it cannot grant native host permission.
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

HOST_RISK_FIELDS = frozenset({"host_allowed", "owner_approved", "writes", "network",
                   "destructive", "sensitive", "opaque", "retrieval_allowed",
                   "context_missing", "evidence_sufficient", "transient"})
OPERATIONS = frozenset({"preflight", "rag", "feedback", "task"})
OUTCOMES = frozenset({"success", "failure", "test_failure", "unchanged"})
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def refine_query(query):
    """Local lexical refinement only; never a provider-generated query."""
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("bounded retrieval query required")
    stop = {"what", "where", "which", "please", "tell", "about", "the", "and", "with", "this", "that", "how", "does", "are"}
    terms = []
    for term in re.findall(r"[A-Za-z0-9_./:-]{2,80}", query):
        if term.lower() not in stop and term not in terms:
            terms.append(term)
        if len(terms) == 24:
            break
    return " ".join(terms) if len(terms) >= 2 else query.strip()


class OperationalAdvisor:
    """Compatibility guard retaining bounded session-local loop observations.

    ``evaluator`` remains a constructor argument for older host integrations,
    but is deliberately never invoked. Ask the executing model to author a
    decision through ``operational_decision`` when deliberation is needed.
    """
    def __init__(self, evaluator=None, *, enabled=False, emit=None, clock=time.monotonic):
        self.evaluator, self.enabled, self.emit, self.clock = evaluator, enabled, emit, clock
        self.lock = threading.RLock()
        self.states = OrderedDict()

    def handle(self, operation, features, *, fingerprint=None, outcome=None):
        if operation not in OPERATIONS or type(features) is not dict or set(features) - HOST_RISK_FIELDS:
            raise ValueError("host operational safety fields required")
        if any(type(value) is not bool for value in features.values()):
            raise ValueError("operational safety features must be boolean")
        if operation == "feedback" and (type(fingerprint) is not str or not DIGEST.fullmatch(fingerprint) or outcome not in OUTCOMES):
            raise ValueError("local digest and categorical outcome required")
        if operation != "feedback" and (fingerprint is not None or outcome is not None):
            raise ValueError("feedback fields on wrong operation")
        with self.lock:
            return self._handle(operation, features, fingerprint, outcome)

    def _handle(self, operation, features, fingerprint, outcome):
        started = self.clock()
        result = dict(category=operation, eligible=False, requested=False, called=False,
                      accepted=False, applied=False, cached=False, recommendation="none", reason="disabled",
                      latency_ms=0.0, fallback_class="agent", provider_attempt="NOT_ATTEMPTED",
                      provider_selected_option="UNKNOWN", provider_confidence="UNKNOWN",
                      acceptance_threshold=0.90, provider_evidence="UNKNOWN", rejection_reason="UNKNOWN")

        def finish(reason, recommendation="none", *, applied=False, fallback="agent"):
            result.update(reason=reason, recommendation=recommendation, applied=applied,
                          fallback_class=fallback, rejection_reason=reason,
                          latency_ms=max(0.0, (self.clock() - started) * 1000))
            if self.emit:
                self.emit(dict(result))
            return result

        if not self.enabled:
            return finish("disabled")
        if operation == "preflight":
            if not features.get("host_allowed", False):
                return finish("host_denied", "stop", applied=True, fallback="policy")
            if (features.get("destructive") or features.get("sensitive")) and not features.get("owner_approved", False):
                return finish("owner_required", "ask_owner", applied=True, fallback="owner")
            if features.get("opaque"):
                return finish("opaque_operation", "ask_owner", applied=True, fallback="owner")
            return finish("host_guard_passed", "proceed", fallback="none")
        if operation == "rag":
            if not features.get("retrieval_allowed", False):
                return finish("scope_denied", "stop", applied=True, fallback="policy")
            if features.get("evidence_sufficient", False):
                return finish("evidence_sufficient", "stop_retrieval", applied=True, fallback="none")
            # Keep the existing permitted query/scope; the retrieval engine
            # enforces limits. Model-authored advice uses a separate boundary.
            return finish("retrieval_guard_passed", "bounded_retrieval", fallback="none")
        if operation == "task":
            return finish("model_decision_required", "defer_to_agent")
        # Fingerprints stay in bounded session memory and never leave this host.
        if outcome == "success":
            self.states.pop(fingerprint, None)
            return finish("progress", fallback="none")
        state = self.states.setdefault(fingerprint, {"repeats": 0})
        self.states.move_to_end(fingerprint)
        while len(self.states) > 256:
            self.states.popitem(last=False)
        state["repeats"] += 1
        if state["repeats"] < 3:
            return finish("below_threshold", fallback="none")
        if state["repeats"] == 3:
            return finish("model_decision_required", "change_plan")
        return finish("identical_loop", "ask_owner", applied=True)
