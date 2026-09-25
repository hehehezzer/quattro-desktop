from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
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


class RuntimeDeploymentStatusTests(unittest.TestCase):
    MANIFEST_REVISION = "a" * 40

    def _git_checkout(self, root: pathlib.Path, *, commit: bool = True) -> str | None:
        git_env = {
            "PATH": os.defpath,
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Quattro Test",
            "GIT_AUTHOR_EMAIL": "quattro-test@example.invalid",
            "GIT_COMMITTER_NAME": "Quattro Test",
            "GIT_COMMITTER_EMAIL": "quattro-test@example.invalid",
        }
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--quiet", str(root)], check=True, env=git_env)
        source_file = root / "src" / "tool.py"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("source", encoding="utf-8")
        if not commit:
            return None
        subprocess.run(
            ["git", "-C", str(root), "add", "src/tool.py"],
            check=True, env=git_env,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "--quiet", "-m", "fixture"],
            check=True, env=git_env,
        )
        return deployment.resolve_git_revision(root)

    def _manifest(
        self,
        source_root: pathlib.Path,
        deployed_root: pathlib.Path,
        manifest_path: pathlib.Path,
        revision: str,
    ) -> dict:
        source_file = source_root / "src" / "tool.py"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        if not source_file.exists():
            source_file.write_text("source", encoding="utf-8")
        deployed_file = deployed_root / ".local/bin/tool.py"
        deployed_file.parent.mkdir(parents=True, exist_ok=True)
        deployed_file.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
        manifest = deployment.build_manifest(
            source_root,
            deployed_root,
            {"tool": ("src/tool.py", ".local/bin/tool.py")},
            revision=revision,
        )
        deployment.write_manifest_atomic(manifest_path, manifest)
        return manifest

    def test_valid_git_checkout_compares_revision_and_file_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            deployed = root / "deployed"
            source_revision = self._git_checkout(source)
            manifest_path = root / "state/manifest.json"
            self._manifest(source, deployed, manifest_path, str(source_revision))

            result = cli._deployment_runtime_status(source, manifest_path, deployed)

        self.assertEqual(result["sourceCheckoutStatus"], "available")
        self.assertEqual(result["sourceRevision"], source_revision)
        self.assertEqual(result["deployedSourceRevision"], source_revision)
        self.assertEqual(result["sourceCheckoutComparison"], "match")
        self.assertFalse(result["revisionDrift"])
        self.assertTrue(result["manifestParity"])
        self.assertTrue(result["deployedParity"])

    def test_installed_artifact_without_git_uses_manifest_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            artifact = root / "installed-artifact"
            (artifact / "quattro_agent").mkdir(parents=True)
            (artifact / "quattro_agent/cli.py").write_text("installed", encoding="utf-8")
            source = root / "release-source"
            deployed = root / "deployed"
            manifest_path = root / "state/manifest.json"
            self._manifest(source, deployed, manifest_path, self.MANIFEST_REVISION)

            with mock.patch.object(
                cli, "resolve_git_revision", side_effect=AssertionError("artifact is not a source checkout"),
            ) as resolve_revision:
                result = cli._deployment_runtime_status(artifact, manifest_path, deployed)
                resolve_revision.assert_not_called()

        self.assertEqual(result["sourceCheckoutStatus"], "not_a_git_checkout")
        self.assertEqual(result["sourceCheckoutComparison"], "unavailable")
        self.assertIsNone(result["sourceRevision"])
        self.assertEqual(result["deployedSourceRevision"], self.MANIFEST_REVISION)
        self.assertIsNone(result["manifestParity"])
        self.assertTrue(result["deployedParity"])

    def test_missing_source_checkout_keeps_status_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "release-source"
            deployed = root / "deployed"
            manifest_path = root / "state/manifest.json"
            self._manifest(source, deployed, manifest_path, self.MANIFEST_REVISION)

            result = cli._deployment_runtime_status(root / "missing-source", manifest_path, deployed)

        self.assertEqual(result["sourceCheckoutStatus"], "missing_checkout")
        self.assertEqual(result["sourceCheckoutComparison"], "unavailable")
        self.assertEqual(result["deployedSourceRevision"], self.MANIFEST_REVISION)
        self.assertTrue(result["deployedParity"])

    def test_invalid_git_head_is_reported_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            self._git_checkout(source, commit=False)
            deployed = root / "deployed"
            manifest_path = root / "state/manifest.json"
            self._manifest(root / "release-source", deployed, manifest_path, self.MANIFEST_REVISION)

            result = cli._deployment_runtime_status(source, manifest_path, deployed)

        self.assertEqual(result["sourceCheckoutStatus"], "invalid_git_head")
        self.assertEqual(result["sourceCheckoutComparison"], "unavailable")
        self.assertIsNone(result["sourceRevision"])
        self.assertEqual(result["deployedSourceRevision"], self.MANIFEST_REVISION)

    def test_missing_source_file_does_not_look_like_installed_file_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            source_revision = self._git_checkout(source)
            deployed = root / "deployed"
            manifest_path = root / "state/manifest.json"
            self._manifest(source, deployed, manifest_path, str(source_revision))
            (source / "src/tool.py").unlink()

            result = cli._deployment_runtime_status(source, manifest_path, deployed)

        self.assertEqual(result["sourceRevision"], source_revision)
        self.assertEqual(result["sourceCheckoutComparison"], "drift")
        self.assertFalse(result["manifestParity"])
        self.assertTrue(result["deployedParity"])

    def test_missing_manifest_revision_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            source_revision = self._git_checkout(source)
            deployed = root / "deployed"

            result = cli._deployment_runtime_status(source, root / "missing-manifest.json", deployed)

        self.assertEqual(result["sourceCheckoutStatus"], "available")
        self.assertEqual(result["sourceRevision"], source_revision)
        self.assertEqual(result["manifestStatus"], "unavailable")
        self.assertIsNone(result["manifestRevision"])
        self.assertIsNone(result["deployedSourceRevision"])
        self.assertEqual(result["sourceCheckoutComparison"], "manifest_unavailable")
        self.assertIsNone(result["revisionDrift"])

    def test_source_and_deployed_revision_drift_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source"
            source_revision = self._git_checkout(source)
            deployed = root / "deployed"
            manifest_path = root / "state/manifest.json"
            self._manifest(source, deployed, manifest_path, self.MANIFEST_REVISION)

            result = cli._deployment_runtime_status(source, manifest_path, deployed)

        self.assertNotEqual(source_revision, self.MANIFEST_REVISION)
        self.assertEqual(result["sourceCheckoutComparison"], "drift")
        self.assertTrue(result["revisionDrift"])
        self.assertEqual(result["sourceRevision"], source_revision)
        self.assertEqual(result["deployedSourceRevision"], self.MANIFEST_REVISION)

    def test_status_json_reports_unavailable_source_checkout_and_manifest_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            deployed = root / "deployed"
            manifest_path = root / "state/manifest.json"
            self._manifest(root / "release-source", deployed, manifest_path, self.MANIFEST_REVISION)
            installed = root / "installed"
            installed.mkdir()
            harness = mock.Mock()
            harness.list_logical_sessions.return_value = []
            harness.store.list_display_approvals.return_value = []
            harness.coordinator.status.return_value = {}
            harness.routing_summary.return_value = {}
            harness.list_tasks.return_value = []
            knowledge_store = mock.Mock()
            knowledge_store.stats.return_value = {}
            knowledge_store.last_trace.return_value = None
            output = io.StringIO()
            with (
                mock.patch.object(cli, "ensure_state_dirs"),
                mock.patch.object(cli, "load_config", return_value={
                    "defaultAgent": "codex",
                    "defaultCodexAccount": "account-1",
                    "defaultPolicyProfile": "workspace-write",
                    "accounts": [],
                }),
                mock.patch.object(cli, "memory_settings", return_value=(False, None, False)),
                mock.patch.object(cli, "project_memory_path", return_value=root / "project-memory"),
                mock.patch.object(cli, "repository_state", side_effect=lambda path: {
                    "repository": str(path), "commitSha": None,
                }),
                mock.patch.object(cli, "command_path", return_value=None),
                mock.patch.object(cli, "retrieval_store", return_value=contextlib.nullcontext(knowledge_store)),
                mock.patch.object(cli, "harness", return_value=harness),
                mock.patch.object(cli, "model_catalog_path", return_value=root / "missing-catalog.json"),
                mock.patch.object(cli, "read_json", side_effect=lambda _path, default: default),
                mock.patch.object(cli, "sessions_status", return_value=[]),
                mock.patch.object(cli, "usage_status", return_value={}),
                mock.patch.object(cli, "dictation_status", return_value={"state": "idle"}),
                mock.patch.object(cli, "crash_rows", return_value=[]),
                mock.patch.multiple(
                    cli,
                    DEFAULT_WORKSPACE=installed,
                    DEPLOYMENT_MANIFEST=manifest_path,
                    HOME=deployed,
                ),
                mock.patch.object(cli.sys, "argv", ["quattro-agent", "status", "--json"]),
                contextlib.redirect_stdout(output),
            ):
                result = cli.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(payload["runtime"]["sourceCheckoutComparison"], "unavailable")
        self.assertEqual(payload["runtime"]["deployedSourceRevision"], self.MANIFEST_REVISION)
        self.assertIsNone(payload["runtime"]["sourceRevision"])


if __name__ == "__main__":
    unittest.main()
