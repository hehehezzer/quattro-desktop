from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.migration_cli import launch_omp, native_access, skill_directory


class MigrationLaunchTests(unittest.TestCase):
    def test_missing_action_approval_precedes_executable_or_file_access(self):
        with patch("quattro_agent.migration_cli.shutil.which") as discovery:
            with self.assertRaisesRegex(ValueError, "action-time approval"):
                launch_omp(Path("/missing"), skills=None, confirmed=False, environment={})
            discovery.assert_not_called()

    def test_verified_skill_root_rejects_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                skill_directory(str(root / "link"))

    def test_launch_uses_locked_route_and_private_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def run(argv, **kwargs):
                import json
                overlay = Path(argv[argv.index("--config") + 1])
                config = json.loads(overlay.read_text())
                self.assertEqual(config["tools"]["approvalMode"], "always-ask")
                self.assertEqual(config["skills"]["customDirectories"], [str(root)])
                self.assertEqual(overlay.stat().st_mode & 0o777, 0o600)
                self.assertEqual(argv[argv.index("--model") + 1], "gpt-6.1-sol")
                self.assertEqual(argv[argv.index("--thinking") + 1], "medium")
                self.assertEqual(kwargs["cwd"], root)
                self.assertIn("QUATTRO_OMP_PYTHON", kwargs["env"])
                self.assertFalse(kwargs["check"])
                return type("Result", (), {"returncode": 0})()
            with patch("quattro_agent.migration_cli.shutil.which", return_value="/bin/omp"), \
                    patch("quattro_agent.migration_cli.subprocess.run", side_effect=run):
                self.assertEqual(launch_omp(root, skills=str(root), confirmed=True,
                                           environment={"HOME": str(root), "PATH": "/bin"}), 0)


if __name__ == "__main__":
    unittest.main()
