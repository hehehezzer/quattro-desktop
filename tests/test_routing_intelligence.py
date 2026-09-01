from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.routing_intelligence import (
    Availability,
    BenchmarkEvidence,
    ContextClass,
    Level,
    ModelCandidate,
    PreferenceMode,
    Risk,
    RoutingTierName,
    Scope,
    benchmark_quality,
    canonical_model_identity,
    evaluate_candidates,
    load_benchmark_cache,
    load_local_outcomes,
    model_identity_record,
    normalize_benchmark_score,
    profile_task,
    record_local_outcome,
    replay_snapshot,
    routing_snapshot,
    save_benchmark_cache,
)
from quattro_agent.omniroute import validate_manual_route_requirements
from quattro_agent.errors import ConfigError


ALL_CAPABILITIES = frozenset({
    "conversation", "coding", "repository_read", "repository_write", "shell", "git",
    "tool_calling", "research", "long_context", "structured_output", "vision",
})


def candidate(
    model: str,
    *,
    quality: float = 0.75,
    cost: float = 1.0,
    limit: int | None = 200_000,
    availability: Availability = Availability.AVAILABLE,
    capabilities: frozenset[str] = ALL_CAPABILITIES,
    latency: float = 500,
) -> ModelCandidate:
    return ModelCandidate(
        provider="provider-a",
        model=model,
        capabilities=capabilities,
        practical_input_limit=limit,
        availability=availability,
        retry_eligible=False,
        metadata_quality=quality,
        input_cost_per_million=cost,
        output_cost_per_million=cost * 2,
        expected_input_tokens=10_000,
        expected_output_tokens=2_000,
        latency_ms=latency,
    )


class TaskProfileMatrixTests(unittest.TestCase):
    def assert_profile(
        self,
        prompt: str,
        tier: RoutingTierName,
        *,
        task_type: str | None = None,
        capability: str | None = None,
    ) -> None:
        result = profile_task(prompt)
        self.assertEqual(result.tier, tier, result.to_dict())
        if task_type:
            self.assertEqual(result.task_type, task_type)
        if capability:
            self.assertIn(capability, result.required_capabilities)

    def test_01_typo(self) -> None:
        self.assert_profile("Fix a typo in README.md", RoutingTierName.FAST, task_type="documentation")

    def test_02_simple_rename_ignores_unrelated_sensitive_noun(self) -> None:
        result = profile_task("Rename Foo to Bar in README; the prose mentions authentication.")
        self.assertEqual(result.tier, RoutingTierName.FAST)
        self.assertEqual(result.risk, Risk.LOW)
        self.assertEqual(result.scope, Scope.LOCAL)
        self.assertIn("repository_write", result.required_capabilities)

    def test_03_small_bug(self) -> None:
        self.assert_profile("Fix the bounded null check bug in one parser and run tests", RoutingTierName.STANDARD)

    def test_04_ordinary_feature(self) -> None:
        self.assert_profile("Implement a normal export feature and unit tests", RoutingTierName.STANDARD)

    def test_05_multi_file_feature(self) -> None:
        result = profile_task("Implement a bounded multi-file feature across two modules with tests")
        self.assertEqual(result.tier, RoutingTierName.STANDARD)
        self.assertEqual(result.scope, Scope.MULTI_MODULE)

    def test_06_unknown_debugging_problem(self) -> None:
        result = profile_task("Investigate an intermittent unknown failure that cannot reproduce")
        self.assertEqual(result.tier, RoutingTierName.REASONING)
        self.assertEqual(result.ambiguity, Level.HIGH)
        self.assertEqual(result.verification_strength.value, "weak")

    def test_07_architecture_design(self) -> None:
        self.assert_profile("Design the system architecture and trade-offs", RoutingTierName.REASONING, task_type="architecture")

    def test_08_concurrency_bug(self) -> None:
        self.assert_profile("Fix a race condition and deadlock across workers", RoutingTierName.REASONING, task_type="concurrency")

    def test_09_authentication_security_change(self) -> None:
        result = profile_task("Fix an intermittent authorization bypass in the repository")
        self.assertEqual(result.tier, RoutingTierName.REASONING)
        self.assertIn(result.risk, {Risk.HIGH, Risk.CRITICAL})
        self.assertIn("repository_write", result.required_capabilities)

    def test_10_database_migration(self) -> None:
        self.assert_profile("Migrate the database schema and backfill every row", RoutingTierName.REASONING, task_type="database_migration")

    def test_11_huge_context_repository_task(self) -> None:
        result = profile_task("Analyze the entire repository with huge context before implementing the change")
        self.assertEqual(result.context_requirement, ContextClass.VERY_LARGE)
        self.assertIn("long_context", result.required_capabilities)

    def test_12_trivial_docs(self) -> None:
        self.assert_profile("Update the docs label from Old to New", RoutingTierName.FAST, task_type="documentation")


class CandidateGateAndSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.standard = profile_task("Implement a normal API feature and unit tests")

    def test_13_quota_exhausted_preferred_provider_falls_back(self) -> None:
        unavailable = candidate("cheap", cost=0.1, availability=Availability.QUOTA_EXHAUSTED)
        fallback = candidate("fallback", cost=1.0)
        result = evaluate_candidates(self.standard, [unavailable, fallback])
        self.assertEqual(result.selected_model, "fallback")
        self.assertIn("unavailable:quota_exhausted", result.candidates[0].rejection_reasons)

    def test_14_insufficient_context_model_is_rejected(self) -> None:
        huge = profile_task("Analyze the entire repository with huge context before implementing")
        result = evaluate_candidates(huge, [candidate("small", limit=32_000), candidate("large", limit=200_000, quality=0.9)])
        self.assertEqual(result.selected_model, "large")
        self.assertIn("insufficient_context", result.candidates[0].rejection_reasons)

    def test_15_low_cost_below_quality_candidate_is_rejected(self) -> None:
        result = evaluate_candidates(self.standard, [
            candidate("cheap-weak", quality=0.3, cost=0.01),
            candidate("capable", quality=0.72, cost=1.0),
        ])
        self.assertEqual(result.selected_model, "capable")
        self.assertIn("below_quality_threshold", result.candidates[0].rejection_reasons)

    def test_16_expensive_high_quality_model_does_not_win_by_default(self) -> None:
        result = evaluate_candidates(self.standard, [
            candidate("sufficient", quality=0.75, cost=1.0),
            candidate("strongest", quality=0.98, cost=20.0),
        ])
        self.assertEqual(result.selected_model, "sufficient")

    def test_missing_execution_capability_is_hard_rejection(self) -> None:
        web = candidate("web", capabilities=frozenset({"conversation", "coding"}), cost=0)
        execution = candidate("execution", cost=1)
        result = evaluate_candidates(self.standard, [web, execution])
        self.assertEqual(result.selected_model, "execution")
        self.assertTrue(result.candidates[0].rejection_reasons[0].startswith("missing_capability:"))

    def test_stable_tie_break_is_provider_then_model(self) -> None:
        result = evaluate_candidates(self.standard, [candidate("z"), candidate("a")])
        self.assertEqual(result.selected_model, "a")

    def test_quality_mode_adds_margin_without_bypassing_gates(self) -> None:
        result = evaluate_candidates(
            self.standard,
            [candidate("barely", quality=0.67), candidate("margin", quality=0.75, cost=2)],
            preference=PreferenceMode.QUALITY,
        )
        self.assertEqual(result.selected_model, "margin")


