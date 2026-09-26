"""Subprocess coverage for the source-checkout CLI entry point."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "quattro-agent"


class CliEntryTests(unittest.TestCase):
    def invoke(self, *arguments, cwd=ROOT, home=None):
        env = os.environ.copy()
        env.pop("QUATTRO_CONFIG", None)
        env.pop("QUATTRO_STATE_DIR", None)
        env["PYTHONPATH"] = str(ROOT / "src")
        if home is not None:
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            env["XDG_STATE_HOME"] = str(home / ".local" / "state")
        return subprocess.run(
            [sys.executable, str(ENTRY), *arguments], cwd=cwd, env=env,
            capture_output=True, text=True, timeout=20, check=False,
        )

    def test_bare_invocation_in_repository_and_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            for cwd in (ROOT, directory):
                with self.subTest(cwd=cwd):
                    result = self.invoke(cwd=cwd, home=pathlib.Path(directory))
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("Invalid AI configuration", result.stderr)
                    self.assertNotIn("usage: quattro-agent", result.stdout)
                    self.assertNotIn("Traceback", result.stderr)

    def test_version(self):
        result = self.invoke("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("quattro-agent", result.stdout)

    def test_help(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: quattro-agent", result.stdout)

    def test_unknown_command(self):
        result = self.invoke("definitely-not-a-command")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_status_dispatch_without_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke("status", "--json", home=pathlib.Path(directory))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Invalid AI configuration", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
