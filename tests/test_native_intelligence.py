"""Tests for launcher-independent native evidence and advisory boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from quattro_agent import native_intelligence as native
from quattro_agent.native_cli import native_status


def request() -> dict:
    return {
        "schema_version": "quattro-jev-decisions-v2",
        "decision_id": "inspection_evidence_gap",
        "question": "Should narrowly relevant inspection precede further implementation?",
        "options": [
            {"id": "narrow_inspection", "description": "Inspect narrowly relevant repository evidence before further work.", "effect": "inspect"},
            {"id": "native_reasoning", "description": "Use native semantic reasoning when evidence does not support inspection.", "effect": "agent"},
        ],
        "context": {"evidence_missing": True, "inspection_count": 0},
        "hard_constraints": {"retry_allowed": False, "parallel_allowed": False,
                              "retrieval_allowed": True},
        "execution_state": {"revision": 0, "phase": "evidence_gathering", "attempt": 0},
        "previous_result": "none",
    }


class NativeIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {
            "QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(root / "config.json"),
            "QUATTRO_NATIVE_TELEMETRY_DB": str(root / "native.sqlite3"),
            "QUATTRO_STATE_DIR": str(root / "state"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.temporary.cleanup)

    def test_missing_authoring_never_constructs_jev_session(self) -> None:
        native.write_native_settings(enabled=True)
        with mock.patch.object(native, "DecisionSession") as session:
            result = native.native_jev_advice(
                {}, context=native.NativeContext(host="pi", session_id="unauthored"),
            )
        self.assertEqual(result["evidence"], "invalid_state")
        session.assert_not_called()

    def test_explicit_off_is_fail_open_and_persisted(self) -> None:
        native.write_native_settings(enabled=False)
        with mock.patch.object(native, "DecisionSession") as session:
            result = native.native_jev_advice(
                request(), context=native.NativeContext(host="codex", session_id="off"),
            )
        self.assertEqual(result["evidence"], "disabled")
        session.assert_not_called()
        self.assertFalse(native.load_native_settings().enabled)

    def test_accepted_advice_records_stages_without_sensitive_input(self) -> None:
        native.write_native_settings(enabled=True)

        class FakeSession:
            def __init__(self, **_kwargs):
                self.counts = {"calls": 0}

            def snapshot(self):
                return {"counts": dict(self.counts)}

            def decide(self, _request, **_kwargs):
                self.counts["calls"] += 1
                return {
                    "selected_action": "narrow_inspection", "selected_effect": "inspect", "confidence": 0.98,
                    "evidence": "native_choice_probabilities", "fallback_required": False, "called": True,
                    "probabilities": {"narrow_inspection": 0.98, "native_reasoning": 0.02},
                    "timing": {"worker_roundtrip_ms": 12.0},
                }

            def close(self):
                return None

        context = native.NativeContext(host="pi", session_id="session-1",
                                       project="/private/project", turn_id="3")
        with mock.patch.object(native, "DecisionSession", FakeSession):
            result = native.native_jev_advice(request(), context=context)
        self.assertEqual(result["selected_action"], "narrow_inspection")
        self.assertEqual(result["usageEvidence"]["providerResponse"], "RECEIVED")
        events = native.NativeTelemetry().trace("session-1")
        self.assertEqual({event["stage"] for event in events}, {
            "requested", "provider_response", "validated", "accepted",
            "advice_delivered", "action_applied",
        })
        encoded = json.dumps(events)
        self.assertNotIn("private/project", encoded)
        self.assertNotIn("secret prompt", encoded)  # no raw prompt is accepted by this boundary

    def test_rejected_advice_records_fallback_reason(self) -> None:
        native.write_native_settings(enabled=True)

        class FakeSession:
            def __init__(self, **_kwargs):
                self.counts = {"calls": 0}

            def snapshot(self):
                return {"counts": dict(self.counts)}

            def decide(self, _request, **_kwargs):
                self.counts["calls"] += 1
                return {
                    "selected_action": None, "confidence": 0.49,
                    "evidence": "uncertain", "fallback_required": True, "called": True,
                    "probabilities": {"narrow_inspection": 0.51, "native_reasoning": 0.49},
                    "timing": {"worker_roundtrip_ms": 12.0},
                }

            def close(self):
                return None

        context = native.NativeContext(host="pi", session_id="rejected-session")
        with mock.patch.object(native, "DecisionSession", FakeSession):
            result = native.native_jev_advice(request(), context=context)
        self.assertFalse(result["usageEvidence"]["accepted"])
        events = native.NativeTelemetry().trace("rejected-session")
        rejected = next(event for event in events if event["stage"] == "rejected")
        self.assertEqual(rejected["metadata"]["fallbackReason"], "uncertain")

    def test_native_boundary_rejects_missing_authored_fallback(self) -> None:
        value = request()
        value["options"] = [value["options"][0], {
            "id": "wait_for_evidence", "description": "Wait for additional evidence before continuing.", "effect": "advise"}]
        with mock.patch.object(native, "DecisionSession") as session:
            result = native.native_jev_advice(value)
        self.assertTrue(result["fallback_required"])
        self.assertEqual(result["evidence"], "invalid_state")
        session.assert_not_called()

    def test_obsolete_category_configuration_is_ignored_and_removed_on_write(self):
        path = Path(os.environ["QUATTRO_NATIVE_INTELLIGENCE_CONFIG"])
        path.write_text(json.dumps({"enabled": True, "categories": ["old_category"], "checkpointsEnabled": False}))
        self.assertTrue(native.load_native_settings().legacy_categories_ignored)
        native.write_native_settings(enabled=False)
        value = json.loads(path.read_text())
        self.assertNotIn("categories", value)
        self.assertFalse(value["checkpointsEnabled"])
        self.assertEqual(value["schemaVersion"], 2)

    def test_passive_status_does_not_create_telemetry(self) -> None:
        native.write_native_settings(enabled=True)
        database = Path(os.environ["QUATTRO_NATIVE_TELEMETRY_DB"])
        self.assertFalse(database.exists())
        status = native_status()
        self.assertTrue(status["passive"])
        self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