class EvidenceAndReplayTests(unittest.TestCase):
    def benchmark(self) -> BenchmarkEvidence:
        return BenchmarkEvidence(
            source="swe-bench",
            source_url="https://swebench.com/verified",
            benchmark="SWE-bench Verified",
            provider="provider-a",
            canonical_model="gpt-test",
            model_version="2026-01",
            variant="base",
            source_date="2026-01-01T00:00:00+00:00",
            retrieved_at="2026-02-01T00:00:00+00:00",
            confidence=0.9,
            dimensions={"repository_task_score": 0.82, "coding_score": 0.78},
        )

    def test_benchmark_cache_round_trip_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "cache.json"
            version = save_benchmark_cache(path, [self.benchmark()])
            records = load_benchmark_cache(path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source, "swe-bench")
        self.assertEqual(len(version), 64)
        self.assertEqual(normalize_benchmark_score("SWE-bench Verified", 82), 0.82)
        with self.assertRaisesRegex(ValueError, "not registered"):
            normalize_benchmark_score("random blog score", 82)

    def test_malformed_or_unallowlisted_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "cache.json"
            row = self.benchmark().to_dict()
            row["source_url"] = "https://benchmark-blog.invalid/value"
            path.write_text(json.dumps({"schema_version": 1, "records": [row]}))
            with self.assertRaisesRegex(ValueError, "allowlisted"):
                load_benchmark_cache(path)

    def test_exact_model_variant_match_has_benchmark_evidence(self) -> None:
        profile = profile_task("Implement a repository feature and tests")
        score, confidence = benchmark_quality(candidate("gpt-test"), profile, [self.benchmark()])
        self.assertIsNotNone(score)
        self.assertGreater(confidence, 0)
        self.assertEqual(canonical_model_identity("provider-a", "gpt-test-lite")[2], "lite")
        self.assertIn("external_aliases", model_identity_record("provider-a", "gpt-test-lite"))

    def test_local_outcomes_require_samples_before_strong_influence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "outcomes.json"
            for _ in range(5):
                row = record_local_outcome(
                    path,
                    provider="provider-a",
                    model="model-a",
                    task_type="implementation",
                    tier="STANDARD",
                    execution_success=True,
                    validated_success=True,
                )
            loaded = load_local_outcomes(path)
        self.assertEqual(row.samples, 5)
        self.assertEqual(row.confidence, 0.25)
        self.assertEqual(len(loaded), 1)

    def test_execution_success_is_separate_from_validated_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "outcomes.json"
            row = record_local_outcome(
                path,
                provider="omniroute",
                model="auto/coding",
                task_type="implementation",
                tier="STANDARD",
                execution_success=True,
                validated_success=None,
            )
        self.assertEqual(row.execution_successes, 1)
        self.assertEqual(row.validation_observed, 0)
        self.assertIsNone(row.validated_success_rate)

    def test_17_failed_fast_task_escalation_is_covered_by_existing_policy(self) -> None:
        from quattro_agent.routing import RoutingDecision, RoutingTier, next_tier
        fast = RoutingDecision(RoutingTier.FAST, "test", "low")
        self.assertIsNone(next_tier(fast, evidence="formatter failed", max_automatic_escalations=2))
        escalated = next_tier(fast, evidence="cannot determine root cause after repeated attempts", max_automatic_escalations=2)
        self.assertEqual(escalated.tier, RoutingTier.STANDARD)

    def test_18_standard_success_requires_no_escalation(self) -> None:
        from quattro_agent.routing import RoutingDecision, RoutingTier, next_tier
        standard = RoutingDecision(RoutingTier.STANDARD, "test", "medium")
        self.assertIsNone(next_tier(standard, evidence="tests passed", max_automatic_escalations=2))

    def test_19_under_sampled_candidate_is_neutral_not_optimistically_best(self) -> None:
        profile = profile_task("Implement a normal API feature and unit tests")
        result = evaluate_candidates(profile, [
            candidate("known", quality=0.72, cost=1),
            candidate("unknown", quality=0.5, cost=0.01),
        ])
        self.assertEqual(result.selected_model, "known")

    def test_20_explicit_model_override_replays_without_substitution(self) -> None:
        profile = profile_task("Fix a typo in README")
        snapshot = routing_snapshot(
            profile,
            route="account-1/gpt-5.6-luna",
            configured_model="account-1/gpt-5.6-luna",
        )
        replay = replay_snapshot(snapshot)
        self.assertTrue(replay["matches"])
        self.assertEqual(replay["replayed_route"], "account-1/gpt-5.6-luna")

    def test_deterministic_auto_replay(self) -> None:
        profile = profile_task("Implement a normal API feature and unit tests")
        snapshot = routing_snapshot(profile, route="auto/coding", configured_model="auto")
        self.assertTrue(replay_snapshot(snapshot)["matches"])

    def test_manual_override_rejects_known_vision_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "catalog.json"
            rows = [
                {"slug": slug, "input_modalities": ["text"]}
                for slug in ("auto", "auto/coding:cheap", "auto/coding", "auto/reasoning", "manual-text")
            ]
            path.write_text(json.dumps({"models": rows}))
            with self.assertRaisesRegex(ConfigError, "does not support vision"):
                validate_manual_route_requirements(
                    path,
                    "manual-text",
                    required_capabilities=("vision",),
                    estimated_tokens=100,
                )

    def test_manual_override_rejects_known_context_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "catalog.json"
            rows = [
                {"slug": slug, "context_window": 8_000, "effective_context_window_percent": 90}
                for slug in ("auto", "auto/coding:cheap", "auto/coding", "auto/reasoning", "manual-small")
            ]
            path.write_text(json.dumps({"models": rows}))
            with self.assertRaisesRegex(ConfigError, "practical context limit"):
                validate_manual_route_requirements(
                    path,
                    "manual-small",
                    required_capabilities=("conversation",),
                    estimated_tokens=7_500,
                )


if __name__ == "__main__":
    unittest.main()
