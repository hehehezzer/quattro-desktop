from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock
from collections.abc import Mapping
from typing import Any


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quattro_agent.intelligence.classical import train_direct_delegate_model
from quattro_agent.intelligence.commands import _interactive_blind_review_batch
from quattro_agent.intelligence.evidence import (
    chronological_partition,
    evidence_acquisition_progress,
)
from quattro_agent.intelligence.readiness import PromotionThresholds
from quattro_agent.intelligence.review import (
    blind_review_payload,
    deterministic_sample_order,
    public_review_item,
    upgrade_blind_review_payload,
    validate_blind_review_payload,
)
from quattro_agent.intelligence.store import IntelligenceStore


REVIEWED_AT = "2026-09-20T12:00:00+00:00"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record(
    store: IntelligenceStore,
    record_id: str,
    request: str,
    *,
    created_at: str = REVIEWED_AT,
    production_decision: str = "DIRECT",
    ml_prediction: str = "DELEGATE",
    group_fingerprint: str | None = None,
) -> str:
    return store.record_routing({
        "record_id": record_id,
        "source_kind": "durable_task",
        "entrypoint": "prompt",
        "decision_applied": True,
        "request_text": request,
        "request_fingerprint": _fingerprint(request),
        "group_fingerprint": group_fingerprint or _fingerprint(record_id),
        "request_redacted": False,
        "request_length": len(request),
        "estimated_tokens": max(1, (len(request) + 3) // 4),
        "task_type": "unknown",
        "complexity": "unknown",
        "category": "general",
        "task_category": "general",
        "repository_present": False,
        "retrieval_required": False,
        "production_decision": production_decision,
        "production_confidence": 0.91,
        "routing_reason": "hidden deterministic reason",
        "selected_worker": "hidden-worker",
        "selected_model": "hidden-model",
        "selected_provider": "hidden-provider",
        "selected_account": "hidden-account",
        "ml_prediction": ml_prediction,
        "ml_confidence": 0.73,
        "ml_model_version": "hidden-shadow-model",
        "inference_latency_ms": 12.5,
        "created_at": created_at,
    })


def _vote(
    store: IntelligenceStore,
    *,
    reviewer: str,
    verdict: str,
    task_category_correction: str | None = None,
    complexity_correction: str | None = None,
) -> dict[str, Any]:
    item = store.create_blind_review_batch(reviewer=reviewer, limit=1)[0]
    visible = public_review_item(item["item_id"], item["request_text"])
    result = store.import_blind_review_votes(
        [{
            "item_id": item["item_id"],
            "verdict": verdict,
            "reason_category": (
                "answerable_from_request_context"
                if verdict == "DIRECT"
                else "execution_required"
            ),
            "note": "",
            "reviewed_at": REVIEWED_AT,
            "visible_request": visible["request"],
            "visible_requirements": visible["requirements"],
            "task_category_correction": task_category_correction,
            "complexity_correction": complexity_correction,
        }],
        reviewer=reviewer,
    )
    if result != {"imported": 1, "skipped": 0}:
        raise AssertionError(f"unexpected blind-review import result: {result}")
    return item


class EvidenceAcquisitionProgressTests(unittest.TestCase):
    def test_progress_exposes_live_deficits_and_drives_priority(self) -> None:
        thresholds = PromotionThresholds(
            minimum_independent_usable_groups=4,
            minimum_independent_usable_groups_per_class=2,
            minimum_categories=2,
            minimum_usable_labels_per_category=2,
            minimum_complexity_bands=2,
            minimum_usable_labels_per_complexity_band=1,
            minimum_human_gold_groups=2,
            minimum_human_gold_groups_per_class=1,
        )
        rows = [
            {
                "record_id": "direct-1",
                "request_text": "Explain what a mutex is",
                "group_fingerprint": "group-direct",
                "label": "DIRECT",
                "label_independent": True,
                "label_source": "human_gold",
                "task_category": "factual_explanatory",
                "complexity": "low",
                "created_at": "2026-09-01T00:00:00+00:00",
            },
            {
                "record_id": "delegate-1",
                "request_text": "Inspect the repository files and report the API entry point",
                "group_fingerprint": "group-delegate",
                "label": "DELEGATE",
                "label_independent": True,
                "label_source": "human_gold",
                "task_category": "factual_explanatory",
                "complexity": "medium",
                "created_at": "2026-09-02T00:00:00+00:00",
            },
            # A second row from the same independent component must not add progress.
            {
                "record_id": "delegate-duplicate",
                "request_text": "Inspect the repository files and report the API entry point",
                "group_fingerprint": "group-delegate",
                "label": "DELEGATE",
                "label_independent": True,
                "label_source": "silver",
                "task_category": "factual_explanatory",
                "complexity": "medium",
                "created_at": "2026-09-03T00:00:00+00:00",
            },
            {
                "record_id": "direct-2",
                "request_text": "Explain queueing in simple terms",
                "group_fingerprint": "group-direct-2",
                "label": "DIRECT",
                "label_independent": True,
                "label_source": "human_gold",
                "task_category": "drafting",
                "complexity": "low",
                "created_at": "2026-09-04T00:00:00+00:00",
            },
        ]
        audit = {
            "acceptedHumanGoldCount": 1,
            "acceptedHumanGoldClassBalance": {"DIRECT": 1},
            "acceptedProvenanceBalance": {"consensus_human_blind": 1},
            "qualityStates": {"single_review": 2, "consensus": 1},
        }

        progress = evidence_acquisition_progress(
            rows,
            blind_audit=audit,
            thresholds=thresholds,
        )

        self.assertEqual(
            progress["global"], {"current": 3, "required": 4, "deficit": 1}
        )
        self.assertEqual(
            progress["classes"]["DIRECT"],
            {"current": 2, "required": 2, "deficit": 0},
        )
        self.assertEqual(
            progress["classes"]["DELEGATE"],
            {"current": 1, "required": 2, "deficit": 1},
        )
        self.assertEqual(
            progress["categoryCoverage"]["categories"]["factual_explanatory"],
            {
                "current": 2,
                "required": 2,
                "deficit": 0,
                "classRepresentation": {"DIRECT": 1, "DELEGATE": 1},
                "acceptedHumanGold": 2,
                "humanGoldClassRepresentation": {"DIRECT": 1, "DELEGATE": 1},
            },
        )
        self.assertEqual(
            progress["humanGold"]["byClass"]["DELEGATE"],
            {"current": 1, "required": 1, "deficit": 0},
        )

        candidates = [
            {
                "record_id": "factual-candidate",
                "request_text": "Explain what a mutex is",
                "complexity": "low",
            },
            {
                "record_id": "repository-candidate",
                "request_text": (
                    "Inspect the repository files and report the API entry point"
                ),
                "complexity": "medium",
            },
        ]
        selected = deterministic_sample_order(
            candidates,
            seed="evidence-priority-test",
            category_counts={},
            acquisition_targets=progress["nextCollectionTargets"],
            limit=1,
        )
        self.assertEqual(selected[0]["record_id"], "repository-candidate")


class BlindReviewContractTests(unittest.TestCase):
    def test_v1_review_artifact_upgrades_without_changing_visible_evidence(self) -> None:
        payload = blind_review_payload([
            public_review_item("br_" + "f" * 32, "Explain queues")
        ])
        payload["schemaVersion"] = 1
        item = payload["items"][0]
        item.pop("taskCategoryCorrection")
        item.pop("complexityCorrection")
        upgraded = upgrade_blind_review_payload(payload)
        self.assertEqual(upgraded["schemaVersion"], 2)
        self.assertEqual(upgraded["items"][0]["request"], "Explain queues")
        self.assertIsNone(upgraded["items"][0]["taskCategoryCorrection"])
        validate_blind_review_payload(upgraded)

    def test_payload_hides_route_shadow_and_execution_evidence_and_allows_corrections(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = _record(
                store,
                "blind-record",
                "Explain write-ahead logging in one paragraph",
            )
            store.update_execution(record_id, {
                "tools": ["hidden-tool"],
                "retrieval_used": True,
                "retrieved_chunk_ids": ["hidden-chunk"],
                "success": False,
                "failure_category": "hidden-failure",
                "execution_time_ms": 987.0,
                "input_tokens": 123,
                "output_tokens": 456,
                "validation_status": "hidden-validation",
                "test_status": "hidden-test-status",
                "build_status": "hidden-build-status",
            })

            queued = store.create_blind_review_batch(reviewer="reviewer-a", limit=1)
            self.assertEqual(len(queued), 1)
            item = public_review_item(queued[0]["item_id"], queued[0]["request_text"])
            item.update({
                "label": "DIRECT",
                "reviewStatus": "completed",
                "reasonCategory": "answerable_from_request_context",
                "taskCategoryCorrection": "explanation",
                "complexityCorrection": "medium",
            })
            payload = blind_review_payload([item])
            validate_blind_review_payload(payload)

            self.assertEqual(item["taskCategoryCorrection"], "explanation")
            self.assertEqual(item["complexityCorrection"], "medium")
            serialized = json.dumps(payload, sort_keys=True)
            for hidden_value in (
                "hidden deterministic reason",
                "hidden-worker",
                "hidden-model",
                "hidden-provider",
                "hidden-account",
                "hidden-shadow-model",
                "hidden-tool",
                "hidden-chunk",
                "hidden-failure",
                "hidden-validation",
                "hidden-test-status",
                "hidden-build-status",
            ):
                self.assertNotIn(hidden_value, serialized)
            forbidden_names = {
                "production_decision",
                "productionDecision",
                "production_confidence",
                "routing_reason",
                "ml_prediction",
                "shadowPrediction",
                "ml_confidence",
                "selected_worker",
                "selected_model",
                "selected_provider",
                "selected_account",
                "tools",
                "retrieval_used",
                "success",
                "failure_category",
                "execution_time_ms",
                "input_tokens",
                "output_tokens",
                "validation_status",
                "test_status",
                "build_status",
            }
            keys: set[str] = set()

            def collect(value: Any) -> None:
                if isinstance(value, Mapping):
                    keys.update(map(str, value))
                    for child in value.values():
                        collect(child)
                elif isinstance(value, list):
                    for child in value:
                        collect(child)

            collect(payload)
            self.assertTrue(forbidden_names.isdisjoint(keys))

    def test_interrupted_private_review_artifact_resumes_without_relabeling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "review.json"
            payload = blind_review_payload([
                public_review_item("br_" + "a" * 32, "Explain mutexes"),
                public_review_item("br_" + "b" * 32, "Explain semaphores"),
            ])
            path.write_text(json.dumps(payload), encoding="utf-8")
            with (
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=[
                    "d", "answerable_from_request_context", "", "", "", "q",
                ]),
                mock.patch("builtins.print"),
            ):
                first = _interactive_blind_review_batch(path, payload)
            self.assertEqual(first["progress"]["pending"], 1)
            resumed = json.loads(path.read_text(encoding="utf-8"))
            with (
                mock.patch("sys.stdin.isatty", return_value=True),
                mock.patch("builtins.input", side_effect=[
                    "d", "answerable_from_request_context", "", "", "",
                ]),
                mock.patch("builtins.print"),
            ):
                second = _interactive_blind_review_batch(path, resumed)
            self.assertEqual(second["finalizedThisRun"], 1)
            self.assertEqual(second["progress"]["pending"], 0)
            final = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([item["label"] for item in final["items"]], [
                "DIRECT", "DIRECT",
            ])

    def test_legacy_or_machine_label_cannot_masquerade_as_blind_human_gold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            record_id = _record(store, "legacy-human", "Explain queues")
            store.label_record(
                record_id,
                "DIRECT",
                source="human_gold",
                reviewer="reviewer-a",
            )
            from quattro_agent.intelligence.dataset import DatasetBuilder, load_dataset
            manifest = DatasetBuilder(store).extract(root / "datasets")
            rows = load_dataset(pathlib.Path(manifest["datasetPath"]))
            self.assertEqual(rows[0]["labeling_method"], "manual_cli_unblinded")
            self.assertFalse(rows[0]["label_independent"])
            self.assertNotEqual(rows[0]["gold_provenance"], "consensus_human_blind")


class EvidenceStateTests(unittest.TestCase):
    def test_adjudication_queue_contains_only_disputed_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            _record(store, "disputed-record", "Explain a queue")
            _vote(store, reviewer="reviewer-a", verdict="DIRECT")
            _vote(store, reviewer="reviewer-b", verdict="DELEGATE")
            _record(store, "fresh-record", "Explain a semaphore")

            selected = store.create_blind_review_batch(
                reviewer="reviewer-c",
                limit=20,
                adjudication_only=True,
            )

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["request_text"], "Explain a queue")

    def test_single_blind_vote_reuses_unchanged_immutable_dataset_snapshot(self) -> None:
        """Report-only single votes must not make extraction fail closed."""
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            record_id = _record(store, "legacy-record", "Explain a queue")
            store.label_record(
                record_id,
                "DIRECT",
                source="human_verified",
                reviewer="legacy-reviewer",
                labeling_method="legacy_exposed_review",
            )
            from quattro_agent.intelligence.dataset import DatasetBuilder

            builder = DatasetBuilder(store)
            first = builder.extract(root / "datasets")
            _vote(store, reviewer="reviewer-a", verdict="DIRECT")
            second = builder.extract(root / "datasets")

            self.assertEqual(first["datasetVersion"], second["datasetVersion"])
            self.assertEqual(first["contentSha256"], second["contentSha256"])
            self.assertFalse(first["snapshotReused"])
            self.assertTrue(second["snapshotReused"])
            self.assertEqual(
                second["currentSourceEvidenceRevision"]["blindVoteCount"], 1
            )

    def test_consensus_taxonomy_corrections_are_report_only_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            _record(store, "taxonomy-record", "Explain a queue")
            for reviewer in ("reviewer-a", "reviewer-b"):
                _vote(
                    store,
                    reviewer=reviewer,
                    verdict="DIRECT",
                    task_category_correction="summarization",
                    complexity_correction="high",
                )
            from quattro_agent.intelligence.dataset import DatasetBuilder, load_dataset
            manifest = DatasetBuilder(store).extract(root / "datasets")
            row = load_dataset(pathlib.Path(manifest["datasetPath"]))[0]
            self.assertEqual(row["evidence_task_category"], "summarization")
            self.assertEqual(row["evidence_complexity"], "high")
            self.assertEqual(row["taxonomy_correction_provenance"], {
                "taskCategory": "consensus_human_blind",
                "complexity": "consensus_human_blind",
            })
            self.assertEqual(row["task_category"], "explanation")
            self.assertEqual(row["complexity"], "low")

    def test_third_independent_vote_adjudicates_a_binary_dispute(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            _record(store, "third-vote-record", "Explain a read-write lock")
            _vote(store, reviewer="reviewer-a", verdict="DIRECT")
            _vote(store, reviewer="reviewer-b", verdict="DELEGATE")
            self.assertEqual(
                store.blind_review_quality_states()["third-vote-record"],
                "disputed",
            )
            _vote(store, reviewer="reviewer-c", verdict="DIRECT")
            resolution = store.blind_human_resolutions()["third-vote-record"]
            self.assertEqual(resolution["label"], "DIRECT")
            self.assertEqual(resolution["provenance"], "adjudicated_human")
            self.assertEqual(
                store.blind_review_quality_states()["third-vote-record"],
                "adjudicated",
            )

    def test_single_review_becomes_disputed_then_rejected_without_history_loss(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = _record(store, "quality-record", "Explain this request")

            _vote(store, reviewer="reviewer-a", verdict="DIRECT")
            self.assertEqual(
                store.blind_review_quality_states()[record_id], "single_review"
            )
            _vote(store, reviewer="reviewer-b", verdict="DELEGATE")
            self.assertEqual(
                store.blind_review_quality_states()[record_id], "disputed"
            )

            adjudication_id = store.adjudicate_blind_review(
                record_id,
                adjudicator="reviewer-c",
                verdict="REJECT",
                reason="Execution is required by the request contract.",
                reviewed_at="2026-09-20T13:00:00+00:00",
            )
            self.assertTrue(adjudication_id.startswith("bra_"))
            self.assertEqual(
                store.blind_review_quality_states()[record_id], "rejected"
            )
            self.assertNotIn(record_id, store.blind_human_resolutions())

            with store._reader() as connection:
                vote_id = str(connection.execute(
                    "SELECT vote_id FROM blind_review_votes WHERE reviewer = 'reviewer-a'"
                ).fetchone()[0])
            with self.assertRaisesRegex(ValueError, "cannot be corrected"):
                store.correct_blind_review_vote(
                    vote_id,
                    reviewer="reviewer-a",
                    verdict="DIRECT",
                    reason_category=None,
                    note="",
                    correction_reason="late correction",
                )

            with store._reader() as connection:
                votes = connection.execute(
                    "SELECT reviewer,verdict FROM blind_review_votes "
                    "WHERE record_id = ? ORDER BY reviewer",
                    (record_id,),
                ).fetchall()
                adjudications = connection.execute(
                    "SELECT count(*) FROM blind_review_adjudications "
                    "WHERE record_id = ?",
                    (record_id,),
                ).fetchone()[0]
            self.assertEqual(
                [(row["reviewer"], row["verdict"]) for row in votes],
                [("reviewer-a", "DIRECT"), ("reviewer-b", "DELEGATE")],
            )
            self.assertEqual(adjudications, 1)

    def test_sqlite_evidence_history_tables_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            record_id = _record(store, "trigger-record", "Explain this request")
            _vote(store, reviewer="reviewer-a", verdict="DIRECT")
            _vote(store, reviewer="reviewer-b", verdict="DELEGATE")
            _vote(store, reviewer="reviewer-c", verdict="DIRECT")
            store.adjudicate_blind_review(
                record_id,
                adjudicator="reviewer-d",
                verdict="REJECT",
                reason="The supplied context is sufficient.",
            )

            statements = (
                "UPDATE blind_review_votes SET note = 'changed'",
                "DELETE FROM blind_review_votes",
                "UPDATE blind_review_resolution_events SET reason = 'changed'",
                "DELETE FROM blind_review_resolution_events",
                "UPDATE blind_review_adjudications SET reason = 'changed'",
                "DELETE FROM blind_review_adjudications",
            )
            for statement in statements:
                with self.subTest(statement=statement):
                    connection = store._connect()
                    try:
                        with self.assertRaisesRegex(
                            sqlite3.IntegrityError, "append-only"
                        ):
                            connection.execute(statement)
                    finally:
                        connection.close()

            with store._reader() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM blind_review_votes"
                    ).fetchone()[0],
                    3,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT count(*) FROM blind_review_adjudications"
                    ).fetchone()[0],
                    1,
                )


