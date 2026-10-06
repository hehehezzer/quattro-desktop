from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.herdr_runtime import HerdrError, HerdrRuntime, HerdrSession, sanitized_terminal_environment


class HerdrRuntimeTests(unittest.TestCase):
    def test_argv_launch_has_no_shell_and_cleanup_has_ownership(self):
        runtime = HerdrRuntime(Path("/tmp/herdr-test.sock"))
        calls = []
        responses = [
            {"workspace": {"workspace_id": "w8"}},
            {"layout": {"focused_pane_id": "w8:p3"}},
            {"type": "ok"},
        ]
        def request(method, params):
            calls.append((method, params))
            return responses.pop(0)
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "_request", request):
            session = runtime.start(["/bin/printf", "$(touch bad); quote'"], directory=Path(directory))
            self.assertEqual(session, HerdrSession("w8", "w8:p3"))
            command = calls[1][1]["root"]["command"]
            self.assertEqual(command[-2:], ["/bin/printf", "$(touch bad); quote'"])
            self.assertNotIn("-c", command)
            self.assertFalse(calls[0][1]["focus"])
            with self.assertRaisesRegex(HerdrError, "unowned"):
                runtime.close(HerdrSession("w99", "w99:p1"))
            runtime.close(session)
            self.assertEqual(calls[-1], ("workspace.close", {"workspace_id": "w8"}))

    def test_environment_omits_credentials_and_injection(self):
        with patch.dict(os.environ, {"HOME": "/native-home", "PATH": "/bin",
                                     "OPENAI_API_KEY": "private", "NODE_OPTIONS": "bad",
                                     "PYTHONPATH": "/hostile", "HERDR_PANE_ID": "w1:p1"}, clear=True):
            result = sanitized_terminal_environment()
        self.assertNotIn("OPENAI_API_KEY", result)
        self.assertNotIn("NODE_OPTIONS", result)
        self.assertNotEqual(result["PYTHONPATH"], "/hostile")
        self.assertEqual(result["HERDR_PANE_ID"], "w1:p1")
        self.assertEqual(result["HOME"], "/native-home")

    def test_status_redacts_private_fields_and_unknown_stays_unknown(self):
        runtime = HerdrRuntime(Path("/tmp/test.sock"))
        with patch.object(runtime, "_request", return_value={"pane": {
                "pane_id": "w1:p1", "agent_status": "new-state", "argv": ["private"], "text": "secret"}}):
            result = runtime.status(HerdrSession("w1", "w1:p1"))
        self.assertEqual(result["agent_status"], "unknown")
        self.assertNotIn("argv", result)
        self.assertNotIn("text", result)

    def test_socket_protocol_correlates_ids_and_hides_server_error_text(self):
        for kind in ("success", "mismatch", "error", "oversized"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "server.sock"
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(str(path))
                path.chmod(0o600)
                server.listen(1)
                def serve():
                    with server, server.accept()[0] as connection:
                        request = json.loads(connection.recv(8192))
                        response = {"id": request["id"], "result": {"type": "pong"}}
                        if kind == "mismatch":
                            response["id"] = "wrong"
                        if kind == "error":
                            response = {"id": request["id"], "error": {"code": "method_not_found", "message": "private"}}
                        wire = json.dumps(response).encode() + b"\n"
                        if kind == "oversized":
                            wire = b"x" * 2048
                        connection.sendall(wire)
                worker = threading.Thread(target=serve)
                worker.start()
                runtime = HerdrRuntime(path, max_bytes=1024)
                if kind == "success":
                    self.assertTrue(runtime.ping())
                else:
                    with self.assertRaises(HerdrError) as caught:
                        runtime.ping()
                    self.assertNotIn("private", str(caught.exception))
                worker.join(2)
                self.assertFalse(worker.is_alive())

    def test_unavailable_and_unsafe_socket_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-socket"
            runtime = HerdrRuntime(path)
            with self.assertRaises(HerdrError):
                runtime.ping()
            path.write_text("ordinary file")
            with self.assertRaisesRegex(HerdrError, "owned Unix socket"):
                runtime.ping()
        with self.assertRaises(ValueError):
            HerdrRuntime(Path("relative.sock"))
        with self.assertRaises(ValueError):
            HerdrRuntime(Path("/tmp/test.sock"), timeout=60)

    def test_launch_rejects_invalid_arguments_before_mutation(self):
        runtime = HerdrRuntime(Path("/tmp/test.sock"))
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "_request") as request:
            for argv in ([], ["relative"], ["/bin/echo", "\x00"]):
                with self.assertRaises(ValueError):
                    runtime.start(argv, directory=Path(directory))
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
