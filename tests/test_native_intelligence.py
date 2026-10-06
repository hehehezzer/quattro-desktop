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

    def test_symlink_configuration_disables_direct_advice_without_read_or_replacement(self) -> None:
        root = Path(self.temporary.name)
        target = root / "target.json"
        original = '{"enabled":true,"operationalEnabled":true}'
        target.write_text(original)
        link = root / "config.json"
        link.symlink_to(target)
        self.assertEqual(native.native_config_path(), link)
        settings = native.load_native_settings()
        self.assertFalse(settings.enabled)
        self.assertFalse(settings.retrieval_enabled)
        self.assertFalse(settings.rtk_enabled)
        with mock.patch.object(native, "DecisionSession") as session:
            result = native.native_jev_advice(
                request(), context=native.NativeContext(host="pi", session_id="unsafe-config"),
            )
        self.assertEqual(result["evidence"], "disabled")
        session.assert_not_called()
        with self.assertRaises(native.ConfigError):
            native.write_native_settings(enabled=True)
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), original)

    def test_missing_configuration_preserves_native_defaults(self) -> None:
        self.assertTrue(native.load_native_settings().enabled)
        self.assertFalse(native.load_native_settings().configured)

    def test_parent_symlink_configuration_disables_advice_and_settings_writes(self) -> None:
        root = Path(self.temporary.name)
        real = root / "real"
        real.mkdir()
        target = real / "config.json"
        original = '{"enabled":true}'
        target.write_text(original)
        linked = root / "linked"
        linked.symlink_to(real, target_is_directory=True)
        path = linked / "config.json"
        with mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(path)}):
            self.assertTrue(native.native_config_has_symlink())
            self.assertFalse(native.load_native_settings().enabled)
            with mock.patch.object(native, "DecisionSession") as session:
                result = native.native_jev_advice(request(), context=native.NativeContext(
                    host="pi", session_id="unsafe-parent-config"))
            self.assertEqual(result["evidence"], "disabled")
            session.assert_not_called()
            with self.assertRaises(native.ConfigError):
                native.write_native_settings(enabled=True)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(target.read_text(), original)

    def test_default_xdg_symlink_origin_is_preserved_and_denied(self) -> None:
        root = Path(self.temporary.name)
        real = root / "xdg-real"
        (real / "quattro").mkdir(parents=True)
        target = real / "quattro/native-intelligence.json"
        target.write_text('{"enabled":true}')
        linked = root / "xdg-linked"
        linked.symlink_to(real, target_is_directory=True)
        with mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": "", "XDG_CONFIG_HOME": str(linked)}):
            self.assertEqual(native.native_config_path(), linked / "quattro/native-intelligence.json")
            self.assertTrue(native.native_config_has_symlink())
            self.assertFalse(native.load_native_settings().enabled)
            with mock.patch.object(native, "DecisionSession") as session:
                result = native.native_jev_advice(request(), context=native.NativeContext(
                    host="pi", session_id="unsafe-xdg-config"))
            self.assertEqual(result["evidence"], "disabled")
            session.assert_not_called()
            with self.assertRaises(native.ConfigError):
                native.write_native_settings(enabled=True)
        self.assertEqual(target.read_text(), '{"enabled":true}')

    def test_existing_nonregular_configuration_never_reads_consults_or_replaces(self) -> None:
        root = Path(self.temporary.name)
        directory = root / "directory-config"
        directory.mkdir()
        paths = [directory]
        if hasattr(os, "mkfifo"):
            fifo = root / "fifo-config"
            os.mkfifo(fifo, 0o600)
            paths.append(fifo)
        for path in paths:
            with self.subTest(kind="directory" if path.is_dir() else "fifo"), \
                    mock.patch.dict(os.environ, {"QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(path)}), \
                    mock.patch.object(Path, "read_text", side_effect=AssertionError("unsafe contents read")), \
                    mock.patch.object(native, "DecisionSession") as session:
                self.assertTrue(native.native_config_is_unsafe())
                self.assertFalse(native.load_native_settings().enabled)
                result = native.native_jev_advice(request(), context=native.NativeContext(
                    host="pi", session_id="unsafe-nonregular-config"))
                self.assertEqual(result["evidence"], "disabled")
                session.assert_not_called()
                with self.assertRaises(native.ConfigError):
                    native.write_native_settings(enabled=True)
                self.assertTrue(path.exists())

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