class EvidenceSelectionTests(unittest.TestCase):
    def test_connected_near_duplicates_do_not_inflate_review_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            requests = (
                "find readme path now",
                "find readme path right now",
                "Explain the greenhouse effect in one sentence",
            )
            for index, request in enumerate(requests):
                _record(store, f"candidate-{index}", request)

            selected = store.create_blind_review_batch(
                reviewer="reviewer-a",
                limit=10,
            )

            self.assertEqual(len(selected), 2)
            selected_requests = {item["request_text"] for item in selected}
            self.assertEqual(
                len(selected_requests & set(requests[:2])),
                1,
                "one connected near-duplicate family should yield one review item",
            )
            self.assertIn(requests[2], selected_requests)

    def test_component_scan_does_not_hold_writer_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            _record(store, "candidate", "Inspect the README")
            from quattro_agent.intelligence.dataset import connected_component_fingerprints

            def probe(rows):
                connection = store._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.rollback()
                finally:
                    connection.close()
                return connected_component_fingerprints(rows)

            with mock.patch(
                "quattro_agent.intelligence.dataset.connected_component_fingerprints",
                side_effect=probe,
            ):
                selected = store.create_blind_review_batch(
                    reviewer="reviewer-a", limit=1,
                )
            self.assertEqual(len(selected), 1)


