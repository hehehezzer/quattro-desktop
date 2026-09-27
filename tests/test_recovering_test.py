"""Bounded host test recovery with a real unittest child and fake Jev choice."""
from pathlib import Path
import sys
import tempfile
import unittest

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
        request = {"available_actions": ["retry_exact", "agent"],
                   "hard_constraints": {"retry_allowed": False,
                                        "parallel_allowed": False, "retrieval_allowed": False}}
        self.assertFalse(allowed_action(request, "retry_exact"))
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

    def test_real_failure_and_host_retry_recover(self):
        choice = Choice("retry_exact")
        result = recovering_test(self.root, "test_flaky.py", choice)
        self.assertEqual(result["status"], "recovered")
        self.assertTrue(result["offloaded"])
        self.assertTrue(result["useful_result"])
        self.assertEqual(result["initial_exit_code"], 1)
        self.assertEqual(result["recovery_exit_code"], 0)
        self.assertEqual(result["initial_output"], "")
        self.assertFalse(result["needs_agent_action"])
        self.assertEqual(choice.requests[0]["failure_summary"], "readiness_assertion_after_wait")
        self.assertNotIn("ready.marker", str(choice.requests[0]))
        self.assertNotIn("expected ready True", str(choice.requests[0]))

    def test_disabled_preserves_failure_for_agent(self):
        result = recovering_test(self.root, "test_flaky.py", None)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["offloaded"])
        self.assertEqual(result["fallback"], "not_admitted")

    def test_stale_test_file_rejects_choice(self):
        choice = Choice("retry_exact", edit=lambda: self.test_file.write_text(self.test_file.read_text() + "\n"))
        result = recovering_test(self.root, "test_flaky.py", choice)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["offloaded"])
        self.assertEqual(result["fallback"], "stale")

    def test_stale_imported_file_rejects_choice(self):
        helper = self.root / "helper.py"
        helper.write_text("READY = True\n")
        choice = Choice("retry_exact", edit=lambda: helper.write_text("READY = False\n"))
        result = recovering_test(self.root, "test_flaky.py", choice)
        self.assertEqual(result["fallback"], "stale")

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
        other = {"decision_type": "context_strategy", "available_actions": ["inspect", "agent"],
                 "relevant_context": {},
                 "hard_constraints": {"retry_allowed": False, "parallel_allowed": False,
                                      "retrieval_allowed": False},
                 "execution_state": {"revision": 0, "phase": "inspection", "attempt": 0},
                 "previous_result": "none"}
        self.assertEqual(gate.decide(other)["evidence"], "inactive_or_stale")


if __name__ == "__main__":
    unittest.main()
