from __future__ import annotations

import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
import sys
sys.path.insert(0, str(SRC))

from quattro_agent.errors import ConfigError, LeaseConflict
from quattro_agent.omniroute import (
    REQUIRED_QUATTRO_ROUTES, validate_catalog_parity,
    validate_omniroute_contract,
)
from quattro_agent.policy import policy_profile
from quattro_agent.adapters import AgentMode, CodexAdapter, RunSpec
from quattro_agent.scheduler import LocalScheduler
from quattro_agent.sessions import load_session_registry, prepare_shared_session_namespace
from quattro_agent.store import TaskStore
import quattro_agent.omniroute as omniroute
import quattro_agent.cli as launcher
import quattro_pr_review as review


def write_rollout(path: pathlib.Path, session_id: str, cwd: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "type": "session_meta",
        "payload": {"id": session_id, "cwd": str(cwd)},
    }) + "\nprivate conversation content\n", encoding="utf-8")


class OmniRouteContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.home = self.root / "account-1"
        self.home.mkdir()
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps({
            "models": [{"slug": slug} for slug in REQUIRED_QUATTRO_ROUTES],
        }) + "\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def config(self, **provider_overrides: object) -> None:
        provider = {
            "name": "OmniRoute",
            "base_url": "http://localhost:20128/api/v1",
            "requires_openai_auth": False,
            "wire_api": "responses",
            **provider_overrides,
        }
        lines = [
            'model_provider = "omniroute"',
            f'model_catalog_json = {json.dumps(str(self.catalog))}',
            "",
            "[model_providers.omniroute]",
            f'name = {json.dumps(provider["name"])}',
            f'base_url = {json.dumps(provider["base_url"])}',
            f'requires_openai_auth = {str(provider["requires_openai_auth"]).lower()}',
            f'wire_api = {json.dumps(provider["wire_api"])}',
        ]
        (self.home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_exact_contract_passes(self):
        self.config()
        with mock.patch.object(omniroute, "APPROVED_CATALOG", self.catalog.resolve()):
            result = validate_omniroute_contract(self.home)
        self.assertEqual(result.provider_id, "omniroute")

    def test_wrong_port_auth_or_wire_fails_closed(self):
        cases = (
            {"base_url": "http://localhost:20129/api/v1"},
            {"requires_openai_auth": True},
            {"wire_api": "chat"},
            {"base_url": "http://user:pass@localhost:20128/api/v1"},
        )
        for values in cases:
            with self.subTest(values=values):
                self.config(**values)
                with mock.patch.object(omniroute, "APPROVED_CATALOG", self.catalog.resolve()), \
                        self.assertRaises(ConfigError):
                    validate_omniroute_contract(self.home)

    def test_missing_required_virtual_route_fails_closed(self):
        self.config()
        self.catalog.write_text(json.dumps({
            "models": [{"slug": "auto"}],
        }) + "\n", encoding="utf-8")
        with mock.patch.object(omniroute, "APPROVED_CATALOG", self.catalog.resolve()), \
                self.assertRaisesRegex(ConfigError, "auto/coding:cheap"):
            validate_omniroute_contract(self.home)

    def test_catalog_parity_rejects_stale_active_copy(self):
        active = self.root / "active-catalog.json"
        active.write_text(self.catalog.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertTrue(validate_catalog_parity(self.catalog, active))
        active.write_text('{"models":[{"slug":"auto"}]}\n', encoding="utf-8")
        with self.assertRaisesRegex(ConfigError, "deployment drift"):
            validate_catalog_parity(self.catalog, active)

    def test_catalog_parity_skips_when_release_source_is_unavailable(self):
        self.assertIsNone(validate_catalog_parity(self.root / "missing.json", self.catalog))

    def test_loopback_only_policy_is_rejected_when_runtime_cannot_conform(self):
        self.config()
        profile = policy_profile(
            "desktop-config-write", project_root=self.root,
            desktop_roots=(self.root,),
        )
        spec = RunSpec(
            task_id="task", run_id="run", project_path=self.root,
            mode=AgentMode.PROMPT, policy=profile, account_home=self.home,
        )
        with self.assertRaisesRegex(ValueError, "cannot enforce loopback network access"):
            CodexAdapter().build_launch("/usr/bin/codex", spec)


class CrossAccountSessionTests(unittest.TestCase):
    def test_both_origins_share_rollouts_without_sharing_auth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            project = root / "project"
            project.mkdir()
            accounts = []
            ids = {
                "account-1": "11111111-1111-1111-1111-111111111111",
                "account-2": "22222222-2222-2222-2222-222222222222",
            }
            for account_id, session_id in ids.items():
                home = root / account_id
                home.mkdir()
                (home / "auth.json").write_text(f"private-{account_id}", encoding="utf-8")
                write_rollout(home / "sessions/2026/08/29" / f"rollout-{session_id}.jsonl", session_id, project)
                accounts.append({
                    "id": account_id, "alias": account_id, "codexHome": str(home), "enabled": True,
                })
            shared = root / "state/private/codex-sessions"
            registry = root / "state/private/registry.json"
            result = prepare_shared_session_namespace(accounts, shared, registry)
            self.assertEqual(result["linkedAccounts"], 2)
            for account in accounts:
                home = pathlib.Path(account["codexHome"])
                self.assertTrue((home / "sessions").is_symlink())
                self.assertEqual((home / "sessions").resolve(), shared.resolve())
                self.assertEqual((home / "auth.json").read_text(), f"private-{account['id']}")
                self.assertFalse((shared / "auth.json").exists())
            persisted = load_session_registry(registry)
            self.assertEqual(persisted[ids["account-1"]]["originatingAccount"], "account-1")
            self.assertEqual(persisted[ids["account-2"]]["originatingAccount"], "account-2")
            # Restart-safe and idempotent.
            again = prepare_shared_session_namespace(accounts, shared, registry)
            self.assertEqual(again, {"migrated": 0, "linkedAccounts": 0})

            config = {"accounts": accounts}
            with mock.patch.object(launcher, "CODEX_SESSION_REGISTRY", registry):
                for launch_account, session_id in (
                    ("account-2", ids["account-1"]),
                    ("account-1", ids["account-2"]),
                ):
                    target = launcher.resolve_codex_resume_target(
                        config, project, session_id=session_id, account_id=launch_account
                    )
                    self.assertIsNotNone(target)
                    self.assertEqual(target["sessionId"], session_id)

    def test_one_writer_lease_per_native_session(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            project = root / "project"
            project.mkdir()
            store = TaskStore(root / "harness.sqlite3")
            scheduler = LocalScheduler(store)
            policy = policy_profile("workspace-write", project_root=project)
            tasks = [store.create_task(
                workflow="resume", agent="codex", project_path=project,
                display_title="resume", policy=policy,
            ) for _ in range(2)]
            runs = [store.create_run(task, account_id="account-1") for task in tasks]
            scheduler.try_acquire(
                task_id=tasks[0], run_id=runs[0], agent="codex", account_id="account-1",
                project_path=project, native_session_ref="shared-session",
            )
            with self.assertRaises(LeaseConflict):
                scheduler.try_acquire(
                    task_id=tasks[1], run_id=runs[1], agent="codex", account_id="account-2",
                    project_path=project, native_session_ref="shared-session",
                )


class ReviewHeartbeatTests(unittest.TestCase):
    def test_long_review_polls_heartbeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "report.json"
            output.write_text("{}", encoding="utf-8")
            heartbeats: list[int] = []
            completed: list[int] = []

            class PollingProcess:
                pid = 1234
                returncode = None

                def __init__(self, _argv, **_kwargs):
                    self.stdin = io.StringIO()
                    self.stderr = io.StringIO("")
                    self.polls = 0

                def wait(self, timeout=None):
                    self.polls += 1
                    if self.polls < 3:
                        raise review.subprocess.TimeoutExpired("codex", timeout)
                    self.returncode = 0
                    return 0

            options = review.ReviewOptions(
                require_containment=False,
                heartbeat=lambda: heartbeats.append(1),
                on_process_completed=completed.append,
            )
            with mock.patch.object(review, "prepare_sanitized_codex_home"), \
                    mock.patch.object(review.subprocess, "Popen", PollingProcess):
                review.run_codex(root, "review", output, options, "codex", root)
            self.assertEqual(len(heartbeats), 2)
            self.assertEqual(completed, [0])

    def test_standalone_publication_requires_run_scoped_flag(self):
        source = (SRC / "quattro_agent/cli.py").read_text(encoding="utf-8")
        self.assertIn("publish=bool(args.publish)", source)
        self.assertNotIn('publish=bool(args.publish or review_config.get("automaticPublication"', source)

    def test_desktop_deployment_copies_the_packaged_cli_dependencies(self):
        for name in ("cli", "paths", "containment"):
            source, deployed = launcher.DEPLOYMENT_MAPPINGS[f"core-{name}"]
            self.assertEqual(source, f"src/quattro_agent/{name}.py")
            self.assertEqual(deployed, f".local/bin/quattro_agent/{name}.py")


if __name__ == "__main__":
    unittest.main()
