from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("stage_herdr_omp", Path(__file__).resolve().parents[1] / "scripts/stage_herdr_omp.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StagingTests(unittest.TestCase):
    def test_preserves_existing_launchers_and_pins_exact_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home, skills = root / "repo", root / "home", root / "skills"
            for path in (source / "src", home, skills):
                path.mkdir(parents=True)
            (source / "src/file.py").write_text("value = 1\n")
            mappings = {"one": ("src/file.py", ".local/bin/file.py")}
            with patch.object(module, "CORE_DEPLOYMENT_MAPPINGS", mappings):
                result = module.stage(source, home, skills)
                bundle = Path(result["bundle"])
                self.assertEqual((bundle / "file.py").read_text(), "value = 1\n")
                self.assertEqual((bundle / "file.py").stat().st_mode & 0o777, 0o400)
                self.assertEqual(module.stage(source, home, skills), result)
                launcher = Path(result["launcher"])
                before = launcher.read_bytes()
                (source / "src/file.py").write_text("value = 2\n")
                with self.assertRaisesRegex(ValueError, "launcher preserved"):
                    module.stage(source, home, skills)
                self.assertEqual(launcher.read_bytes(), before)
                self.assertEqual((bundle / "file.py").read_text(), "value = 1\n")

    def test_linked_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "original").write_text("value = 1\n")
            (root / "src/file.py").symlink_to(root / "original")
            with patch.object(module, "CORE_DEPLOYMENT_MAPPINGS", {"one": ("src/file.py", "unused")}):
                with self.assertRaisesRegex(ValueError, "regular file"):
                    module.stage(root, root, root)


if __name__ == "__main__":
    unittest.main()
