from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from quattro_agent.provider_access import resolve_typesafe_credential, typesafe_credential_status


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "environment.d/60-quattro-typesafe.conf"
        self.path.parent.mkdir(mode=0o700)
        self.secret = secrets.token_hex(32)
        self.store(self.secret)
        self.patch = mock.patch("quattro_agent.provider_access.xdg_config_home", return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def store(self, value):
        self.path.write_text("TYPESAFE_API_KEY=" + value + "\n")
        self.path.chmod(0o600)

    def resolve(self, environment=None):
        return resolve_typesafe_credential(environment={} if environment is None else environment)

    def test_persistent_source_and_environment_override(self):
        self.assertEqual(self.resolve(), self.secret)
        override = secrets.token_hex(32)
        self.assertEqual(self.resolve({"TYPESAFE_API_KEY": override}), override)
        self.assertEqual(self.path.read_text(), "TYPESAFE_API_KEY=" + self.secret + "\n")

    def test_explicit_empty_or_invalid_override_does_not_fall_through(self):
        for value in ("", "abc\nAuthorization: injected", "$(command)", "${OTHER}", " ", "x" * 4097):
            self.assertIsNone(self.resolve({"TYPESAFE_API_KEY": value}))

    def test_missing_and_invalid_sources_fail_closed_without_output(self):
        for value in ("", "${OTHER}", "$(command)", "bad key", "x" * 17000):
            self.store(value)
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(self.resolve())
            self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.path.unlink()
        self.assertIsNone(self.resolve())

    def test_quotes_comments_and_duplicate_rejection(self):
        self.path.write_text('# comment\nTYPESAFE_API_KEY="' + self.secret + '"\n')
        self.assertEqual(self.resolve(), self.secret)
        self.path.write_text("TYPESAFE_API_KEY=" + self.secret + "\nTYPESAFE_API_KEY=duplicate\n")
        self.assertIsNone(self.resolve())

    @unittest.skipUnless(os.name == "posix", "POSIX permission checks")
    def test_permissions_symlinks_and_special_files_rejected(self):
        self.path.chmod(0o644)
        self.assertIsNone(self.resolve())
        self.path.chmod(0o600)
        target = self.path.with_name("other.conf")
        self.path.rename(target)
        self.path.symlink_to(target)
        self.assertIsNone(self.resolve())
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        self.assertIsNone(self.resolve())

    def test_resolution_does_not_mutate_or_cache_session_environment(self):
        first = {"TYPESAFE_API_KEY": self.secret}
        second = {"TYPESAFE_API_KEY": ""}
        self.assertEqual(self.resolve(first), self.secret)
        self.assertIsNone(self.resolve(second))
        self.assertEqual(first, {"TYPESAFE_API_KEY": self.secret})
        self.store("replacement-test-value")
        self.assertEqual(self.resolve(), "replacement-test-value")

    def test_status_metadata_only(self):
        from quattro_agent import cli
        data = {"defaultAgent": "codex", "activeAccount": "account-1", "agents": {},
                "accounts": [], "sessions": [], "recent": [],
                "cooperation": {"global": {"active": 0, "limit": 5}, "repositories": []}}
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": self.secret}), \
                mock.patch.object(cli, "dashboard", return_value=data):
            self.assertEqual(typesafe_credential_status(), "configured")
            for as_json in (True, False):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    cli.print_status(as_json)
                self.assertNotIn(self.secret, out.getvalue())
                self.assertIn("configured", out.getvalue())
            self.assertEqual(data["typesafeCredential"], "configured")
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.assertEqual(typesafe_credential_status(), "missing")

    def test_enabled_native_launch_warns_once_when_missing(self):
        from quattro_agent import native_session
        transport = mock.Mock(url="http://127.0.0.1:1", token="fixture")
        transport.start.return_value = transport
        child = mock.Mock()
        child.wait.return_value = 0
        child.poll.return_value = 0
        with mock.patch.object(native_session, "typesafe_credential_status", return_value="missing"), \
                mock.patch.object(native_session, "TurnGate"), \
                mock.patch.object(native_session, "TurnTransport", return_value=transport), \
                mock.patch.object(native_session.subprocess, "Popen", return_value=child), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            result = native_session.launch_routed_native(
                agent="pi", binary="pi", command=["pi"], env={},
                config={"routing": {"jev": {"mode": "COOPERATIVE"}}},
                directory=self.root, session_id="fixture", account="account-1",
                state_root=self.root, runtime_factory=mock.Mock())
        self.assertEqual(result, 0)
        self.assertEqual(out.getvalue().count("Jev unavailable"), 1)
        self.assertNotIn(self.secret, out.getvalue())

    def test_persistent_key_only_crosses_worker_pipe_not_env_or_telemetry(self):
        from quattro_agent.jev_shadow import ShadowRun
        from test_jev import FakeProcess
        parent = self

        class Process(FakeProcess):
            def __init__(self, argv, **kwargs):
                parent.assertNotIn(parent.secret, json.dumps([argv, kwargs["env"]]))
                super().__init__()

            def communicate(self, payload, **kwargs):
                parent.assertEqual(json.loads(payload)["key"], parent.secret)
                return super().communicate(payload, **kwargs)

        environment = dict(os.environ)
        environment.pop("TYPESAFE_API_KEY", None)
        database = self.root / "evidence.sqlite3"
        with mock.patch.dict(os.environ, environment, clear=True), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            run = ShadowRun(database=database, request="hello", decision="DIRECT",
                            record_id=None, source_task_id=None, authoritative_tier="FAST",
                            timeout_ms=300, popen=Process)
            run.start()
            self.assertTrue(run.done.wait(2))
            run.close()
        self.assertEqual(run.record["status"], "success")
        self.assertNotIn(self.secret, json.dumps(run.record))
        self.assertNotIn(self.secret.encode(), database.read_bytes())
        self.assertNotIn(self.secret, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
