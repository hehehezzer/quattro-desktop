import unittest
from unittest import mock
from quattro_agent.operational_advice import OperationalAdvisor, refine_query


class AdviceTests(unittest.TestCase):
    def make(self):
        self.evaluator = mock.Mock(side_effect=AssertionError("legacy provider request"))
        return OperationalAdvisor(self.evaluator, enabled=True)

    def test_host_denial_and_sensitive_owner_gate_never_call(self):
        advisor = self.make()
        for features in ({"host_allowed": False}, {"host_allowed": True, "sensitive": True}):
            result = advisor.handle("preflight", features)
            self.assertIn(result["recommendation"], {"stop", "ask_owner"})
            self.assertTrue(result["applied"])
            self.assertFalse(result["requested"])
        self.evaluator.assert_not_called()

    def test_forged_raw_features_rejected(self):
        advisor = self.make()
        for features in ({"command": "send secret"}, {"host_allowed": "true"}, {"query": "private source"}):
            with self.assertRaises(ValueError):
                advisor.handle("preflight", features)

    def test_opaque_cannot_proceed(self):
        self.assertEqual(self.make().handle("preflight", {"host_allowed": True, "opaque": True})["recommendation"], "ask_owner")

    def test_approval_assertion_cannot_override_host_denial_or_authorize_opaque_action(self):
        advisor = self.make()
        for allowed, expected in ((False, "stop"), (True, "ask_owner")):
            result = advisor.handle("preflight", {"host_allowed": allowed, "owner_approved": True, "opaque": True})
            self.assertEqual(result["recommendation"], expected)
            self.assertFalse(result["accepted"])
            self.assertFalse(result["called"])
        self.evaluator.assert_not_called()

    def test_host_guard_pass_is_not_provider_acceptance_or_permission(self):
        result = self.make().handle("preflight", {"host_allowed": True, "writes": True})
        self.assertFalse(result["accepted"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["recommendation"], "proceed")
        self.assertEqual(result["provider_attempt"], "NOT_ATTEMPTED")
        self.evaluator.assert_not_called()

    def test_rag_scope_and_evidence_guards(self):
        advisor = self.make()
        self.assertEqual(advisor.handle("rag", {"retrieval_allowed": False})["recommendation"], "stop")
        self.assertEqual(advisor.handle("rag", {"retrieval_allowed": True, "evidence_sufficient": True})["recommendation"], "stop_retrieval")
        self.assertEqual(advisor.handle("rag", {"retrieval_allowed": True})["recommendation"], "bounded_retrieval")
        self.evaluator.assert_not_called()

    def test_no_template_generated_at_any_legacy_boundary(self):
        advisor = self.make()
        for operation in ("task", "rag", "preflight"):
            result = advisor.handle(operation, {"host_allowed": True, "retrieval_allowed": True})
            self.assertFalse(result["requested"])
            self.assertFalse(result["called"])
        self.evaluator.assert_not_called()

    def test_loop_changes_plan_then_blocks_identical_input_without_provider(self):
        advisor = self.make()
        results = [advisor.handle("feedback", {}, fingerprint="a" * 64, outcome="test_failure") for _ in range(8)]
        self.assertEqual(results[2]["recommendation"], "change_plan")
        self.assertEqual(results[-1]["recommendation"], "ask_owner")
        self.assertTrue(results[-1]["applied"])
        self.evaluator.assert_not_called()

    def test_disabled_and_progress_reset(self):
        advisor = self.make()
        advisor.enabled = False
        self.assertEqual(advisor.handle("preflight", {"host_allowed": True})["reason"], "disabled")
        advisor.enabled = True
        for _ in range(2):
            advisor.handle("feedback", {}, fingerprint="b" * 64, outcome="failure")
        advisor.handle("feedback", {}, fingerprint="b" * 64, outcome="success")
        self.assertEqual(advisor.handle("feedback", {}, fingerprint="b" * 64, outcome="failure")["reason"], "below_threshold")

    def test_local_loop_state_is_bounded(self):
        advisor = self.make()
        for i in range(300):
            advisor.handle("feedback", {}, fingerprint=f"{i:064x}", outcome="failure")
        self.assertLessEqual(len(advisor.states), 256)

    def test_refinement_is_local_bounded_and_not_provider_instruction(self):
        self.assertEqual(refine_query("please tell about repository architecture and architecture"), "repository architecture")
        self.assertLessEqual(len(refine_query(" ".join("term" + str(i) for i in range(100))).split()), 24)
        with self.assertRaises(ValueError):
            refine_query("x" * 2001)
