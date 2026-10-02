import unittest
from quattro_agent.operational_advice import OperationalAdvisor, refine_query


class AdviceTests(unittest.TestCase):
    def make(self, action="continue", confidence=.99, **extra):
        self.requests = []
        def evaluate(request):
            self.requests.append(request)
            return dict(selected_action=action, confidence=confidence, called=True, **extra)
        return OperationalAdvisor(evaluate, enabled=True)

    def test_host_denial_and_sensitive_owner_gate_never_call(self):
        advisor = self.make()
        for features in ({"host_allowed": False}, {"host_allowed": True, "sensitive": True}):
            result = advisor.handle("preflight", features)
            self.assertIn(result["recommendation"], {"stop", "ask_owner"})
            self.assertFalse(result["requested"])
        self.assertEqual(self.requests, [])

    def test_forged_raw_features_rejected(self):
        advisor = self.make()
        for features in ({"command": "send secret"}, {"host_allowed": "true"}, {"query": "private source"}):
            with self.assertRaises(ValueError):
                advisor.handle("preflight", features)

    def test_opaque_or_uncertain_cannot_proceed(self):
        for confidence in (.3, float("nan"), 1.1):
            self.assertEqual(self.make(confidence=confidence).handle("preflight", {"host_allowed": True})["recommendation"], "ask_owner")
        self.assertEqual(self.make().handle("preflight", {"host_allowed": True, "opaque": True})["recommendation"], "ask_owner")

    def test_valid_preflight_is_advice_not_application(self):
        result = self.make().handle("preflight", {"host_allowed": True, "writes": True})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["recommendation"], "proceed")

    def test_rag_denied_and_enough_evidence_stop_without_call(self):
        advisor = self.make("retrieve")
        self.assertEqual(advisor.handle("rag", {"retrieval_allowed": False})["recommendation"], "stop")
        self.assertEqual(advisor.handle("rag", {"retrieval_allowed": True, "evidence_sufficient": True})["recommendation"], "stop_retrieval")
        self.assertEqual(self.requests, [])

    def test_rag_minimal_features_no_query_and_bounded_strategy(self):
        result = self.make("inspect").handle("rag", {"retrieval_allowed": True})
        self.assertEqual(result["recommendation"], "narrow_retrieval")
        self.assertEqual(self.requests[0]["relevant_context"], {"context_missing": True, "retrieval_required": True})
        self.assertNotIn("query", str(self.requests))

    def test_loop_changes_plan_once_instead_of_unbounded_baseline(self):
        advisor = self.make("change_strategy")
        results = [advisor.handle("feedback", {}, fingerprint="a" * 64, outcome="test_failure") for _ in range(8)]
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(results[2]["recommendation"], "change_plan")
        self.assertEqual(results[-1]["recommendation"], "ask_owner")
        self.assertNotIn("a" * 64, str(self.requests))
        # Baseline repeats all eight failures. Intervened harness stops at three.
        baseline = 8
        intervened = next(i + 1 for i, r in enumerate(results) if r["recommendation"] == "change_plan")
        self.assertLess(intervened, baseline)

    def test_unavailable_and_wrong_category_fail_conservatively(self):
        advisor = OperationalAdvisor(lambda _: (_ for _ in ()).throw(TimeoutError()), enabled=True)
        self.assertEqual(advisor.handle("preflight", {"host_allowed": True})["recommendation"], "ask_owner")
        self.assertEqual(self.make("parallel").handle("preflight", {"host_allowed": True})["recommendation"], "ask_owner")

    def test_disabled_and_progress_reset(self):
        advisor = self.make("change_strategy")
        advisor.enabled = False
        self.assertFalse(advisor.handle("preflight", {"host_allowed": True})["requested"])
        advisor.enabled = True
        for _ in range(2):
            advisor.handle("feedback", {}, fingerprint="b" * 64, outcome="failure")
        advisor.handle("feedback", {}, fingerprint="b" * 64, outcome="success")
        self.assertEqual(advisor.handle("feedback", {}, fingerprint="b" * 64, outcome="failure")["reason"], "below_threshold")

    def test_recursive_callback_no_nested_provider_call(self):
        advisor = self.make()
        def recursive(request):
            nested = advisor.handle("preflight", {"host_allowed": True})
            self.assertEqual(nested["reason"], "recursive")
            return {"selected_action": "continue", "confidence": .99, "called": True}
        advisor.evaluator = recursive
        self.assertTrue(advisor.handle("preflight", {"host_allowed": True})["accepted"])

    def test_identical_state_cooldown_is_not_global_call_cap(self):
        advisor = self.make(confidence=.2)
        clock = [0]
        advisor.clock = lambda: clock[0]
        advisor.handle("preflight", {"host_allowed": True, "writes": True})
        again = advisor.handle("preflight", {"host_allowed": True, "writes": True})
        self.assertEqual(again["reason"], "cooldown")
        self.assertFalse(again["called"])
        advisor.handle("preflight", {"host_allowed": True, "writes": False})
        clock[0] = 31
        advisor.handle("preflight", {"host_allowed": True, "writes": True})
        self.assertEqual(len(self.requests), 3)

    def test_refinement_is_local_bounded_and_not_provider_instruction(self):
        self.assertEqual(refine_query("please tell about repository architecture and architecture"), "repository architecture")
        self.assertLessEqual(len(refine_query(" ".join("term" + str(i) for i in range(100))).split()), 24)
        with self.assertRaises(ValueError):
            refine_query("x" * 2001)
