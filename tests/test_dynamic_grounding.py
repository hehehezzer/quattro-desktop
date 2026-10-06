"""Hermetic host capability evidence and deterministic legacy boundary coverage."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from quattro_agent import shared_intelligence as shared
from quattro_agent.native_intelligence import NativeContext


class DynamicGroundingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "native.json"
        self.config.write_text(json.dumps({"enabled": True, "operationalEnabled": True}))
        patch = mock.patch.dict(os.environ, {
            "QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(self.config),
            "QUATTRO_NATIVE_TELEMETRY_DB": str(Path(self.tmp.name) / "events.sqlite3")})
        patch.start()
        self.addCleanup(patch.stop)

    def snapshot(self, *, available=True, tools=None):
        with mock.patch.object(shared, "rtk_status", return_value={"available": available, "supportedCommandRoots": ["git"], "availableCommandRoots": ["git"]}):
            return shared.decision_capabilities(host_tools=tools)

    def test_snapshot_checks_runtime_without_executing_command(self):
        result = self.snapshot(tools=["rtk_run", "search_knowledge", "rtk_status"])
        self.assertTrue(result["capabilities"]["tool.rtk_run"])
        self.assertTrue(result["capabilities"]["rtk.git"])
        self.assertTrue(result["capabilities"]["tool.search_knowledge"])
        self.assertFalse(result["rtk"]["command_executed"])
        self.assertFalse(result["host"]["grants_permissions"])
        self.assertEqual(result["host"]["network"], "unknown")
        self.assertFalse(result["capabilities"]["parallel"])
        self.assertFalse(result["capabilities"]["retry_exact"])

    def test_rtk_absent_or_not_registered_is_unavailable(self):
        for available, tools in [(False, ["rtk_run"]), (True, ["search_knowledge"]), (True, [])]:
            with self.subTest(available=available, tools=tools):
                result = self.snapshot(available=available, tools=tools)
                self.assertFalse(result["capabilities"]["tool.rtk_run"])
                self.assertFalse(result["capabilities"]["rtk.git"])

    def test_policy_allowlist_is_not_installed_client_support(self):
        result = self.snapshot()
        self.assertTrue(result["capabilities"]["rtk.git"])
        for unsupported in ("python", "cat", "yarn", "bun"):
            self.assertFalse(result["capabilities"]["rtk." + unsupported])
        with mock.patch.object(shared, "rtk_status", return_value={"available": True,
                "supportedCommandRoots": ["git"], "availableCommandRoots": []}):
            self.assertFalse(shared.decision_capabilities()["capabilities"]["rtk.git"])

    def test_caller_inventory_never_attests_foreign_tools_or_permissions(self):
        result = self.snapshot(tools=["search_knowledge", "bash", "root_shell", "allow_network"])
        self.assertTrue(result["capabilities"]["tool.search_knowledge"])
        for foreign in ("tool.bash", "tool.root_shell", "allow_network"):
            self.assertNotIn(foreign, result["capabilities"])
        self.assertEqual(result["host"]["authorization"], "not_attested")
        self.assertIn("root_shell", result["host"]["unverified_tools"])

    def test_feature_settings_narrow_actual_capabilities(self):
        self.config.write_text(json.dumps({"enabled": True, "rtkEnabled": False, "retrievalEnabled": False}))
        result = self.snapshot()
        self.assertFalse(result["capabilities"]["tool.rtk_run"])
        self.assertFalse(result["capabilities"]["tool.search_knowledge"])
        self.assertFalse(result["capabilities"]["tool.refresh_history"])
        with mock.patch.object(shared.subprocess, "run") as execute:
            self.assertFalse(shared.rtk_status()["available"])
            with self.assertRaises(RuntimeError):
                shared.rtk_run(["git", "status"])
        execute.assert_not_called()

    def test_retrieval_denial_is_independent_of_jev_and_guard_switches(self):
        self.config.write_text(json.dumps({"enabled": False, "operationalEnabled": False,
                                          "retrievalEnabled": False}))
        with mock.patch.object(shared, "RetrievalStore", side_effect=AssertionError("opened")), mock.patch.object(shared, "_directory", side_effect=AssertionError("inspected")):
            result = shared.call("search_knowledge", {"query": "bounded project architecture"})
            history = shared.call("refresh_history", {})
        self.assertEqual(result["route"], "retrieval_disabled")
        self.assertEqual(result["retrievedTokens"], 0)
        self.assertEqual(history["episodic"], "disabled")

    def test_discovery_cannot_take_model_grants(self):
        with self.assertRaises(ValueError):
            shared.call("decision_capabilities", {"permissions": {"root_shell": True}})
        with mock.patch.object(shared, "rtk_status", return_value={"available": False}):
            result = shared.call("decision_capabilities", {"__quattro_host_tools": ["search_knowledge"]})
        self.assertEqual(result["available_tools"], ["search_knowledge"])

    def test_dynamic_decision_gets_host_map_outside_provider_request(self):
        request = {"schema_version": "quattro-jev-decisions-v2", "decision_id": "validation_preparation",
                   "question": "Which bounded check should come next?",
                   "options": [{"id": "local_inspection", "description": "Inspect current check evidence", "effect": "inspect"},
                               {"id": "model_review", "description": "Continue native model deliberation", "effect": "agent"}],
                   "context": {"checks_prepared": True},
                   "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
                   "execution_state": {"revision": 1, "phase": "validation", "attempt": 0}, "previous_result": "none"}
        with mock.patch.object(shared, "rtk_status", return_value={"available": False}), mock.patch.object(shared, "native_jev_advice", return_value={}) as evaluate:
            shared.call("operational_decision", {**request, "__quattro_host_tools": ["search_knowledge", "root_shell"]},
                        telemetry_context=NativeContext(host="pi", session_id="synthetic"))
        self.assertEqual(evaluate.call_args.args[0], request)
        capabilities = evaluate.call_args.kwargs["capabilities"]
        self.assertTrue(capabilities["tool.search_knowledge"])
        self.assertNotIn("tool.root_shell", capabilities)
        self.assertFalse(capabilities["tool.rtk_run"])

    def test_rtk_subprocess_uses_minimal_environment(self):
        completed = mock.Mock(returncode=0, stdout="rtk synthetic", stderr="")
        with mock.patch.dict(os.environ, {"QUATTRO_SYNTHETIC_UNTRUSTED": "synthetic"}), mock.patch.object(shared.shutil, "which", return_value="/synthetic/rtk"), mock.patch.object(shared.subprocess, "run", return_value=completed) as execute:
            shared.rtk_status()
            self.assertNotIn("QUATTRO_SYNTHETIC_UNTRUSTED", execute.call_args.kwargs["env"])
            self.assertEqual(execute.call_args_list[0].args[0], ["/synthetic/rtk", "--version"])
            self.assertEqual(execute.call_args_list[1].args[0], ["/synthetic/rtk", "--help"])
