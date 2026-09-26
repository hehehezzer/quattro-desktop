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
    if (not isinstance(options, dict) or options.get("mode") != "COOPERATIVE"
            or (not native_proxy and policy.network is not NetworkAccess.FULL)):
        return ()
    timeout = options.get("timeoutMs", 1500)
    if type(timeout) is not int or not 100 <= timeout <= 3000:
        return ()
    script = str(Path(__file__).with_name("decision_mcp.py").resolve())
    values = {
        "command": sys.executable,
        "args": [script, "--mode", "COOPERATIVE", "--timeout-ms", str(timeout),
                 *(["--native-proxy"] if native_proxy else [])],
        "env_vars": ["QUATTRO_TURN_GATE_URL", "QUATTRO_DECISION_TOKEN"] if native_proxy else [],
        "enabled": True,
        "required": False,
        "startup_timeout_sec": 5,
        "tool_timeout_sec": 5,
    }
    return tuple(arg for name, value in values.items()
                 for arg in ("-c", "mcp_servers.quattro_decisions." + name + "=" + json.dumps(value)))
