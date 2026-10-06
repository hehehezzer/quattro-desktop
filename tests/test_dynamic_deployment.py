"""Native rollout preserves independently reviewed scoped authority files."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("dynamic_native_deployment", ROOT / "scripts/deploy_dynamic_native.py")
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


class DynamicDeploymentTests(unittest.TestCase):
    def fixture(self, directory):
        home = Path(directory)
        package = home / ".local/bin/quattro_agent"
        shutil.copytree(ROOT / "src/quattro_agent", package, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "src/quattro", home / ".local/bin/quattro", ignore=shutil.ignore_patterns("__pycache__"))
        for path in (ROOT / "src").glob("quattro_*.py"):
            shutil.copy2(path, home / ".local/bin" / path.name)
        with (package / "retrieval.py").open("a") as stream:
            stream.write("\n# installed reviewed retrieval hardening\n")
        (package / "scoped_pi.py").write_text("# reviewed sealed authority\n")
        (package / "decision_checkpoint.py").write_text("# preserve checkpoint provenance\n")
        extension = home / ".pi/agent/extensions/quattro-intelligence.ts"
        extension.parent.mkdir(parents=True)
        targets = [home / ".local/bin/quattro-intelligence",
                   home / ".local/bin/quattro-intelligence-mcp", extension]
        for path in targets:
            path.write_text("# existing native entrypoint\n")
            path.chmod(0o700)
        return home, package, targets

    def test_preview_is_read_only_and_apply_preserves_scoped_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            home, package, targets = self.fixture(directory)
            before = {str(path): path.read_bytes() for path in home.rglob("*") if path.is_file()}
            preview = deployment.deploy(ROOT, home)
            self.assertFalse(preview["applied"])
            self.assertFalse((home / ".local/lib").exists())
            applied = deployment.deploy(ROOT, home, apply=True)
            self.assertTrue(applied["hashes_verified"])
            self.assertTrue(applied["dependency_imports_verified"])
            self.assertTrue((Path(applied["bundle"]) / "quattro_agent/jev_worker.py").is_file())
            self.assertFalse(applied["scoped_authorities_changed"])
            for path in package.rglob("*"):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), before[str(path)])
            bundle = Path(applied["bundle"])
            self.assertEqual((bundle / "quattro_agent/retrieval.py").read_bytes(), (package / "retrieval.py").read_bytes())
            self.assertFalse((bundle / "quattro_agent/scoped_pi.py").exists())
            self.assertFalse((bundle / "quattro_agent/decision_checkpoint.py").exists())
            for index, target in enumerate(targets):
                self.assertEqual((Path(applied["backup"]) / str(index)).read_bytes(), before[str(target)])
                self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            receipt = json.loads((home / ".local/lib/quattro-dynamic-native/current.json").read_text())
            self.assertEqual(receipt["bundle_sha256"], preview["bundle_sha256"])
            self.assertFalse(receipt["settings_changed"])
            self.assertFalse(receipt["sessions_restarted"])

    def test_tampered_existing_bundle_and_symlink_targets_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            home, _, targets = self.fixture(directory)
            first = deployment.deploy(ROOT, home, apply=True)
            path = Path(first["bundle"]) / "quattro_agent/decision_taxonomy.py"
            path.write_text("# synthetic tampering\n")
            with self.assertRaises(ValueError):
                deployment.deploy(ROOT, home, apply=True)
            targets[0].unlink()
            targets[0].symlink_to(targets[1])
            with self.assertRaises(ValueError):
                deployment.deploy(ROOT, home)

    def test_real_wrapper_startup_keeps_bundle_immutable_for_reapply(self):
        with tempfile.TemporaryDirectory() as directory:
            home, _, targets = self.fixture(directory)
            applied = deployment.deploy(ROOT, home, apply=True)
            result = subprocess.run([str(targets[0]), "--help"],
                                    env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                                    capture_output=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(list(Path(applied["bundle"]).rglob("*.pyc")))
            self.assertTrue(deployment.deploy(ROOT, home, apply=True)["hashes_verified"])

    def test_extra_bundle_member_and_internal_symlinks_are_rejected(self):
        for mutation in ("extra_member", "versions_link", "receipt_link", "receipt_directory"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                home, _, _ = self.fixture(directory)
                applied = deployment.deploy(ROOT, home, apply=True)
                base = home / ".local/lib/quattro-dynamic-native"
                sentinel = home / "sentinel"
                sentinel.write_text("synthetic preservation sentinel")
                if mutation == "extra_member":
                    (Path(applied["bundle"]) / "unexpected.py").write_text("# forbidden extra member\n")
                elif mutation == "versions_link":
                    (base / "versions").rename(home / "moved_versions")
                    (base / "versions").symlink_to(home / "moved_versions", target_is_directory=True)
                else:
                    (base / "current.json").unlink()
                    if mutation == "receipt_link":
                        (base / "current.json").symlink_to(sentinel)
                    else:
                        (base / "current.json").mkdir()
                with self.assertRaises(ValueError):
                    deployment.deploy(ROOT, home, apply=True)
                self.assertEqual(sentinel.read_text(), "synthetic preservation sentinel")

    def test_receipt_failure_rolls_back_wrapper_content_and_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            home, _, targets = self.fixture(directory)
            before = {path: (path.read_bytes(), path.stat().st_mode & 0o777) for path in targets}
            write = deployment.atomic_write
            def fail_receipt(path, data, mode):
                if path.name == "current.json":
                    raise OSError("synthetic publication failure")
                return write(path, data, mode)
            with mock.patch.object(deployment, "atomic_write", side_effect=fail_receipt):
                with self.assertRaises(OSError):
                    deployment.deploy(ROOT, home, apply=True)
            for path, original in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777), original)
            self.assertFalse((home / ".local/lib/quattro-dynamic-native/current.json").exists())
