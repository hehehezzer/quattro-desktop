import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from quattro_agent import operational_native as operation
from quattro_agent.native_intelligence import NativeContext
from quattro_agent import shared_intelligence
import quattro_intelligence_mcp as mcp


class NativeOperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "native.json"
        self.config.write_text(json.dumps({"enabled": True, "operationalEnabled": True}))
        env = mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(self.config),
            "QUATTRO_NATIVE_TELEMETRY_DB": str(Path(self.tmp.name) / "metadata.sqlite3")})
        env.start(); self.addCleanup(env.stop)
        operation._sessions.clear()

    def test_activation_defaults_off(self):
        self.config.write_text('{"enabled":true}')
        with mock.patch.object(operation, "native_jev_advice") as evaluator:
            result = operation.operational_call({"operation": "preflight", "features": {"host_allowed": True}})
        evaluator.assert_not_called()
        self.assertEqual(result["reason"], "disabled")

    def test_codex_explicit_guard_returns_without_authorizing(self):
        with mock.patch.object(operation, "native_jev_advice", return_value={"selected_action": "continue", "confidence": .99, "called": True}):
            result = operation.operational_call({"operation": "preflight", "features": {"host_allowed": True, "writes": True}}, context=NativeContext(host="codex", session_id="test"))
        self.assertEqual(result["recommendation"], "proceed")
        self.assertFalse(result["applied"])
        tool = next(t for t in mcp.TOOLS if t["name"] == "operational_guard")
        self.assertFalse(tool["inputSchema"]["properties"]["features"]["additionalProperties"])

    def test_rag_advice_only_narrows_existing_search(self):
        with mock.patch.object(operation, "native_jev_advice", return_value={"selected_action": "inspect", "confidence": .99, "called": True}), mock.patch.object(shared_intelligence, "search_knowledge", return_value={"context": None}) as search:
            shared_intelligence.call("search_knowledge", {"query": "synthetic", "limit": 8, "budget": 4000})
        self.assertEqual(search.call_args.kwargs["limit"], 2)
        self.assertEqual(search.call_args.kwargs["budget"], 2000)

    def test_rag_denied_does_not_search(self):
        self.config.write_text(json.dumps({"enabled": True, "operationalEnabled": True, "retrievalEnabled": False}))
        with mock.patch.object(shared_intelligence, "search_knowledge") as search, mock.patch.object(operation, "native_jev_advice") as advice:
            result = shared_intelligence.call("search_knowledge", {"query": "synthetic"})
        search.assert_not_called(); advice.assert_not_called()
        self.assertIsNone(result["context"])

    def test_rag_advice_preserves_stricter_caller_budget(self):
        with mock.patch.object(operation, "native_jev_advice", return_value={"selected_action": "inspect", "confidence": .99, "called": True}), mock.patch.object(shared_intelligence, "search_knowledge", return_value={"context": None}) as search:
            shared_intelligence.call("search_knowledge", {"query": "repository architecture", "budget": 100, "limit": 1})
        self.assertEqual(search.call_args.kwargs['budget'], 100)
        self.assertEqual(search.call_args.kwargs['limit'], 1)

    def test_trivial_query_never_becomes_retrieval_after_refinement(self):
        with mock.patch.object(operation, 'native_jev_advice') as advice, mock.patch.object(shared_intelligence, 'RetrievalStore', side_effect=AssertionError('unexpected retrieval')):
            result = shared_intelligence.call('search_knowledge', {'query': 'what is 2 times 3'})
        advice.assert_not_called()
        self.assertEqual(result['retrievedTokens'], 0)

    def test_session_separation_and_provider_payload_no_fingerprint(self):
        with mock.patch.object(operation, "native_jev_advice", return_value={"selected_action": "change_strategy", "confidence": .99, "called": True}) as evaluate:
            for host in ("pi", "codex"):
                for _ in range(3):
                    operation.operational_call({"operation": "feedback", "features": {}, "fingerprint": "f" * 64, "outcome": "failure"}, context=NativeContext(host=host, session_id="same"))
        self.assertEqual(evaluate.call_count, 2)
        self.assertNotIn("f" * 64, str(evaluate.call_args_list))

    def test_codex_mcp_guard_actual_tool_boundary(self):
        with mock.patch.object(mcp, "DecisionSession") as session, mock.patch.object(operation, "native_jev_advice", return_value={"selected_action": "continue", "confidence": .99, "called": True}):
            runtime = mcp.NativeMcpRuntime()
            try:
                result = runtime.handle_call(1, {"name": "operational_guard", "arguments": {
                    "operation": "preflight", "features": {"host_allowed": True, "writes": True}}})
            finally:
                runtime.close()
        self.assertEqual(result["structuredContent"]["recommendation"], "proceed")
        self.assertFalse(result["structuredContent"]["applied"])
