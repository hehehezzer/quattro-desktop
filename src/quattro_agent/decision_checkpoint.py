"""Host-local checkpoint observations and explicit model-authored decisions.

Observations never manufacture a question, option or context parameter. Only a
validated authored v2 decision may leave the host. Advice creates no authority,
action receipt or completion proof, and checkpoint advice is never cached.
"""
from __future__ import annotations

import json
import math
import re
import time
import uuid
from collections import OrderedDict

from .decision_taxonomy import (allowed_action, dynamic_schema, option_effect,
                                validate_request)
from .jev import JevFailure

VERSION = "quattro-checkpoint-v2"
PROVENANCE = frozenset({"host_observed", "agent_asserted", "unknown"})
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
ABSTRACT_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
PRIVATE_NAME = re.compile(r"prompt|response|transcript|command|argv|query|path|filename|source_code|environment|credential|secret|token|password|authorization|cookie|private_key", re.I)


def validate_envelope(value):
    required = {"schema_version", "checkpoint", "scope_id", "policy_revision",
                "state_revision", "state_provenance", "observations", "provenance"}
    if (type(value) is not dict or set(value) not in (required, required | {"decision"})
            or value["schema_version"] != VERSION):
        raise ValueError("bounded v2 local checkpoint envelope required")
    for key in ("scope_id", "policy_revision"):
        if type(value[key]) is not str or not IDENTIFIER.fullmatch(value[key]):
            raise ValueError("opaque local binding required")
    if (type(value["checkpoint"]) is not str or not ABSTRACT_IDENTIFIER.fullmatch(value["checkpoint"])
            or type(value["state_provenance"]) is not str or value["state_provenance"] not in PROVENANCE
            or type(value["state_revision"]) is not int or not 0 <= value["state_revision"] <= 1_000_000):
        raise ValueError("bounded checkpoint event and observed counter required")
    observations, provenance = value["observations"], value["provenance"]
    if (type(observations) is not dict or len(observations) > 24
            or type(provenance) is not dict or set(provenance) != set(observations)):
        raise ValueError("bounded observations with explicit provenance required")
    for name, item in observations.items():
        if (type(name) is not str or not ABSTRACT_IDENTIFIER.fullmatch(name) or PRIVATE_NAME.search(name)
                or type(provenance[name]) is not str or provenance[name] not in PROVENANCE):
            raise ValueError("abstract observation with explicit provenance required")
        if item is None:
            if provenance[name] != "unknown":
                raise ValueError("unknown observation needs unknown provenance")
        elif (provenance[name] == "unknown" or not (type(item) is bool
                or type(item) in (int, float) and abs(item) <= 1_000_000 and math.isfinite(item)
                or type(item) is str and ABSTRACT_IDENTIFIER.fullmatch(item))):
            raise ValueError("bounded scalar observation required")
    result = {**value, "observations": dict(observations), "provenance": dict(provenance)}
    if "decision" in value:
        try:
            result["decision"] = json.loads(json.dumps(validate_request(value["decision"]), allow_nan=False))
        except JevFailure as error:
            raise ValueError("explicit authored v2 decision required") from error
        if result["decision"]["execution_state"]["revision"] != value["state_revision"]:
            raise ValueError("authored decision must match observed revision")
    try:
        size = len(json.dumps(result, allow_nan=False, separators=(",", ":")).encode())
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError("bounded checkpoint JSON required") from error
    if size > 16_384:
        raise ValueError("checkpoint envelope exceeds bounds")
    return result


def projection(envelope):
    """Return authored content exactly; host observations remain local."""
    value = validate_envelope(envelope)
    if "decision" not in value:
        raise ValueError("native_authorship_required")
    return value["decision"]


