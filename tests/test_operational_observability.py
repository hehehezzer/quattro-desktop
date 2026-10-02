"""Categorical evidence only; no live calls and no reconstructed past confidence."""
import unittest
from quattro_agent.operational_advice import OperationalAdvisor


class OperationalObservabilityTests(unittest.TestCase):
    def evaluate(self, payload):
        return OperationalAdvisor(lambda _: payload, enabled=True).handle("task", {"writes": True})

    def test_timeout_uncertainty_delegation_low_confidence_distinct(self):
        cases = [
            ({"fallback_required": True, "evidence": "timeout"}, "timeout", "UNKNOWN", "UNKNOWN"),
            ({"fallback_required": True, "evidence": "uncertain"}, "provider_uncertainty", "UNKNOWN", "UNKNOWN"),
            ({"fallback_required": True, "evidence": "uncertain", "provider_selected_action": "agent", "confidence": .98}, "delegation_to_agent", "agent", .98),
            ({"fallback_required": True, "evidence": "uncertain", "provider_selected_action": "continue", "confidence": .4}, "low_confidence", "continue", .4),
        ]
        for payload, reason, option, confidence in cases:
            with self.subTest(reason=reason):
                result = self.evaluate(payload)
                self.assertEqual(result["rejection_reason"], reason)
                self.assertEqual(result["provider_selected_option"], option)
                self.assertEqual(result["provider_confidence"], confidence)
                self.assertEqual(result["acceptance_threshold"], .90)
                self.assertFalse(result["accepted"])
                self.assertFalse(result["applied"])

    def test_malformed_output_never_retains_arbitrary_text(self):
        for payload in (None, "synthetic private response", {"selected_action": "synthetic private response", "confidence": .99}, {"selected_action": "continue", "confidence": float('nan')}):
            result = self.evaluate(payload)
            self.assertEqual(result["rejection_reason"], "malformed_output")
            self.assertNotIn("synthetic private response", str(result))
        self.assertEqual(self.evaluate({"selected_action": "continue", "confidence": float('nan')})["provider_confidence"], "UNKNOWN")

    def test_host_denial_and_provider_denial_distinct(self):
        calls = []
        advisor = OperationalAdvisor(lambda request: calls.append(request), enabled=True)
        result = advisor.handle("preflight", {"host_allowed": False})
        self.assertEqual(result["rejection_reason"], "host_denied")
        self.assertTrue(result["applied"])
        self.assertFalse(result["called"])
        self.assertEqual(calls, [])
        result = self.evaluate({"fallback_required": True, "evidence": "hard_policy", "confidence": .99, "provider_selected_action": "more_context"})
        self.assertEqual(result["rejection_reason"], "provider_denial")

    def test_accepted_advice_keeps_application_separate(self):
        result = self.evaluate({"selected_action": "validate", "confidence": .96, "called": True})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["rejection_reason"], "NONE")
        self.assertEqual(result["recommendation"], "validate_first")
        self.assertEqual(result["provider_selected_option"], "validate")

    def test_cached_rejection_keeps_original_reason_without_new_call(self):
        advisor = OperationalAdvisor(lambda _: {"selected_action": "continue", "confidence": .4, "called": True}, enabled=True)
        advisor.handle("task", {"writes": True})
        result = advisor.handle("task", {"writes": True})
        self.assertEqual(result["reason"], "cooldown")
        self.assertEqual(result["rejection_reason"], "low_confidence")
        self.assertEqual(result["provider_confidence"], .4)
        self.assertFalse(result["called"])
