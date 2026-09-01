from __future__ import annotations
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
from quattro_release import ReleaseError, create_release, load_release, restore_release

class ReleaseTests(unittest.TestCase):
    def test_private_release_round_trip_and_hash_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary); deployed=root/"home"; releases=root/"releases"
            target=deployed/".local/bin/quattro-agent"; target.parent.mkdir(parents=True)
            target.write_text("old",encoding="utf-8"); target.chmod(0o755)
            manifest=create_release(releases,"a"*40,deployed,[".local/bin/quattro-agent"])
            self.assertEqual(manifest.stat().st_mode & 0o777,0o600)
            target.write_text("new",encoding="utf-8")
            restored=restore_release(manifest,deployed)
            self.assertEqual(restored,[target]); self.assertEqual(target.read_text(),"old")
            self.assertEqual(target.stat().st_mode & 0o777,0o755)

    def test_authentication_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary); deployed=root/"home"; auth=deployed/"auth.json"
            deployed.mkdir(); auth.write_text("x")
            for index, name in enumerate(("auth.json", "auth.json.bak", "credentials-backup", ".env.local", "id_rsa.old", "token.txt")):
                with self.subTest(name=name), self.assertRaises(ReleaseError):
                    create_release(root / f"releases-{index}", "b"*40, deployed, [name])

    def test_restore_rejects_revision_mismatch_and_symlink_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary); deployed=root/"home"; releases=root/"releases"
            target=deployed/".local/bin/tool"; target.parent.mkdir(parents=True)
            target.write_text("old")
            manifest=create_release(releases,"c"*40,deployed,[".local/bin/tool"])
            with self.assertRaises(ReleaseError):
                restore_release(manifest,deployed,release_root=releases,expected_revision="d"*40)
            link=root/"link.json"; link.symlink_to(manifest)
            with self.assertRaises(ReleaseError):
                restore_release(link,deployed,release_root=releases)

    def test_partial_restore_failure_rolls_back_prior_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary); deployed=root/"home"; releases=root/"releases"
            first=deployed/"a"; second=deployed/"b"; deployed.mkdir()
            first.write_text("old-a"); second.write_text("old-b")
            manifest=create_release(releases,"e"*40,deployed,["a","b"])
            first.write_text("new-a"); second.write_text("new-b")
            import quattro_release
            real_copy=quattro_release._atomic_copy
            calls={"count":0}
            def fail_second(source, target, mode):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated")
                return real_copy(source,target,mode)
            with mock.patch.object(quattro_release,"_atomic_copy",side_effect=fail_second):
                with self.assertRaises(OSError):
                    restore_release(manifest,deployed,release_root=releases,expected_revision="e"*40)
            self.assertEqual(first.read_text(),"new-a")
            self.assertEqual(second.read_text(),"new-b")

    def test_release_inventory_removes_files_that_were_previously_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary); deployed=root/"home"; releases=root/"releases"
            deployed.mkdir()
            manifest=create_release(releases,"f"*40,deployed,["new/module.py"])
            introduced=deployed/"new/module.py"; introduced.parent.mkdir(); introduced.write_text("new")
            restored=restore_release(
                manifest,deployed,release_root=releases,expected_revision="f"*40
            )
            self.assertIn(introduced,restored)
            self.assertFalse(introduced.exists())

if __name__ == "__main__": unittest.main()
