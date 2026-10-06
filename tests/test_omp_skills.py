"""Hermetic OMP skill migration parity and safe traversal checks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("migrate_omp_skills", Path(__file__).resolve().parents[1] / "scripts/migrate_omp_skills.py")
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class OmpSkillsTests(unittest.TestCase):
    def skill(self, root, name="example", body="body"):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: useful playbook\n---\n{body}\n")
        (directory / "reference.txt").write_text("supporting content")
        return directory

    def test_backup_stage_and_detect_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.skill(base / "source")
            manifest = migration.migrate({"shared": base / "source"}, base / "evidence", base / "stage")
            self.assertEqual([], migration.verify(manifest))
            self.assertEqual((source / "SKILL.md").read_bytes(), (base / "stage/example/SKILL.md").read_bytes())
            (source / "reference.txt").write_text("changed")
            self.assertEqual(1, len(migration.verify(manifest)))

    def test_collision_preserves_both_original_playbooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.skill(base / "a", body="first")
            self.skill(base / "b", body="second")
            manifest = migration.migrate({"pi": base / "a", "shared": base / "b"}, base / "evidence", base / "stage")
            self.assertEqual({"pi-example", "shared-example"}, {s["omp_name"] for s in manifest["skills"]})
            self.assertEqual([], migration.verify(manifest))
            self.assertIn("name: pi-example", (base / "stage/pi-example/SKILL.md").read_text())
            self.assertEqual((base / "a/example/SKILL.md").read_bytes(), (base / "stage/pi-example/SKILL.original.md").read_bytes())

    def test_external_symlink_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = self.skill(base / "source")
            (skill / "linked").symlink_to(base / "external")
            with self.assertRaises(ValueError):
                migration.migrate({"shared": base / "source"}, base / "evidence")
            self.assertFalse((base / "evidence").exists())

    def test_credentials_and_overwrite_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            skill = self.skill(base / "source")
            (skill / "auth.json").write_text("must not be read")
            with self.assertRaises(ValueError):
                migration.migrate({"shared": base / "source"}, base / "evidence")
            (skill / "auth.json").unlink()
            migration.migrate({"shared": base / "source"}, base / "evidence")
            with self.assertRaises(ValueError):
                migration.migrate({"shared": base / "source"}, base / "evidence")

    def test_added_file_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.skill(base / "source")
            manifest = migration.migrate({"shared": base / "source"}, base / "evidence")
            (source / "new-file.txt").write_text("new")
            self.assertTrue(migration.verify(manifest))

    def test_nested_catalog_requires_explicit_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.skill(base / "source/.system")
            manifest = migration.migrate({"codex": base / "source"}, base / "evidence")
            self.assertEqual([], manifest["skills"])


if __name__ == "__main__":
    unittest.main()
