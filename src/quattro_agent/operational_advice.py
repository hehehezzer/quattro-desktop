"""Minimal-feature Jev interventions; host grants remain authoritative.

No source text, command, path, output or fingerprint crosses the evaluator
boundary. Fingerprints are ephemeral local digests, never telemetry. This
module proposes constraints; it cannot execute, authorize or select a model.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import OrderedDict

FLAGS = frozenset({"host_allowed", "owner_approved", "writes", "network",
                   "destructive", "sensitive", "opaque", "retrieval_allowed",
                   "context_missing", "evidence_sufficient", "transient"})
OPERATIONS = frozenset({"preflight", "rag", "feedback", "task"})
OUTCOMES = frozenset({"success", "failure", "test_failure", "unchanged"})
PROVIDER_EVIDENCE = frozenset({"timeout", "uncertain", "hard_policy", "native_choice_probabilities",
    "missing_credential", "rate_limited", "circuit_open", "closed", "worker_failure",
    "invalid_state", "unsupported_decision", "capacity", "budget", "cancelled", "trivial", "disabled"})
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
    def __init__(self, evaluator, *, enabled=False, emit=None, clock=time.monotonic):
        self.evaluator, self.enabled, self.emit, self.clock = evaluator, enabled, emit, clock
        self.lock = threading.RLock()
        self.states = OrderedDict()
        self.busy = False
        self.memo = OrderedDict()
        self.revision = 0

    def handle(self, operation, features, *, fingerprint=None, outcome=None):
        if operation not in OPERATIONS or type(features) is not dict or set(features) - FLAGS:
            raise ValueError("categorical operational features required")
        if any(type(value) is not bool for value in features.values()):
            raise ValueError("operational features must be boolean")
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
                      latency_ms=0.0, provider_selected_option="UNKNOWN", provider_confidence="UNKNOWN",
                      acceptance_threshold=0.90, provider_evidence="UNKNOWN", rejection_reason="UNKNOWN")
        cache_key = (operation, tuple(sorted(features.items())))
        def finish(reason, recommendation="none"):
            result.update(reason=reason, recommendation=recommendation,
                          latency_ms=max(0.0, (self.clock() - started) * 1000))
            if not result["accepted"] and result["rejection_reason"] == "UNKNOWN":
                result["rejection_reason"] = reason
            elif result["accepted"]:
                result["rejection_reason"] = "NONE"
            if result["requested"]:
                self.memo[cache_key] = (self.clock() + 30, dict(result))
                self.memo.move_to_end(cache_key)
                while len(self.memo) > 64:
                    self.memo.popitem(last=False)
            if self.emit:
                self.emit(dict(result))
            return result
        if not self.enabled:
            return finish("disabled")
        if operation == "preflight":
            if not features.get("host_allowed", False):
                result["applied"] = True
                return finish("host_denied", "stop")
            if (features.get("destructive") or features.get("sensitive")) and not features.get("owner_approved", False):
                result["applied"] = True
                return finish("owner_required", "ask_owner")
            category, actions = "progress_strategy", ["continue", "validate", "agent"]
            context = {"changes_present": features.get("writes", False),
                       "verification_required": any(features.get(k, False) for k in ("network", "destructive", "sensitive", "opaque"))}
        elif operation == "rag":
            if not features.get("retrieval_allowed", False):
                return finish("scope_denied", "stop")
            if features.get("evidence_sufficient", False):
                result["applied"] = True
                return finish("evidence_sufficient", "stop_retrieval")
            category, actions = "context_strategy", ["inspect", "retrieve", "sufficient", "agent"]
            context = {"context_missing": features.get("context_missing", True), "retrieval_required": True}
        elif operation == "task":
            category, actions = "progress_strategy", ["continue", "validate", "more_context", "agent"]
            context = {"multi_step_required": True, "modification_required": features.get("writes", False),
                       "context_missing": features.get("context_missing", False)}
        else:
            # Bounded in-memory history; eviction never increases access.
            state = self.states.setdefault(fingerprint, {"repeats": 0, "consulted": False})
            self.states.move_to_end(fingerprint)
            while len(self.states) > 256:
                self.states.popitem(last=False)
            if outcome == "success":
                self.states.pop(fingerprint, None)
                return finish("progress")
            state["repeats"] += 1
            if state["repeats"] < 3:
                return finish("below_threshold")
            if state["consulted"]:
                result["applied"] = True
                return finish("identical_loop", "ask_owner")
            state["consulted"] = True
            category, actions = "retry_strategy", ["change_strategy", "agent"]
            context = {"context_missing": features.get("context_missing", False), "verification_required": True}
        result["eligible"] = True
        cached = self.memo.get(cache_key) if operation != "feedback" else None
        if cached and cached[0] > self.clock():
            result.update({key: cached[1][key] for key in ("accepted", "provider_selected_option", "provider_confidence",
                "acceptance_threshold", "provider_evidence", "rejection_reason")})
            result["cached"] = True
            return finish("cached" if result["accepted"] else "cooldown", cached[1]["recommendation"])
        if self.busy:
            return finish("recursive", "ask_owner")
        self.busy = True
        self.revision = min(1_000_000, self.revision + 1)
        request = dict(decision_type=category, available_actions=actions, relevant_context=context,
                       hard_constraints={"retry_allowed": False, "parallel_allowed": False,
                                         "retrieval_allowed": operation == "rag"},
                       execution_state={"revision": self.revision, "phase": "inspection", "attempt": 0},
                       previous_result="test_failure" if outcome == "test_failure" else "unknown_failure" if operation == "feedback" else "none")
        result["requested"] = True
        try:
            advice = self.evaluator(request)
            fallback_recommendation = "ask_owner" if operation != "rag" else "narrow_retrieval"
            if type(advice) is not dict:
                return finish("malformed_output", fallback_recommendation)
            evidence = advice.get("evidence")
            if type(evidence) is str and evidence in PROVIDER_EVIDENCE:
                result["provider_evidence"] = evidence
            usage = advice.get("usageEvidence")
            usage = usage if type(usage) is dict else {}
            result["called"] = advice.get("called", usage.get("providerAttempted", False)) is True
            confidence = advice.get("confidence")
            action = advice.get("selected_action")
            provider_action = advice.get("provider_selected_action", action)
            if type(provider_action) is str and provider_action in actions:
                result["provider_selected_option"] = provider_action
            valid_confidence = type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1
            if valid_confidence:
                result["provider_confidence"] = confidence
            if "fallback_required" in advice and type(advice["fallback_required"]) is not bool:
                return finish("malformed_output", fallback_recommendation)
            if "provider_selected_action" in advice and result["provider_selected_option"] == "UNKNOWN":
                return finish("malformed_output", fallback_recommendation)
            if evidence == "timeout":
                return finish("timeout", fallback_recommendation)
            if provider_action == "agent":
                return finish("delegation_to_agent", fallback_recommendation)
            if valid_confidence and confidence < result["acceptance_threshold"]:
                return finish("low_confidence", fallback_recommendation)
            if advice.get("fallback_required") is True:
                reason = "provider_uncertainty" if evidence == "uncertain" else "provider_denial" if evidence == "hard_policy" else "provider_fallback"
                return finish(reason, fallback_recommendation)
            if not valid_confidence or type(action) is not str or action not in actions:
                return finish("malformed_output", fallback_recommendation)
            result["accepted"] = True
            mapping = {"preflight": {"continue": "proceed", "validate": "safer_alternative", "agent": "ask_owner"},
                       "rag": {"inspect": "narrow_retrieval", "retrieve": "bounded_retrieval", "sufficient": "stop_retrieval", "agent": "ask_owner"},
                       "task": {"continue": "continue_plan", "validate": "validate_first", "more_context": "gather_context", "agent": "ask_owner"},
                       "feedback": {"change_strategy": "change_plan", "agent": "ask_owner"}}
            recommendation = mapping[operation][action]
            # Categorical uncertainty around opaque operations cannot be a grant.
            if operation == "preflight" and recommendation == "proceed" and any(features.get(k, False) for k in ("opaque", "destructive", "sensitive")):
                recommendation = "ask_owner"
            return finish("advice", recommendation)
        except TimeoutError:
            return finish("timeout", "ask_owner" if operation != "rag" else "narrow_retrieval")
        except Exception:
            return finish("unavailable", "ask_owner" if operation != "rag" else "narrow_retrieval")
        finally:
            self.busy = False
