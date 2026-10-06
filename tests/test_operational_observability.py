"""Legacy host guards never report fabricated provider evidence."""
import unittest
from unittest import mock
from quattro_agent.operational_advice import OperationalAdvisor


class OperationalObservabilityTests(unittest.TestCase):
    def test_host_denial_owner_and_agent_categories_distinct(self):
        advisor = OperationalAdvisor(mock.Mock(side_effect=AssertionError("provider")), enabled=True)
        cases = [("preflight", {"host_allowed": False}, "policy"),
                 ("preflight", {"host_allowed": True, "sensitive": True}, "owner"),
                 ("task", {"writes": True}, "agent"),
                 ("preflight", {"host_allowed": True}, "none")]
        for operation, features, fallback in cases:
            result = advisor.handle(operation, features)
            self.assertEqual(result["fallback_class"], fallback)
            self.assertEqual(result["provider_attempt"], "NOT_ATTEMPTED")
            self.assertEqual(result["provider_selected_option"], "UNKNOWN")
            self.assertEqual(result["provider_confidence"], "UNKNOWN")
            self.assertFalse(result["accepted"])
            self.assertFalse(result["called"])
        advisor.evaluator.assert_not_called()

    def test_guard_pass_keeps_permission_and_application_separate(self):
        result = OperationalAdvisor(enabled=True).handle("preflight", {"host_allowed": True})
        self.assertFalse(result["applied"])
        self.assertFalse(result["accepted"])
        self.assertEqual(result["recommendation"], "proceed")

    def test_guard_telemetry_contains_no_fingerprints_or_model_text(self):
        events = []
        advisor = OperationalAdvisor(enabled=True, emit=events.append)
        for _ in range(4):
            advisor.handle("feedback", {}, fingerprint="a" * 64, outcome="failure")
        self.assertNotIn("a" * 64, str(events))
        self.assertTrue(all(event["provider_attempt"] == "NOT_ATTEMPTED" for event in events))