def consult(envelope, evaluator, *, enabled=True, is_current=None, capabilities=(),
            cancelled=None, clock=time.monotonic):
    started = clock()
    result = dict(category="checkpoint", eligible=False, requested=False, called=False,
                  provider_attempt="NOT_ATTEMPTED", accepted=False, applied=False, cached=False,
                  recommendation="defer_to_agent", reason="native_authorship_required",
                  fallback_class="agent", latency_ms=0.0, provider_selected_option="UNKNOWN",
                  provider_confidence="UNKNOWN", acceptance_threshold=0.90,
                  provider_evidence="UNKNOWN", rejection_reason="native_authorship_required",
                  consultation_id=uuid.uuid4().hex, advice_delivered=False,
                  action_admitted=False, receipt_consumed=False, execution_observed=False,
                  task_validated=False, model_use="UNKNOWN", state_provenance="unknown")

    def finish(reason):
        result["reason"] = reason
        result["rejection_reason"] = "NONE" if result["accepted"] else reason
        result["latency_ms"] = max(0.0, (clock() - started) * 1000)
        return result

    # Old local envelopes, missing authorship and invalid authored payloads must
    # never revive the retired projection or cause a provider attempt.
    if type(envelope) is not dict or envelope.get("schema_version") != VERSION or "decision" not in envelope:
        return finish("native_authorship_required")
    try:
        value = validate_envelope(envelope)
    except (ValueError, TypeError):
        return finish("native_authorship_required")
    request = value["decision"]
    result.update(eligible=True, checkpoint=value["checkpoint"], state_provenance=value["state_provenance"])

    def current():
        try:
            return is_current is None or is_current(value) is True
        except Exception:
            return False

    def stopped():
        try:
            return cancelled is not None and cancelled() is not False
        except Exception:
            return True

    if not enabled:
        return finish("disabled")
    if stopped():
        return finish("cancelled")
    if not current():
        return finish("stale_state")
    result["requested"] = True
    try:
        advice = evaluator(json.loads(json.dumps(request, allow_nan=False)))
    except Exception:
        result["provider_attempt"] = "UNKNOWN"
        return finish("unavailable")
    if type(advice) is not dict:
        result["provider_attempt"] = "UNKNOWN"
        return finish("malformed_output")
    usage = advice.get("usageEvidence")
    usage = usage if type(usage) is dict else {}
    result["called"] = advice.get("called", usage.get("providerAttempted")) is True
    attempt = "CONFIRMED" if result["called"] else advice.get("provider_attempt", "UNKNOWN")
    result["provider_attempt"] = attempt if type(attempt) is str and attempt in {"CONFIRMED", "NOT_ATTEMPTED", "UNKNOWN"} else "UNKNOWN"
    if stopped():
        return finish("cancelled")
    if not current():
        return finish("stale_state")
    action = advice.get("provider_selected_action", advice.get("selected_action"))
    confidence = advice.get("confidence")
    valid_confidence = type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1
    effect = option_effect(request, action) if type(action) is str else None
    if effect is not None:
        # Authored ids and prose are not retained in checkpoint telemetry.
        result["provider_selected_option"] = "AUTHORED_OPTION"
    if valid_confidence:
        result["provider_confidence"] = confidence
    evidence = advice.get("evidence")
    if type(evidence) is str and evidence in {"timeout", "uncertain", "hard_policy", "native_choice_probabilities", "missing_credential", "rate_limited", "circuit_open", "closed", "worker_failure", "cancelled"}:
        result["provider_evidence"] = evidence
    if effect == "agent":
        return finish("delegation_to_agent")
    if not valid_confidence or effect is None or type(advice.get("fallback_required", False)) is not bool:
        return finish("malformed_output")
    if confidence < 0.90:
        return finish("low_confidence")
    if advice.get("fallback_required") or advice.get("selected_action") != action:
        return finish("provider_fallback")
    if not result["called"] or result["provider_evidence"] != "native_choice_probabilities":
        return finish("provider_evidence_missing")
    if not allowed_action(request, action, capabilities=capabilities):
        return finish("hard_policy")
    result.update(accepted=True, fallback_class="none", recommendation=effect)
    return finish("advice")


def envelope_schema():
    """Local observation wrapper with optional explicit authored decision."""
    identifier = {"type": "string", "pattern": "^[A-Za-z0-9_.:-]{1,128}$"}
    abstract = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$", "maxLength": 64}
    origin = {"type": "string", "enum": sorted(PROVENANCE)}
    properties = {"schema_version": {"const": VERSION}, "checkpoint": dict(abstract),
                  "scope_id": dict(identifier), "policy_revision": dict(identifier),
                  "state_revision": {"type": "integer", "minimum": 0, "maximum": 1_000_000},
                  "state_provenance": dict(origin),
                  "observations": {"type": "object", "maxProperties": 24, "propertyNames": dict(abstract),
                    "additionalProperties": {"anyOf": [{"type": "null"}, {"type": "boolean"},
                        {"type": "number", "minimum": -1_000_000, "maximum": 1_000_000}, dict(abstract)]}},
                  "provenance": {"type": "object", "maxProperties": 24, "propertyNames": dict(abstract), "additionalProperties": dict(origin)},
                  "decision": dynamic_schema()}
    return {"type": "object", "properties": properties, "required": [key for key in properties if key != "decision"], "additionalProperties": False}


class CheckpointTracker:
    """Bounded host observations only; the native model must author any advice."""
    def __init__(self, scope_id=None):
        self.scope_id = scope_id or uuid.uuid4().hex
        self.revision = 0
        self.inspected = False
        self.signatures = OrderedDict()

    def observe(self, *, inspection=False, writes=False, outcome="unknown", signature=None):
        if outcome not in {"success", "failure", "test_failure", "unknown", "unchanged"}:
            raise ValueError("categorical observed result required")
        if signature is not None and (type(signature) is not str or not re.fullmatch(r"[0-9a-f]{64}", signature)):
            raise ValueError("local signature required")
        self.revision = min(1_000_000, self.revision + 1)
        repeats = 0
        if signature is not None:
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
        observations = {"inspection_returned": inspection, "mutation_observed": writes,
                        "repeat_count": repeats, "observed_result": outcome}
        return dict(schema_version=VERSION, checkpoint=checkpoint, scope_id=self.scope_id,
                    policy_revision="existing-scope", state_revision=self.revision,
                    state_provenance="host_observed", observations=observations,
                    provenance={name: "host_observed" for name in observations})

    def current(self, envelope):
        return envelope["scope_id"] == self.scope_id and envelope["state_revision"] == self.revision
