from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
import unittest


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import quattro_deployment as deployment
from quattro_agent.cli import DEPLOYMENT_MAPPINGS
from quattro_release import create_source_release, restore_release


class DeploymentManifestTests(unittest.TestCase):
    REVISION = "a" * 40
    PREVIOUS_REVISION = "b" * 40

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
