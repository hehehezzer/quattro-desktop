from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap_pip  # noqa: E402


class PipBootstrapTests(unittest.TestCase):
    def test_download_accepts_only_the_pinned_digest(self) -> None:
        payload = b"incident-fixed-pip-wheel"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "pip.whl"
            with (
                mock.patch.object(
                    bootstrap_pip.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(payload),
                ),
                mock.patch.object(
                    bootstrap_pip,
                    "PIP_WHEEL_SHA256",
                    hashlib.sha256(payload).hexdigest(),
                ),
            ):
                bootstrap_pip.download_verified_wheel(destination)
            self.assertEqual(destination.read_bytes(), payload)

    def test_download_removes_wheel_after_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "pip.whl"
            with mock.patch.object(
                bootstrap_pip.urllib.request,
                "urlopen",
                return_value=io.BytesIO(b"substituted-wheel"),
            ):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    bootstrap_pip.download_verified_wheel(destination)
            self.assertFalse(destination.exists())

    def test_download_rejects_oversized_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "pip.whl"
            with (
                mock.patch.object(
                    bootstrap_pip.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(b"12345"),
                ),
                mock.patch.object(bootstrap_pip, "MAX_WHEEL_BYTES", 4),
            ):
                with self.assertRaisesRegex(ValueError, "size bound"):
                    bootstrap_pip.download_verified_wheel(destination)
            self.assertFalse(destination.exists())

    def test_version_parser_orders_short_and_prerelease_versions(self) -> None:
        minimum = bootstrap_pip.MINIMUM_PIP_VERSION
        self.assertLess(bootstrap_pip.parse_version("24.0"), minimum)
        self.assertLess(bootstrap_pip.parse_version("26.2"), minimum)
        self.assertLess(bootstrap_pip.parse_version("26.2.1"), minimum)
        self.assertLess(bootstrap_pip.parse_version("26.2.2rc1"), minimum)
        self.assertEqual(bootstrap_pip.parse_version("26.2.2"), minimum)
        self.assertGreater(bootstrap_pip.parse_version("26.2.2.post1"), minimum)
        with self.assertRaisesRegex(ValueError, "Unrecognized"):
            bootstrap_pip.parse_version("latest")

    def test_timed_out_version_probe_is_unusable(self) -> None:
        with mock.patch.object(
            bootstrap_pip.subprocess,
            "run",
            side_effect=bootstrap_pip.subprocess.TimeoutExpired(["python"], 300),
        ):
            self.assertIsNone(bootstrap_pip.installed_pip_version(Path("python")))

    @unittest.skipIf(os.name == "nt", "symlink creation is not portable on Windows CI")
    def test_bootstrap_preserves_virtual_environment_interpreter_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            interpreter = Path(temporary) / "python"
            interpreter.symlink_to(Path(sys.executable))
            with mock.patch.object(
                bootstrap_pip,
                "installed_pip_version",
                return_value="26.2.2",
            ) as probe:
                self.assertEqual(bootstrap_pip.bootstrap_pip(interpreter), "26.2.2")
            probe.assert_called_once_with(interpreter.absolute())


if __name__ == "__main__":
    unittest.main()
