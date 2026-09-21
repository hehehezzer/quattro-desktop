from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.errors import ConfigError
from quattro_agent.model_registry import (
    default_policy_path, execution_target_for_route, load_model_registry, select_execution_target,
    target_matches_actual,
)
from quattro_agent.routing_intelligence import profile_task


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "src/quattro/omniroute-model-catalog.json"


class ModelRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.targets = load_model_registry(default_policy_path(), CATALOG)

    def test_trivial_request_selects_smallest_verified_target(self) -> None:
        profile = profile_task(
            "hello", agent="codex", workflow="direct-response", policy_name="audit-read-only",
        )
        target = select_execution_target(profile, self.targets, preferred_account="account-1")
        self.assertEqual(target.tier, "FAST")
        self.assertEqual(target.route, "account-1/gpt-5.6-luna")
        self.assertEqual(target.mode, "EXPLICIT")
        self.assertEqual(target.fallbacks[0], "account-2/gpt-5.6-luna")

    def test_conceptual_explanation_stays_chat_minimal(self) -> None:
        profile = profile_task(
            "Explain dependency injection.", agent="codex",
            workflow="direct-response", policy_name="audit-read-only",
        )
        self.assertEqual(profile.tier.value, "FAST")
        self.assertEqual(profile.task_type, "conversation")
        self.assertEqual(profile.context_profile.value, "CHAT_MINIMAL")
        self.assertEqual(profile.required_capabilities, ("conversation",))

    def test_tiers_select_distinct_capability_policy(self) -> None:
        standard = profile_task(
            "Implement a bounded parser and add regression tests.", agent="codex",
            workflow="prompt", policy_name="workspace-write",
        )
        reasoning = profile_task(
            "Audit the distributed authorization architecture and diagnose a race condition.",
            agent="codex", workflow="prompt", policy_name="audit-read-only",
        )
        standard_target = select_execution_target(
            standard, self.targets, preferred_account="account-2",
        )
        reasoning_target = select_execution_target(
            reasoning, self.targets, preferred_account="account-1",
        )
        self.assertEqual(standard_target.route, "account-2/gpt-5.6-terra")
        self.assertEqual(reasoning_target.route, "account-1/gpt-5.6-sol")

    def test_registry_rejects_unapproved_route(self) -> None:
        payload = json.loads(default_policy_path().read_text())
        payload["targets"][0]["route"] = "account-1/invented-model"
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "models.json"
            policy.write_text(json.dumps(payload))
            with self.assertRaises(ConfigError):
                load_model_registry(policy, CATALOG)

    def test_registry_rejects_identity_or_capability_claims_not_in_catalog(self) -> None:
        payload = json.loads(default_policy_path().read_text())
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "models.json"
            payload["targets"][0]["provider"] = "invented-provider"
            policy.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ConfigError, "identity does not match"):
                load_model_registry(policy, CATALOG)
            payload = json.loads(default_policy_path().read_text())
            payload["targets"][0]["capabilities"].append("vision")
            policy.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ConfigError, "absent from trusted catalog"):
                load_model_registry(policy, CATALOG)

    def test_unavailable_account_is_removed_before_selection(self) -> None:
        profile = profile_task(
            "hello", agent="codex", workflow="direct-response", policy_name="audit-read-only",
        )
        target = select_execution_target(
            profile, self.targets, preferred_account="account-1",
            unavailable_routes=frozenset({"account-1/gpt-5.6-luna"}),
        )
        self.assertEqual(target.route, "account-2/gpt-5.6-luna")

    def test_disabled_accounts_are_not_eligible(self) -> None:
        profile = profile_task(
            "hello", agent="codex", workflow="direct-response", policy_name="audit-read-only",
        )
        target = select_execution_target(
            profile, self.targets, preferred_account="account-1",
            available_accounts=frozenset({"account-2"}),
        )
        self.assertEqual(target.account, "account-2")

    def test_target_fidelity_is_exact_with_known_provider_alias(self) -> None:
        profile = profile_task(
            "hello", agent="codex", workflow="direct-response", policy_name="audit-read-only",
        )
        target = select_execution_target(profile, self.targets, preferred_account="account-1")
        self.assertTrue(target_matches_actual(
            target, actual_provider="cx", actual_model="gpt-5.6-luna",
        ))
        self.assertFalse(target_matches_actual(
            target, actual_provider="cx", actual_model="gpt-5.6-luna-high",
        ))
        self.assertFalse(target_matches_actual(
            target, actual_provider="other", actual_model="gpt-5.6-luna",
        ))

    def test_manual_account_route_has_no_automatic_fallback(self) -> None:
        profile = profile_task(
            "hello", agent="codex", workflow="direct-response", policy_name="audit-read-only",
        )
        target = execution_target_for_route(
            profile, self.targets, "account-2/gpt-5.6-luna",
            available_accounts=frozenset({"account-1", "account-2"}),
        )
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.mode, "MANUAL")
        self.assertEqual(target.fallbacks, ())


if __name__ == "__main__":
    unittest.main()
