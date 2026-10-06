"""Native host guards and explicit authored checkpoint advice; no grant creation."""
from collections import OrderedDict
import json
import threading
import uuid

from .native_intelligence import (NativeContext, NativeTelemetry, load_native_settings,
                                  native_config_path, native_config_is_unsafe, native_jev_advice)
from .operational_advice import OperationalAdvisor
from .decision_checkpoint import consult, validate_envelope

_sessions = OrderedDict()
_lock = threading.RLock()


def _operational_configuration_state():
    """Distinguish an explicit host disable from an unsafe configuration."""
    try:
        path = native_config_path()
        if native_config_is_unsafe(path):
            return "unsafe"
        if not path.is_file():
            return "disabled"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unsafe"
    if type(raw) is not dict:
        return "unsafe"
    enabled = raw.get("operationalEnabled", False)
    if type(enabled) is not bool:
        return "unsafe"
    return "enabled" if enabled else "disabled"


def operational_enabled():
    return _operational_configuration_state() == "enabled"


def operational_call(arguments, *, context=None, decision_session=None, capabilities=()):
    if type(arguments) is not dict or set(arguments) - {"operation", "features", "fingerprint", "outcome", "checkpoint", "decision"}:
        raise ValueError("bounded operational request required")
    checkpoint = arguments.get("operation") == "checkpoint"
    if checkpoint:
        if set(arguments) - {"operation", "checkpoint", "decision"}:
            raise ValueError("guard fields on checkpoint operation")
    elif "checkpoint" in arguments or "decision" in arguments:
        raise ValueError("authored checkpoint fields on wrong operation")
    # Unsafe settings are not an owner-authorized guard disable. Links and
    # existing nonregular files deny before any content read; malformed host
    # flags deny before settings lookup, advisor creation or provider activity.
    configuration_state = _operational_configuration_state()
    if configuration_state == "unsafe":
        operation = arguments.get("operation")
        category = operation if type(operation) is str and operation in {"preflight", "rag", "feedback", "task", "checkpoint"} else "host_guard"
        return dict(category=category, eligible=False, requested=False, called=False,
                    accepted=False, applied=True, cached=False, recommendation="stop", reason="host_denied",
                    latency_ms=0.0, fallback_class="policy", provider_attempt="NOT_ATTEMPTED",
                    provider_selected_option="UNKNOWN", provider_confidence="UNKNOWN", acceptance_threshold=0.90,
                    provider_evidence="UNKNOWN", rejection_reason="host_denied",
                    coverage="unsafe_host_configuration; no_provider_consultation")
    context = context or NativeContext()
    # Anonymous one-shot requests must never share loop history.
    key = (context.host, context.session_id, context.project)
    settings = load_native_settings()
    # The explicit host control enables deterministic guards independently of
    # the model's advisory preferences. Turning Jev off cannot approve a tool
    # or reset no-progress observations; it only disables consultations.
    guards_enabled = configuration_state == "enabled"
    consultation_enabled = guards_enabled and settings.enabled and context.session_enabled
    if checkpoint:
        envelope = arguments.get("checkpoint")
        if "decision" in arguments:
            if type(envelope) is not dict or "decision" in envelope:
                raise ValueError("duplicate or misplaced authored decision")
            envelope = dict(envelope, decision=arguments["decision"])
        try:
            validated = validate_envelope(envelope)
        except ValueError:
            # consult returns an explicit local authorship requirement for old
            # observations or malformed decisions, without provider activity.
            validated = envelope
        else:
            # Model JSON cannot attest host observations, policy or grants.
            validated["state_provenance"] = "agent_asserted"
            validated["provenance"] = {
                name: "unknown" if value is None else "agent_asserted"
                for name, value in validated["observations"].items()}

        def evaluate(request):
            return native_jev_advice(request, context=context,
                                    decision_session=decision_session,
                                    capabilities=capabilities, cacheable=False)

        # Fresh native context and trusted capabilities are separate from the
        # authored envelope. Checkpoints never reuse provider advice caches.
        result = consult(validated, evaluate, enabled=consultation_enabled, capabilities=capabilities)
    else:
        with _lock:
            advisor = _sessions.get(key)
            if advisor is None:
                advisor = OperationalAdvisor(None)
                if context.session_id != "unknown":
                    _sessions[key] = advisor
                    while len(_sessions) > 128:
                        _sessions.popitem(last=False)
            advisor.enabled = guards_enabled
            result = advisor.handle(arguments.get("operation"), arguments.get("features", {}),
                                    fingerprint=arguments.get("fingerprint"), outcome=arguments.get("outcome"))
    trace = "operation-" + uuid.uuid4().hex[:20]
    requested = checkpoint and result.get("requested") is True
    NativeTelemetry(enabled=settings.telemetry_enabled).record(
        kind="jev" if requested else "instrumentation",
        stage="validated" if requested else "skipped",
        status=("ACCEPTED" if result.get("accepted") else "FALLBACK") if requested else "GUARD_ONLY",
        context=context, trace_id=trace, metadata=result)
    result["traceId"] = trace
    result["coverage"] = ("checkpoint_advice_returned; native_action_application_unknown" if requested
                          else "local_checkpoint_result; no_provider_consultation" if checkpoint
                          else "deterministic_host_guard; no_provider_consultation")
    return result
