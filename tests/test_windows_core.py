from __future__ import annotations

import json
import contextlib
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from quattro.platform.locking import exclusive_lock
from quattro_agent.adapters import AgentMode, CodexAdapter, PiAdapter, RunSpec
from quattro_agent.policy import PolicyProfile
from quattro_agent.recovery import checkpoint_payload, recovery_packet
from quattro_agent.routing import RoutingTier, classify_request
from quattro_agent.store import TaskStore
from quattro_deployment import build_manifest, verify_manifest_files, write_manifest_atomic


@unittest.skipUnless(sys.platform == "win32", "Windows Core hosted validation")
class WindowsCoreTests(unittest.TestCase):
    def test_native_package_cli_starts_without_desktop(self):
        result = subprocess.run([sys.executable, "-m", "quattro_agent", "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Quattro AI control plane", result.stdout)

    def test_sqlite_wal_session_store_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            project = root / "project"; project.mkdir()
            store = TaskStore(root / "state" / "tasks.sqlite3")
            policy = PolicyProfile(name="windows-read-only")
            task_id = store.create_task(workflow="general", agent="codex", project_path=project, display_title="Windows", policy=policy)
            self.assertEqual(store.get_task(task_id)["state"], "created")
            with contextlib.closing(sqlite3.connect(store.path)) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")

    def test_routing_and_adapter_contracts(self):
        classify = lambda request: classify_request(
            request=request, config={}, agent="codex", workflow="general", policy_name="read-only",
        ).tier
        self.assertEqual(classify("fix a typo"), RoutingTier.FAST)
        self.assertEqual(classify("implement a normal feature"), RoutingTier.STANDARD)
        self.assertEqual(classify("audit a security architecture"), RoutingTier.REASONING)
        with tempfile.TemporaryDirectory() as temporary:
            project = pathlib.Path(temporary).resolve()
            policy = PolicyProfile(
                name="windows-read-only", readable_roots=(str(project),), max_commands=1,
            )
            spec = RunSpec(task_id="task", run_id="run", project_path=project, mode=AgentMode.PROMPT, policy=policy, account_home=project / "codex", private_input="hello")
            self.assertIn("exec", CodexAdapter().build_launch("codex.exe", spec).argv)
            self.assertIn("-p", PiAdapter().build_launch("pi.exe", spec).argv)

    def test_recovery_payload_is_portable(self):
        snapshot = {"exists": True, "branch": None, "head": None, "dirty": False, "changedPaths": []}
        checkpoint = checkpoint_payload(objective="resume", requirements=["preserve"], repository_path="C:/work/project", working_directory="C:/work/project", next_action="continue", repository_snapshot=snapshot)
        packet, differences = recovery_packet(checkpoint, current_repository_state=snapshot)
        self.assertIn("OBJECTIVE", packet)
        self.assertEqual(differences, [])

    def test_file_lock_and_core_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            with exclusive_lock(root / "state/lock") as stream:
                self.assertFalse(stream.closed)
            source = root / "source"; deployed = root / "deployed"
            source.mkdir(); deployed.mkdir()
            (source / "core.py").write_text("core", encoding="utf-8")
            (deployed / "core.py").write_text("core", encoding="utf-8")
            manifest = build_manifest(source, deployed, {"core": "core.py"}, revision="c" * 40)
            manifest_path = root / "state/core-manifest.json"
            write_manifest_atomic(manifest_path, manifest)
            self.assertTrue(verify_manifest_files(manifest, source, deployed)["allMatch"])
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["parity"]["mismatched"], 0)


if __name__ == "__main__":
    unittest.main()
