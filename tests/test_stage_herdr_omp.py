from pathlib import Path
import importlib.util
import hashlib
import json
import os
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
                with self.assertRaisesRegex(ValueError, "symbolic links"):
                    module.stage(root, root, root)

    def test_linked_source_directory_rejected_before_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, home, skills, outside = [root / name for name in ("repo", "home", "skills", "outside")]
            for path in (source / "src", home, skills, outside):
                path.mkdir(parents=True)
            (outside / "file.py").write_text("value = 1\n")
            (source / "src/package").symlink_to(outside, target_is_directory=True)
            with patch.object(module, "CORE_DEPLOYMENT_MAPPINGS", {"one": ("src/package/file.py", "unused")}):
                with self.assertRaisesRegex(ValueError, "ancestors"):
                    module.stage(source, home, skills)
            self.assertEqual(list(home.iterdir()), [])

    def test_linked_bundle_or_launcher_parent_rejected_before_any_mutation(self):
        for destination in ("package", "bin"):
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, home, skills, outside = [root / name for name in ("repo", "home", "skills", "outside")]
                for path in (source / "src/package", home, skills, outside):
                    path.mkdir(parents=True)
                data = b"value = 1\n"
                (source / "src/plain.py").write_bytes(data)
                (source / "src/package/file.py").write_bytes(data)
                hashes = {name: hashlib.sha256(data).hexdigest() for name in ("plain.py", "package/file.py")}
                digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
                bundle = home / ".local/lib/quattro-herdr-omp" / digest
                bundle.mkdir(parents=True)
                sentinel = bundle / "plain.py"
                sentinel.write_bytes(data)
                sentinel.chmod(0o600)
                if destination == "package":
                    (bundle / "package").symlink_to(outside, target_is_directory=True)
                else:
                    (home / ".local/bin").symlink_to(outside, target_is_directory=True)
                mappings = {name: ("src/" + name, "unused") for name in hashes}
                with patch.object(module, "CORE_DEPLOYMENT_MAPPINGS", mappings):
                    with self.assertRaisesRegex(ValueError, "ancestors"):
                        module.stage(source, home, skills)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertEqual(sentinel.read_bytes(), data)
                self.assertEqual(sentinel.stat().st_mode & 0o777, 0o600)
                self.assertFalse((bundle / "manifest.json").exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires POSIX FIFO")
    def test_nonregular_launcher_rejected_without_opening_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in (root / "src", root / ".local/bin"):
                path.mkdir(parents=True)
            (root / "src/file.py").write_text("value = 1\n")
            os.mkfifo(root / ".local/bin/quattro-omp")
            with patch.object(module, "CORE_DEPLOYMENT_MAPPINGS", {"one": ("src/file.py", "unused")}):
                with self.assertRaisesRegex(ValueError, "regular file"):
                    module.stage(root, root, root)
            self.assertFalse((root / ".local/lib").exists())


if __name__ == "__main__":
    unittest.main()