class SealedHoldoutTests(unittest.TestCase):
    def test_holdout_component_scan_does_not_hold_writer_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            _record(store, "sealed-record", "Inspect the README")
            from quattro_agent.intelligence.dataset import connected_component_fingerprints
            component = connected_component_fingerprints(store.list_records())["sealed-record"]
            store.save_dataset_manifest("dd-dataset-test", {
                "datasetVersion": "dd-dataset-test",
                "datasetSchemaVersion": "direct-delegate-dataset-v11",
            })
            store.save_dataset_split_assignments(
                "dd-dataset-test", {component: "test"}
            )

            def probe(rows):
                connection = store._connect()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.rollback()
                finally:
                    connection.close()
                return connected_component_fingerprints(rows)

            with mock.patch(
                "quattro_agent.intelligence.dataset.connected_component_fingerprints",
                side_effect=probe,
            ):
                sealed = store.seal_holdout(
                    dataset_version="dd-dataset-test",
                    members=[{
                        "group_fingerprint": component,
                        "record_id": "sealed-record",
                        "label": "DELEGATE",
                        "created_at": REVIEWED_AT,
                    }],
                )
            self.assertEqual(sealed["member_count"], 1)

    def test_future_duplicate_inherits_sealed_component_protection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            store = IntelligenceStore(root / "intelligence.sqlite3")
            _record(store, "sealed-source", "Fix this endpoint")
            for reviewer in ("reviewer-a", "reviewer-b"):
                _vote(store, reviewer=reviewer, verdict="DELEGATE")
            from quattro_agent.intelligence.dataset import (
                DatasetBuilder, connected_component_fingerprints, load_dataset,
            )
            component = connected_component_fingerprints(store.list_records())["sealed-source"]
            store.save_dataset_manifest("dd-dataset-seed", {
                "datasetVersion": "dd-dataset-seed",
                "datasetSchemaVersion": "direct-delegate-dataset-v11",
            })
            store.save_dataset_split_assignments(
                "dd-dataset-seed", {component: "test"}
            )
            store.seal_holdout(
                dataset_version="dd-dataset-seed",
                members=[{
                    "group_fingerprint": component,
                    "record_id": "sealed-source",
                    "label": "DELEGATE",
                    "created_at": REVIEWED_AT,
                }],
            )
            _record(store, "later-duplicate", "Repair the API route")
            second = DatasetBuilder(store).extract(root / "datasets")
            second_rows = load_dataset(pathlib.Path(second["datasetPath"]))
            protected = [
                row for row in second_rows
                if row["record_id"] in {"sealed-source", "later-duplicate"}
            ]
            self.assertEqual(len(protected), 2)
            self.assertTrue(all(row["holdout_sealed"] for row in protected))
            self.assertTrue(all(row["split"] == "test" for row in protected))
            self.assertEqual(len({row["group_fingerprint"] for row in protected}), 1)

    def test_evaluation_exposure_prevents_late_holdout_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            store.save_dataset_manifest(
                "dd-dataset-test",
                {
                    "datasetVersion": "dd-dataset-test",
                    "datasetSchemaVersion": "direct-delegate-dataset-v11",
                    "sourceEvidenceCount": 1,
                    "splitAssignments": {"exposed-group": "test"},
                },
            )
            store.save_dataset_split_assignments(
                "dd-dataset-test", {"exposed-group": "test"}
            )
            member = {
                "group_fingerprint": "exposed-group",
                "record_id": "exposed-record",
                "label": "DIRECT",
                "created_at": "2026-09-20T00:00:00+00:00",
                "split": "test",
                "holdout_sealed": False,
            }
            self.assertEqual(store.record_evaluation_exposure(
                [member], dataset_version="dd-dataset-test", purpose="readiness"
            ), 1)
            with self.assertRaisesRegex(ValueError, "reserved before evaluation"):
                store.seal_holdout(
                    dataset_version="dd-dataset-test", members=[member]
                )

    def test_exposed_duplicate_blocks_sealing_the_connected_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            _record(store, "opened-record", "Fix this endpoint")
            _record(store, "candidate-record", "Repair the API route")
            from quattro_agent.intelligence.dataset import connected_component_fingerprints
            records = store.list_records()
            components = connected_component_fingerprints(records)
            store.save_dataset_manifest("dd-dataset-test", {
                "datasetVersion": "dd-dataset-test",
                "datasetSchemaVersion": "direct-delegate-dataset-v11",
                "splitAssignments": {components["candidate-record"]: "test"},
            })
            store.save_dataset_split_assignments(
                "dd-dataset-test", {components["candidate-record"]: "test"}
            )
            store.record_evaluation_exposure(
                [{"record_id": "opened-record", "split": "test"}],
                dataset_version="dd-dataset-test",
                purpose="readiness",
            )
            with self.assertRaisesRegex(ValueError, "reserved before evaluation"):
                store.seal_holdout(
                    dataset_version="dd-dataset-test",
                    members=[{
                        "group_fingerprint": components["candidate-record"],
                        "record_id": "candidate-record",
                        "label": "DELEGATE",
                        "created_at": REVIEWED_AT,
                    }],
                )

    def test_sealed_holdout_is_idempotent_immutable_and_integrity_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            store.save_dataset_manifest(
                "dd-dataset-test",
                {
                    "datasetVersion": "dd-dataset-test",
                    "datasetSchemaVersion": "direct-delegate-dataset-v11",
                    "sourceEvidenceCount": 1,
                    "splitAssignments": {"sealed-group": "test"},
                },
            )
            store.save_dataset_split_assignments(
                "dd-dataset-test", {"sealed-group": "test"}
            )
            member = {
                "group_fingerprint": "sealed-group",
                "record_id": "sealed-record",
                "label": "DIRECT",
                "created_at": "2026-09-20T00:00:00+00:00",
                "gold_provenance": "consensus_human_blind",
            }

            first = store.seal_holdout(
                dataset_version="dd-dataset-test",
                members=[member],
            )
            repeated = store.seal_holdout(
                dataset_version="dd-dataset-test",
                members=[member],
            )
            self.assertEqual(first["holdout_id"], repeated["holdout_id"])
            summary = store.sealed_holdout_summary()
            self.assertTrue(summary["sealed"])
            self.assertTrue(summary["allIntegrityValid"])
            self.assertEqual(summary["cohortCount"], 1)
            self.assertEqual(summary["latest"]["sourceGroupIds"], ["sealed-group"])
            self.assertEqual(
                summary["latest"]["integritySha256"], first["integrity_sha256"]
            )

            for statement in (
                "UPDATE sealed_holdouts SET member_count = 2",
                "DELETE FROM sealed_holdouts",
                "UPDATE sealed_holdout_members SET label = 'DELEGATE'",
                "DELETE FROM sealed_holdout_members",
                "INSERT INTO sealed_holdout_members(holdout_id,group_fingerprint,"
                "record_id,label,evidence_created_at) VALUES('"
                + first["holdout_id"]
                + "','extra-group','extra-record','DIRECT',"
                "'2026-09-20T00:00:00.000+00:00')",
            ):
                with self.subTest(statement=statement):
                    connection = store._connect()
                    try:
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                            connection.execute(statement)
                    finally:
                        connection.close()
            self.assertTrue(store.sealed_holdout_summary()["allIntegrityValid"])

            with self.assertRaisesRegex(ValueError, "already sealed"):
                store.seal_holdout(
                    dataset_version="dd-dataset-test",
                    members=[member | {"label": "DELEGATE"}],
                )

    def test_store_rejects_non_test_member_before_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = IntelligenceStore(pathlib.Path(temporary) / "intelligence.sqlite3")
            store.save_dataset_manifest(
                "dd-dataset-test",
                {
                    "datasetVersion": "dd-dataset-test",
                    "datasetSchemaVersion": "direct-delegate-dataset-v11",
                    "splitAssignments": {"train-group": "train"},
                },
            )
            store.save_dataset_split_assignments(
                "dd-dataset-test", {"train-group": "train"}
            )
            with self.assertRaisesRegex(ValueError, "registered test split"):
                store.seal_holdout(
                    dataset_version="dd-dataset-test",
                    members=[{
                        "group_fingerprint": "train-group",
                        "record_id": "train-record",
                        "label": "DIRECT",
                        "created_at": "2026-09-20T00:00:00+00:00",
                    }],
                )

    def test_training_rejects_a_sealed_group_assigned_to_train(self) -> None:
        rows = []
        for index in range(8):
            rows.append({
                "record_id": f"train-{index}",
                "group_fingerprint": f"group-{index}",
                "request_text": (
                    f"Explain concept {index}"
                    if index < 4
                    else f"Inspect repository module {index} and run tests"
                ),
                "label": "DIRECT" if index < 4 else "DELEGATE",
                "label_source": "human_gold",
                "label_independent": True,
                "split": "train",
                "request_length": 20,
                "estimated_tokens": 5,
                "complexity": "low" if index < 4 else "medium",
                "category": "general",
                "task_category": "factual_explanatory",
                "repository_present": index >= 4,
                "retrieval_required": False,
                "tool_required": index >= 4,
                "repository_required": index >= 4,
                "current_information_required": False,
                "execution_required": index >= 4,
                "modification_required": False,
                "verification_required": index >= 4,
                "multi_step_required": False,
                "holdout_sealed": index == 0,
            })

        with self.assertRaisesRegex(
            ValueError, "sealed holdout groups cannot enter training"
        ):
            train_direct_delegate_model(
                rows,
                dataset_version="dd-dataset-test",
                epochs=1,
                calibrate=False,
            )


