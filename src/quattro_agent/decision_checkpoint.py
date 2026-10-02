"""Local checkpoint envelope. Only the existing categorical projection leaves host.

No cache reuse: state invalidation is not yet comprehensive across native hosts.
An envelope is an observation/assertion, never an authorization or completion proof.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from collections import OrderedDict

VERSION = "quattro-checkpoint-v1"
CHECKPOINTS = {"after_inspection", "failure_no_progress"}
PHASES = {"inspection", "implementation", "validation", "completion"}
RESULTS = {"none", "success", "transient_failure", "test_failure", "unknown_failure"}
FLAGS = {"repository_required", "modification_required", "retrieval_required",
         "multi_step_required", "verification_required", "context_missing",
         "independent_steps", "tests_available", "changes_present"}
PROVENANCE = {"host_observed", "agent_asserted", "unknown"}
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def validate_envelope(value):
    required = {"schema_version", "checkpoint", "scope_id", "policy_revision",
                "state_revision", "phase", "attempt", "previous_result",
                "state_provenance", "features", "provenance"}
    if type(value) is not dict or set(value) != required or value["schema_version"] != VERSION:
        raise ValueError("fixed local checkpoint envelope required")
    for key in ("scope_id", "policy_revision"):
        if type(value[key]) is not str or not IDENTIFIER.fullmatch(value[key]):
            raise ValueError("opaque local binding required")
    for key, choices in (("checkpoint", CHECKPOINTS), ("phase", PHASES),
                         ("previous_result", RESULTS), ("state_provenance", PROVENANCE)):
        if type(value[key]) is not str or value[key] not in choices:
            raise ValueError("invalid checkpoint category")
    for key, maximum in (("state_revision", 1_000_000), ("attempt", 100)):
        if type(value[key]) is not int or not 0 <= value[key] <= maximum:
            raise ValueError("invalid observed counter")
    features, provenance = value["features"], value["provenance"]
    if type(features) is not dict or set(features) - FLAGS or type(provenance) is not dict or set(provenance) != set(features):
        raise ValueError("allowlisted features with explicit provenance required")
    for key, flag in features.items():
        origin = provenance[key]
        if type(origin) is not str or origin not in PROVENANCE:
            raise ValueError("invalid feature provenance")
        if flag is None:
            if origin != "unknown":
                raise ValueError("unknown feature needs unknown provenance")
        elif type(flag) is not bool or origin == "unknown":
            raise ValueError("known boolean needs observed or asserted provenance")
    return {**value, "features": dict(features), "provenance": dict(provenance)}


def projection(envelope):
    value = validate_envelope(envelope)
    failure = value["checkpoint"] == "failure_no_progress"
    return dict(decision_type="retry_strategy" if failure else "progress_strategy",
                available_actions=["change_strategy", "agent"] if failure else ["continue", "validate", "more_context", "agent"],
                relevant_context={k: v for k, v in value["features"].items() if v is not None},
                hard_constraints={"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
                execution_state={"revision": value["state_revision"], "phase": value["phase"], "attempt": value["attempt"]},
                previous_result=value["previous_result"])


def consult(envelope, evaluator, *, enabled=True, is_current=None, clock=time.monotonic):
    value = validate_envelope(envelope)
    request = projection(value)
    started = clock()
    result = dict(category="checkpoint", checkpoint=value["checkpoint"], eligible=True,
                  requested=False, called=False, provider_attempt="NOT_ATTEMPTED",
                  accepted=False, applied=False, cached=False, recommendation="defer_to_agent",
                  reason="disabled", fallback_class="agent", latency_ms=0.0,
                  provider_selected_option="UNKNOWN", provider_confidence="UNKNOWN",
                  acceptance_threshold=0.90, provider_evidence="UNKNOWN", rejection_reason="disabled",
                  consultation_id=uuid.uuid4().hex, advice_delivered=False,
                  action_admitted=False, receipt_consumed=False, execution_observed=False,
                  task_validated=False, model_use="UNKNOWN", state_provenance=value["state_provenance"])

    def finish(reason):
        result["reason"] = reason
        result["rejection_reason"] = "NONE" if result["accepted"] else reason
        result["latency_ms"] = max(0.0, (clock() - started) * 1000)
        return result

    def current():
        try:
            return is_current is None or is_current(value) is True
        except Exception:
            return False

    if not enabled:
        return finish("disabled")
    if not current():
        return finish("stale_state")
    result["requested"] = True
    try:
        advice = evaluator(request)
    except Exception:
        result["provider_attempt"] = "UNKNOWN"
        return finish("unavailable")
    if type(advice) is not dict:
        result["provider_attempt"] = "UNKNOWN"
        return finish("malformed_output")
    usage = advice.get("usageEvidence")
    usage = usage if type(usage) is dict else {}
    result["called"] = advice.get("called", usage.get("providerAttempted")) is True
    result["provider_attempt"] = "CONFIRMED" if result["called"] else advice.get("provider_attempt", "UNKNOWN")
    if type(result["provider_attempt"]) is not str or result["provider_attempt"] not in {"CONFIRMED", "NOT_ATTEMPTED", "UNKNOWN"}:
        result["provider_attempt"] = "UNKNOWN"
    if not current():
        return finish("stale_state")
    action = advice.get("provider_selected_action", advice.get("selected_action"))
    confidence = advice.get("confidence")
    valid_confidence = type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1
    if type(action) is str and action in request["available_actions"]:
        result["provider_selected_option"] = action
    if valid_confidence:
        result["provider_confidence"] = confidence
    evidence = advice.get("evidence")
    if type(evidence) is str and evidence in {"timeout", "uncertain", "hard_policy", "native_choice_probabilities", "missing_credential", "rate_limited", "circuit_open", "closed", "worker_failure", "cancelled"}:
        result["provider_evidence"] = evidence
    if action == "agent":
        return finish("delegation_to_agent")
    if not valid_confidence or action not in request["available_actions"] or type(advice.get("fallback_required", False)) is not bool:
        return finish("malformed_output")
    if confidence < 0.90:
        return finish("low_confidence")
    if advice.get("fallback_required") or advice.get("selected_action") != action:
        return finish("provider_fallback")
    result.update(accepted=True, fallback_class="none", recommendation={
        "continue": "continue_plan", "validate": "validate_first",
        "more_context": "gather_context", "change_strategy": "change_plan"}[action])
    return finish("advice")


def envelope_schema():
    """JSON schema for existing explicit tools, not a new MCP tool."""
    enum = lambda values: {"type": "string", "enum": sorted(values)}
    properties = {"schema_version": {"const": VERSION}, "checkpoint": enum(CHECKPOINTS),
                  "scope_id": {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{1,128}$"},
                  "policy_revision": {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{1,128}$"},
                  "state_revision": {"type": "integer", "minimum": 0, "maximum": 1_000_000},
                  "attempt": {"type": "integer", "minimum": 0, "maximum": 100},
                  "phase": enum(PHASES), "previous_result": enum(RESULTS),
                  "state_provenance": enum(PROVENANCE),
                  "features": {"type": "object", "properties": {k: {"type": ["boolean", "null"]} for k in sorted(FLAGS)}, "additionalProperties": False},
                  "provenance": {"type": "object", "properties": {k: enum(PROVENANCE) for k in sorted(FLAGS)}, "additionalProperties": False}}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


class CheckpointTracker:
    """Host-local tool-result observations; no contents, semantic claims or grants.

    after_inspection means an inspection tool returned, not that all inspection
    is complete or its evidence is sufficient. Unknown results stay unknown.
    """
    def __init__(self, scope_id=None):
        self.scope_id = scope_id or uuid.uuid4().hex
        self.revision = 0
        self.inspected = False
        self.phase = "inspection"
        self.signatures = OrderedDict()

    def observe(self, *, inspection=False, writes=False, outcome="unknown", signature=None):
        if outcome not in {"success", "failure", "test_failure", "unknown", "unchanged"}:
            raise ValueError("categorical observed result required")
        self.revision = min(1_000_000, self.revision + 1)
        if writes:
            self.phase = "implementation"
        repeats = 0
        if signature is not None:
            if type(signature) is not str or not re.fullmatch(r"[0-9a-f]{64}", signature):
                raise ValueError("local signature required")
            repeats = self.signatures.get(signature, 0) + 1
            self.signatures[signature] = repeats
            self.signatures.move_to_end(signature)
            while len(self.signatures) > 256:
                self.signatures.popitem(last=False)
        if outcome in {"failure", "test_failure"} or repeats == 3:
            checkpoint = "failure_no_progress"
        elif inspection and not self.inspected:
            self.inspected = True
            checkpoint = "after_inspection"
        else:
            return None
        previous = {"success": "success", "failure": "unknown_failure", "test_failure": "test_failure"}.get(outcome, "none")
        return dict(schema_version=VERSION, checkpoint=checkpoint, scope_id=self.scope_id,
                    policy_revision="existing-scope", state_revision=self.revision,
                    phase=self.phase, attempt=min(100, max(0, repeats - 1)), previous_result=previous,
                    state_provenance="host_observed", features={"repository_required": True},
                    provenance={"repository_required": "host_observed"})

    def current(self, envelope):
        return envelope["scope_id"] == self.scope_id and envelope["state_revision"] == self.revision
