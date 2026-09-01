from __future__ import annotations

import pathlib
import sys
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.routing import (
    RoutingTier, automatic_model_override, classify_request, context_budget_tokens,
    effective_reasoning_effort, next_exceptional_effort, next_tier,
)


CONFIG = {"routing": {
    "fastReasoningEffort": "low",
    "standardReasoningEffort": "medium",
    "reasoningReasoningEffort": "high",
    "maxAutomaticEscalations": 2,
    "exceptionalReasoningEffort": "ultra",
    "maxExceptionalEscalations": 1,
    "fastAutoRoute": "auto/coding:cheap",
    "standardAutoRoute": "auto/coding",
    "reasoningAutoRoute": "auto/reasoning",
    "fastContextBudgetTokens": 1200,
    "standardContextBudgetTokens": 2500,
    "reasoningContextBudgetTokens": 4000,
}}


class RoutingTests(unittest.TestCase):
    def test_simple_task_is_fast(self) -> None:
        for prompt in (
            "Locate the config symbol and summarize it",
            "Find the file that defines the authentication configuration. Do not modify anything.",
        ):
            decision = classify_request(request=prompt, config=CONFIG, agent="codex", workflow="general-task", policy_name="workspace-write")
            self.assertEqual(decision.tier, RoutingTier.FAST)
            self.assertEqual(decision.reasoning_effort, "low")

    def test_normal_implementation_and_uncertain_are_standard(self) -> None:
        implementation = classify_request(request="Implement the normal API integration and tests", config=CONFIG, agent="codex", workflow="general-task", policy_name="workspace-write")
        uncertain = classify_request(request="Please investigate this request", config=CONFIG, agent="codex", workflow="general-task", policy_name="workspace-write")
        self.assertEqual(implementation.tier, RoutingTier.STANDARD)
        self.assertEqual(uncertain.tier, RoutingTier.STANDARD)

    def test_security_and_architecture_are_reasoning(self) -> None:
        decision = classify_request(request="Make a security-critical architecture decision for concurrent auth", config=CONFIG, agent="codex", workflow="general-task", policy_name="workspace-write")
        self.assertEqual(decision.tier, RoutingTier.REASONING)
        self.assertEqual(decision.reasoning_effort, "high")

    def test_escalation_is_bounded_and_evidence_gated(self) -> None:
        fast = classify_request(request="Search for the handler", config=CONFIG, agent="codex", workflow="general-task", policy_name="workspace-write")
        self.assertIsNone(next_tier(fast, evidence="one test command failed", max_automatic_escalations=2))
        standard = next_tier(fast, evidence="The failure is ambiguous and requires root cause analysis", max_automatic_escalations=2)
        self.assertIsNotNone(standard)
        self.assertEqual(standard.tier, RoutingTier.STANDARD)
        reasoning = next_tier(standard, evidence="interacting failures remain ambiguous", max_automatic_escalations=2)
        self.assertIsNotNone(reasoning)
        self.assertEqual(reasoning.tier, RoutingTier.REASONING)
        self.assertIsNone(next_tier(reasoning, evidence="security ambiguity", max_automatic_escalations=2))
        exceptional = next_exceptional_effort(
            reasoning, evidence="The production incident still has interacting failures and no root cause",
            exceptional_effort="ultra", max_exceptional_escalations=1,
        )
        self.assertIsNotNone(exceptional)
        self.assertEqual(exceptional.reasoning_effort, "ultra")
        self.assertIsNone(next_exceptional_effort(
            exceptional, evidence="still unresolved root cause", exceptional_effort="ultra", max_exceptional_escalations=1,
        ))

    def test_auto_route_hints_respect_manual_model_choice(self) -> None:
        self.assertEqual(automatic_model_override(CONFIG, RoutingTier.FAST, "auto"), "auto/coding:cheap")
        self.assertEqual(automatic_model_override(CONFIG, RoutingTier.STANDARD, "auto"), "auto/coding")
        self.assertEqual(automatic_model_override(CONFIG, RoutingTier.REASONING, "auto"), "auto/reasoning")
        self.assertIsNone(automatic_model_override(CONFIG, RoutingTier.FAST, "auto/coding:cheap"))
        self.assertIsNone(automatic_model_override(CONFIG, RoutingTier.STANDARD, "auto/coding"))
        self.assertIsNone(automatic_model_override(CONFIG, RoutingTier.REASONING, "auto/reasoning"))
        self.assertIsNone(automatic_model_override(CONFIG, RoutingTier.FAST, "account-1/gpt-5.6-terra"))

    def test_context_budget_is_tier_aware_and_bounded(self) -> None:
        self.assertEqual(context_budget_tokens(CONFIG, RoutingTier.FAST), 1200)
        self.assertEqual(context_budget_tokens(CONFIG, RoutingTier.STANDARD), 2500)
        self.assertEqual(context_budget_tokens(CONFIG, RoutingTier.REASONING), 4000)
        invalid = {"routing": {"fastContextBudgetTokens": 100_000}}
        self.assertEqual(context_budget_tokens(invalid, RoutingTier.FAST), 1200)

    def test_effective_effort_is_authoritative_for_normal_and_exceptional_tiers(self) -> None:
        hostile = {"routing": dict(CONFIG["routing"], fastReasoningEffort="xhigh")}
        self.assertEqual(
            effective_reasoning_effort(hostile, {"tier": "FAST", "reasoning_effort": "xhigh"}),
            "low",
        )
        self.assertEqual(
            effective_reasoning_effort(CONFIG, {"tier": "REASONING", "reasoning_effort": "low"}),
            "high",
        )
        self.assertEqual(
            effective_reasoning_effort(CONFIG, {
                "tier": "REASONING", "reasoning_effort": "ultra",
                "exceptional_escalations": 1,
            }),
            "ultra",
        )


if __name__ == "__main__":
    unittest.main()
