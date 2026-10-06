from __future__ import annotations

import io
import os
from pathlib import Path
import socket
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.herdr_runtime import HerdrSession
from quattro_agent.migration_cli import launch_omp, start_omp
from quattro_agent.native_intelligence import NativeContext
from quattro_agent.omp_sessions import OMPSessionRegistry, OMPSessionError
from quattro_agent.shared_intelligence import call


@unittest.skipUnless(os.name == "posix", "Herdr requires Unix sockets")
class OMPNativeRegistryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sock = self.root / "herdr.sock"
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(self.sock))
        self.sock.chmod(0o600)
        self.addCleanup(listener.close)
        self.path = self.root / "private" / "sessions.json"
        self.registry = OMPSessionRegistry(self.path)
        self.handle = HerdrSession("w1", "w1:p1")

    def test_start_binds_only_actual_receipt_and_hidden_reference(self):
        with patch("quattro_agent.migration_cli.omp_registry_path", return_value=self.path), \
                patch("quattro_agent.herdr_runtime.HerdrRuntime.start", return_value=self.handle) as start, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(start_omp(self.root, skills=str(self.root), socket=str(self.sock), confirmed=True), 0)
        argv = start.call_args.args[0]
        logical = argv[argv.index("--native-session-ref") + 1]
        row = self.registry.get(logical)
        self.assertEqual((row["workspace"], row["pane"], row["lifecycle"]), ("w1", "w1:p1", "active"))
        self.assertIsNone(row["nativeSessionId"])

    def test_unapproved_start_has_no_registry_or_runtime_access(self):
        with patch("quattro_agent.migration_cli.omp_registry_path", side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, "action-time"):
                start_omp(self.root, skills=None, socket=str(self.sock), confirmed=False)
        self.assertFalse(self.path.exists())

    def test_failed_launch_keeps_uncertain_record_without_retry(self):
        with patch("quattro_agent.migration_cli.omp_registry_path", return_value=self.path), \
                patch("quattro_agent.herdr_runtime.HerdrRuntime.start", side_effect=RuntimeError("uncertain")) as start:
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                start_omp(self.root, skills=str(self.root), socket=str(self.sock), confirmed=True)
        self.assertEqual(start.call_count, 1)
        import json
        rows = json.loads(self.path.read_text())["sessions"]
        self.assertEqual(next(iter(rows.values()))["lifecycle"], "launch_uncertain")

    def test_child_launch_and_private_observer_bind_actual_identity(self):
        logical = self.registry.begin(socket=self.sock, directory=self.root)
        self.registry.created(logical, self.handle)
        environment = {"HERDR_SOCKET_PATH": str(self.sock), "HERDR_WORKSPACE_ID": "w1", "HERDR_PANE_ID": "w1:p1"}
        with patch.dict(os.environ, environment), \
                patch("quattro_agent.migration_cli.omp_registry_path", return_value=self.path), \
                patch("quattro_agent.migration_cli.shutil.which", return_value="/bin/omp"), \
                patch("quattro_agent.migration_cli.subprocess.run") as run:
            run.return_value.returncode = 0
            launch_omp(self.root, skills=str(self.root), confirmed=True, environment={"PATH": "/bin"}, native_session_ref=logical)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["QUATTRO_OMP_LOGICAL_SESSION"], logical)
        self.assertEqual(env["QUATTRO_OMP_HERDR_PANE"], "w1:p1")
        with patch.dict(os.environ, env):
            result = call("observe_omp_session", {}, telemetry_context=NativeContext(host="omp", session_id="native_123", project=str(self.root)))
        self.assertFalse(result["approvalGranted"])
        self.assertEqual(self.registry.get(logical)["nativeSessionId"], "native_123")

    def test_wrong_pane_and_native_restart_are_rejected(self):
        logical = self.registry.begin(socket=self.sock, directory=self.root)
        self.registry.created(logical, self.handle)
        with self.assertRaises(OMPSessionError):
            self.registry.verify_launch(logical, socket=self.sock, directory=self.root, handle=HerdrSession("w1", "w1:p2"))
        self.registry.observe_native(logical, socket=self.sock, directory=self.root, handle=self.handle, native_session_id="native_123")
        with self.assertRaisesRegex(OMPSessionError, "restart/resume"):
            self.registry.verify_launch(logical, socket=self.sock, directory=self.root, handle=self.handle)

    def test_observer_rejects_model_arguments_and_other_host(self):
        for args, context in [({"nativeId": "forged"}, NativeContext(host="omp")), ({}, NativeContext(host="codex"))]:
            with self.assertRaisesRegex(ValueError, "trusted OMP"):
                call("observe_omp_session", args, telemetry_context=context)


if __name__ == "__main__":
    unittest.main()
