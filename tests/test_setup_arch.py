"""User-state preservation and opt-in boundaries of Arch onboarding."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from setup_arch import Files


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() != 0, "Linux user setup")
class ArchSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="quattro-setup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"

    def setup_command(self, *arguments):
        return subprocess.run(
            [str(ROOT / "install.sh"), "--arch", "--home", str(self.home), *arguments],
            capture_output=True, text=True, timeout=30,
        )

    def test_dry_run_and_rejected_selections_never_mutate_the_target(self):
        for arguments in (("--features", "desktop,intelligence", "--dry-run"),
                          ("--features", "applications", "--yes"),
                          ("--features", "jev", "--yes"),
                          ("--features", "intelligence,native", "--yes")):
            with self.subTest(arguments=arguments):
                result = self.setup_command(*arguments)
                self.assertEqual(result.returncode == 0, "--dry-run" in arguments,
                                 result.stdout + result.stderr)
                self.assertFalse(self.home.exists())

    def test_desktop_only_staging_preserves_existing_core_and_records_replacement(self):
        config = self.home / ".config"
        hyprland = config / "hypr/hyprland.lua"
        hyprland.parent.mkdir(parents=True)
        original = b"-- my existing desktop preferences\n"
        hyprland.write_bytes(original)
        hyprland.chmod(0o600)
        core = config / "quattro/intelligence.json"
        core.parent.mkdir()
        core.write_text('{"operator-owned": true}\n')
        result = self.setup_command("--features", "desktop", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(core.read_text(), '{"operator-owned": true}\n')
        self.assertFalse((self.home / ".local/share/quattro/intelligence/venv").exists())
        journals = list((self.home / ".local/state/quattro/setup-backups").glob("*/rollback.json"))
        self.assertEqual(len(journals), 1)
        entries = json.loads(journals[0].read_text())
        preserved = next(item for item in entries if item["path"] == str(hyprland))
        self.assertEqual((journals[0].parent / preserved["saved"]).read_bytes(), original)
        self.assertEqual(preserved["mode"], 0o600)
        self.assertNotIn(str(core), {item["path"] for item in entries})

    def test_file_journal_retains_original_across_multiple_changes(self):
        target = self.root / "settings"
        target.write_text("original preferences")
        target.chmod(0o640)
        files = Files(self.root / "backups")
        files.text(target, "first update")
        files.text(target, "second update")
        entries = json.loads((files.backup / "rollback.json").read_text())
        self.assertEqual(len(entries), 1)
        self.assertEqual((files.backup / entries[0]["saved"]).read_text(), "original preferences")
        self.assertEqual(entries[0]["mode"], 0o640)

    def test_symlink_ancestor_cannot_redirect_configuration_writes(self):
        outside = self.root / "outside"
        outside.mkdir()
        victim = outside / "settings"
        victim.write_text("must remain unchanged")
        alias = self.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        files = Files(self.root / "backups")
        with self.assertRaises(ValueError):
            files.text(alias / "settings", "not authorized")
        self.assertEqual(victim.read_text(), "must remain unchanged")
        self.assertFalse(files.backup.exists())


if __name__ == "__main__":
    unittest.main()
