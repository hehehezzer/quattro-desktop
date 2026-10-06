"""Bounded test execution preserves failures for model-authored recovery."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent.recovering_test import recovering_test
from quattro_agent.adapters import AgentMode, PiAdapter, RunSpec
from quattro_agent.decision_launch import OPTIONS, codex_arguments
from quattro_agent.policy import policy_profile
from quattro_agent.decision_mcp import handle
from quattro_agent.turn_gate import TurnGate
from quattro_agent.decision_taxonomy import allowed_action


class Choice:
    def __init__(self, action=None, edit=None):
        self.action = action
        self.edit = edit
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        if self.edit:
            self.edit()
        return {"selected_action": self.action, "fallback_required": self.action is None,
                "evidence": "uncertain" if self.action is None else "choice", "confidence": 0.9,
                "timing": {"rtt_ms": 50, "blocking_ms": 75, "request_body_bytes": 400}}


class RecoveringTestTests(unittest.TestCase):
    def test_retry_exact_requires_retry_budget(self):
        request = {"schema_version": "quattro-jev-decisions-v2", "decision_id": "failed_check_next_step",
                   "question": "Should this unchanged bounded check be repeated now?",
                   "options": [{"id": "repeat_check", "description": "Repeat the existing bounded check once", "effect": "retry_exact", "capability": "retry_exact"},
                               {"id": "reason_about_failure", "description": "Continue native reasoning about the failure", "effect": "agent"}],
                   "context": {"check_failed": True},
                   "execution_state": {"revision": 1, "phase": "validation", "attempt": 1}, "previous_result": "failed",
                   "hard_constraints": {"retry_allowed": False,
                                        "parallel_allowed": False, "retrieval_allowed": False}}
        self.assertFalse(allowed_action(request, "repeat_check", capabilities={"retry_exact": True}))
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tests").mkdir()
        self.test_file = self.root / "tests" / "test_flaky.py"
        self.test_file.write_text(
            "import pathlib, time, unittest\n"
            "class Check(unittest.TestCase):\n"
            " def test_ready(self):\n"
            "  time.sleep(0.6)\n"
            "  marker=pathlib.Path(__file__).with_name('ready.marker')\n"
            "  if not marker.exists():\n"
            "   marker.write_text('ready')\n"
            "   self.fail('expected ready True, got False after wait')\n"
        )
        (self.root / "tests" / "test_sanity.py").write_text(
            "import unittest\nclass Check(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n")

    def test_real_failure_preserved_without_hidden_static_retry_decision(self):
        choice = Choice("retry_exact")
        result = recovering_test(self.root, "test_flaky.py", choice)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["offloaded"])
        self.assertFalse(result["useful_result"])
        self.assertEqual(result["initial_exit_code"], 1)
        self.assertIn("AssertionError", result["initial_output"])
        self.assertTrue(result["needs_agent_action"])
        self.assertEqual(result["fallback"], "model_decision_required")
        self.assertEqual(choice.requests, [])
        self.assertNotIn("recovery_exit_code", result)
        # A subsequent explicit host invocation remains available to the model.
        second = recovering_test(self.root, "test_flaky.py", choice)
        self.assertEqual(second["status"], "passed")
        self.assertEqual(choice.requests, [])

    def test_disabled_preserves_failure_for_agent(self):
        result = recovering_test(self.root, "test_flaky.py", None)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["offloaded"])
        self.assertEqual(result["fallback"], "not_admitted")

    def test_legacy_choice_cannot_mutate_files_or_trigger_an_implicit_retry(self):
        choice = Choice("retry_exact", edit=mock.Mock(side_effect=AssertionError("provider mutation")))
        result = recovering_test(self.root, "test_flaky.py", choice)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["fallback"], "model_decision_required")
        choice.edit.assert_not_called()
        self.assertEqual(choice.requests, [])

    def test_name_and_symlink_guard(self):
        for name in ("../outside.py", "test_missing.py", "test_bad;touch.py"):
            self.assertEqual(recovering_test(self.root, name, Choice())["status"], "invalid")
        (self.root / "tests" / "test_link.py").symlink_to(self.test_file)
        self.assertEqual(recovering_test(self.root, "test_link.py", Choice())["status"], "invalid")

    def test_pi_tool_requires_explicit_profile_and_gate(self):
        policy = policy_profile("full-access-explicit", project_root=self.root)
        spec = RunSpec(task_id="t", run_id="r", project_path=self.root,
                       mode=AgentMode.PROMPT, policy=policy, private_input="test")
        baseline = PiAdapter().build_launch("/usr/bin/pi", spec)
        self.assertIn("--no-extensions", baseline.argv)
        self.assertNotIn("quattro_test", ",".join(baseline.argv))
        token = OPTIONS.set({"mode": "COOPERATIVE", "experimentalTestRecovery": True})
        try:
            plan = PiAdapter().build_launch("/usr/bin/pi", spec)
        finally:
            OPTIONS.reset(token)
        self.assertIn("--no-extensions", plan.argv)
        self.assertIn("-e", plan.argv)
        self.assertIn("quattro_test", ",".join(plan.argv))
        self.assertEqual(plan.environment_overrides["QUATTRO_TEST_ALLOWED"], "1")

    def test_class_gate_does_not_enable_other_jev_advice(self):
        codex_policy = policy_profile("workspace-write", project_root=self.root)
        args = codex_arguments(codex_policy, {"mode": "OFF", "testRecoveryMode": "COOPERATIVE",
                                               "timeoutMs": 1200})
        encoded = " ".join(args)
        self.assertIn("--test-recovery", encoded)
        self.assertIn("--test-only", encoded)
        listing = handle({"id": 1, "method": "tools/list"}, Choice(),
                         test_enabled=True, advisory_enabled=False)
        self.assertEqual([tool["name"] for tool in listing["result"]["tools"]], ["quattro_test"])
        gate = object.__new__(TurnGate)
        gate._decision_options = {"mode": "OFF", "testRecoveryMode": "COOPERATIVE"}
        service = gate._new_decisions()
        self.assertEqual(service.mode, "COOPERATIVE")
        service.close()
        other = {"schema_version": "quattro-jev-decisions-v2", "decision_id": "check_evidence_review",
                 "question": "Which evidence review should follow the failed check?",
                 "options": [{"id": "review_evidence", "description": "Inspect current check evidence", "effect": "inspect"},
                             {"id": "native_deliberation", "description": "Continue native model deliberation", "effect": "agent"}],
                 "context": {},
                 "hard_constraints": {"retry_allowed": False, "parallel_allowed": False,
                                      "retrieval_allowed": False},
                 "execution_state": {"revision": 0, "phase": "inspection", "attempt": 0},
                 "previous_result": "none"}
        self.assertEqual(gate.decide(other)["evidence"], "inactive_or_stale")


if __name__ == "__main__":
    unittest.main()
