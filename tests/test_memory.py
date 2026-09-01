from __future__ import annotations

import pathlib
import tempfile
import unittest

import sys


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import quattro_memory as memory
from quattro_agent.paths import xdg_data_home


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vault = pathlib.Path(self.temp.name) / "agents"
        self.project_vault = pathlib.Path(self.temp.name) / "projects"

    def tearDown(self):
        self.temp.cleanup()

    def test_initialization_creates_complete_healthy_vault(self):
        created = memory.initialize_vault(self.vault)
        self.assertIn("INDEX.md", created)
        self.assertEqual(memory.vault_status(self.vault)["status"], "ok")

    def test_initialization_preserves_existing_memory(self):
        self.vault.mkdir()
        index = self.vault / "INDEX.md"
        index.write_text("# Existing\n", encoding="utf-8")
        memory.initialize_vault(self.vault)
        self.assertEqual(index.read_text(encoding="utf-8"), "# Existing\n")

    def test_project_vault_initialization_and_linking_preserve_project_notes(self):
        memory.initialize_vault(self.vault)
        project = self.vault / "Projects" / "example"
        project.mkdir()
        (project / "PROJECT.md").write_text("# Example\n", encoding="utf-8")
        memory.initialize_project_vault(self.project_vault, self.vault)
        moved = memory.link_project_vault(self.vault, self.project_vault)
        self.assertIn("example", moved)
        self.assertTrue((self.project_vault / "example" / "PROJECT.md").is_file())
        self.assertTrue((self.vault / "Projects").is_symlink())
        self.assertEqual(memory.project_vault_status(self.project_vault)["status"], "ok")

    def test_project_vault_setting_defaults_and_validates(self):
        expected = xdg_data_home() / "quattro/memory/projects"
        self.assertEqual(memory.project_memory_path({}), expected.resolve())
        with self.assertRaisesRegex(memory.MemoryError, "projectVaultPath"):
            memory.project_memory_path({"memory": {"projectVaultPath": ""}})

    def test_obsidian_registration_preserves_other_vaults(self):
        memory.initialize_vault(self.vault)
        registry = pathlib.Path(self.temp.name) / "obsidian.json"
        registry.write_text('{"theme":"system","vaults":{"existing":{"path":"/tmp/other"}}}', encoding="utf-8")
        identifier = memory.register_obsidian_vault(self.vault, registry)
        import json
        value = json.loads(registry.read_text(encoding="utf-8"))
        self.assertEqual(value["theme"], "system")
        self.assertEqual(value["vaults"]["existing"]["path"], "/tmp/other")
        self.assertEqual(value["vaults"][identifier]["path"], str(self.vault))

    def test_missing_vault_fails_closed(self):
        with self.assertRaisesRegex(memory.MemoryError, "Configured memory"):
            memory.require_vault(self.vault)

    def test_audit_detects_token_like_values(self):
        memory.initialize_vault(self.vault)
        (self.vault / "Sessions" / "unsafe.md").write_text("access_token=synthetic-test-value", encoding="utf-8")
        self.assertEqual(memory.audit_vault(self.vault), ["Sessions/unsafe.md"])

    def test_policy_names_canonical_vault_and_security_boundary(self):
        policy = memory.memory_policy(self.vault, self.project_vault)
        self.assertIn(str(self.vault), policy)
        self.assertIn(str(self.project_vault), policy)
        self.assertIn("For project work", policy)
        self.assertIn("Never store secrets", policy)

    def test_obsidian_uri_is_encoded(self):
        uri = memory.obsidian_uri(pathlib.Path("/tmp/a vault"))
        self.assertEqual(uri, "obsidian://open?path=%2Ftmp%2Fa+vault")


if __name__ == "__main__":
    unittest.main()
