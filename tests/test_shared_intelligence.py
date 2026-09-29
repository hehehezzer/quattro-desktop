"""Contract tests for the native, routing-free intelligence boundary."""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock
import importlib.util

from quattro_agent import shared_intelligence as shared
from quattro_intelligence_mcp import handle


class SharedIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._telemetry = tempfile.TemporaryDirectory()
        self.addCleanup(self._telemetry.cleanup)
        self._telemetry_env = mock.patch.dict(
            os.environ,
            {"QUATTRO_NATIVE_TELEMETRY_DB": str(pathlib.Path(self._telemetry.name) / "native.sqlite3")},
        )
        self._telemetry_env.start()
        self.addCleanup(self._telemetry_env.stop)

    def test_trivial_prompt_skips_database_and_context(self) -> None:
        with mock.patch.object(shared, "RetrievalStore", side_effect=AssertionError("opened")):
            for query in ("what is 2 times 3", "Hi", "Thanks!"):
                result = shared.search_knowledge(query)
                self.assertEqual(result["retrievedTokens"], 0)
                self.assertIsNone(result["context"])

    def test_search_is_bounded_and_repository_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "FACT.md").write_text("The silver otter opens the copper gate.\n")
            # Non-Git sources are deliberately not indexed: create a tracked repo.
            import subprocess
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "FACT.md"], check=True)
            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root / "state")}):
                result = shared.search_knowledge("where is the silver otter copper gate documented",
                                                 directory=str(root), budget=2000, limit=2)
            self.assertLessEqual(result["retrievedTokens"], 2000)
            self.assertEqual(result["context"]["structuredState"]["repository"], str(root))

    def test_invalid_config_and_missing_rtk_degrade(self) -> None:
        with self.assertRaises(ValueError):
            shared.search_knowledge("repository", budget=9000)
        with mock.patch.object(shared.shutil, "which", return_value=None):
            self.assertFalse(shared.rtk_status()["available"])
            with self.assertRaises(RuntimeError):
                shared.rtk_run(["git", "status"])

    def test_mcp_discovers_only_shared_tools(self) -> None:
        names = {item["name"] for item in handle({"id": 1, "method": "tools/list"})["result"]["tools"]}
        self.assertEqual(names, {"search_knowledge", "rtk_status", "rtk_run", "refresh_history", "operational_decision"})
        self.assertFalse(any("route" in name or "delegate" in name for name in names))
        response = handle({"id": 2, "method": "tools/call",
                           "params": {"name": "search_knowledge", "arguments": {"query": "what is 2 times 3"}}})
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["retrievedTokens"], 0)

    def test_native_codex_config_preserves_existing_settings_and_is_idempotent(self) -> None:
        installer_path = pathlib.Path(__file__).resolve().parents[1] / "scripts/configure_native_intelligence.py"
        spec = importlib.util.spec_from_file_location("configure_native_intelligence", installer_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            config = root / "config.toml"
            config.write_text('model = "gpt-6-sol"\n')
            command = root / "quattro-intelligence-mcp"
            command.write_text("#!/bin/sh\nexit 0\n")
            self.assertTrue(module.configure(config, command))
            self.assertFalse(module.configure(config, command))
            self.assertIn("operational_decision", config.read_text())
            image = root / "quattro-image-mcp"
            image.write_text("#!/bin/sh\nexit 0\n")
            self.assertTrue(module.configure_image(config, image))
            self.assertFalse(module.configure_image(config, image))
            self.assertIn('model = "gpt-6-sol"', config.read_text())
            self.assertIn('approval_mode = "approve"', config.read_text())
            self.assertNotIn("auth.json", config.read_text())
            config.write_text("[broken\n")
            with self.assertRaises(ValueError):
                module.configure(config, command)

    def test_native_install_configures_pi_and_preserves_native_off(self) -> None:
        installer_path = pathlib.Path(__file__).resolve().parents[1] / "scripts/configure_native_intelligence.py"
        spec = importlib.util.spec_from_file_location("configure_native_intelligence_pi", installer_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            home = pathlib.Path(temporary)
            config = home / ".config/quattro/native-intelligence.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"schemaVersion": 1, "enabled": False, "custom": "preserve"}))
            self.assertFalse(module.configure_native_defaults(home))
            self.assertFalse(json.loads(config.read_text())["enabled"])
            source = pathlib.Path(__file__).resolve().parents[1] / "adapters/pi/quattro-intelligence.ts"
            self.assertTrue(module.configure_pi(home, source))
            self.assertFalse(module.configure_pi(home, source))
            self.assertTrue((home / ".pi/agent/extensions/quattro-intelligence.ts").is_file())

    def test_image_tool_reuses_bridge_without_payload_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch("quattro_image_mcp.generate_image", return_value={
                "structuredContent": {"path": temporary + "/generated-images/a.png"},
                "content": [{"type": "image", "data": "large-base64"}],
            }) as generate:
                result = shared.image_generate("silver otter", directory=temporary)
            self.assertEqual(result, {"path": temporary + "/generated-images/a.png"})
            generate.assert_called_once_with({"prompt": "silver otter"}, project_root=pathlib.Path(temporary))

    def test_recent_episodes_refresh_without_quattro_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            private = root / "quattro/agents/private"
            private.mkdir(parents=True)
            with sqlite3.connect(private / "harness.sqlite3") as source:
                source.execute("CREATE TABLE tasks(task_id TEXT,project_path TEXT,display_title TEXT,state TEXT,terminal_code TEXT,terminal_summary TEXT,created_at TEXT)")
                source.execute("CREATE TABLE events(event_id TEXT,task_id TEXT,event_type TEXT,display_payload_json TEXT,created_at TEXT,sequence INTEGER)")
                source.execute("CREATE TABLE session_checkpoints(checkpoint_id TEXT,task_id TEXT,quattro_session_id TEXT,kind TEXT,content_json TEXT,created_at TEXT)")
                source.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)",
                               ("t1", "/project", "Silver otter task", "done", None, "gate opened", "2026-01-01"))
                source.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                               ("e1", "t1", "fixed", json.dumps({"summary": "copper gate"}), "2026-01-02", 1))
                source.commit()
            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root)}):
                with shared.RetrievalStore(private / "retrieval.sqlite3") as store:
                    self.assertEqual(shared._index_episodes(store, "/project"), "recent_only")
                    self.assertEqual(shared._index_episodes(store, "/project", full=True), "complete")
                    found, _ = store.search("copper gate", repository="/project",
                                            source_types=("session",), allowed_origins=("episodic",))
                    self.assertTrue(found)

    def test_shared_vault_survives_missing_project_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "home/.config/quattro").mkdir(parents=True)
            (root / "home/.config/quattro/ai.json").write_text("{}")
            shared_vault = root / "shared"
            (shared_vault / "Shared").mkdir(parents=True)
            (shared_vault / "Shared/NOTE.md").write_text("Silver otter project knowledge")
            with (mock.patch.object(shared.pathlib.Path, "home", return_value=root / "home"),
                  mock.patch.object(shared, "load_ai_config", return_value={"memory": {
                      "enabled": True, "vaultPath": str(shared_vault),
                      "projectVaultPath": str(root / "missing")}})):
                with shared.RetrievalStore(root / "retrieval.sqlite3") as store:
                    self.assertEqual(shared._index_memory(store, root / "project"), "available")

    def test_optional_history_open_failure_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            private = root / "quattro/agents/private"
            private.mkdir(parents=True)
            (private / "harness.sqlite3").write_bytes(b"broken")
            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": str(root)}):
                with shared.RetrievalStore(private / "retrieval.sqlite3") as store:
                    with mock.patch.object(shared.sqlite3, "connect", side_effect=sqlite3.OperationalError("locked")):
                        self.assertEqual(shared._index_episodes(store, "/project"), "unavailable")

    def test_malformed_memory_config_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / ".config/quattro").mkdir(parents=True)
            (root / ".config/quattro/ai.json").write_text("{}")
            with (mock.patch.object(shared.pathlib.Path, "home", return_value=root),
                  mock.patch.object(shared, "load_ai_config", return_value={"memory": {
                      "enabled": True, "vaultPath": ""}})):
                with shared.RetrievalStore(root / "retrieval.sqlite3") as store:
                    with self.assertRaisesRegex(ValueError, "configuration is malformed"):
                        shared._index_memory(store, root / "project")


if __name__ == "__main__":
    unittest.main()
