"""Trusted launcher registration for the optional runtime decision tool.

The context is local to a harness call, not process-global configuration. Native
Codex owns its MCP lifetime. Routed Pi uses that same Codex execution adapter.
"""
from __future__ import annotations

from contextvars import ContextVar
import json
from pathlib import Path
import sys

from .policy import NetworkAccess

OPTIONS: ContextVar[dict | None] = ContextVar("jev_runtime_options", default=None)
NATIVE_PROXY: ContextVar[dict | None] = ContextVar("jev_native_proxy", default=None)


def proxy_environment():
    return dict(NATIVE_PROXY.get() or {})


def codex_arguments(policy, options=None, *, native_proxy=False):
    options = OPTIONS.get() if options is None else options
    native_proxy = native_proxy or bool(NATIVE_PROXY.get())
    test_recovery = (sys.platform == "linux" and (options.get("experimentalTestRecovery") is True
                      or options.get("testRecoveryMode") == "COOPERATIVE") and bool(policy.writable_roots)
                     if isinstance(options, dict) else False)
    global_mode = options.get("mode") if isinstance(options, dict) else None
    test_class_mode = options.get("testRecoveryMode") if isinstance(options, dict) else None
    tool_mode = "COOPERATIVE" if (global_mode == "COOPERATIVE"
                                  or test_class_mode == "COOPERATIVE") else "OFF"
    if (not isinstance(options, dict) or global_mode not in {"OFF", "COOPERATIVE"}
            or not (global_mode == "COOPERATIVE" or test_recovery)
            or (not native_proxy and policy.network is not NetworkAccess.FULL)):
        return ()
    timeout = options.get("timeoutMs", 1500)
    if type(timeout) is not int or not 100 <= timeout <= 3000:
        return ()
    script = str(Path(__file__).with_name("decision_mcp.py").resolve())
    values = {
        "command": sys.executable,
        "args": [script, "--mode", tool_mode, "--timeout-ms", str(timeout),
                 *(["--test-only"] if global_mode == "OFF" else []),
                 *(["--test-recovery"] if test_recovery else []),
                 *(["--native-proxy"] if native_proxy else [])],
        "env_vars": ["QUATTRO_TURN_GATE_URL", "QUATTRO_DECISION_TOKEN"] if native_proxy else [],
        "enabled": True,
        "required": False,
        "startup_timeout_sec": 5,
        "tool_timeout_sec": 45 if test_recovery else 5,
    }
    return tuple(arg for name, value in values.items()
                 for arg in ("-c", "mcp_servers.quattro_decisions." + name + "=" + json.dumps(value)))
