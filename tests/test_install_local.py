from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import importlib.util


ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("install_local", ROOT / "scripts/install_local.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class LocalInstallerTests(unittest.TestCase):
    def test_dependency_free_install_has_current_desktop_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "bin"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/install_local.py"), "--target", str(target)],
                check=True,
            )
            result = subprocess.run(
                [str(target / "quattro-agent"), "--version"],
                cwd=target, text=True, capture_output=True, check=True,
            )
            self.assertIn("0.2.0", result.stdout)
            source = subprocess.run(
                [sys.executable, "-c", "from quattro.deployment.profiles import DESKTOP_DEPLOYMENT_MAPPINGS as m; print(len(m))"],
                cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True, check=True,
            )
            installed = subprocess.run(
                [sys.executable, "-c", "from quattro.deployment.profiles import DESKTOP_DEPLOYMENT_MAPPINGS as m; print(len(m))"],
                cwd=target, text=True, capture_output=True, check=True,
            )
            self.assertEqual(installed.stdout, source.stdout)

    def test_failed_replacement_rolls_back_every_installed_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "bin"
            target.mkdir()
            names = (*installer.PACKAGES, *installer.MODULES, "quattro-agent")
            for name in names:
                path = target / name
                if "." not in name and name != "quattro-agent":
                    path.mkdir(); (path / "old").write_text("old")
                else:
                    path.write_text("old")
            real_replace = installer.os.replace
            replacements = 0

            def fail_midway(source, destination):
                nonlocal replacements
                if pathlib.Path(source).parent.name.startswith(".quattro-install-"):
                    replacements += 1
                    if replacements == 4:
                        raise OSError("injected replacement failure")
                return real_replace(source, destination)

            with mock.patch.object(installer.os, "replace", side_effect=fail_midway), self.assertRaises(OSError):
                installer.install(target)
            for name in names:
                path = target / name
                self.assertTrue(path.exists(), name)
                self.assertEqual((path / "old").read_text() if path.is_dir() else path.read_text(), "old")


if __name__ == "__main__":
    unittest.main()
