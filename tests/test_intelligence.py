from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import pathlib
import sys
import tempfile
import typing
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.intelligence.classical import DirectDelegateModel, train_direct_delegate_model
from quattro_agent.intelligence.adjudication import (
    auto_adjudicate_unlabeled,
    judge_request,
)
from quattro_agent.intelligence.commands import intelligence_command
from quattro_agent.intelligence.commands import (
    _interactive_blind_review_batch,
    _interactive_review_batch,
)
from quattro_agent.intelligence.dataset import (
    DatasetBuilder,
    _chronological_blind_group_splits,
    _near_duplicate_pairs,
    _semantic_duplicate_pairs,
    dataset_quality,
    load_dataset,
    validate_dataset_identity,
)
from quattro_agent.intelligence.evaluation import (
    benchmark_direct_delegate,
    calibration_metrics,
    chronological_evaluation,
    classification_metrics,
    disagreement_telemetry,
    observed_outcome_evidence,
)
from quattro_agent.intelligence.features import (
    extract_decision_features,
    feature_audit,
    forbidden_payload_paths,
)
from quattro_agent.intelligence.probes import (
    boundary_probes,
    controlled_probes,
    import_controlled_probes,
)
from quattro_agent.intelligence.review import (
    RUBRIC_VERSION,
    agreement_metrics,
    blind_review_payload,
    public_review_item,
    sampling_category,
    validate_blind_review_payload,
)
from quattro_agent.intelligence.store import IntelligenceStore
from quattro_agent.intelligence.telemetry import record_routing_telemetry, sanitize_request
from quattro_agent.intelligence.maturity import data_maturity
from quattro_agent.intelligence.readiness import PromotionThresholds, promotion_gate_summary
from quattro_agent.policy import policy_profile
from quattro_agent.store import TaskStore


CURATED = pathlib.Path(__file__).resolve().parents[1] / "benchmarks/direct_delegate_curated_v1.json"