class ChronologicalEvidenceTests(unittest.TestCase):
    def test_component_uses_newest_member_timestamp_for_chronology(self) -> None:
        start = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
        rows = [
            {
                "record_id": f"record-{index}",
                "group_fingerprint": f"group-{index}",
                "label": "DIRECT" if index % 2 == 0 else "DELEGATE",
                "label_independent": True,
                "created_at": (start + dt.timedelta(days=index)).isoformat(),
            }
            for index in range(10)
        ]
        rows.append({
            "record_id": "late-family-member",
            "group_fingerprint": "group-0",
            "label": None,
            "label_independent": False,
            "created_at": (start + dt.timedelta(days=30)).isoformat(),
        })
        partition = chronological_partition(rows)
        self.assertIn("group-0", partition["unsealedNewest"])
        self.assertNotIn("group-0", partition["train"])

    def test_partition_keeps_sealed_and_newest_groups_out_of_train(self) -> None:
        start = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
        rows = [
            {
                "record_id": f"record-{index}",
                "group_fingerprint": f"group-{index:02d}",
                "label": "DIRECT" if index % 2 == 0 else "DELEGATE",
                "label_independent": True,
                "created_at": (start + dt.timedelta(days=index)).isoformat(),
            }
            for index in range(11)
        ]

        partition = chronological_partition(
            rows,
            sealed_group_fingerprints={"group-02"},
        )

        self.assertEqual(partition["futureHoldout"], ["group-02"])
        self.assertNotIn("group-02", partition["train"])
        self.assertNotIn("group-02", partition["validation"])
        self.assertNotIn("group-02", partition["unsealedNewest"])
        self.assertEqual(partition["unsealedNewest"], ["group-10"])
        self.assertNotIn("group-10", partition["train"])
        self.assertEqual(
            set().union(*map(set, partition.values())),
            {f"group-{index:02d}" for index in range(11)},
        )


if __name__ == "__main__":
    unittest.main()
