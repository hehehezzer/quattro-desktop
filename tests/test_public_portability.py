from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from quattro_agent.cli import starter_config, tool_environment  # noqa: E402
from quattro_agent.config import validate_ai_config  # noqa: E402
from quattro_agent.paths import codex_account_root, omniroute_base_url  # noqa: E402
from quattro_agent.containment import bubblewrap_path, build_bwrap_command  # noqa: E402


class PublicPortabilityTests(unittest.TestCase):
    def test_starter_config_is_memory_off_and_credential_free(self):
        config = starter_config()
        validated = validate_ai_config(config)
        self.assertFalse(validated["memory"]["enabled"])
        self.assertFalse(validated["memory"]["enforceOnLaunch"])
        self.assertTrue(validated["fullAccessRequiresConfirmation"])
        self.assertNotIn("auth.json", repr(config))
        self.assertNotIn("maintainer-only-path", repr(config))

    def test_xdg_and_quattro_overrides_are_resolved_without_home_assumptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with mock.patch.dict(os.environ, {
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_STATE_HOME": str(root / "state"),
                "QUATTRO_CODEX_DATA_DIR": str(root / "codex"),
            }, clear=False):
                self.assertEqual(codex_account_root(), root / "codex/accounts")
                config = starter_config()
                self.assertTrue(config["accounts"][0]["codexHome"].endswith("codex/accounts/default"))

    def test_omniroute_endpoint_is_explicitly_configurable(self):
        with mock.patch.dict(os.environ, {
            "QUATTRO_OMNIROUTE_BASE_URL": "http://127.0.0.1:23000/api/v1",
        }, clear=False):
            self.assertEqual(omniroute_base_url(), "http://127.0.0.1:23000/api/v1")

    def test_child_environment_excludes_arbitrary_parent_values(self):
        with mock.patch.dict(os.environ, {
            "PATH": "/usr/bin",
            "HOME": "/tmp/example-home",
            "WAYLAND_DISPLAY": "wayland-example",
            "QUATTRO_TEST_SECRET": "must-not-cross",
            "OPENAI_API_KEY": "must-not-cross",
            "GH_TOKEN": "must-not-cross",
        }, clear=True), mock.patch(
            "quattro_agent.cli.command_path", return_value="/usr/bin/codex"
        ):
            environment = tool_environment("codex")
        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertEqual(environment["HOME"], "/tmp/example-home")
        self.assertEqual(environment["WAYLAND_DISPLAY"], "wayland-example")
        self.assertNotIn("QUATTRO_TEST_SECRET", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("GH_TOKEN", environment)

    def test_source_checkout_can_initialize_a_clean_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            environment = os.environ.copy()
            environment.update({
                "PYTHONPATH": str(SRC),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
            })
            result = subprocess.run(
                [sys.executable, str(SRC / "quattro-agent"), "config", "init"],
                cwd=ROOT, env=environment, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            config = root / "config/quattro/ai.json"
            self.assertTrue(config.is_file())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(bubblewrap_path(), "bubblewrap is unavailable")
    def test_containment_does_not_expose_an_outside_canary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            project = root / "project"
            runtime = root / "runtime"
            report = root / "report"
            outside = root / "outside"
            for path in (project, runtime, report, outside):
                path.mkdir()
            canary = outside / "canary.txt"
            canary.write_text("outside-secret", encoding="utf-8")
            command, environment, _ = build_bwrap_command(
                [sys.executable, "-c", "from pathlib import Path; print(Path('/outside/canary.txt').read_text())"],
                project_root=project, runtime_root=runtime, report_root=report,
                environment={"HOME": str(runtime), "PATH": os.environ.get("PATH", "")},
            )
            result = subprocess.run(command, env=environment, check=False,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("outside-secret", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
