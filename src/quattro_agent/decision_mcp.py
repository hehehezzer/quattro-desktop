"""Private stdio adapter for session-wide operational advice in Codex execution.

Routed Pi delegates to the same Codex harness; its UI tool prohibitions remain
unchanged. This adapter never executes actions and never returns provider text.
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
from quattro_agent.decision_taxonomy import ACTIONS, CONTEXT_FLAGS, CONTEXT_CATEGORIES


DESCRIPTION = (
    "Prefer this fast decision service over lengthy model deliberation for routine "
    "context, sequencing/parallelization, test-order, retry, and continue-versus-validate "
    "choices at meaningful execution milestones. Not for every tool call. Pass only "
    "categorical signals, never prompt text, code, paths, tool output, or secrets. "
    "Increment revision whenever execution evidence changes. Use agent reasoning on "
    "fallback_required, ambiguous semantic choices, architecture, or debugging. "
    "The selected action is advice: Quattro permissions, user constraints, budgets, "
    "hard retry limits and mandatory validation always win. This tool cannot select "
    "models, authorize actions, certify validation, or complete a task."
)


def tool_spec():
    return {"name": "operational_decision", "description": DESCRIPTION,
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": False, "openWorldHint": True}, "inputSchema": {
        "type": "object", "additionalProperties": False,
        "required": ["decision_type", "available_actions", "relevant_context",
                     "hard_constraints", "execution_state", "previous_result"],
        "properties": {
            "decision_type": {"type": "string", "enum": list(ACTIONS)},
            "available_actions": {"type": "array", "minItems": 2, "maxItems": 4,
                                  "uniqueItems": True,
                                  "description": "Use actions for the selected type; always include agent. " +
                                  json.dumps({name: list(actions) for name, actions in ACTIONS.items()}),
                                  "items": {"type": "string", "enum": sorted({action for actions in ACTIONS.values() for action in actions})}},
            "relevant_context": {"type": "object", "additionalProperties": False,
                                 "properties": {**{name: {"type": "boolean"} for name in sorted(CONTEXT_FLAGS)},
                                                **{name: {"type": "string", "enum": list(values)}
                                                   for name, values in CONTEXT_CATEGORIES.items()}}},
            "hard_constraints": {"type": "object", "additionalProperties": False,
                                 "required": ["retry_allowed", "parallel_allowed", "retrieval_allowed"],
                                 "properties": {name: {"type": "boolean"} for name in
                                                ("retry_allowed", "parallel_allowed", "retrieval_allowed")}},
            "execution_state": {"type": "object", "additionalProperties": False,
                                "required": ["revision", "phase", "attempt"], "properties": {
                                    "revision": {"type": "integer", "minimum": 0, "maximum": 1000000},
                                    "phase": {"type": "string", "enum": ["inspection", "implementation", "validation", "completion"]},
                                    "attempt": {"type": "integer", "minimum": 0, "maximum": 100}}},
            "previous_result": {"type": "string", "enum": ["none", "success", "transient_failure", "test_failure", "unknown_failure"]},
        },
    }}


def handle(message, session):
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
        response["result"] = {"tools": [tool_spec()]}
    elif method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict) or params.get("name") != "operational_decision":
            response["error"] = {"code": -32602, "message": "unsupported decision tool"}
        else:
            result = session.decide(params.get("arguments"))
            result["telemetry"] = session.snapshot()
            response["result"] = {"content": [{"type": "text", "text": json.dumps(result, allow_nan=False)}]}
    else:
        response["error"] = {"code": -32601, "message": "unsupported method"}
    return response


class NativeDecisionProxy:
    """No provider access in an execution child; use the existing session gate."""
    def __init__(self):
        self.telemetry = {}

    def decide(self, request):
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
    args = parser.parse_args()
    session = NativeDecisionProxy() if args.native_proxy else DecisionSession(mode=args.mode, timeout_ms=args.timeout_ms)
    try:
        while True:
            line = sys.stdin.buffer.readline(8193)
            if not line:
                break
            if len(line) > 8192:
                break  # Bounded framing; never interpret a truncated request.
            try:
                response = handle(json.loads(line), session)
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
