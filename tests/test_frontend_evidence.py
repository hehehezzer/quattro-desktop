"""Forced frontend execution is history, not routing correctness evidence."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.intelligence.dataset import (
    DatasetBuilder, dataset_quality, frontend_evidence_projection,
    frontend_forced_execution, load_dataset, validate_dataset_identity,
)
from quattro_agent.intelligence.store import IntelligenceStore


class FrontendEvidenceTests(unittest.TestCase):
    def _row(self, **changes):
        row = {
            "record_id": "synthetic", "source_kind": "historical_task",
            "entrypoint": "interactive", "decision_applied": True,
            "production_decision": "DELEGATE", "outcome_success": True,
            "validation_status": "passed", "failure_category": None,
            "label": "DELEGATE", "label_source": "silver",
            "labeling_method": "silver_consensus", "label_independent": True,
            "request_fingerprint": "a" * 64, "group_fingerprint": "synthetic-group", "request_text": "Explain recursion",
            "split": "train", "holdout_sealed": False,
        }
        return row | changes

    def test_forced_execution_marked_regardless_of_legacy_applied_flag(self):
        for kind in ("historical_task", "durable_task"):
            for entrypoint in ("interactive", "resume"):
                for applied in (False, True):
                    original = self._row(source_kind=kind, entrypoint=entrypoint,
                                         decision_applied=applied)
                    projected = frontend_evidence_projection(original)
                    self.assertTrue(frontend_forced_execution(original))
                    self.assertEqual(projected["execution_provenance"], "frontend_forced_execution")
                    self.assertFalse(projected["production_evidence_eligible"])
                    self.assertIsNone(projected["production_decision"])
                    self.assertIsNone(projected["outcome_success"])
                    self.assertIsNone(projected["label"])
                    self.assertEqual(projected["reviewed_label"], "DELEGATE")
                    self.assertEqual(projected["observed_decision_applied"], applied)
                    self.assertEqual(original["production_decision"], "DELEGATE")
                    self.assertEqual(projected, frontend_evidence_projection(projected))

    def test_independent_blind_gold_survives_but_forced_outcome_does_not(self):
        for method in ("blind_human_review_v1", "blind_human_review_v2"):
            projected = frontend_evidence_projection(self._row(
                label="DIRECT", label_source="human_gold", labeling_method=method))
            self.assertEqual(projected["label"], "DIRECT")
            self.assertTrue(projected["classification_evidence_eligible"])
            self.assertTrue(projected["label_independent"])
            self.assertIsNone(projected["production_decision"])
            self.assertIsNone(projected["outcome_success"])
            self.assertEqual(projected, frontend_evidence_projection(projected))

    def test_exposed_review_and_conflicting_gold_are_not_classification_gold(self):
        for changes in ({"labeling_method": "legacy_exposed_review"},
                        {"label_conflict": True}, {"review_outcome": "EXCLUDE"}):
            projected = frontend_evidence_projection(self._row(
                label_source="human_gold", labeling_method="blind_human_review_v2") | changes)
            self.assertIsNone(projected["label"])
            self.assertFalse(projected["classification_evidence_eligible"])

    def test_authoritative_turns_and_independent_probes_are_unchanged(self):
        for changes in ({"entrypoint": "interactive_turn"}, {"entrypoint": "prompt"},
                        {"source_kind": "probe_gold"}, {"source_kind": "runtime"}):
            original = self._row(**changes)
            self.assertFalse(frontend_forced_execution(original))
            self.assertEqual(frontend_evidence_projection(original), original)

    def test_quality_cannot_count_unprojected_forced_labels(self):
        quality = dataset_quality([self._row()])
        self.assertEqual(quality["frontendForcedExecutionCount"], 1)
        self.assertEqual(quality["verifiedLabelCount"], 0)
        self.assertEqual(quality["usableIndependentGroupCount"], 0)

    def test_extraction_preserves_database_and_rejects_unquarantined_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "evidence.sqlite3")
            record_id = store.record_routing(self._row(request_fingerprint="a" * 64))
            store.label_record(record_id, "DELEGATE", source="human_verified", reviewer="synthetic-reviewer")
            before = store.record(record_id)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            path = pathlib.Path(manifest["datasetPath"])
            rows = load_dataset(path)
            validate_dataset_identity(path, rows)
            self.assertEqual(store.record(record_id), before)
            self.assertEqual(store.record_label(record_id)["label"], "DELEGATE")
            self.assertEqual(manifest["frontendForcedExecutionCount"], 1)
            self.assertIsNone(rows[0]["label"])
            self.assertEqual(rows[0]["observed_production_decision"], "DELEGATE")
            self.assertEqual(rows[0]["reviewed_label"], "DELEGATE")
            legacy = dict(rows[0], production_decision="DELEGATE", decision_applied=True)
            legacy.pop("execution_provenance")
            old_path = root / "legacy.jsonl"
            old_path.write_text(json.dumps(legacy) + "\n")
            with self.assertRaisesRegex(ValueError, "unquarantined frontend-forced"):
                load_dataset(old_path)
