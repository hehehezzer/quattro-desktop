from __future__ import annotations

import io
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "scripts"))

import check_public_history as public_history  # noqa: E402


class PublicPortabilityTests(unittest.TestCase):
    def test_public_history_token_scan_has_boundaries_and_narrow_fixture_allowlist(self):
        token_pattern = public_history.TOKEN_PATTERNS[2]
        self.assertIsNone(re.search(token_pattern, "task-intelligence"))
        shaped = "s" + "k-" + "livecredentialvalue123"
        self.assertIsNotNone(re.search(token_pattern, f"value={shaped}"))
        fixture = "s" + "k-" + "synthetic-1234567890abcdefghijkl"
        self.assertTrue(public_history.allowed_historical_test_fixture(
            token_pattern,
            f"commit:tests/test_intelligence.py:74:value = {fixture}"
        ))
        self.assertFalse(public_history.allowed_historical_test_fixture(
            token_pattern,
            f"commit:src/runtime.py:74:value = {fixture}"
        ))
        self.assertFalse(public_history.allowed_historical_test_fixture(
            public_history.TOKEN_PATTERNS[0],
            f"commit:tests/test_intelligence.py:74:value = {fixture}"
        ))

    def test_public_history_uses_real_git_grep_and_fails_closed(self):
        script = ROOT / "scripts/check_public_history.py"

        def scan(files: dict[str, str]) -> subprocess.CompletedProcess[str]:
            with tempfile.TemporaryDirectory() as directory:
                repository = pathlib.Path(directory)
                subprocess.run(
                    ["git", "init", "-q", "-b", "main"], cwd=repository, check=True
                )
                subprocess.run(
                    ["git", "config", "user.name", "Test"], cwd=repository, check=True
                )
                subprocess.run(
                    ["git", "config", "user.email", "test@example.invalid"],
                    cwd=repository,
                    check=True,
                )
                for relative, content in files.items():
                    target = repository / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                subprocess.run(["git", "add", "."], cwd=repository, check=True)
                subprocess.run(
                    ["git", "commit", "-qm", "fixture"], cwd=repository, check=True
                )
                return subprocess.run(
                    [sys.executable, str(script)],
                    cwd=repository,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

        fixture = "s" + "k-" + "synthetic-1234567890abcdefghijkl"
        allowed = scan({
            "tests/test_intelligence.py": f"task-intelligence {fixture}\n",
        })
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

        real_key = "s" + "k-" + "livecredentialvalue123"
        rejected = scan({"config.txt": f"value={real_key}\n"})
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("credential marker", rejected.stderr)

        wrong_path = scan({"src/runtime.py": fixture + "\n"})
        self.assertNotEqual(wrong_path.returncode, 0)

        mixed = scan({
            "tests/test_intelligence.py": f"{fixture} {real_key}\n",
        })
        self.assertNotEqual(mixed.returncode, 0)

    def test_public_history_fails_closed_on_marker_only_process_errors(self):
        for returncode in (2, 128, -15):
            with self.subTest(returncode=returncode):
                def scan(command, **kwargs):
                    failed_marker = (
                        "-F" in command
                        and command[command.index("-e") + 1] == public_history.MARKERS[0]
                    )
                    return subprocess.CompletedProcess(
                        command, returncode if failed_marker else 1, stdout=""
                    )

                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    mock.patch.object(public_history, "run", side_effect=["abc123\n", ""]),
                    mock.patch.object(public_history.subprocess, "run", side_effect=scan),
                    mock.patch("sys.stdout", stdout),
                    mock.patch("sys.stderr", stderr),
                ):
                    result = public_history.main()
                self.assertEqual(result, 1)
                self.assertIn("private marker scan failed", stderr.getvalue())
                self.assertNotIn("PASS", stdout.getvalue())
                self.assertNotIn("credential scan failed", stderr.getvalue())

    def test_public_history_rejects_real_marker_scan_revision_failure(self):
        actual_run = subprocess.run
        with tempfile.TemporaryDirectory() as directory:
            repository = pathlib.Path(directory)
            actual_run(["git", "init", "-q", "-b", "main"], cwd=repository, check=True)
            (repository / "sample.txt").write_text(
                public_history.MARKERS[0] + "operator\n", encoding="utf-8"
            )
            actual_run(["git", "add", "sample.txt"], cwd=repository, check=True)
            actual_run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "fixture"],
                cwd=repository, check=True,
            )
            scan_errors = []

            def scan(command, *args, **kwargs):
                command = list(command)
                failed_marker = (
                    command[:2] == ["git", "grep"]
                    and "-F" in command
                    and command[command.index("-e") + 1] == public_history.MARKERS[0]
                )
                if failed_marker:
                    command[-2] = "nonexistent-scan-revision"
                result = actual_run(command, *args, cwd=repository, **kwargs)
                if failed_marker:
                    scan_errors.append(result.returncode)
                return result

            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                mock.patch.object(public_history.subprocess, "run", side_effect=scan),
                mock.patch("sys.stdout", stdout),
                mock.patch("sys.stderr", stderr),
            ):
                result = public_history.main()
            self.assertEqual(scan_errors, [128])
            self.assertEqual(result, 1)
            self.assertIn("private marker scan failed", stderr.getvalue())
            self.assertNotIn("PASS", stdout.getvalue())

    def test_public_history_reports_git_grep_execution_errors(self):
        failed = subprocess.CompletedProcess(
            args=["git", "grep"], returncode=128, stdout="", stderr="invalid regex"
        )
        stderr = io.StringIO()
        with (
            mock.patch.object(public_history, "run", side_effect=["abc123\n", ""]),
            mock.patch.object(public_history.subprocess, "run", return_value=failed),
            mock.patch("sys.stderr", stderr),
        ):
            result = public_history.main()
        self.assertEqual(result, 1)
        self.assertIn("credential scan failed", stderr.getvalue())



if __name__ == "__main__":
    unittest.main()
