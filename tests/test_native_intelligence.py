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
        "decision_type": "context_strategy",
        "available_actions": ["inspect", "retrieve", "sufficient", "agent"],
        "relevant_context": {"repository_required": True, "context_missing": True},
        "hard_constraints": {"retry_allowed": False, "parallel_allowed": False,
                              "retrieval_allowed": True},
        "execution_state": {"revision": 0, "phase": "inspection", "attempt": 0},
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

    def test_trivial_admission_never_constructs_jev_session(self) -> None:
        native.write_native_settings(enabled=True)
        value = dict(request())
        value["relevant_context"] = {}
        with mock.patch.object(native, "DecisionSession") as session:
            result = native.native_jev_advice(
                value, context=native.NativeContext(host="pi", session_id="trivial"),
            )
        self.assertEqual(result["evidence"], "trivial")
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
                    "selected_action": "retrieve", "confidence": 0.98,
                    "evidence": "native_choice_probabilities", "fallback_required": False,
                    "probabilities": {"retrieve": 0.98, "agent": 0.02},
                    "timing": {"worker_roundtrip_ms": 12.0},
                }

            def close(self):
                return None

        context = native.NativeContext(host="pi", session_id="session-1",
                                       project="/private/project", turn_id="3")
        with mock.patch.object(native, "DecisionSession", FakeSession):
            result = native.native_jev_advice(request(), context=context)
        self.assertEqual(result["selected_action"], "retrieve")
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
                    "evidence": "uncertain", "fallback_required": True,
                    "probabilities": {"retrieve": 0.51, "agent": 0.49},
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

    def test_passive_status_does_not_create_telemetry(self) -> None:
        native.write_native_settings(enabled=True)
        database = Path(os.environ["QUATTRO_NATIVE_TELEMETRY_DB"])
        self.assertFalse(database.exists())
        status = native_status()
        self.assertTrue(status["passive"])
        self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
