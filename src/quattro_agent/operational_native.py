"""Opt-in native bridge for deterministic host guards; no provider requests."""
from collections import OrderedDict
import json
import threading
import uuid

from .native_intelligence import (NativeContext, NativeTelemetry, load_native_settings,
                                  native_config_path)
from .operational_advice import OperationalAdvisor

_sessions = OrderedDict()
_lock = threading.RLock()


def operational_enabled():
    try:
        path = native_config_path()
        return (path.is_file() and not path.is_symlink()
                and json.loads(path.read_text()).get("operationalEnabled") is True)
    except (OSError, ValueError):
        return False


def operational_call(arguments, *, context=None, decision_session=None):
    if type(arguments) is not dict or set(arguments) - {"operation", "features", "fingerprint", "outcome"}:
        raise ValueError("bounded operational request required")
    context = context or NativeContext()
    # Anonymous one-shot requests must never share loop history.
    key = (context.host, context.session_id, context.project)
    settings = load_native_settings()
    enabled = operational_enabled() and settings.enabled and context.session_enabled
    with _lock:
        advisor = _sessions.get(key)
        if advisor is None:
            advisor = OperationalAdvisor(None)
            if context.session_id != "unknown":
                _sessions[key] = advisor
                while len(_sessions) > 128:
                    _sessions.popitem(last=False)
        advisor.enabled = enabled
        result = advisor.handle(arguments.get("operation"), arguments.get("features", {}),
                                fingerprint=arguments.get("fingerprint"), outcome=arguments.get("outcome"))
    trace = "operation-" + uuid.uuid4().hex[:20]
    NativeTelemetry(enabled=settings.telemetry_enabled).record(
        kind="instrumentation", stage="skipped", status="GUARD_ONLY",
        context=context, trace_id=trace, metadata=result)
    result["traceId"] = trace
    result["coverage"] = "deterministic_host_guard; no_provider_consultation"
    return result
