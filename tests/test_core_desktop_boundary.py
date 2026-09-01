from __future__ import annotations

import ast
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from quattro.deployment.migration import migrate_legacy_manifest
from quattro.deployment.profiles import (
    CORE_DEPLOYMENT_MAPPINGS, DESKTOP_DEPLOYMENT_MAPPINGS, DESKTOP_RETIRED_PATHS,
)
from quattro.platform.directories import config_home, data_home, state_home
from quattro.platform.executables import find_executable
from quattro_deployment import build_manifest, load_manifest, write_manifest_atomic


class CoreDesktopBoundaryTests(unittest.TestCase):
    def test_core_never_imports_desktop_package(self):
        roots = [SRC / "quattro_agent", SRC / "quattro/core", SRC / "quattro/adapters", SRC / "quattro/platform"]
        violations = []
        for root in roots:
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    for name in names:
                        if name == "quattro_desktop" or name.startswith("quattro_desktop."):
                            violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
        self.assertEqual(violations, [])

    def test_desktop_consumes_core_platform_boundary(self):
        source = (SRC / "quattro_desktop/status.py").read_text(encoding="utf-8")
        self.assertIn("from quattro.platform.processes import platform_name", source)

    def test_profile_inventories_are_disjoint_and_correctly_owned(self):
        self.assertTrue(set(CORE_DEPLOYMENT_MAPPINGS).isdisjoint(DESKTOP_DEPLOYMENT_MAPPINGS))
        for source, deployed in CORE_DEPLOYMENT_MAPPINGS.values():
            joined = f"{source} {deployed}".lower()
            for desktop_token in ("quickshell", "hypr", "wallpaper", "systemd", "qml"):
                self.assertNotIn(desktop_token, joined)
        for source, _deployed in DESKTOP_DEPLOYMENT_MAPPINGS.values():
            self.assertFalse(source.startswith("src/quattro_agent/"))

    def test_desktop_inventory_contains_complete_qml_and_hyprland_sources(self):
        owned = {source for source, _deployed in DESKTOP_DEPLOYMENT_MAPPINGS.values()}
        expected = {
            path.relative_to(ROOT).as_posix()
            for directory in (ROOT / "src/quickshell", ROOT / "src/hypr")
            for path in directory.rglob("*") if path.is_file()
        }
        self.assertEqual(expected - owned, set())
        self.assertIn(".local/share/quattro/wallpapers/avengers-doomsday.png", DESKTOP_RETIRED_PATHS)
        self.assertTrue(DESKTOP_RETIRED_PATHS.isdisjoint({deployed for _source, deployed in CORE_DEPLOYMENT_MAPPINGS.values()}))

    def test_missing_desktop_assets_cannot_block_core_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "source"
            deployed = root / "deployed"
            source.mkdir(); deployed.mkdir()
            mappings = {}
            for name, (source_path, deployed_path) in CORE_DEPLOYMENT_MAPPINGS.items():
                original = ROOT / source_path
                target_source = source / source_path
                target_deployed = deployed / deployed_path
                target_source.parent.mkdir(parents=True, exist_ok=True)
                target_deployed.parent.mkdir(parents=True, exist_ok=True)
                target_source.write_bytes(original.read_bytes())
                target_deployed.write_bytes(original.read_bytes())
                mappings[name] = (source_path, deployed_path)
            manifest = build_manifest(source, deployed, mappings, revision="a" * 40)
            self.assertTrue(manifest["parity"]["allMatch"])

    def test_core_doctor_succeeds_without_desktop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            env = os.environ.copy()
            env.update({
                "PYTHONPATH": str(SRC),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "QUATTRO_WORKSPACE": str(ROOT),
            })
            init = subprocess.run([sys.executable, str(SRC / "quattro-agent"), "config", "init"], env=env, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            doctor = subprocess.run([sys.executable, str(SRC / "quattro-agent"), "doctor", "--json"], env=env, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            payload = json.loads(doctor.stdout)
            self.assertEqual(payload["core"]["status"], "HEALTHY")
            self.assertEqual(payload["desktop"]["status"], "OPTIONAL_NOT_INSTALLED")

    def test_windows_directory_conventions(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch("sys.platform", "win32"), mock.patch.dict(os.environ, {
            "APPDATA": str(pathlib.Path(temporary) / "Roaming"),
            "LOCALAPPDATA": str(pathlib.Path(temporary) / "Local"),
        }, clear=False):
            self.assertEqual(config_home(), (pathlib.Path(temporary) / "Roaming").resolve())
            self.assertEqual(data_home(), (pathlib.Path(temporary) / "Local").resolve())
            self.assertEqual(state_home(), (pathlib.Path(temporary) / "Local").resolve())

    def test_executable_discovery_respects_path_first(self):
        with mock.patch("shutil.which", return_value="/custom/bin/codex"):
            self.assertEqual(find_executable("codex"), "/custom/bin/codex")


class DeploymentMigrationTests(unittest.TestCase):
    def test_legacy_manifest_is_split_archived_and_state_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = root / "source"; deployed = root / "home"; state = root / "state"
            source.mkdir(); deployed.mkdir(); state.mkdir()
            mappings = {
                "launcher": ("src/quattro-agent", ".local/bin/quattro-agent"),
                "agents-qml": ("src/quickshell/components/Agents.qml", ".config/quickshell/components/Agents.qml"),
                "retired-wallpaper": ("src/wallpapers/avengers-doomsday.png", ".local/share/quattro/wallpapers/avengers-doomsday.png"),
            }
            for source_path, deployed_path in mappings.values():
                left = source / source_path; right = deployed / deployed_path
                left.parent.mkdir(parents=True, exist_ok=True); right.parent.mkdir(parents=True, exist_ok=True)
                left.write_text(source_path, encoding="utf-8"); right.write_text(source_path, encoding="utf-8")
            legacy = state / "deployment/manifest.json"
            write_manifest_atomic(legacy, build_manifest(source, deployed, mappings, revision="b" * 40))
            database = state / "tasks.sqlite3"; database.write_bytes(b"durable-state-canary")
            result = migrate_legacy_manifest(
                legacy, state / "deployment/core-manifest.json", state / "deployment/desktop-manifest.json",
                core_names={"launcher"}, desktop_names={"agents-qml"},
            )
            self.assertEqual(result["status"], "migrated")
            self.assertFalse(legacy.exists())
            self.assertTrue(pathlib.Path(result["archive"]).is_file())
            core = load_manifest(state / "deployment/core-manifest.json")
            desktop = load_manifest(state / "deployment/desktop-manifest.json")
            self.assertEqual([row["name"] for row in core["files"]], ["launcher"])
            self.assertEqual({row["name"] for row in desktop["files"]}, {"agents-qml", "retired-wallpaper"})
            self.assertEqual(database.read_bytes(), b"durable-state-canary")
            self.assertEqual(core["rollback"], desktop["rollback"])


if __name__ == "__main__":
    unittest.main()
