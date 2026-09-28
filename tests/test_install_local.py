from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]


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


if __name__ == "__main__":
    unittest.main()
