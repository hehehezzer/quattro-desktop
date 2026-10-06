"""Private stdio adapter for advice and gated host-owned recovery tools.

Routed Pi delegates to the same Codex harness. The optional test tool
runs only a fixed host argument vector and returns bounded results. Provider text
never directly becomes an executable command.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
from urllib.parse import urlsplit
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quattro_agent.decision_service import DecisionSession
from quattro_agent.decision_taxonomy import dynamic_schema
from quattro_agent.jev import decode
from quattro_agent.recovering_test import recovering_test


DESCRIPTION = (
    "Author the question, option ids/descriptions and relevant abstract context for "
    "the actual development decision, then call operational_decision. At substantive "
    "planning, tool/RTK choice, context, verification and next-action milestones, "
    "refresh decision_capabilities first and create a new decision when evidence "
    "changes. Options are 2..8 model-authored alternatives with exactly one effect "
    "agent fallback. Effect names are transport safety mappings, not a question "
    "catalog. Use capability ids returned by the host for capability-bearing options. "
    "Pass only abstract prose and scalar evidence: no prompts, source, paths, "
    "commands, outputs, credentials or copied retrieved text. Set constraints only "
    "to restrict existing authority. Increment revision when evidence changes. "
    "On fallback use native reasoning; never repeat unchanged decisions. Advice "
    "cannot grant permissions, create tools, select model/account, certify tests "
    "or complete work. Existing safety, budgets and mandatory checks always win."
)


def dynamic_tool_schema():
    return dynamic_schema()


def capability_tool_spec():
    return {"name": "decision_capabilities", "description":
            "Refresh host-observed decision capabilities before authoring alternatives. "
            "Availability is separate from permission; absent capabilities cannot be invented.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}


def managed_capabilities():
    """The managed session gate has no attested execution-tool inventory.

    This separate MCP boundary cannot claim another MCP's tools or native
    permissions. Capability-free advisory alternatives remain available.
    """
    return {"capabilities": {},
            "available_tools": ["operational_decision", "decision_capabilities"],
            "rtk": {"available": False, "status": "not_attested"},
            "retrieval": {"available": False, "status": "not_attested"},
            "host": {"permissions": "native_host_authoritative",
                     "grants_permissions": False, "authorization": "not_attested",
                     "reason": "managed_execution_inventory_unavailable"}}


def tool_spec():
    return {"name": "operational_decision", "description": DESCRIPTION,
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": False, "openWorldHint": True},
            "inputSchema": dynamic_tool_schema()}


def handle(message, session, *, test_enabled=False, advisory_enabled=True):
    if not isinstance(message, dict) or "id" not in message:
        return None
    method = message.get("method")
    response = {"jsonrpc": "2.0", "id": message["id"]}
    if method == "initialize":
        response["result"] = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "quattro-decisions", "version": "1.0.0"},
                              "instructions": DESCRIPTION}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        tools = [capability_tool_spec(), tool_spec()] if advisory_enabled else []
        if test_enabled:
            tools.append({"name": "quattro_test",
                          "description": "Run one bounded test file in tests/. Supply test_flaky.py or tests/test_flaky.py, never an absolute path. Run one bounded invocation; return failures for native model-authored follow-up.",
                          "annotations": {"readOnlyHint": False, "destructiveHint": False,
                                          "idempotentHint": False, "openWorldHint": False},
                          "inputSchema": {"type": "object", "additionalProperties": False,
                                          "required": ["test_file"], "properties": {
                                              "test_file": {"type": "string",
                                                            "pattern": "^(tests/)?test_[A-Za-z0-9_]{1,60}\\.py$"}}}})
        response["result"] = {"tools": tools}
    elif method == "tools/call":
        params = message.get("params")
        if isinstance(params, dict) and params.get("name") == "decision_capabilities" and advisory_enabled:
            if params.get("arguments", {}) != {}:
                response["error"] = {"code": -32602, "message": "invalid capability arguments"}
            else:
                result = managed_capabilities()
                response["result"] = {"content": [{"type": "text", "text": json.dumps(result)}]}
        elif isinstance(params, dict) and params.get("name") == "quattro_test" and test_enabled:
            arguments = params.get("arguments")
            if not isinstance(arguments, dict) or set(arguments) != {"test_file"}:
                response["error"] = {"code": -32602, "message": "invalid test arguments"}
            else:
                result = recovering_test(Path.cwd(), arguments["test_file"], session)
                response["result"] = {"content": [{"type": "text", "text": json.dumps(result, allow_nan=False)}],
                                      "isError": result["status"] in {"invalid", "failed"}}
        elif not isinstance(params, dict) or params.get("name") != "operational_decision" or not advisory_enabled:
            response["error"] = {"code": -32602, "message": "unsupported decision tool"}
        else:
            observed = managed_capabilities()
            trusted = [key for key, available in observed.get("capabilities", {}).items() if available is True]
            result = session.decide(params.get("arguments"), capabilities=trusted)
            result["outcome"] = "FALLBACK" if result["fallback_required"] else "ADVISORY"
            result["agent_reasoning_avoided"] = False
            result["telemetry"] = session.snapshot()
            response["result"] = {"content": [{"type": "text", "text": json.dumps(result, allow_nan=False)}]}
    else:
        response["error"] = {"code": -32601, "message": "unsupported method"}
    return response


class NativeDecisionProxy:
    """No provider access in an execution child; use the existing session gate."""
    def __init__(self):
        self.telemetry = {}

    def decide(self, request, **_kwargs):
        connection = None
        try:
            from quattro_agent.decision_taxonomy import validate_request
            validate_request(request)
            base = urlsplit(os.environ.get("QUATTRO_TURN_GATE_URL", ""))
            token = os.environ.get("QUATTRO_DECISION_TOKEN", "")
            if (base.scheme != "http" or base.hostname != "127.0.0.1" or not base.port
                    or base.path not in ("", "/") or base.query or base.fragment
                    or base.username or base.password or not token):
                raise ValueError("invalid private endpoint")
            connection = http.client.HTTPConnection(base.hostname, base.port, timeout=4)
            connection.request("POST", "/decision", json.dumps(request).encode(),
                               {"Content-Type": "application/json", "Authorization": "Bearer " + token})
            with connection.getresponse() as response:
                raw = response.read(32769)
                if response.status != 200 or len(raw) > 32768:
                    raise ValueError("invalid response")
            result = json.loads(raw)
            if not isinstance(result, dict) or type(result.get("fallback_required")) is not bool:
                raise ValueError("invalid decision")
            self.telemetry = result.pop("telemetry", {})
            return result
        except Exception:
            return {"selected_action": None, "confidence": None, "evidence": "session_unavailable",
                    "fallback_required": True}
        finally:
            if connection is not None:
                connection.close()

    def snapshot(self):
        return self.telemetry

    def close(self):
        pass  # The Quattro session, not this child, owns the provider worker.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("OFF", "SHADOW", "COOPERATIVE"), default="OFF")
    parser.add_argument("--timeout-ms", type=int, default=1500)
    parser.add_argument("--native-proxy", action="store_true")
    parser.add_argument("--test-recovery", action="store_true")
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    session = NativeDecisionProxy() if args.native_proxy else DecisionSession(mode=args.mode, timeout_ms=args.timeout_ms)
    try:
        while True:
            # The inner decision remains capped at 8192 bytes; JSON-RPC adds
            # method, request id and tool wrapper fields around that envelope.
            line = sys.stdin.buffer.readline(16385)
            if not line:
                break
            if len(line) > 16384:
                break  # Bounded framing; never interpret a truncated request.
            try:
                response = handle(decode(line), session, test_enabled=args.test_recovery,
                                  advisory_enabled=not args.test_only)
            except Exception:
                response = {"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32603, "message": "decision service unavailable"}}
            if response is not None:
                sys.stdout.write(json.dumps(response, allow_nan=False) + "\n")
                sys.stdout.flush()
    finally:
        session.close()


if __name__ == "__main__":
    main()