class IntelligenceStoreTests(unittest.TestCase):
    def test_blind_vote_annotations_resolve_at_runtime(self) -> None:
        hints = typing.get_type_hints(IntelligenceStore.import_blind_review_votes)
        self.assertIn("votes", hints)

    def test_request_sanitization_removes_credential_shapes(self) -> None:
        synthetic_key = "s" + "k-" + "synthetic-1234567890abcdefghijkl"
        value = (
            "debug Authorization: Bearer secret-value-123456789 and "
            f"https://alice:password@example.test/path {synthetic_key}"
        )
        safe, redacted = sanitize_request(value)
        self.assertTrue(redacted)
        self.assertNotIn("secret-value", safe)
        self.assertNotIn("alice:password", safe)
        self.assertNotIn(synthetic_key, safe)

    def test_runtime_telemetry_lists_are_bounded_at_storage_boundary(self) -> None:
        """Storage caps oversized runtime telemetry lists and values."""
        with tempfile.TemporaryDirectory() as temporary:
            database = pathlib.Path(temporary) / "intelligence.sqlite3"
            record_id = record_routing_telemetry(
                database,
                request="Explain WAL mode",
                production_decision="DIRECT",
                routing_reason="test",
                production_confidence=0.9,
                selected_worker=None,
                selected_model="model",
                selected_provider="provider",
                selected_account="account",
                project=None,
                repository_present=False,
                run_shadow=False,
                alternatives=["x" * 2_000 for _ in range(500)],
            )
            self.assertIsNotNone(record_id)
            store = IntelligenceStore(database)
            row = store.record(str(record_id))
            self.assertLessEqual(len(row["alternatives"]), 100)
            self.assertLessEqual(max(len(str(item)) for item in row["alternatives"]), 512)
            store.update_execution(
                str(record_id),
                {"tools": ["tool" * 500 for _ in range(500)]},
            )
            updated = store.record(str(record_id))
            self.assertLessEqual(len(updated["tools"]), 100)

    def test_label_is_verified_and_marks_router_correction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = store.record_routing({
                "source_kind": "test",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Explain logistic regression",
                "request_fingerprint": "a" * 64,
                "group_fingerprint": "b" * 64,
                "request_redacted": False,
                "request_length": 27,
                "estimated_tokens": 7,
                "task_type": "conversation",
                "complexity": "low",
                "category": "reasoning",
                "repository_present": False,
                "retrieval_required": False,
                "production_decision": "DELEGATE",
            })
            store.label_record(
                record_id,
                "DIRECT",
                source="human_verified",
                notes="Authorization: Bearer should-not-remain-123456",
                reviewer="test-reviewer",
            )
            row = store.labeled_records()[0]
            self.assertEqual(row["verified_label"], "DIRECT")
            self.assertEqual(row["review_status"], "verified")
            self.assertTrue(row["user_correction"])
            self.assertNotIn("should-not-remain", row["label_notes"])
            with store._reader() as connection:
                history_count = connection.execute(
                    "SELECT count(*) FROM routing_label_history WHERE record_id = ?",
                    (record_id,),
                ).fetchone()[0]
            self.assertEqual(history_count, 1)

    def test_historical_extraction_sanitizes_and_does_not_auto_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            task_store = TaskStore(root / "harness.sqlite3")
            task_store.create_task(
                workflow="general-task",
                agent="codex",
                project_path=root,
                display_title="Test task",
                policy=policy_profile("workspace-write", project_root=root),
                private_payload={
                    "prompt": "Fix parser with api_key=synthetic-super-secret-value-123456",
                    "mode": "prompt",
                    "delegation": {
                        "decision": "DELEGATE",
                        "reason": "request_requires_execution",
                        "confidence": 0.98,
                    },
                    "routing": {
                        "task_profile": {
                            "task_type": "repository_execution",
                            "complexity": "medium",
                            "required_capabilities": ["repository_read", "repository_write"],
                        }
                    },
                },
            )
            intelligence = IntelligenceStore(root / "intelligence.sqlite3")
            result = DatasetBuilder(intelligence).sync_task_history(task_store.path)
            self.assertEqual(result["created"], 1)
            self.assertEqual(intelligence.status()["verifiedLabels"], 0)
            row = intelligence.list_records()[0]
            self.assertNotIn("super-secret", row["request_text"])
            self.assertIsNone(row["success"])
            self.assertIsNone(row["ml_prediction"])
            self.assertEqual(row["inference_error_code"], "historical_backfill")

    def test_review_queue_round_trip_validates_record_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            state = root / "state"
            store = IntelligenceStore(
                state / "private" / "intelligence" / "intelligence.sqlite3"
            )
            record_id = store.record_routing({
                "source_kind": "direct_response",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Explain WAL mode",
                "request_fingerprint": "a" * 64,
                "group_fingerprint": "a" * 64,
                "request_redacted": False,
                "request_length": 16,
                "estimated_tokens": 4,
                "task_type": "conversation",
                "complexity": "low",
                "category": "general",
                "repository_present": False,
                "retrieval_required": False,
                "production_decision": "DIRECT",
            })
            store.update_execution(record_id, {"success": True})
            defaults = {
                "value": None,
                "label": None,
                "source": None,
                "notes": "",
                "input": None,
                "dataset": None,
                "model": None,
                "prompt": None,
                "repository_present": False,
                "output_directory": None,
                "output": None,
                "activate_shadow": False,
                "no_sync": False,
                "limit": 10,
                "production_decision": "DIRECT",
                "pretty": False,
            }
            queue_path = root / "queue.json"
            with self.assertRaisesRegex(ValueError, "requires --output"):
                intelligence_command(
                    argparse.Namespace(action="review-queue", **defaults),
                    state_root=state,
                    task_store_path=root / "missing.sqlite3",
                )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                intelligence_command(
                    argparse.Namespace(
                        action="review-queue",
                        **(defaults | {"output": str(queue_path)}),
                    ),
                    state_root=state,
                    task_store_path=root / "missing.sqlite3",
                )
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["status"], "review_queue_created")
            self.assertNotIn("reviews", summary)
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(queue["reviewCount"], 1)
            self.assertTrue(queue["mlPredictionHidden"])
            self.assertNotIn("mlPrediction", queue["reviews"][0])
            self.assertTrue(queue["productionEvidenceHidden"])
            self.assertNotIn("secondary", queue["reviews"][0])
            queue["reviews"][0]["label"] = "DIRECT"
            queue["reviews"][0]["reviewStatus"] = "verified"
            queue["reviews"][0]["source"] = "reviewed_outcome"
            queue["reviews"][0]["reviewer"] = "test-reviewer"
            queue["reviews"][0]["reviewedAt"] = "2026-09-18T12:00:00+00:00"
            review_path = root / "review.json"
            review_path.write_text(json.dumps(queue), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                intelligence_command(
                    argparse.Namespace(
                        action="review-import",
                        **(defaults | {"input": str(review_path)}),
                    ),
                    state_root=state,
                    task_store_path=root / "missing.sqlite3",
                )
            self.assertEqual(json.loads(output.getvalue())["imported"], 1)
            self.assertEqual(store.record(record_id)["user_correction"], False)
            self.assertEqual(store.record_label(record_id)["review_status"], "verified")
            self.assertEqual(
                store.record_label(record_id)["labeling_method"],
                "legacy_exposed_review",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                intelligence_command(
                    argparse.Namespace(
                        action="review-import",
                        **(defaults | {"input": str(review_path)}),
                    ),
                    state_root=state,
                    task_store_path=root / "missing.sqlite3",
                )
            repeated = json.loads(output.getvalue())
            self.assertEqual(repeated["imported"], 0)
            self.assertEqual(repeated["skipped"], 1)

    def test_review_queue_can_blindly_label_nonterminal_routing_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            store.record_routing({
                "record_id": "routing-only",
                "source_kind": "durable_task",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Execute a repository inspection.",
                "request_fingerprint": "a" * 64,
                "group_fingerprint": "a" * 64,
                "request_redacted": False,
                "request_length": 32,
                "estimated_tokens": 8,
                "task_type": "repository_read",
                "complexity": "low",
                "category": "coding",
                "repository_present": True,
                "retrieval_required": True,
                "production_decision": "DELEGATE",
            })
            self.assertEqual(len(store.review_queue(limit=10)), 1)
            self.assertEqual(store.review_audit()["eligibleRecordCount"], 1)

    def test_review_batch_persists_progress_and_reports_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            review_path = pathlib.Path(temporary_directory) / "review.json"
            payload = {
                "schemaVersion": 2,
                "kind": "quattro-intelligence-review-queue",
                "progress": {
                    "verified": 0,
                    "excluded": 0,
                    "pending": 2,
                    "skipped": 0,
                    "total": 2,
                },
                "reviews": [
                    {"request": "Explain one concept.", "label": None, "reviewStatus": "pending"},
                    {"request": "Inspect this repository.", "label": None, "reviewStatus": "pending"},
                ],
            }
            review_path.write_text(json.dumps(payload), encoding="utf-8")
            with (
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=["d", "s"]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = _interactive_review_batch(
                    review_path,
                    payload,
                    "test-reviewer",
                )

            saved = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertEqual(result["finalizedThisRun"], 1)
            self.assertEqual(result["skippedThisRun"], 1)
            self.assertEqual(saved["progress"]["verified"], 1)
            self.assertEqual(saved["progress"]["pending"], 1)
            self.assertEqual(saved["reviews"][0]["reviewer"], "test-reviewer")

    def test_review_batch_is_atomic_on_stale_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_ids = []
            for index in range(2):
                record_ids.append(store.record_routing({
                    "record_id": f"record-{index}",
                    "source_kind": "direct_response",
                    "entrypoint": "prompt",
                    "decision_applied": True,
                    "request_text": f"Explain topic {index}",
                    "request_fingerprint": str(index) * 64,
                    "group_fingerprint": str(index) * 64,
                    "request_redacted": False,
                    "request_length": 15,
                    "estimated_tokens": 4,
                    "task_type": "conversation",
                    "complexity": "low",
                    "category": "general",
                    "repository_present": False,
                    "retrieval_required": False,
                    "production_decision": "DIRECT",
                }))
            with self.assertRaisesRegex(ValueError, "stale or mismatched"):
                store.apply_review_labels([
                    {
                        "record_id": record_ids[0],
                        "request_fingerprint": "0" * 64,
                        "label": "DIRECT",
                        "source": "human_verified",
                        "reviewer": "test-reviewer",
                        "reviewed_at": "2026-09-18T12:00:00+00:00",
                    },
                    {
                        "record_id": record_ids[1],
                        "request_fingerprint": "stale",
                        "label": "DIRECT",
                        "source": "human_verified",
                        "reviewer": "test-reviewer",
                        "reviewed_at": "2026-09-18T12:00:00+00:00",
                    },
                ])
            self.assertEqual(store.labeled_records(), [])

    def test_ambiguous_review_is_persisted_and_excluded_from_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = store.record_routing({
                "source_kind": "direct_response",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Maybe inspect this if useful",
                "request_fingerprint": "a" * 64,
                "group_fingerprint": "a" * 64,
                "request_redacted": False,
                "request_length": 28,
                "estimated_tokens": 7,
                "task_type": "unknown",
                "complexity": "unknown",
                "category": "general",
                "repository_present": False,
                "retrieval_required": False,
                "production_decision": "DIRECT",
            })
            result = store.apply_review_labels([{
                "record_id": record_id,
                "request_fingerprint": "a" * 64,
                "outcome": "EXCLUDE",
                "source": "human_verified",
                "reviewer": "test-reviewer",
                "reviewed_at": "2026-09-18T12:00:00+00:00",
                "notes": "boundary is ambiguous",
            }])
            self.assertEqual(result, {"imported": 0, "excluded": 1, "skipped": 0})
            self.assertEqual(store.labeled_records(), [])
            self.assertEqual(store.review_queue(limit=10), [])
            with self.assertRaisesRegex(ValueError, "adjudication"):
                store.label_record(
                    record_id,
                    "DIRECT",
                    source="human_verified",
                    reviewer="test-reviewer",
                )
            audit = store.review_audit()
            self.assertEqual(audit["excludedRecordCount"], 1)
            self.assertEqual(audit["remainingRecordCount"], 0)


class ClassicalModelTests(unittest.TestCase):
    def _dataset(self, root: pathlib.Path) -> tuple[IntelligenceStore, list[dict], dict]:
        store = IntelligenceStore(root / "intelligence.sqlite3")
        builder = DatasetBuilder(store)
        builder.import_curated(CURATED)
        manifest = builder.extract(root / "datasets")
        rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
        return store, rows, manifest

    def test_dataset_split_is_grouped_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _store, rows, manifest = self._dataset(pathlib.Path(temporary))
            self.assertEqual(manifest["labeledCount"], 36)
            assignments: dict[str, str] = {}
            for row in rows:
                existing = assignments.setdefault(row["group_fingerprint"], row["split"])
                self.assertEqual(existing, row["split"])
            self.assertEqual(set(manifest["classBalance"]), {"DIRECT", "DELEGATE"})
            self.assertEqual(
                manifest["splitClassBalance"],
                {
                    "train": {"DELEGATE": 12, "DIRECT": 12},
                    "validation": {"DELEGATE": 3, "DIRECT": 3},
                    "test": {"DELEGATE": 3, "DIRECT": 3},
                },
            )
            self.assertEqual(dataset_quality(rows)["status"], "BLOCKED_BY_DATA")
            quality = dataset_quality(rows)
            self.assertIn("reviewedRealCodingBalance", quality)
            self.assertIn("reviewedRealRetrievalRequirementBalance", quality)
            self.assertIn("reviewedRealToolRequirementBalance", quality)
            self.assertEqual(quality["potentialNearDuplicateCrossSplitPairs"], 0)
            self.assertTrue(quality["futureInformationLeakage"]["passed"])
            self.assertIn("datasetVersion", manifest)
            same_directory = DatasetBuilder(_store).extract(
                pathlib.Path(temporary) / "datasets"
            )
            self.assertEqual(manifest["datasetVersion"], same_directory["datasetVersion"])
            repeated = DatasetBuilder(_store).extract(pathlib.Path(temporary) / "datasets-repeat")
            self.assertEqual(manifest["datasetVersion"], repeated["datasetVersion"])
            with self.assertRaisesRegex(ValueError, "manifest is immutable"):
                _store.save_dataset_manifest(
                    manifest["datasetVersion"],
                    manifest | {"classBalance": {"DIRECT": 999}},
                )

            seed = _store.list_records()[0]
            _store.record_routing({
                **seed,
                "record_id": "duplicate-request",
                "source_task_id": None,
                "group_fingerprint": "different-session",
            })
            _store.record_routing({
                **seed,
                "record_id": "linked-session",
                "source_task_id": None,
                "request_text": "Different request in the same session",
                "request_fingerprint": "f" * 64,
                "group_fingerprint": "different-session",
            })
            linked_manifest = DatasetBuilder(_store).extract(
                pathlib.Path(temporary) / "datasets-linked"
            )
            linked_rows = load_dataset(pathlib.Path(linked_manifest["datasetPath"]))
            linked = [
                row for row in linked_rows
                if row["record_id"] in {seed["record_id"], "duplicate-request", "linked-session"}
            ]
            self.assertEqual(len({row["split"] for row in linked}), 1)

    def test_near_duplicate_guard_includes_short_prompts(self) -> None:
        records = [
            {"request_text": "find readme path now", "request_fingerprint": "a"},
            {"request_text": "find readme path right now", "request_fingerprint": "b"},
        ]
        pairs = _near_duplicate_pairs(records)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][:2], (0, 1))
        self.assertGreaterEqual(pairs[0][2], 0.80)

    def test_conflicting_component_labels_are_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            requests = (
                "Research transit safety using two credible sources and summarize one limit.",
                "Research transit safety using two credible sources and summarize the limit.",
            )
            for index, request in enumerate(requests):
                record_id = store.record_routing({
                    "record_id": f"conflict-{index}",
                    "source_kind": "durable_task",
                    "entrypoint": "prompt",
                    "decision_applied": True,
                    "request_text": request,
                    "request_fingerprint": str(index) * 64,
                    "group_fingerprint": str(index) * 64,
                    "request_redacted": False,
                    "request_length": len(request),
                    "estimated_tokens": len(request.split()),
                    "task_type": "research",
                    "complexity": "low",
                    "category": "research",
                    "repository_present": False,
                    "retrieval_required": True,
                    "production_decision": "DELEGATE",
                })
                store.label_record(
                    record_id,
                    "DIRECT" if index else "DELEGATE",
                    source="human_verified",
                    reviewer="test-reviewer",
                )

            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            self.assertEqual(manifest["quarantinedConflictRowCount"], 2)
            self.assertTrue(all(row["label_conflict"] for row in rows))
            self.assertTrue(all(row["label"] is None for row in rows))
            self.assertEqual(
                {row["reviewed_label"] for row in rows},
                {"DIRECT", "DELEGATE"},
            )
            self.assertEqual(dataset_quality(rows)["conflictingLabelGroups"], 1)

    def test_dataset_schema_and_content_version_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _store, rows, manifest = self._dataset(root)
            original = pathlib.Path(manifest["datasetPath"])
            validate_dataset_identity(original, rows)
            tampered = root / original.name
            changed = [dict(row) for row in rows]
            changed[0]["request_text"] += " changed"
            tampered.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in changed) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "content version mismatch"):
                validate_dataset_identity(tampered, load_dataset(tampered))

            incompatible = root / "incompatible.jsonl"
            changed[0]["feature_version"] = "future-features"
            incompatible.write_text(json.dumps(changed[0]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incompatible feature version"):
                load_dataset(incompatible)

    def test_training_save_load_and_benchmark_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            _store, rows, manifest = self._dataset(root)
            first = train_direct_delegate_model(rows, dataset_version=manifest["datasetVersion"])
            second = train_direct_delegate_model(rows, dataset_version=manifest["datasetVersion"])
            self.assertEqual(first.payload["model_version"], second.payload["model_version"])
            with_unlabeled = rows + [{
                **rows[0],
                "record_id": "unlabeled-extra",
                "request_text": "This must not silently become a DIRECT label",
                "label": None,
                "split": "train",
            }]
            ignored = train_direct_delegate_model(
                with_unlabeled, dataset_version=manifest["datasetVersion"]
            )
            self.assertEqual(first.payload["model_version"], ignored.payload["model_version"])
            artifact = root / "model.json"
            first.save(artifact)
            loaded = DirectDelegateModel.load(artifact)
            report = benchmark_direct_delegate(loaded, rows)
            self.assertEqual(report["status"], "evaluated")
            self.assertGreater(report["sampleCount"], 0)
            self.assertIsNotNone(report["validation"])
            self.assertEqual(report["model"]["metrics"]["confusionMatrix"]["labels"], [
                "DIRECT", "DELEGATE"
            ])
            self.assertIn("confidenceCalibration", report)
            self.assertTrue(report["benchmarkReproducibility"]["passed"])
            self.assertIn("performanceByCategory", report)
            self.assertIn("performanceByClass", report)
            self.assertIn("performanceByCoding", report)
            self.assertIn("performanceByRetrievalRequirement", report)
            self.assertIn("performanceByToolRequirement", report)
            self.assertIn("realPerformanceByCategory", report)
            self.assertIn("realPerformanceByToolRequirement", report)
            self.assertIn(
                "confidenceIntervals95", report["confidenceCalibration"]
            )
            self.assertEqual(report["featureAblation"]["status"], "not_run")
            self.assertEqual(report["productionConclusion"], "BLOCKED_BY_DATA")

    def test_shadow_inference_failure_never_breaks_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            corrupt = root / "corrupt.json"
            corrupt.write_text("{}\n", encoding="utf-8")
            store.register_model(
                model_version="broken-v1",
                algorithm="broken",
                dataset_version="test",
                artifact_path=corrupt,
                metrics={},
            )
            store.activate_shadow_model("broken-v1")
            record_id = record_routing_telemetry(
                store.path,
                request="Explain Docker volumes",
                production_decision="DIRECT",
                routing_reason="test",
                production_confidence=1.0,
                selected_worker=None,
                selected_model="auto",
                selected_provider="omniroute",
                selected_account="account-test",
                project=root,
                repository_present=False,
                entrypoint="prompt",
            )
            self.assertIsNotNone(record_id)
            row = store.record(str(record_id))
            self.assertEqual(row["production_decision"], "DIRECT")
            self.assertIsNone(row["ml_prediction"])
            self.assertEqual(row["inference_error_code"], "inference_failed")

    def test_model_loader_rejects_non_finite_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "model.json"
            path.write_text(json.dumps({
                "algorithm": "tfidf-logistic-regression-stdlib-v1",
                "feature_version": "direct-delegate-features-v1",
                "vocabulary": {},
                "idf": [],
                "weights": [float("nan")],
                "intercept": 0.0,
                "threshold": 0.5,
                "numeric_means": [0.0],
                "numeric_scales": [1.0],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                DirectDelegateModel.load(path)

    def test_active_shadow_model_logs_prediction_and_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store, rows, manifest = self._dataset(root)
            model = train_direct_delegate_model(rows, dataset_version=manifest["datasetVersion"])
            artifact = root / "models" / "model.json"
            model.save(artifact)
            store.register_model(
                model_version=str(model.payload["model_version"]),
                algorithm=str(model.payload["algorithm"]),
                dataset_version=manifest["datasetVersion"],
                artifact_path=artifact,
                metrics={},
            )
            store.activate_shadow_model(str(model.payload["model_version"]))
            record_id = record_routing_telemetry(
                store.path,
                request="Fix the parser in this repository and run tests",
                production_decision="DIRECT",
                routing_reason="forced-test-baseline",
                production_confidence=0.5,
                selected_worker="codex",
                selected_model="auto/coding",
                selected_provider="omniroute",
                selected_account="account-test",
                project=root,
                repository_present=True,
                profile={
                    "task_type": "repository_execution",
                    "complexity": "medium",
                    "required_capabilities": ["repository_read", "repository_write"],
                },
                entrypoint="prompt",
            )
            row = store.record(str(record_id))
            self.assertEqual(row["ml_prediction"], "DELEGATE")
            self.assertTrue(row["disagreement"])
            self.assertGreaterEqual(row["ml_confidence"], 0.5)
            self.assertTrue(row["retrieval_required"])
            self.assertTrue(row["tool_required"])

    def test_binary_metrics(self) -> None:
        result = classification_metrics(
            ["DIRECT", "DIRECT", "DELEGATE", "DELEGATE"],
            ["DIRECT", "DELEGATE", "DELEGATE", "DIRECT"],
        )
        self.assertEqual(result["accuracy"], 0.5)
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["f1"], 0.5)
        self.assertEqual(result["confusionMatrix"]["matrix"], [[1, 1], [1, 1]])

    def test_chronological_evaluation_uses_older_groups_for_training(self) -> None:
        rows = []
        for index in range(40):
            label = "DIRECT" if index % 2 == 0 else "DELEGATE"
            rows.append({
                "record_id": f"record-{index}",
                "request_text": (
                    f"Explain concept {index}" if label == "DIRECT"
                    else f"Implement repository change {index} and run tests"
                ),
                "label": label,
                "label_source": "human_verified",
                "label_independent": True,
                "group_fingerprint": f"group-{index}",
                "created_at": f"2026-09-{1 + index // 24:02d}T{index % 24:02d}:00:00+00:00",
                "reviewed_at": f"2026-09-{1 + index // 24:02d}T{index % 24:02d}:30:00+00:00",
                "category": "general" if label == "DIRECT" else "coding",
                "complexity": "low" if label == "DIRECT" else "medium",
                "task_type": "conversation" if label == "DIRECT" else "repository_execution",
                "repository_present": label == "DELEGATE",
                "retrieval_required": label == "DELEGATE",
                "tool_required": label == "DELEGATE",
                "request_length": 20,
                "estimated_tokens": 5,
                "context_tokens": 0,
            })
        rows.append({
            **rows[0],
            "record_id": "invalid-time",
            "group_fingerprint": "invalid-time",
            "created_at": "not-a-timestamp",
            "reviewed_at": "not-a-timestamp",
        })
        report = chronological_evaluation(rows)
        self.assertEqual(report["status"], "evaluated")
        self.assertEqual(report["trainingGroupCount"], 28)
        self.assertEqual(report["evaluationGroupCount"], 12)
        self.assertEqual(report["evaluationClassBalance"], {"DELEGATE": 6, "DIRECT": 6})
        self.assertEqual(report["invalidTimestampCount"], 1)

    def test_cli_training_gate_blocks_small_dataset_and_shadow_activation(self) -> None:
        """Training rejects immature data without activating a shadow model."""
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            state = root / "state"
            dataset_directory = root / "datasets"

            def run(action: str, **values: object) -> tuple[int, dict]:
                defaults = {
                    "action": action,
                    "value": None,
                    "label": None,
                    "source": None,
                    "notes": "",
                    "input": None,
                    "dataset": None,
                    "model": None,
                    "prompt": None,
                    "repository_present": False,
                    "output_directory": None,
                    "output": None,
                    "activate_shadow": False,
                    "no_sync": False,
                    "limit": 50,
                    "production_decision": None,
                    "pretty": False,
                }
                defaults.update(values)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = intelligence_command(
                        argparse.Namespace(**defaults),
                        state_root=state,
                        task_store_path=root / "missing-harness.sqlite3",
                    )
                return code, json.loads(output.getvalue())

            self.assertEqual(run("import-labels", input=str(CURATED))[0], 0)
            dataset_code, dataset = run(
                "dataset", output_directory=str(dataset_directory), no_sync=True
            )
            self.assertEqual(dataset_code, 0)
            train_code, trained = run(
                "train", dataset=dataset["datasetPath"], activate_shadow=True
            )
            self.assertEqual(train_code, 2)
            self.assertEqual(trained["status"], "BLOCKED_BY_DATA")
            self.assertIsNone(
                IntelligenceStore(
                    state / "private" / "intelligence" / "intelligence.sqlite3"
                ).active_shadow_model()
            )
            quality_code, quality = run("quality", dataset=dataset["datasetPath"])
            self.assertEqual(quality_code, 0)
            self.assertEqual(quality["quality"]["status"], "BLOCKED_BY_DATA")
            readiness_code, readiness = run(
                "readiness",
                dataset=dataset["datasetPath"],
            )
            self.assertEqual(readiness_code, 0)
            self.assertEqual(readiness["status"], "BLOCKED BY DATA")
            self.assertFalse(readiness["promotionReady"])
            threshold_path = root / "thresholds.json"
            threshold_path.write_text(json.dumps({
                "schemaVersion": 1,
                "thresholds": {
                    "minimumIndependentUsableGroups": 1,
                    "minimumIndependentUsableGroupsPerClass": 1,
                },
            }), encoding="utf-8")
            thresholded_code, thresholded = run(
                "readiness",
                dataset=dataset["datasetPath"],
                thresholds=str(threshold_path),
            )
            self.assertEqual(thresholded_code, 0)
            self.assertIn("promotionGates", thresholded)


class Phase18IntelligenceTests(unittest.TestCase):
    def test_decision_features_keep_direct_contracts_tool_free(self) -> None:
        for request in (
            "Explain what a REST API is",
            "Summarize the supplied text in three bullets",
            "Draft a short email declining the meeting",
            "Now explain database indexes",
        ):
            with self.subTest(request=request):
                features = extract_decision_features(request)
                self.assertFalse(features["repository_required"])
                self.assertFalse(features["retrieval_required"])
                self.assertFalse(features["tool_required"])
                self.assertFalse(features["execution_required"])
                self.assertFalse(features["modification_required"])

    def test_decision_features_repair_delegate_boundaries(self) -> None:
        repository = extract_decision_features(
            "Locate the exact README path in this repository"
        )
        self.assertTrue(repository["repository_required"])
        self.assertTrue(repository["retrieval_required"])
        self.assertTrue(repository["tool_required"])
        workflow = extract_decision_features(
            "Inspect the repository, update the parser, then run tests"
        )
        self.assertTrue(workflow["modification_required"])
        self.assertTrue(workflow["multi_step_required"])
        self.assertEqual(workflow["complexity"], "high")
        current = extract_decision_features(
            "Research the latest official release status using two sources"
        )
        self.assertTrue(current["current_information_required"])
        self.assertTrue(current["retrieval_required"])

    def test_feature_audit_excludes_router_and_outcome_leakage(self) -> None:
        audit = feature_audit()
        self.assertIn("production_decision", audit["leakageOrPostDecision"])
        self.assertIn("retrieval_used", audit["leakageOrPostDecision"])
        self.assertIn("source_kind", audit["questionable"])
        self.assertIn("repository_required", audit["safeAtDecisionTime"])
        self.assertNotIn("production_decision", audit["safeAtDecisionTime"])

    def test_safe_model_vector_ignores_router_and_outcome_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            import_controlled_probes(store)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            model = train_direct_delegate_model(
                rows,
                dataset_version=manifest["datasetVersion"],
                feature_set="safe_metadata",
            )
            row = rows[0]
            base = model.vectorize(row["request_text"], profile=row)
            leaked = model.vectorize(
                row["request_text"],
                profile=row | {
                    "production_decision": "DELEGATE",
                    "routing_reason": "request_requires_execution",
                    "selected_worker": "codex",
                    "retrieval_used": True,
                    "outcome_success": True,
                    "validation_status": "Passed",
                    "source_kind": "durable_task",
                    "entrypoint": "prompt",
                    "tier": "REASONING",
                },
            )
            self.assertEqual(base, leaked)

    def test_legacy_model_vector_preserves_repository_presence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            import_controlled_probes(store)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            model = train_direct_delegate_model(
                rows,
                dataset_version=manifest["datasetVersion"],
                feature_set="legacy_full",
            )
            request = "Inspect the parser"
            absent = model.vectorize(request, repository_present=False)
            present = model.vectorize(request, repository_present=True)
            self.assertNotEqual(absent, present)

    def test_silver_never_influences_calibration_or_threshold_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            import_controlled_probes(store)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            validation_count = sum(
                row["split"] == "validation"
                and row["label_source"] == "probe_gold"
                for row in rows
            )
            silver_rows = [
                row | {
                    "record_id": f"silver-{index}",
                    "group_fingerprint": f"silver-group-{index}",
                    "label_source": "silver",
                    "split": "validation",
                }
                for index, row in enumerate(rows[:10])
            ]
            model = train_direct_delegate_model(
                [*rows, *silver_rows],
                dataset_version="calibration-source-test",
            )
            self.assertEqual(
                model.payload["calibration"]["sample_count"], validation_count
            )

    def test_phase_17_v4_dataset_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "legacy.jsonl"
            path.write_text(json.dumps({
                "schema_version": "direct-delegate-dataset-v4",
                "feature_version": "direct-delegate-features-v1",
                "record_id": "legacy",
                "split": "test",
                "label": "DIRECT",
                "request_text": "Explain WAL mode",
            }) + "\n", encoding="utf-8")
            self.assertEqual(load_dataset(path)[0]["record_id"], "legacy")

    def test_probe_generator_is_balanced_held_out_and_duplicate_safe(self) -> None:
        probes = controlled_probes()
        self.assertEqual(len(probes), 226)
        self.assertEqual(len(boundary_probes()), 16)
        balance = {
            (split, label): sum(
                probe["split"] == split and probe["label"] == label
                for probe in probes
            )
            for split in ("train", "validation", "test")
            for label in ("DIRECT", "DELEGATE")
        }
        self.assertEqual(balance[("validation", "DIRECT")], 30)
        self.assertEqual(balance[("validation", "DELEGATE")], 30)
        self.assertEqual(balance[("test", "DIRECT")], 30)
        self.assertEqual(balance[("test", "DELEGATE")], 30)
        rows = [
            {
                "request_text": probe["request"],
                "request_fingerprint": str(index),
                "split": probe["split"],
            }
            for index, probe in enumerate(probes)
        ]
        self.assertEqual(_near_duplicate_pairs(rows), [])

    def test_probe_import_and_label_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            result = import_controlled_probes(store)
            self.assertEqual(result["count"], 226)
            self.assertEqual(result["uncertainCount"], 1)
            self.assertEqual(result["classBalance"], {"DELEGATE": 132, "DIRECT": 93})
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            self.assertEqual(
                {row["label_source"] for row in rows},
                {"probe_gold", "excluded"},
            )
            split_balance = manifest["splitClassBalance"]
            self.assertGreaterEqual(split_balance["validation"]["DIRECT"], 30)
            self.assertGreaterEqual(split_balance["validation"]["DELEGATE"], 30)
            self.assertGreaterEqual(split_balance["test"]["DIRECT"], 30)
            self.assertGreaterEqual(split_balance["test"]["DELEGATE"], 30)

    def test_silver_requires_unanimity_and_never_rewrites_human_gold(self) -> None:
        self.assertEqual(
            judge_request("Inspect the repository and locate the parser file")["label"],
            "DELEGATE",
        )
        self.assertIsNone(judge_request("Help with this thing")["label"])
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = store.record_routing({
                "source_kind": "runtime",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Explain write-ahead logging without tools",
                "request_fingerprint": "a" * 64,
                "group_fingerprint": "a" * 64,
                "request_redacted": False,
                "request_length": 42,
                "estimated_tokens": 11,
                "task_type": "conversation",
                "complexity": "low",
                "category": "reasoning",
                "repository_present": False,
                "retrieval_required": False,
                "production_decision": "DIRECT",
            })
            store.label_record(
                record_id,
                "DIRECT",
                source="human_verified",
                reviewer="reviewer",
            )
            with self.assertRaisesRegex(ValueError, "human-gold"):
                store.label_record(record_id, "DELEGATE", source="silver")

    def test_auto_adjudication_excludes_uncertain_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            for index, request in enumerate((
                "Inspect the repository and locate the parser file",
                "Help with this thing",
            )):
                safe, _redacted = sanitize_request(request)
                store.record_routing({
                    "record_id": f"record-{index}",
                    "source_kind": "runtime",
                    "entrypoint": "prompt",
                    "decision_applied": True,
                    "request_text": safe,
                    "request_fingerprint": str(index) * 64,
                    "group_fingerprint": str(index) * 64,
                    "request_redacted": False,
                    "request_length": len(safe),
                    "estimated_tokens": 8,
                    "task_type": "unknown",
                    "complexity": "unknown",
                    "category": "general",
                    "repository_present": False,
                    "retrieval_required": False,
                    "production_decision": "DIRECT",
                })
            result = auto_adjudicate_unlabeled(store)
            self.assertEqual(result["promoted"], 1)
            self.assertEqual(result["excluded"], 1)
            self.assertEqual(store.record_label("record-0")["source"], "silver")
            self.assertEqual(store.latest_reviews()["record-1"]["outcome"], "EXCLUDE")
            with store._reader() as connection:
                vote_count = connection.execute(
                    "SELECT count(*) FROM routing_adjudications"
                ).fetchone()[0]
            self.assertEqual(vote_count, 6)


class Phase19IntelligenceTests(unittest.TestCase):
    def test_forbidden_alias_audit_finds_nested_and_serialized_metadata(self) -> None:
        payload = {
            "safe": {
                "routerDecision": "DELEGATE",
                "nested": '{"actualProvider":"example"}',
            }
        }
        findings = forbidden_payload_paths(payload)
        self.assertIn("$.safe.routerDecision", findings)
        self.assertIn("$.safe.nested<json>.actualProvider", findings)

    def test_human_gold_requires_explicit_correction_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = store.record_routing({
                "source_kind": "runtime",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Explain queues",
                "request_fingerprint": "a" * 64,
                "group_fingerprint": "a" * 64,
                "request_length": 14,
                "estimated_tokens": 4,
                "complexity": "low",
                "category": "reasoning",
                "repository_present": False,
                "retrieval_required": False,
                "production_decision": "DIRECT",
            })
            store.label_record(
                record_id,
                "DIRECT",
                source="human_verified",
                reviewer="reviewer-a",
            )
            with self.assertRaisesRegex(ValueError, "explicit correction audit"):
                store.label_record(
                    record_id,
                    "DELEGATE",
                    source="reviewed_outcome",
                    reviewer="reviewer-b",
                )

    def test_automated_labels_require_independent_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = store.record_routing({
                "source_kind": "runtime",
                "entrypoint": "prompt",
                "decision_applied": True,
                "request_text": "Inspect this repository",
                "request_fingerprint": "b" * 64,
                "group_fingerprint": "b" * 64,
                "request_length": 23,
                "estimated_tokens": 6,
                "complexity": "medium",
                "category": "coding",
                "repository_present": True,
                "retrieval_required": True,
                "production_decision": "DELEGATE",
            })
            with self.assertRaisesRegex(ValueError, "probe-gold"):
                store.label_record(record_id, "DELEGATE", source="probe_gold")
            with self.assertRaisesRegex(ValueError, "three matching"):
                store.label_record(record_id, "DELEGATE", source="silver")

    def test_current_dataset_rejects_feature_smuggling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            import_controlled_probes(store)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            target = next(
                row for row in rows if row["feature_provenance"] == "text_recomputed_v2"
            ) if any(
                row["feature_provenance"] == "text_recomputed_v2" for row in rows
            ) else None
            self.assertIsNone(target)
            row = dict(rows[0])
            row["feature_provenance"] = "text_recomputed_v2"
            row["source_kind"] = "runtime"
            row["decision_applied"] = True
            row["production_decision"] = "DIRECT"
            row["category"] = "coding" if row["category"] != "coding" else "general"
            path = root / "smuggled.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-reproducible"):
                load_dataset(path)

    def test_phase_19_reports_data_deficit_without_replacing_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            state = root / "state"
            output = root / "phase-1-9.json"
            defaults = {
                "action": "phase-1-9",
                "value": None,
                "label": None,
                "source": None,
                "notes": "",
                "input": None,
                "dataset": None,
                "model": None,
                "prompt": None,
                "repository_present": False,
                "output_directory": None,
                "output": str(output),
                "activate_shadow": False,
                "no_sync": False,
                "limit": 50,
                "production_decision": None,
                "reviewer": None,
                "pretty": False,
            }
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = intelligence_command(
                    argparse.Namespace(**defaults),
                    state_root=state,
                    task_store_path=root / "missing.sqlite3",
                )
            summary = json.loads(stream.getvalue())
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(
                summary["phaseStatus"],
                "COMPLETE — PIPELINE READY / BLOCKED BY DATA",
            )
            self.assertIsNone(report["candidateModelVersion"])
            self.assertEqual(
                report["activeShadowModelBefore"],
                report["activeShadowModelAfter"],
            )
            self.assertTrue(output.with_suffix(".md").is_file())

    def test_metrics_report_per_class_rates(self) -> None:
        result = classification_metrics(
            ["DIRECT", "DIRECT", "DELEGATE", "DELEGATE"],
            ["DIRECT", "DELEGATE", "DELEGATE", "DIRECT"],
        )
        self.assertEqual(set(result["perClass"]), {"DIRECT", "DELEGATE"})
        self.assertEqual(result["perClass"]["DIRECT"]["falseNegativeRate"], 0.5)
        self.assertEqual(result["perClass"]["DELEGATE"]["falsePositiveRate"], 0.5)

    def test_legacy_exposed_review_is_not_counted_as_independent_real_evidence(self) -> None:
        """Legacy non-blind reviews remain ineligible as independent evidence."""
        quality = dataset_quality([{
            "record_id": "legacy-real",
            "request_text": "Inspect the repository",
            "label": "DELEGATE",
            "label_source": "human_gold",
            "label_independent": False,
            "group_fingerprint": "legacy-group",
            "request_fingerprint": "legacy-request",
            "split": "test",
            "category": "coding",
            "task_category": "repository_inspection",
            "complexity": "medium",
            "created_at": "2026-09-01T00:00:00+00:00",
        }])
        self.assertEqual(quality["reviewedRealLabelCount"], 1)
        self.assertEqual(quality["reviewedRealIndependentGroupCount"], 0)

    def test_data_maturity_reports_coverage_routes_outcomes_duplicates_and_freshness(self) -> None:
        """Maturity reports cover evidence, outcomes, duplicates, and recency."""
        rows = [
            {
                "record_id": "maturity-direct",
                "request_text": "Explain WAL mode without tools",
                "label": "DIRECT",
                "label_independent": True,
                "group_fingerprint": "group-direct",
                "production_decision": "DIRECT",
                "task_category": "explanation",
                "complexity": "low",
                "category": "reasoning",
                "created_at": "2026-09-01T00:00:00+00:00",
                "outcome_success": True,
                "selected_provider": "omniroute",
                "selected_model": "model-a",
            },
            {
                "record_id": "maturity-delegate",
                "request_text": "Inspect the repository and run tests",
                "label": "DELEGATE",
                "label_independent": True,
                "group_fingerprint": "group-delegate",
                "production_decision": "DELEGATE",
                "task_category": "repository_verification",
                "complexity": "medium",
                "category": "coding",
                "created_at": "2026-09-02T00:00:00+00:00",
                "outcome_success": False,
                "selected_provider": "omniroute",
                "selected_model": "model-b",
            },
            {
                "record_id": "maturity-unlabeled",
                "request_text": "Draft a short note",
                "label": None,
                "label_independent": False,
                "group_fingerprint": "group-unlabeled",
                "production_decision": "DIRECT",
                "task_category": "drafting",
                "complexity": "low",
                "category": "general",
                "created_at": "2026-09-03T00:00:00+00:00",
                "outcome_success": None,
            },
        ]
        report = data_maturity(
            rows,
            now=dt.datetime(2026, 9, 4, tzinfo=dt.timezone.utc),
            duplicate_stats={"potentialNearDuplicatePairs": 1},
        )
        self.assertEqual(report["totalExamples"], 3)
        self.assertEqual(report["eligibleExamples"], 2)
        self.assertEqual(report["deterministicRouteBalance"], {"DELEGATE": 1, "DIRECT": 2})
        self.assertEqual(report["outcomes"]["successes"], 1)
        self.assertEqual(report["outcomes"]["failures"], 1)
        self.assertIn("omniroute/model-a", report["outcomes"]["byCandidateProviderModel"])
        self.assertEqual(report["freshness"]["asOf"], "2026-09-04T00:00:00+00:00")
        self.assertEqual(report["duplicates"]["potentialNearDuplicatePairs"], 1)
        self.assertEqual(report["status"], "insufficient_data")

    def test_promotion_thresholds_are_configurable_and_qualifying_fixture_is_ready(self) -> None:
        """Custom thresholds can admit a fixture that satisfies every gate."""
        policy = PromotionThresholds.from_mapping({
            "minimumIndependentUsableGroups": 2,
            "minimumIndependentUsableGroupsPerClass": 1,
            "minimumCategories": 1,
            "minimumUsableLabelsPerCategory": 1,
            "minimumDisagreements": 2,
            "minimumCategoryEvaluationSamples": 2,
            "minimumCategoryClassSamples": 1,
        })
        self.assertEqual(policy.minimum_categories, 1)
        with self.assertRaisesRegex(ValueError, "unknown intelligence threshold"):
            PromotionThresholds.from_mapping({"minimiumCategories": 1})
        maturity = {
            "candidateGates": {
                name: True for name in (
                    "independentUsableGroups", "directGroups", "delegateGroups",
                    "validationPerClass", "testPerClass", "categoryCoverage",
                    "blindHumanGoldBothClasses", "credibleChronology",
                    "zeroDecisionOutcomeLeakage", "zeroCrossSplitContamination",
                    "featureSchemaFrozen",
                )
            },
            "labelCompleteness": {"rate": 1.0},
            "classImbalance": {"ratio": 1.0},
            "featureCoverage": {"missingRate": 0.0},
            "rejections": {"leakage": 0},
            "eligibleExamples": 2,
        }
        evaluation = {
            "status": "evaluated",
            "baseline": {"metrics": {
                "balancedAccuracy": 0.70,
                "f1": 0.70,
                "delegateFalseNegativeRate": 0.10,
            }},
            "model": {"metrics": {
                "balancedAccuracy": 0.80,
                "f1": 0.75,
                "delegateFalseNegativeRate": 0.05,
            }},
            "confidenceCalibration": {
                "expectedCalibrationError": 0.02,
                "brierScore": 0.04,
            },
            "performanceByTaskCategory": {
                f"category-{index}": {
                    "sampleCount": 2,
                    "classBalance": {"DIRECT": 1, "DELEGATE": 1},
                    "modelMetrics": {"balancedAccuracy": 0.80},
                    "baselineMetrics": {"balancedAccuracy": 0.70},
                }
                for index in range(1)
            },
            "pairedComparison": {
                "disagreements": 2,
                "modelWins": 2,
                "baselineWins": 0,
                "exactMcNemarPValue": 0.01,
            },
            "benchmarkReproducibility": {"passed": True},
        }
        ready = promotion_gate_summary(
            maturity=maturity,
            evaluation=evaluation,
            thresholds=policy,
        )
        self.assertTrue(ready["promotionReady"])
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(ready["gatesFailed"], [])

    def test_calibration_and_disagreement_reports_do_not_invent_counterfactuals(self) -> None:
        """Evaluation distinguishes observed outcomes from counterfactuals."""
        examples = [
            {"delegateProbability": 0.9, "confidence": 0.9, "correct": True, "label": "DELEGATE"},
            {"delegateProbability": 0.1, "confidence": 0.9, "correct": True, "label": "DIRECT"},
        ]
        calibration = calibration_metrics(examples)
        self.assertEqual(calibration["delegateProbability"]["sampleCount"], 2)
        self.assertEqual(calibration["confidence"]["sampleCount"], 2)
        rows = [{
            "record_id": "disagreement",
            "production_decision": "DIRECT",
            "ml_prediction": "DELEGATE",
            "ml_confidence": 0.8,
            "task_category": "repository_inspection",
            "complexity": "medium",
            "repository_required": True,
            "retrieval_required": True,
            "tool_required": True,
            "outcome_success": True,
            "label": "DELEGATE",
            "label_independent": True,
        }]
        disagreements = disagreement_telemetry(rows)
        outcomes = observed_outcome_evidence(rows)
        self.assertEqual(disagreements["count"], 1)
        self.assertEqual(disagreements["representative"][0]["counterfactual"], "unavailable")
        self.assertEqual(outcomes["counterfactualStatus"], "unavailable")
        self.assertEqual(outcomes["disagreementObservedOutcome"]["successes"], 1)


class Phase110IntelligenceTests(unittest.TestCase):
    @staticmethod
    def _record(store: IntelligenceStore, record_id: str, request: str) -> str:
        safe, redacted = sanitize_request(request)
        return store.record_routing({
            "record_id": record_id,
            "source_kind": "direct_response",
            "entrypoint": "prompt",
            "decision_applied": True,
            "request_text": safe,
            "request_fingerprint": record_id[-1] * 64,
            "group_fingerprint": record_id[-1] * 64,
            "request_redacted": redacted,
            "request_length": len(safe),
            "estimated_tokens": (len(safe) + 3) // 4,
            "task_type": "unknown",
            "complexity": "unknown",
            "category": "general",
            "repository_present": False,
            "retrieval_required": False,
            "production_decision": "DIRECT",
            "ml_prediction": "DELEGATE",
        })

    def test_blind_payload_uses_exact_allowlist_and_rejects_serialized_leakage(self) -> None:
        payload = blind_review_payload([
            public_review_item("br_" + "a" * 32, "Fix this endpoint and run tests")
        ])
        validate_blind_review_payload(payload)
        item = payload["items"][0]
        self.assertEqual(
            set(item),
            {
                "itemId", "request", "requirements", "label", "reasonCategory",
                "note", "reviewStatus",
            },
        )
        for forbidden in (
            "productionDecision", "mlPrediction", "selectedWorker", "sourceKind",
            "repositoryPresent", "validationStatus",
        ):
            self.assertNotIn(forbidden, item)
        compromised = json.loads(json.dumps(payload))
        compromised["items"][0]["note"] = '{"routerDecision":"DELEGATE"}'
        with self.assertRaisesRegex(ValueError, "leaks hidden evidence"):
            validate_blind_review_payload(compromised)

    def test_blind_review_queue_supports_independent_consensus_and_agreement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            self._record(store, "record-a", "Explain write-ahead logging")
            first = store.create_blind_review_batch(reviewer="reviewer-a", limit=1)
            second = store.create_blind_review_batch(reviewer="reviewer-b", limit=1)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            now = "2026-09-19T12:00:00+00:00"
            for reviewer, item in (("reviewer-a", first[0]), ("reviewer-b", second[0])):
                result = store.import_blind_review_votes([{
                    "item_id": item["item_id"],
                    "verdict": "DIRECT",
                    "reason_category": "answerable_from_request_context",
                    "note": "",
                    "reviewed_at": now,
                    "visible_request": item["request_text"],
                    "visible_requirements": public_review_item(
                        item["item_id"], item["request_text"]
                    )["requirements"],
                }], reviewer=reviewer)
                self.assertEqual(result["imported"], 1)
            audit = store.blind_review_audit()
            self.assertEqual(audit["rubricVersion"], RUBRIC_VERSION)
            self.assertEqual(audit["acceptedHumanGoldClassBalance"], {"DIRECT": 1})
            self.assertEqual(audit["agreement"]["agreementRate"], 1.0)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            self.assertEqual(rows[0]["label_source"], "human_gold")
            self.assertEqual(rows[0]["labeling_method"], "blind_human_review_v2")
            self.assertTrue(rows[0]["label_independent"])

    def test_blind_import_binds_visible_request_to_hidden_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            self._record(store, "record-d", "Explain write-ahead logging")
            item = store.create_blind_review_batch(reviewer="reviewer-a", limit=1)[0]
            public = public_review_item(item["item_id"], item["request_text"])
            with self.assertRaisesRegex(ValueError, "visible evidence was altered"):
                store.import_blind_review_votes([{
                    "item_id": item["item_id"],
                    "verdict": "DIRECT",
                    "reason_category": None,
                    "note": "",
                    "reviewed_at": "2026-09-19T12:00:00+00:00",
                    "visible_request": "Inspect the repository and run tests",
                    "visible_requirements": public["requirements"],
                }], reviewer="reviewer-a")
            self.assertEqual(store.blind_review_audit()["activeVoteCount"], 0)

    def test_blind_vote_correction_is_append_only_and_retracts_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            self._record(store, "record-b", "Explain a queue")
            items = []
            for reviewer in ("reviewer-a", "reviewer-b"):
                item = store.create_blind_review_batch(reviewer=reviewer, limit=1)[0]
                store.import_blind_review_votes([{
                    "item_id": item["item_id"],
                    "verdict": "DIRECT",
                    "reason_category": None,
                    "note": "",
                    "reviewed_at": "2026-09-19T12:00:00+00:00",
                    "visible_request": item["request_text"],
                    "visible_requirements": public_review_item(
                        item["item_id"], item["request_text"]
                    )["requirements"],
                }], reviewer=reviewer)
                items.append(item)
            self.assertEqual(len(store.blind_human_resolutions()), 1)
            with store._reader() as connection:
                original = connection.execute(
                    "SELECT vote_id FROM blind_review_votes WHERE reviewer = 'reviewer-a'"
                ).fetchone()[0]
            replacement = store.correct_blind_review_vote(
                str(original),
                reviewer="reviewer-a",
                verdict="DELEGATE",
                reason_category="boundary_or_insufficient_context",
                note="corrected",
                correction_reason="misread the execution requirement",
            )
            self.assertTrue(replacement.startswith("brv_"))
            self.assertEqual(store.blind_human_resolutions(), {})
            with store._reader() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM blind_review_votes"
                    ).fetchone()[0],
                    3,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT action FROM blind_review_resolution_events "
                        "ORDER BY event_id DESC LIMIT 1"
                    ).fetchone()[0],
                    "retracted",
                )

    def test_one_reviewer_cannot_create_consensus_through_multiple_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            self._record(store, "record-c", "Explain a semaphore")
            first = store.create_blind_review_batch(reviewer="reviewer-a", limit=1)[0]
            second = store.create_blind_review_batch(reviewer="reviewer-a", limit=1)[0]
            with self.assertRaisesRegex(ValueError, "duplicate reviewer votes"):
                store.import_blind_review_votes([
                    {
                        "item_id": item["item_id"],
                        "verdict": "DIRECT",
                        "reason_category": None,
                        "note": "",
                        "reviewed_at": "2026-09-19T12:00:00+00:00",
                        "visible_request": item["request_text"],
                        "visible_requirements": public_review_item(
                            item["item_id"], item["request_text"]
                        )["requirements"],
                    }
                    for item in (first, second)
                ], reviewer="reviewer-a")
            self.assertEqual(store.blind_human_resolutions(), {})

    def test_semantic_duplicate_guard_groups_endpoint_paraphrases(self) -> None:
        rows = [
            {"request_text": value, "request_fingerprint": str(index)}
            for index, value in enumerate((
                "fix this endpoint",
                "repair the API route",
                "the endpoint is broken, correct it",
                "explain photosynthesis",
            ))
        ]
        pairs = _semantic_duplicate_pairs(rows)
        self.assertEqual({(left, right) for left, right, _score in pairs}, {
            (0, 1), (0, 2), (1, 2),
        })

    def test_semantic_duplicate_guard_reuses_supplied_lexical_pairs(self) -> None:
        rows = [
            {"request_text": "fix this endpoint", "request_fingerprint": "a"},
            {"request_text": "repair the API route", "request_fingerprint": "b"},
        ]
        with mock.patch(
            "quattro_agent.intelligence.dataset._near_duplicate_pairs",
            side_effect=AssertionError("lexical pairs were recomputed"),
        ):
            pairs = _semantic_duplicate_pairs(rows, lexical_pairs=[])
        self.assertEqual([(left, right) for left, right, _score in pairs], [(0, 1)])

    def test_split_manifest_is_fingerprinted_and_registered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            import_controlled_probes(store)
            manifest = DatasetBuilder(store).extract(root / "datasets")
            split_path = pathlib.Path(manifest["splitManifestPath"])
            split_payload = json.loads(split_path.read_text(encoding="utf-8"))
            self.assertEqual(
                split_payload["contentSha256"],
                manifest["splitManifestFingerprint"],
            )
            self.assertEqual(
                store.dataset_manifest(manifest["datasetVersion"])[
                    "splitManifestFingerprint"
                ],
                manifest["splitManifestFingerprint"],
            )

    def test_chronological_blind_split_has_global_temporal_boundary(self) -> None:
        rows = [
            {
                "component_fingerprint": f"group-{index:03d}",
                "labeling_method": "blind_human_review_v2",
                "label": "DIRECT" if index % 2 == 0 else "DELEGATE",
                "created_at": (
                    dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
                    + dt.timedelta(hours=index)
                ).isoformat(),
            }
            for index in range(100)
        ]
        assignments = _chronological_blind_group_splits(rows)
        self.assertEqual(len(assignments), 100)
        train_indexes = [
            index for index in range(100)
            if assignments[f"group-{index:03d}"] == "train"
        ]
        validation_indexes = [
            index for index in range(100)
            if assignments[f"group-{index:03d}"] == "validation"
        ]
        test_indexes = [
            index for index in range(100)
            if assignments[f"group-{index:03d}"] == "test"
        ]
        self.assertLess(max(train_indexes), min(validation_indexes))
        self.assertLess(max(validation_indexes), min(test_indexes))

    def test_sampling_taxonomy_covers_required_categories(self) -> None:
        cases = {
            "Hello": "conversational_trivial",
            "Explain database indexes": "factual_explanatory",
            "Research the latest official release": "current_information_retrieval",
            "Inspect this repository and locate the parser": "repository_inspection",
            "Fix this endpoint in the repository": "small_code_modification",
            "Inspect the repository, refactor multiple modules, then run tests": "substantial_code_modification",
            "Debug why this service crashes": "debugging",
            "Run the build and verify the test result": "test_build_verification",
            "Research the history using two sources": "research",
            "Use the browser then run the shell command": "tool_orchestration",
            "Implement the workflow, then verify it end to end": "multi_step_implementation",
            "Analyze the architecture trade-offs conceptually": "complex_reasoning_no_execution",
        }
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(sampling_category(request), expected)

    def test_blind_batch_interface_persists_only_contract_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "blind.json"
            payload = blind_review_payload([
                public_review_item("br_" + "c" * 32, "Explain queues")
            ])
            path.write_text(json.dumps(payload), encoding="utf-8")
            with (
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=[
                    "d", "answerable_from_request_context", "clear request",
                ]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = _interactive_blind_review_batch(path, payload)
            saved = json.loads(path.read_text(encoding="utf-8"))
            validate_blind_review_payload(saved)
            self.assertEqual(result["finalizedThisRun"], 1)
            self.assertEqual(saved["items"][0]["label"], "DIRECT")

    def test_agreement_metrics_support_cohen_and_fleiss(self) -> None:
        votes = [
            {"record_id": "a", "verdict": "DIRECT"},
            {"record_id": "a", "verdict": "DIRECT"},
            {"record_id": "b", "verdict": "DIRECT"},
            {"record_id": "b", "verdict": "DELEGATE"},
            {"record_id": "c", "verdict": "UNCERTAIN"},
            {"record_id": "c", "verdict": "UNCERTAIN"},
        ]
        metrics = agreement_metrics(votes)
        self.assertEqual(metrics["multiReviewedRecordCount"], 3)
        self.assertEqual(metrics["agreementRate"], 0.666667)
        self.assertIsNotNone(metrics["cohenKappaTwoReviewer"])
        self.assertIn("2", metrics["fleissKappaByRaterCount"])

    def test_phase_110_blocks_candidate_without_blind_human_gold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            state = root / "state"
            output = root / "phase-1-10-report.json"
            defaults = {
                "action": "phase-1-10",
                "value": None,
                "label": None,
                "source": None,
                "notes": "",
                "input": None,
                "dataset": None,
                "model": None,
                "prompt": None,
                "repository_present": False,
                "output_directory": None,
                "output": str(output),
                "activate_shadow": False,
                "no_sync": False,
                "limit": 50,
                "production_decision": None,
                "reviewer": None,
                "pretty": False,
            }
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = intelligence_command(
                    argparse.Namespace(**defaults),
                    state_root=state,
                    task_store_path=root / "missing.sqlite3",
                )
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(
                report["phaseStatus"],
                "COMPLETE — HUMAN DATA PIPELINE READY / BLOCKED BY DATA",
            )
            self.assertEqual(report["mlViability"], "BLOCKED BY DATA")
            self.assertEqual(report["phase2Readiness"], "NOT READY")
            self.assertIsNone(report["candidateModelVersion"])
            self.assertFalse(
                report["candidateGate"]["gates"]["blindHumanGoldBothClasses"]
            )
            self.assertTrue(output.with_suffix(".md").is_file())


if __name__ == "__main__":
    unittest.main()
