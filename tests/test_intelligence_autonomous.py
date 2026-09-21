from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.intelligence.autonomous import (  # noqa: E402
    autonomous_agreement,
    autonomous_evidence_report,
    autonomous_training_rows,
)
from quattro_agent.intelligence.classical import (  # noqa: E402
    train_direct_delegate_model,
)


def _rows(count: int = 128) -> list[dict[str, object]]:
    categories = (
        "explanation", "external_research", "implementation", "repository_modification",
    )
    complexities = ("low", "medium", "high")
    rows: list[dict[str, object]] = []
    for index in range(count):
        decision = "DIRECT" if index % 2 == 0 else "DELEGATE"
        rows.append({
            "record_id": f"autonomous-{index}",
            "request_text": f"Explain or inspect independent request {index}",
            "request_fingerprint": f"{index:064x}",
            "group_fingerprint": f"group-{index}",
            "production_decision": decision,
            "ml_prediction": "DELEGATE" if index % 3 == 0 else "DIRECT",
            "outcome_success": index % 5 != 0,
            "selected_provider": "omniroute",
            "source_kind": "runtime",
            "entrypoint": "prompt",
            "task_category": categories[index % len(categories)],
            "complexity": complexities[index % len(complexities)],
            "category": "coding" if index % 2 else "reasoning",
            "request_length": 40 + index,
            "estimated_tokens": 10 + index,
            "repository_present": False,
            "repository_required": index % 2 == 1,
            "retrieval_required": index % 3 == 0,
            "tool_required": index % 4 == 0,
            "current_information_required": index % 5 == 0,
            "execution_required": index % 2 == 1,
            "modification_required": index % 3 == 1,
            "verification_required": index % 4 == 1,
            "multi_step_required": index % 5 == 1,
            "split": "train" if index < 80 else "validation" if index < 104 else "test",
            "created_at": f"2026-09-{(index % 28) + 1:02d}T00:00:00+00:00",
            "label": None,
            "label_source": "excluded",
            "label_independent": False,
            "holdout_sealed": False,
        })
    return rows


class AutonomousEvidenceTests(unittest.TestCase):
    def test_autonomous_targets_are_explicitly_not_human_gold(self) -> None:
        rows = _rows()
        projected = autonomous_training_rows(rows)
        self.assertEqual(len(projected), len(rows))
        self.assertEqual(
            {row["label_source"] for row in projected},
            {"autonomous_deterministic"},
        )
        self.assertEqual(
            {row["labeling_method"] for row in projected},
            {"autonomous_deterministic_observation_v1"},
        )
        self.assertTrue(all(row["gold_provenance"] is None for row in projected))
        expected = {
            row["group_fingerprint"]: row["production_decision"] for row in rows
        }
        self.assertEqual(
            {row["group_fingerprint"]: row["label"] for row in projected},
            expected,
        )
        outcomes = {
            row["group_fingerprint"]: row["outcome_success"] for row in rows
        }
        self.assertTrue(all(
            row["outcome_success"] == outcomes[row["group_fingerprint"]]
            for row in projected
        ))

    def test_training_readiness_separates_observations_from_promotion(self) -> None:
        _projected, report = autonomous_evidence_report(_rows())
        self.assertEqual(report["trainingReadiness"]["status"], "READY")
        self.assertTrue(report["trainingReadiness"]["gates"]["zeroFeatureLeakage"])
        self.assertFalse(report["protectedHumanGoldUsedAsAutonomousTarget"])
        self.assertEqual(report["humanGoldCreated"], 0)
        self.assertFalse(report["outcomeObservation"]["counterfactualAvailable"])

    def test_autonomous_candidate_training_is_explicit_and_offline(self) -> None:
        rows = autonomous_training_rows(_rows())
        with self.assertRaisesRegex(ValueError, "not independently sourced"):
            train_direct_delegate_model(
                rows,
                dataset_version="dd-autonomous-test",
                calibrate=False,
            )
        model = train_direct_delegate_model(
            rows,
            dataset_version="dd-autonomous-test",
            calibrate=False,
            allow_autonomous_sources=True,
        )
        self.assertEqual(
            model.payload["training"]["evidence_mode"],
            "autonomous_observation_experimental",
        )
        agreement = autonomous_agreement(model, rows)
        self.assertEqual(agreement["status"], "evaluated")
        self.assertTrue(agreement["notCounterfactual"])
        self.assertGreaterEqual(agreement["sampleCount"], 20)


if __name__ == "__main__":
    unittest.main()
