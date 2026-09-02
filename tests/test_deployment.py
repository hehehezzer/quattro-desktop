from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import quattro_deployment as deployment
import quattro_agent.cli as cli
from quattro_agent.cli import DEPLOYMENT_MAPPINGS
from quattro_release import create_source_release, restore_release


class DeploymentManifestTests(unittest.TestCase):
    REVISION = "a" * 40
    PREVIOUS_REVISION = "b" * 40

    def test_profile_rollback_is_isolated_and_rewrites_healthy_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"; deployed = root / "home"; releases = root / "releases"
            source.mkdir(); deployed.mkdir()
            mapping = {"launcher": ("src/launcher", ".local/bin/launcher")}
            current_source = source / "src/launcher"; current_live = deployed / ".local/bin/launcher"
            current_source.parent.mkdir(parents=True); current_live.parent.mkdir(parents=True)
            current_source.write_text("new", encoding="utf-8"); current_live.write_text("new", encoding="utf-8")
            desktop_canary = deployed / ".config/quickshell/shell.qml"
            desktop_canary.parent.mkdir(parents=True); desktop_canary.write_text("desktop", encoding="utf-8")
            old_source = root / "old-source"; (old_source / "src").mkdir(parents=True)
            (old_source / "src/launcher").write_text("old", encoding="utf-8")
            old_revision = "4" * 40; current_revision = "5" * 40
            retired_path = ".local/bin/retired-core-helper"
            old_release = create_source_release(
                releases, old_revision, old_source, mapping,
                release_id=f"c0-{old_revision}", profile="core",
                absent_paths=[retired_path],
            )
            manifest_path = root / "state/core-manifest.json"
            active = deployment.build_manifest(
                source, deployed, mapping, revision=current_revision,
                rollback_manifest=old_release.relative_to(releases).as_posix(),
                rollback_revision=old_revision,
                absent_paths=[retired_path],
            )
            deployment.write_manifest_atomic(manifest_path, active)
            stale = deployed / retired_path
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("must be removed", encoding="utf-8")
            with mock.patch.multiple(
                cli,
                HOME=deployed,
                DEFAULT_WORKSPACE=source,
                RELEASE_ROOT=releases,
                CORE_DEPLOYMENT_MANIFEST=manifest_path,
                CORE_DEPLOYMENT_MAPPINGS=mapping,
            ):
                result = cli._rollback_profile("core", old_revision[:12])
                status = cli._deployment_status("core")
            self.assertEqual(current_live.read_text(encoding="utf-8"), "old")
            self.assertEqual(desktop_canary.read_text(encoding="utf-8"), "desktop")
            self.assertFalse(stale.exists())
            self.assertEqual(result["revision"], old_revision)
            self.assertTrue(result["liveParity"]["allMatch"])
            self.assertEqual(status["status"], "ok")
            self.assertEqual(status["manifest"]["gitRevision"], old_revision)
            self.assertTrue(status["manifest"]["rollback"]["available"])
            stale.write_text("reappeared", encoding="utf-8")
            with mock.patch.multiple(
                cli, HOME=deployed, DEFAULT_WORKSPACE=source, RELEASE_ROOT=releases,
                CORE_DEPLOYMENT_MANIFEST=manifest_path, CORE_DEPLOYMENT_MAPPINGS=mapping,
            ):
                drifted = cli._deployment_status("core")
            self.assertEqual(drifted["status"], "drift")

    def test_absent_only_profile_rollback_is_valid_and_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"; deployed = root / "home"; old_home = root / "old-home"
            releases = root / "releases"
            source.mkdir(); deployed.mkdir(); old_home.mkdir()
            mapping = {"launcher": ("src/launcher", ".local/bin/launcher")}
            source_file = source / "src/launcher"; live_file = deployed / ".local/bin/launcher"
            source_file.parent.mkdir(parents=True); live_file.parent.mkdir(parents=True)
            source_file.write_text("new", encoding="utf-8"); live_file.write_text("new", encoding="utf-8")
            old_revision = "8" * 40; current_revision = "9" * 40
            old_release = cli.create_release(
                releases, old_revision, old_home, [".local/bin/launcher"],
                release_id=f"c0-{old_revision}", profile="core",
            )
            manifest_path = root / "state/core-manifest.json"
            active = deployment.build_manifest(
                source, deployed, mapping, revision=current_revision,
                rollback_manifest=old_release.relative_to(releases).as_posix(),
                rollback_revision=old_revision,
            )
            deployment.write_manifest_atomic(manifest_path, active)
            with mock.patch.multiple(
                cli, HOME=deployed, DEFAULT_WORKSPACE=source, RELEASE_ROOT=releases,
                CORE_DEPLOYMENT_MANIFEST=manifest_path, CORE_DEPLOYMENT_MAPPINGS=mapping,
            ):
                result = cli._rollback_profile("core", old_revision[:12])
                status = cli._deployment_status("core")
            self.assertFalse(live_file.exists())
            self.assertEqual(result["manifest"]["files"], [])
            self.assertEqual(result["manifest"]["absentPaths"], [".local/bin/launcher"])
            self.assertEqual(status["status"], "ok")

    def test_profile_rollback_rejects_cross_profile_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"; deployed = root / "home"; releases = root / "releases"
            source.mkdir(); deployed.mkdir()
            mapping = {"launcher": ("src/launcher", ".local/bin/launcher")}
            for base in (source / "src/launcher", deployed / ".local/bin/launcher"):
                base.parent.mkdir(parents=True, exist_ok=True); base.write_text("current", encoding="utf-8")
            revision = "6" * 40
            wrong = create_source_release(
                releases, revision, source, mapping,
                release_id=f"de-{revision}", profile="desktop",
            )
            manifest_path = root / "state/core-manifest.json"
            active = deployment.build_manifest(
                source, deployed, mapping, revision="7" * 40,
                rollback_manifest=wrong.relative_to(releases).as_posix(),
                rollback_revision=revision,
            )
            deployment.write_manifest_atomic(manifest_path, active)
            with mock.patch.multiple(
                cli, HOME=deployed, DEFAULT_WORKSPACE=source, RELEASE_ROOT=releases,
                CORE_DEPLOYMENT_MANIFEST=manifest_path, CORE_DEPLOYMENT_MAPPINGS=mapping,
            ), self.assertRaises(SystemExit):
                cli._rollback_profile("core", revision[:12])

    def roots(self, directory: str) -> tuple[pathlib.Path, pathlib.Path]:
        root = pathlib.Path(directory)
        source = root / "source"
        deployed = root / "deployed"
        source.mkdir()
        deployed.mkdir()
        return source, deployed

    def test_manifest_records_git_revision_hash_parity_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            (source / "launcher").write_text("same", encoding="utf-8")
            (deployed / "bin").mkdir()
            (deployed / "bin" / "launcher").write_text("same", encoding="utf-8")

            manifest = deployment.build_manifest(
                source,
                deployed,
                {"quattro-agent": ("launcher", "bin/launcher")},
                revision=self.REVISION,
                rollback_manifest="history/previous.json",
                rollback_revision=self.PREVIOUS_REVISION,
                generated_at="2026-08-29T12:00:00Z",
            )

        self.assertEqual(manifest["gitRevision"], self.REVISION)
        self.assertTrue(manifest["parity"]["allMatch"])
        self.assertEqual(manifest["parity"]["matched"], 1)
        self.assertTrue(manifest["rollback"]["available"])
        self.assertEqual(manifest["rollback"]["previousGitRevision"], self.PREVIOUS_REVISION)
        self.assertNotIn("contents", json.dumps(manifest).lower())

    def test_manifest_reports_mismatch_without_copying_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            (source / "module.py").write_text("source-value", encoding="utf-8")
            (deployed / "module.py").write_text("deployed-value", encoding="utf-8")

            manifest = deployment.build_manifest(
                source,
                deployed,
                {"module": "module.py"},
                revision=self.REVISION,
            )

        self.assertFalse(manifest["files"][0]["matches"])
        self.assertEqual(manifest["parity"]["mismatched"], 1)
        serialized = json.dumps(manifest)
        self.assertNotIn("source-value", serialized)
        self.assertNotIn("deployed-value", serialized)

    def test_atomic_manifest_is_private_and_validated_on_load(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            (source / "tool").write_bytes(b"tool")
            (deployed / "tool").write_bytes(b"tool")
            manifest = deployment.build_manifest(
                source, deployed, {"tool": "tool"}, revision=self.REVISION
            )
            target = pathlib.Path(directory) / "state" / "deployment.json"
            deployment.write_manifest_atomic(target, manifest)

            loaded = deployment.load_manifest(target)
            target_mode = target.stat().st_mode & 0o777

        self.assertEqual(loaded, manifest)
        self.assertEqual(target_mode, 0o600)

    def test_validation_rejects_extra_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            (source / "tool").write_bytes(b"tool")
            (deployed / "tool").write_bytes(b"tool")
            manifest = deployment.build_manifest(
                source, deployed, {"tool": "tool"}, revision=self.REVISION
            )
            manifest["environment"] = {"EXAMPLE": "not allowed"}
            with self.assertRaises(deployment.DeploymentManifestError):
                deployment.validate_manifest(manifest)

    def test_atomic_write_does_not_repermission_existing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            (source / "tool").write_bytes(b"tool")
            (deployed / "tool").write_bytes(b"tool")
            manifest = deployment.build_manifest(
                source, deployed, {"tool": "tool"}, revision=self.REVISION
            )
            parent = pathlib.Path(directory) / "shared"
            parent.mkdir(mode=0o750)
            parent.chmod(0o750)

            deployment.write_manifest_atomic(parent / "deployment.json", manifest)

            self.assertEqual(parent.stat().st_mode & 0o777, 0o750)

    def test_sensitive_or_escaping_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            with self.assertRaises(deployment.DeploymentManifestError):
                deployment.build_manifest(
                    source, deployed, {"auth": "auth.json"}, revision=self.REVISION
                )
            for name in ("auth.json.bak", "credentials-backup", ".env.local", "id_rsa.old", "token.txt"):
                with self.subTest(name=name), self.assertRaises(deployment.DeploymentManifestError):
                    deployment.build_manifest(
                        source, deployed, {"sensitive": name}, revision=self.REVISION
                    )
            with self.assertRaises(deployment.DeploymentManifestError):
                deployment.build_manifest(
                    source, deployed, {"escape": "../outside"}, revision=self.REVISION
                )

    def test_live_verification_detects_post_deployment_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            source, deployed = self.roots(directory)
            (source / "tool").write_text("same", encoding="utf-8")
            (deployed / "tool").write_text("same", encoding="utf-8")
            manifest = deployment.build_manifest(
                source, deployed, {"tool": "tool"}, revision=self.REVISION
            )
            self.assertTrue(
                deployment.verify_manifest_files(manifest, source, deployed)["allMatch"]
            )
            (deployed / "tool").write_text("drift", encoding="utf-8")
            result = deployment.verify_manifest_files(manifest, source, deployed)
            self.assertFalse(result["allMatch"])
            self.assertEqual(result["driftCount"], 1)
            self.assertTrue(result["sourceVerified"])

    def test_public_mapping_builds_without_removed_wallpaper_asset(self):
        self.assertNotIn("doomsday-wallpaper", DEPLOYMENT_MAPPINGS)
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "source"
            deployed = pathlib.Path(directory) / "deployed"
            source.mkdir()
            deployed.mkdir()
            for source_relative, deployed_relative in DEPLOYMENT_MAPPINGS.values():
                source_file = pathlib.Path(__file__).parents[1] / source_relative
                source_target = source / source_relative
                deployed_file = deployed / deployed_relative
                source_target.parent.mkdir(parents=True, exist_ok=True)
                deployed_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, source_target)
                shutil.copy2(source_file, deployed_file)
            manifest = deployment.build_manifest(
                source,
                deployed,
                DEPLOYMENT_MAPPINGS,
                revision=self.REVISION,
            )
        self.assertTrue(manifest["parity"]["allMatch"])

    def test_source_release_deploys_current_mapping_to_manifest_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            deployed = root / "deployed"
            releases = root / "releases"
            deployed.mkdir()
            candidate = create_source_release(
                releases,
                self.REVISION,
                pathlib.Path(__file__).parents[1],
                DEPLOYMENT_MAPPINGS,
            )
            restore_release(
                candidate,
                deployed,
                release_root=releases,
                expected_revision=self.REVISION,
            )
            manifest = deployment.build_manifest(
                pathlib.Path(__file__).parents[1],
                deployed,
                DEPLOYMENT_MAPPINGS,
                revision=self.REVISION,
            )
        self.assertTrue(manifest["parity"]["allMatch"])


if __name__ == "__main__":
    unittest.main()
