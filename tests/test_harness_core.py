from __future__ import annotations

import copy
import contextlib
import json
import os
import pathlib
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))

from quattro_agent.adapters import (  # noqa: E402
    AgentMode,
    CodexAdapter,
    PiAdapter,
    RunSpec,
    adapter_for,
)
from quattro_agent.config import (  # noqa: E402
    ConfigError,
    load_ai_config,
    migrate_ai_config,
    validate_ai_config,
)
from quattro_agent.errors import (  # noqa: E402
    LeaseConflict,
    ProcessIdentityError,
    PolicyEscalationError,
    PrivacyError,
    StateTransitionError,
    WorkflowError,
)
from quattro_agent.delegation import (  # noqa: E402
    compact_pi_json_output,
    decide_delegation,
    ensure_pi_worker_home,
)
from quattro_agent.models import RunState, StepState, TaskState  # noqa: E402
from quattro_agent.policy import (  # noqa: E402
    ApprovalMode,
    MemoryAccess,
    NetworkAccess,
    PolicyProfile,
    policy_profile,
)
from quattro_agent.privacy import display_json  # noqa: E402
from quattro_agent.scheduler import LocalScheduler, SchedulerLimits  # noqa: E402
from quattro_agent.store import TaskStore  # noqa: E402
from quattro_agent.supervisor import (  # noqa: E402
    ProcessIdentity,
    ProcessSupervisor,
    minimal_environment,
    read_process_identity,
    verify_process_identity,
)
from quattro_agent.validators import (  # noqa: E402
    ValidationResult,
    ValidationStatus,
    aggregate_validation,
)
from quattro_agent.workflow import (  # noqa: E402
    JoinStatus,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowNode,
)


def valid_config(home: pathlib.Path) -> dict:
    account_root = home / ".local/share/quattro-ai/codex/accounts"
    return {
        "schemaVersion": 3,
        "defaultAgent": "codex",
        "defaultCodexAccount": "account-1",
        "defaultPolicyProfile": "workspace-write",
        "fullAccessRequiresConfirmation": True,
        "accounts": [{
            "id": "account-1",
            "alias": "Account 1",
            "codexHome": str(account_root / "account-1"),
            "enabled": True,
        }],
        "usageRefresh": {"enabled": True, "intervalMinutes": 15},
        "crossDeviceSync": {"enabled": False, "directory": None},
        "crashCapture": {"enabled": True, "automaticDiagnosis": False},
        "dictation": {
            "engine": "whisper.cpp",
            "modelPath": "~/.local/share/whisper/model.bin",
            "maxRecordingSeconds": 60,
            "retainAudio": False,
        },
        "memory": {
            "enabled": True,
            "vaultPath": "~/.local/share/quattro/memory/shared",
            "projectVaultPath": "~/.local/share/quattro/memory/projects",
            "enforceOnLaunch": True,
        },
        "prReview": {
            "runtime": "codex",
            "codexAccount": "account-1",
            "githubAccount": None,
            "defaultRepository": None,
            "reviewMode": "comment",
            "automaticPublication": False,
            "maximumDepth": "full",
            "runTests": True,
            "securityScanning": True,
            "commentBehavior": "summary",
            "severityThreshold": "LOW",
            "model": None,
            "timeoutSeconds": 1800,
            "maxFiles": 500,
            "maxDiffBytes": 5_000_000,
        },
    }


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temporary.name)
        self.config = valid_config(self.home)

    def tearDown(self):
        self.temporary.cleanup()

    def test_strict_current_config_validation(self):
        validated = validate_ai_config(self.config, home=self.home)
        self.assertEqual(validated["defaultAgent"], "codex")
        self.assertEqual(validated["delegation"], {"enabled": True, "maxWorkers": 3})
        self.assertEqual(validated["cooperation"]["globalLimit"], 5)
        self.assertEqual(validated["cooperation"]["perRepositoryLimit"], 3)
        self.assertEqual(validated["cooperation"], {"globalLimit": 5, "perRepositoryLimit": 3})
        self.assertEqual(validated["workspace"], {"projectRoot": "~/Projects"})
        self.assertIsNot(validated, self.config)

    def test_workspace_project_root_is_structured_and_safe(self):
        explicit = copy.deepcopy(self.config)
        explicit["workspace"] = {"projectRoot": "/srv/projects"}
        self.assertEqual(
            validate_ai_config(explicit, home=self.home)["workspace"]["projectRoot"],
            "/srv/projects",
        )
        unsafe = copy.deepcopy(self.config)
        unsafe["workspace"] = {"projectRoot": "/"}
        with self.assertRaises(ConfigError):
            validate_ai_config(unsafe, home=self.home)
        relative = copy.deepcopy(self.config)
        relative["workspace"] = {"projectRoot": "Projects"}
        with self.assertRaises(ConfigError):
            validate_ai_config(relative, home=self.home)

    def test_cooperation_limits_and_worktree_root_are_strict(self):
        explicit = copy.deepcopy(self.config)
        explicit["cooperation"] = {
            "globalLimit": 7,
            "perRepositoryLimit": 2,
        }
        validated = validate_ai_config(explicit, home=self.home)["cooperation"]
        self.assertEqual((validated["globalLimit"], validated["perRepositoryLimit"]), (7, 2))
        invalid = copy.deepcopy(explicit)
        invalid["cooperation"]["perRepositoryLimit"] = 8
        with self.assertRaises(ConfigError):
            validate_ai_config(invalid, home=self.home)
        invalid = copy.deepcopy(explicit)
        invalid["cooperation"]["globalLimit"] = 0
        with self.assertRaises(ConfigError):
            validate_ai_config(invalid, home=self.home)

    def test_normal_routing_efforts_are_quattro_owned(self):
        validated = validate_ai_config(self.config, home=self.home)
        self.assertEqual(validated["routing"]["fastReasoningEffort"], "low")
        self.assertEqual(validated["routing"]["standardReasoningEffort"], "medium")
        self.assertEqual(validated["routing"]["reasoningReasoningEffort"], "high")
        invalid = copy.deepcopy(validated)
        invalid["routing"]["fastReasoningEffort"] = "xhigh"
        with self.assertRaisesRegex(ConfigError, "Quattro owns normal task effort"):
            validate_ai_config(invalid, home=self.home)


class DelegationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temporary.name)
        self.config = valid_config(self.home)

    def tearDown(self):
        self.temporary.cleanup()

    def test_simple_work_stays_with_codex(self):
        decision = decide_delegation("Fix a one-line typo in README", "implementation")
        self.assertFalse(decision.delegate)
        self.assertEqual(decision.reason, "simple_direct_task")

    def test_bounded_repository_exploration_delegates(self):
        decision = decide_delegation(
            "Explore the repository and locate the session recovery implementation",
            "exploration",
        )
        self.assertTrue(decision.delegate)

    def test_worker_home_is_credential_free_and_uses_omniroute_auto(self):
        with tempfile.TemporaryDirectory() as directory:
            home = ensure_pi_worker_home(pathlib.Path(directory) / "worker")
            models = json.loads((home / "models.json").read_text(encoding="utf-8"))
            provider = models["providers"]["omniroute"]
            self.assertEqual(provider["baseUrl"], "http://localhost:20128/api/v1")
            self.assertEqual(provider["models"][0]["id"], "auto")
            self.assertFalse((home / "auth.json").exists())

    def test_pi_json_is_compacted_with_usage(self):
        payload = json.dumps({
            "type": "message_end",
            "message": {
                "role": "assistant",
                "provider": "omniroute",
                "model": "auto",
                "content": [{"type": "text", "text": "focused finding"}],
                "usage": {"input": 21, "output": 8, "totalTokens": 29},
            },
        })
        result, usage = compact_pi_json_output(payload)
        self.assertIn("STATUS", result)
        self.assertIn("focused finding", result)
        self.assertEqual(usage["provider"], "omniroute")
        self.assertEqual(usage["totalTokens"], 29)

    def test_unknown_fields_and_non_boolean_flags_are_rejected(self):
        unknown = copy.deepcopy(self.config)
        unknown["apiToken"] = "do-not-store"
        with self.assertRaises(ConfigError):
            validate_ai_config(unknown, home=self.home)
        bad_boolean = copy.deepcopy(self.config)
        bad_boolean["fullAccessRequiresConfirmation"] = "yes"
        with self.assertRaises(ConfigError):
            validate_ai_config(bad_boolean, home=self.home)

    def test_default_policy_is_strict_and_full_access_cannot_be_a_default(self):
        unsafe = copy.deepcopy(self.config)
        unsafe["defaultPolicyProfile"] = "full-access-explicit"
        with self.assertRaises(ConfigError):
            validate_ai_config(unsafe, home=self.home)
        no_confirmation = copy.deepcopy(self.config)
        no_confirmation["fullAccessRequiresConfirmation"] = False
        with self.assertRaises(ConfigError):
            validate_ai_config(no_confirmation, home=self.home)

    def test_duplicate_and_disabled_default_accounts_are_rejected(self):
        duplicate = copy.deepcopy(self.config)
        duplicate["accounts"].append(copy.deepcopy(duplicate["accounts"][0]))
        with self.assertRaises(ConfigError):
            validate_ai_config(duplicate, home=self.home)
        disabled = copy.deepcopy(self.config)
        disabled["accounts"][0]["enabled"] = False
        with self.assertRaises(ConfigError):
            validate_ai_config(disabled, home=self.home)

    def test_account_homes_cannot_escape_the_isolated_root(self):
        unsafe = copy.deepcopy(self.config)
        unsafe["accounts"][0]["codexHome"] = str(self.home / "elsewhere")
        with self.assertRaises(ConfigError):
            validate_ai_config(unsafe, home=self.home)

    def test_v1_migration_is_copy_on_write_and_strictly_validates(self):
        version_one = copy.deepcopy(self.config)
        version_one["schemaVersion"] = 1
        del version_one["prReview"]
        del version_one["memory"]["projectVaultPath"]
        original = copy.deepcopy(version_one)
        migrated = migrate_ai_config(version_one)
        self.assertEqual(version_one, original)
        self.assertEqual(migrated["schemaVersion"], 3)
        self.assertIn("projectVaultPath", migrated["memory"])
        self.assertIn("prReview", migrated)
        validate_ai_config(migrated, home=self.home)

    def test_v2_full_access_migrates_to_safe_task_policy_with_deprecated_history(self):
        version_two = copy.deepcopy(self.config)
        version_two["schemaVersion"] = 2
        version_two["codexFullAccess"] = True
        del version_two["defaultPolicyProfile"]
        del version_two["fullAccessRequiresConfirmation"]
        migrated = migrate_ai_config(version_two)
        self.assertEqual(migrated["schemaVersion"], 3)
        self.assertEqual(migrated["defaultPolicyProfile"], "workspace-write")
        self.assertTrue(migrated["fullAccessRequiresConfirmation"])
        self.assertNotIn("codexFullAccess", migrated)
        self.assertEqual(migrated["deprecated"]["legacyCodexFullAccess"], {
            "removed": True,
            "previouslyEnabled": True,
        })
        validate_ai_config(migrated, home=self.home)

    def test_loader_detects_duplicate_json_keys_and_weak_permissions(self):
        duplicate_path = self.home / "duplicate.json"
        duplicate_path.write_text('{"schemaVersion":3,"schemaVersion":3}', encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_ai_config(duplicate_path, home=self.home)

        config_path = self.home / "ai.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")
        os.chmod(config_path, 0o644)
        with self.assertRaises(ConfigError):
            load_ai_config(config_path, require_private=True, home=self.home)
        os.chmod(config_path, 0o600)
        self.assertEqual(load_ai_config(config_path, require_private=True, home=self.home)["schemaVersion"], 3)


class PolicyAndPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.project = self.root / "project"
        self.memory = self.root / "memory"
        self.project.mkdir()
        self.memory.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_child_policy_may_reduce_but_never_expand_authority(self):
        parent = policy_profile(
            "workspace-write", project_root=self.project, memory_roots=(self.memory,)
        )
        child = parent.child(
            name="read-only-child",
            writable_roots=(),
            network=NetworkAccess.NONE,
            allowed_tools=frozenset(),
            approval_mode=ApprovalMode.ALWAYS_ASK,
            max_seconds=100,
            max_commands=1,
            memory_access=MemoryAccess.NONE,
        )
        parent.assert_child(child)
        with self.assertRaises(PolicyEscalationError):
            child.child(name="escalated", writable_roots=(str(self.project),))

    def test_child_network_tool_and_external_effect_escalation_is_rejected(self):
        parent = policy_profile("audit-read-only", project_root=self.project)
        with self.assertRaises(PolicyEscalationError):
            parent.assert_child(PolicyProfile(
                name="bad",
                readable_roots=parent.readable_roots,
                network=NetworkAccess.FULL,
                allowed_tools=parent.allowed_tools | {"publish"},
                external_effects=frozenset({"github.comment"}),
            ))

    def test_policy_round_trip_preserves_authority(self):
        profile = policy_profile(
            "full-access-explicit",
            project_root=self.project,
            memory_roots=(self.memory,),
        )
        self.assertEqual(PolicyProfile.from_dict(profile.to_dict()), profile)

    def test_display_json_rejects_private_key_families(self):
        for key in (
            "prompt", "promptText", "response", "environment", "access_token",
            "apiToken", "credentials",
        ):
            with self.subTest(key=key), self.assertRaises(PrivacyError):
                display_json({key: "private"})
        self.assertEqual(display_json({"state": "running", "progress": 3}),
                         '{"progress":3,"state":"running"}')


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.store = TaskStore(self.root / "state" / "harness.db")
        self.policy = policy_profile("workspace-write", project_root=self.project)

    def tearDown(self):
        self.temporary.cleanup()

    def task(self, **overrides) -> str:
        values = {
            "workflow": "general",
            "agent": "codex",
            "project_path": self.project,
            "display_title": "Safe task",
            "policy": self.policy,
        }
        values.update(overrides)
        return self.store.create_task(**values)


class TaskStoreTests(StoreTestCase):
    def test_v1_step_schema_migrates_atomically_with_existing_rows(self):
        task_id = self.task()
        run_id = self.store.create_run(task_id)
        step_id = self.store.create_step(task_id, "Tests", position=0, run_id=run_id)
        with contextlib.closing(sqlite3.connect(self.store.path, isolation_level=None)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE steps RENAME TO steps_v2")
            connection.execute("""CREATE TABLE steps (
                step_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                run_id TEXT REFERENCES runs(run_id) ON DELETE SET NULL,
                name TEXT NOT NULL, position INTEGER NOT NULL, state TEXT NOT NULL,
                display_metadata_json TEXT NOT NULL, private_payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(task_id, name)
            )""")
            connection.execute("INSERT INTO steps SELECT * FROM steps_v2")
            connection.execute("DROP TABLE steps_v2")
            connection.execute("UPDATE schema_meta SET value='1' WHERE key='schema_version'")
            connection.commit()
        migrated = TaskStore(self.store.path)
        with contextlib.closing(sqlite3.connect(migrated.path)) as connection:
            self.assertEqual(
                connection.execute("SELECT step_id FROM steps").fetchone()[0], step_id
            )
            self.assertEqual(
                connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0],
                "2",
            )
        run_two = migrated.create_run(task_id)
        migrated.create_step(task_id, "Tests", position=1, run_id=run_two)

    def test_database_is_private_wal_and_contains_all_core_tables(self):
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        with contextlib.closing(sqlite3.connect(self.store.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertTrue({
            "tasks", "runs", "steps", "events", "artifacts", "approvals", "leases",
            "external_effects", "task_dependencies",
            "logical_sessions", "task_logical_sessions", "session_checkpoints",
            "physical_sessions", "session_recoveries",
        }.issubset(tables))

    def test_task_transitions_are_enforced_and_terminal_history_is_retained(self):
        task_id = self.task()
        self.store.transition_task(task_id, TaskState.QUEUED)
        self.store.transition_task(task_id, TaskState.RUNNING)
        self.store.transition_task(task_id, TaskState.VALIDATING_RESULT)
        self.store.transition_task(task_id, TaskState.SUCCEEDED, terminal_code="ok")
        with self.assertRaises(StateTransitionError):
            self.store.transition_task(task_id, TaskState.RUNNING)
        task = self.store.display_task(task_id)
        self.assertEqual(task["state"], "succeeded")
        self.assertIsNotNone(task["completedAt"])
        self.assertGreaterEqual(len(self.store.display_events(task_id)), 5)

    def test_compare_and_transition_prevents_concurrent_double_start(self):
        task_id = self.task()
        self.store.transition_task(task_id, TaskState.QUEUED)

        def start() -> str:
            try:
                self.store.transition_task(task_id, TaskState.RUNNING, expected=TaskState.QUEUED)
                return "started"
            except StateTransitionError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: start(), range(2)))
        self.assertEqual(sorted(results), ["rejected", "started"])

    def test_display_projection_never_contains_private_payloads(self):
        task_id = self.task(
            private_payload={"prompt": "private task", "environment": {"TOKEN": "private"}},
            display_metadata={"phase": "queued"},
        )
        private = self.store.get_task(task_id, include_private=True)
        self.assertIn("prompt", private["private_payload"])
        projection = json.dumps(self.store.display_task(task_id), sort_keys=True)
        self.assertNotIn("private task", projection)
        self.assertNotIn("TOKEN", projection)
        self.assertNotIn("private_payload", projection)

    def test_failed_display_serialization_rolls_back_the_whole_task(self):
        with self.assertRaises(PrivacyError):
            self.task(display_metadata={"promptText": "must remain private"})
        self.assertEqual(self.store.list_display_tasks(), [])

    def test_runs_steps_artifacts_and_approvals_are_transactional(self):
        task_id = self.task()
        run_one = self.store.create_run(task_id)
        run_two = self.store.create_run(task_id)
        self.assertEqual(self.store.get_run(run_one)["attempt"], 1)
        self.assertEqual(self.store.get_run(run_two)["attempt"], 2)
        self.store.transition_run(run_one, RunState.STARTING)
        self.store.transition_run(
            run_one,
            RunState.FAILED,
            exit_code=2,
            error_code="test",
            private_result={"response": "private output"},
        )
        displayed_run = json.dumps(self.store.display_run(run_one), sort_keys=True)
        self.assertNotIn("private output", displayed_run)
        self.assertNotIn("private_result", displayed_run)

        step = self.store.create_step(task_id, "unit tests", position=1, run_id=run_two)
        self.store.transition_step(step, StepState.RUNNING)
        self.store.transition_step(step, StepState.PASSED)

        artifact_file = self.root / "artifact.txt"
        artifact_file.write_text("evidence", encoding="utf-8")
        artifact = self.store.add_artifact(
            task_id, kind="report", path=artifact_file, display_name="Report", calculate_hash=True
        )
        self.assertTrue(artifact.startswith("artifact_"))

        approval = self.store.request_approval(
            task_id, scope="publish", confirmation_summary="Publish one review"
        )
        self.assertEqual(self.store.resolve_approval(approval, True), "approved")
        with self.assertRaises(StateTransitionError):
            self.store.resolve_approval(approval, True)

    def test_expired_approval_is_projected_non_actionable(self):
        task_id = self.task()
        approval = self.store.request_approval(
            task_id,
            scope="publish",
            confirmation_summary="Expired publication",
            expires_at="2000-01-01T00:00:00+00:00",
        )
        projected = self.store.display_approval(approval)
        self.assertFalse(projected["capabilities"]["approve"])
        self.assertFalse(projected["capabilities"]["reject"])

    def test_event_and_step_bindings_have_exact_nonduplicated_values(self):
        task_id = self.task()
        run_id = self.store.create_run(task_id)
        step_id = self.store.create_step(
            task_id,
            "evidence gate",
            position=7,
            run_id=run_id,
            display_metadata={"validator": "unit"},
            private_payload={"prompt": "not displayed"},
        )
        self.store.append_event(
            task_id,
            "custom.checked",
            run_id=run_id,
            display={"stepId": step_id, "status": "Passed"},
            private={"response": "not displayed"},
        )
        with contextlib.closing(sqlite3.connect(self.store.path)) as connection:
            connection.row_factory = sqlite3.Row
            step = connection.execute(
                "SELECT * FROM steps WHERE step_id = ?", (step_id,)
            ).fetchone()
            custom = connection.execute(
                "SELECT * FROM events WHERE task_id = ? AND event_type = 'custom.checked'",
                (task_id,),
            ).fetchone()
        self.assertEqual((step["step_id"], step["task_id"], step["run_id"]),
                         (step_id, task_id, run_id))
        self.assertEqual(step["position"], 7)
        self.assertEqual((custom["task_id"], custom["run_id"]), (task_id, run_id))
        projected = self.store.display_events(task_id)
        self.assertNotIn("not displayed", json.dumps(projected))

    def test_external_effect_idempotency_prevents_duplicate_publication(self):
        task_id = self.task()
        first = self.store.record_external_effect_intent(
            task_id,
            idempotency_key="owner/repo#1:head-sha:policy-v1",
            provider="github",
            effect_type="review",
            display_summary="Publish review for one commit",
        )
        second = self.store.record_external_effect_intent(
            task_id,
            idempotency_key="owner/repo#1:head-sha:policy-v1",
            provider="github",
            effect_type="review",
            display_summary="Publish review for one commit",
        )
        self.assertEqual(first["effect_id"], second["effect_id"])
        self.assertEqual(
            self.store.complete_external_effect(
                "owner/repo#1:head-sha:policy-v1", external_id="comment-42"
            ),
            "completed",
        )
        self.assertEqual(
            self.store.complete_external_effect(
                "owner/repo#1:head-sha:policy-v1", external_id="comment-42"
            ),
            "completed",
        )

    def test_failed_external_effect_can_reenter_intent_and_complete(self):
        task_id = self.task()
        key = "owner/repo#2:head-sha:policy-v1"
        self.store.record_external_effect_intent(
            task_id, idempotency_key=key, provider="github",
            effect_type="review", display_summary="Publish review",
        )
        self.store.complete_external_effect(key, failed=True)
        self.assertEqual(self.store.retry_external_effect(key), "intent")
        self.assertEqual(
            self.store.complete_external_effect(key, external_id="review-2"),
            "completed",
        )

    def test_dependency_cycles_are_rejected(self):
        first, second, third = self.task(), self.task(), self.task()
        self.store.add_dependency(second, first)
        self.store.add_dependency(third, second)
        with self.assertRaises(WorkflowError):
            self.store.add_dependency(first, third)

    def test_concurrent_task_creation_does_not_lose_rows(self):
        def create(index: int) -> str:
            return self.task(display_title=f"Task {index}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            identifiers = list(executor.map(create, range(30)))
        self.assertEqual(len(set(identifiers)), 30)
        self.assertEqual(len(self.store.list_display_tasks(limit=100)), 30)


class SchedulerTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.scheduler = LocalScheduler(
            self.store,
            SchedulerLimits(max_total=2, per_agent={"codex": 2, "pi": 1}, per_account=1,
                            per_repository=2,
                            lease_ttl_seconds=1),
        )

    def _run(self, agent: str = "codex") -> tuple[str, str]:
        task_id = self.task(agent=agent)
        run_id = self.store.create_run(task_id, agent=agent)
        return task_id, run_id

    def test_account_and_project_write_limits_are_enforced_and_released(self):
        first_task, first_run = self._run()
        first = self.scheduler.try_acquire(
            task_id=first_task, run_id=first_run, agent="codex", account_id="account-1",
            project_path=self.project,
        )
        second_task, second_run = self._run()
        with self.assertRaises(LeaseConflict):
            self.scheduler.try_acquire(
                task_id=second_task, run_id=second_run, agent="codex", account_id="account-1",
                project_path=self.project,
            )
        self.assertGreater(self.scheduler.release(first), 0)
        self.scheduler.try_acquire(
            task_id=second_task, run_id=second_run, agent="codex", account_id="account-1",
            project_path=self.project,
        )

    def test_two_top_level_tasks_can_share_repository_with_separate_slots(self):
        first_task, first_run = self._run()
        second_task, second_run = self._run()
        self.scheduler.try_acquire(
            task_id=first_task, run_id=first_run, agent="codex", account_id="account-1",
            project_path=self.project,
        )
        second = self.scheduler.try_acquire(
            task_id=second_task, run_id=second_run, agent="codex", account_id="account-2",
            project_path=self.project,
        )
        self.assertIn("repository:", " ".join(second.resources))

    def test_atomic_concurrent_acquire_allows_repository_capacity(self):
        runs = [self._run() for _ in range(2)]
        barrier = threading.Barrier(2)

        def acquire(item: tuple[int, tuple[str, str]]) -> str:
            index, pair = item
            barrier.wait()
            try:
                self.scheduler.try_acquire(
                    task_id=pair[0], run_id=pair[1], agent="codex",
                    account_id=f"account-{index}", project_path=self.project,
                )
                return "acquired"
            except LeaseConflict:
                return "busy"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(acquire, enumerate(runs)))
        self.assertEqual(sorted(results), ["acquired", "acquired"])

    def test_five_distinct_projects_are_allowed_and_sixth_is_blocked(self):
        scheduler = LocalScheduler(
            self.store,
            SchedulerLimits(
                max_total=5, per_agent={"codex": 5, "pi": 5}, per_account=5,
                per_repository=3,
                lease_ttl_seconds=1,
            ),
        )
        leases = []
        for index in range(5):
            project = self.root / f"project-{index}"
            project.mkdir()
            task_id, run_id = self._run()
            leases.append(scheduler.try_acquire(
                task_id=task_id, run_id=run_id, agent="codex",
                account_id="account-1", project_path=project,
            ))
        sixth = self.root / "project-5"
        sixth.mkdir()
        task_id, run_id = self._run()
        with self.assertRaises(LeaseConflict):
            scheduler.try_acquire(
                task_id=task_id, run_id=run_id, agent="codex",
                account_id="account-1", project_path=sixth,
            )
        for lease in leases:
            scheduler.release(lease)

    def test_three_same_repository_slots_are_allowed_and_fourth_is_blocked(self):
        scheduler = LocalScheduler(
            self.store,
            SchedulerLimits(
                max_total=5, per_agent={"codex": 5, "pi": 5}, per_account=5,
                per_repository=3, lease_ttl_seconds=1,
            ),
        )
        leases = []
        for _index in range(3):
            task_id, run_id = self._run()
            leases.append(scheduler.try_acquire(
                task_id=task_id, run_id=run_id, agent="codex",
                account_id="account-1", project_path=self.project,
            ))
        task_id, run_id = self._run()
        with self.assertRaises(LeaseConflict):
            scheduler.try_acquire(
                task_id=task_id, run_id=run_id, agent="codex",
                account_id="account-1", project_path=self.project,
            )
        for lease in leases:
            scheduler.release(lease)

    def test_subdirectories_of_one_git_repository_share_repository_slot_group(self):
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        nested = self.project / "packages/app"
        nested.mkdir(parents=True)
        first_task, first_run = self._run()
        self.scheduler.try_acquire(
            task_id=first_task, run_id=first_run, agent="codex",
            account_id="account-1", project_path=self.project,
        )
        second_task, second_run = self._run()
        second = self.scheduler.try_acquire(
            task_id=second_task, run_id=second_run, agent="codex",
            account_id="account-2", project_path=nested,
        )
        self.assertEqual(
            self.scheduler.project_resource(self.project),
            self.scheduler.project_resource(nested),
        )
        self.assertTrue(any(item.startswith("repository:") for item in second.resources))

    def test_preexisting_task_without_lease_does_not_consume_atomic_capacity(self):
        first_task, _first_run = self._run()
        self.store.transition_task(first_task, TaskState.QUEUED)
        self.store.transition_task(first_task, TaskState.READY)
        self.store.transition_task(first_task, TaskState.RUNNING)
        second_task, second_run = self._run()
        lease = self.scheduler.try_acquire(
            task_id=second_task, run_id=second_run, agent="codex",
            account_id="account-2", project_path=self.project,
        )
        self.assertTrue(lease.resources)

    def test_stale_cancelling_task_with_terminal_run_does_not_block_project(self):
        first_task, first_run = self._run()
        self.store.transition_task(first_task, TaskState.QUEUED)
        self.store.transition_task(first_task, TaskState.READY)
        self.store.transition_task(first_task, TaskState.RUNNING)
        self.store.transition_run(first_run, RunState.STARTING)
        self.store.transition_run(first_run, RunState.RUNNING)
        self.store.transition_run(first_run, RunState.SUCCEEDED, exit_code=0)
        self.store.transition_task(first_task, TaskState.VALIDATING_RESULT)
        self.store.transition_task(first_task, TaskState.CANCELLING)

        second_task, second_run = self._run()
        lease = self.scheduler.try_acquire(
            task_id=second_task, run_id=second_run, agent="codex",
            account_id="account-2", project_path=self.project,
        )
        self.assertTrue(any(
            item.startswith(self.scheduler.project_resource(self.project) + ":")
            for item in lease.resources
        ))


class WorkflowTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.engine = WorkflowEngine(self.store)
        self.parent = self.task(display_title="Parent")
        self.store.transition_task(self.parent, TaskState.QUEUED)
        self.store.transition_task(self.parent, TaskState.READY)
        self.store.transition_task(self.parent, TaskState.WAITING_ON_CHILDREN)
        self.child_policy = self.policy.child(
            name="child",
            writable_roots=(),
            network=NetworkAccess.NONE,
            allowed_tools=frozenset(),
            approval_mode=ApprovalMode.ALWAYS_ASK,
            max_seconds=100,
            max_commands=1,
            memory_access=MemoryAccess.NONE,
        )

    def test_workflow_definition_rejects_cycles_and_unknown_agents(self):
        one = WorkflowNode("one", "One", "codex", self.child_policy, ("two",))
        two = WorkflowNode("two", "Two", "pi", self.child_policy, ("one",))
        with self.assertRaises(WorkflowError):
            WorkflowDefinition("cycle", (one, two)).validate()
        with self.assertRaises(WorkflowError):
            WorkflowNode("bad", "Bad", "other", self.child_policy)

    def test_dag_instantiation_readiness_and_join(self):
        definition = WorkflowDefinition("implementation-review", (
            WorkflowNode("inventory", "Inventory", "codex", self.child_policy),
            WorkflowNode("review", "Review", "pi", self.child_policy, ("inventory",)),
        ))
        children = self.engine.instantiate(definition, parent_task_id=self.parent)
        self.assertEqual(self.engine.queue_ready_children(self.parent), (children["inventory"],))
        self.store.transition_task(children["inventory"], TaskState.RUNNING)
        self.store.transition_task(children["inventory"], TaskState.SUCCEEDED)
        self.assertEqual(self.engine.queue_ready_children(self.parent), (children["review"],))
        self.assertEqual(self.engine.join_children(self.parent).status, JoinStatus.WAITING)
        self.store.transition_task(children["review"], TaskState.RUNNING)
        self.store.transition_task(children["review"], TaskState.SUCCEEDED)
        result = self.engine.join_children(self.parent)
        self.assertEqual(result.status, JoinStatus.READY_TO_VALIDATE)
        self.assertEqual(self.store.display_task(self.parent)["state"], "validating_result")

    def test_child_policy_escalation_is_rejected_by_store(self):
        elevated = policy_profile("full-access-explicit", project_root=self.project)
        with self.assertRaises(PolicyEscalationError):
            self.engine.spawn_child(
                self.parent, workflow="bad", agent="codex", title="Bad", policy=elevated
            )

    def test_failed_child_blocks_join(self):
        child = self.engine.spawn_child(
            self.parent, workflow="review", agent="pi", title="Reviewer",
            policy=self.child_policy,
        )
        self.store.transition_task(child, TaskState.QUEUED)
        self.store.transition_task(child, TaskState.RUNNING)
        self.store.transition_task(child, TaskState.FAILED, terminal_code="review_failed")
        result = self.engine.join_children(self.parent)
        self.assertEqual(result.status, JoinStatus.BLOCKED)
        self.assertEqual(result.failed_task_ids, (child,))


class ValidatorAndAdapterTests(StoreTestCase):
    def test_validation_aggregation_is_failure_and_blocker_aware(self):
        passed = ValidationResult("pytest", ValidationStatus.PASSED, "All tests passed")
        not_run = ValidationResult("runtime", ValidationStatus.NOT_RUN, "No desktop change")
        failed = ValidationResult("lint", ValidationStatus.FAILED, "Lint failed")
        self.assertEqual(aggregate_validation((passed,)).status, ValidationStatus.PASSED)
        self.assertEqual(aggregate_validation((passed, not_run)).status, ValidationStatus.BLOCKED)
        self.assertEqual(aggregate_validation((passed, failed)).status, ValidationStatus.FAILED)
        self.assertEqual(aggregate_validation(()).status, ValidationStatus.NOT_RUN)

    def test_only_codex_and_pi_adapters_exist(self):
        self.assertIsInstance(adapter_for("codex"), CodexAdapter)
        self.assertIsInstance(adapter_for("pi"), PiAdapter)
        with self.assertRaises(ValueError):
            adapter_for("other")

    def test_codex_launch_plan_keeps_input_and_environment_values_private(self):
        spec = RunSpec(
            task_id="task", run_id="run", project_path=self.project,
            mode=AgentMode.PROMPT, policy=self.policy,
            account_id="account-1", account_home=self.root / "account",
            private_input="sensitive objective",
        )
        plan = CodexAdapter().build_launch("/usr/bin/codex", spec)
        self.assertEqual(plan.stdin_text, "sensitive objective\n")
        display = json.dumps(plan.display_dict(), sort_keys=True)
        self.assertNotIn("sensitive objective", display)
        self.assertNotIn(str(self.root / "account"), display)
        self.assertNotIn("CODEX_HOME", display)
        self.assertEqual(plan.display_dict()["overrideCount"], 1)
        self.assertIn("-s", plan.argv)
        self.assertEqual(plan.argv[plan.argv.index("-s") + 1], "workspace-write")

    def test_codex_resume_targets_exact_native_session(self):
        spec = RunSpec(
            task_id="task", run_id="run", project_path=self.project,
            mode=AgentMode.RESUME, policy=self.policy,
            account_id="account-2", account_home=self.root / "account",
            native_session_ref="00000000-0000-0000-0000-000000000002",
        )
        plan = CodexAdapter().build_launch("/usr/bin/codex", spec)
        self.assertIn("00000000-0000-0000-0000-000000000002", plan.argv)
        self.assertNotIn("--all", plan.argv)

    def test_pi_declares_harness_containment_requirement(self):
        self.assertTrue(PiAdapter().capabilities.requires_harness_containment)
        spec = RunSpec(
            task_id="task", run_id="run", project_path=self.project,
            mode=AgentMode.RESUME, policy=self.policy,
        )
        with self.assertRaisesRegex(ValueError, "cannot enforce full network access"):
            PiAdapter().build_launch("/usr/bin/pi", spec)

    def test_only_delegated_pi_uses_worker_omniroute_route(self):
        read_only = policy_profile("audit-read-only", project_root=self.project)
        direct = PiAdapter().build_launch("/usr/bin/pi", RunSpec(
            task_id="direct", run_id="run-direct", project_path=self.project,
            mode=AgentMode.PROMPT, policy=read_only, private_input="direct",
        ))
        delegated = PiAdapter().build_launch("/usr/bin/pi", RunSpec(
            task_id="child", run_id="run-child", project_path=self.project,
            mode=AgentMode.PROMPT, policy=read_only, private_input="bounded",
            delegated_worker=True,
        ))
        self.assertNotIn("--provider", direct.argv)
        self.assertIn("--no-tools", direct.argv)
        self.assertEqual(delegated.argv[delegated.argv.index("--provider") + 1], "omniroute")
        self.assertEqual(delegated.argv[delegated.argv.index("--model") + 1], "auto")
        self.assertIn("read,grep,find,ls", delegated.argv)
        self.assertNotIn("bash", delegated.argv)


class SupervisorTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.supervisor = ProcessSupervisor(
            self.store,
            heartbeat_interval=0.02,
            lease_ttl_seconds=1,
            termination_grace_seconds=0.05,
        )

    def prepared_run(self) -> tuple[str, str]:
        task_id = self.task()
        run_id = self.store.create_run(task_id)
        return task_id, run_id

    def test_minimal_environment_does_not_inherit_arbitrary_secrets(self):
        with mock.patch.dict(os.environ, {
            "QUATTRO_TEST_SECRET": "hidden",
            "PATH": os.environ["PATH"],
            "WAYLAND_DISPLAY": "wayland-1",
            "DISPLAY": ":1",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        }):
            environment = minimal_environment({"CODEX_HOME": "/tmp/account"})
        self.assertNotIn("QUATTRO_TEST_SECRET", environment)
        self.assertEqual(environment["CODEX_HOME"], "/tmp/account")
        self.assertEqual(environment["WAYLAND_DISPLAY"], "wayland-1")
        self.assertEqual(environment["DISPLAY"], ":1")
        self.assertEqual(
            environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus"
        )

    def test_process_success_records_identity_heartbeats_and_outcome(self):
        task_id, run_id = self.prepared_run()
        managed = self.supervisor.start(
            task_id=task_id,
            run_id=run_id,
            argv=(sys.executable, "-c", "import time; time.sleep(0.08)"),
            cwd=self.project,
            deadline_seconds=1,
        )
        self.assertTrue(verify_process_identity(managed.identity))
        result = self.supervisor.wait(managed)
        self.assertEqual(result.state, RunState.SUCCEEDED)
        run = self.store.get_run(run_id)
        self.assertEqual(run["state"], "succeeded")
        self.assertEqual(run["exit_code"], 0)
        self.assertIsNotNone(run["heartbeat_at"])

    def test_short_lived_process_exit_before_proc_identity_is_recorded(self):
        task_id, run_id = self.prepared_run()

        class AlreadyExited:
            pid = 12345
            returncode = 0

            def poll(self):
                return self.returncode

        with mock.patch(
            "quattro_agent.supervisor.subprocess.Popen", return_value=AlreadyExited()
        ), mock.patch(
            "quattro_agent.supervisor.read_process_identity",
            side_effect=ProcessIdentityError("process exited"),
        ):
            managed = self.supervisor.start(
                task_id=task_id,
                run_id=run_id,
                argv=(sys.executable, "-c", "pass"),
                cwd=self.project,
            )
        self.assertEqual(managed.identity.start_ticks, -1)
        self.assertEqual(managed.identity.process_group, -1)

    def test_deadline_terminates_the_process_group(self):
        task_id, run_id = self.prepared_run()
        managed = self.supervisor.start(
            task_id=task_id,
            run_id=run_id,
            argv=(sys.executable, "-c", "import time; time.sleep(10)"),
            cwd=self.project,
            deadline_seconds=0.08,
        )
        result = self.supervisor.wait(managed)
        self.assertEqual(result.state, RunState.TIMED_OUT)
        self.assertIsNotNone(managed.process.returncode)
        self.assertFalse(verify_process_identity(managed.identity))

    def test_cancellation_escalates_and_records_cancelled(self):
        task_id, run_id = self.prepared_run()
        managed = self.supervisor.start(
            task_id=task_id,
            run_id=run_id,
            argv=(sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, lambda *_: None); time.sleep(10)"),
            cwd=self.project,
            deadline_seconds=2,
        )
        cancellation = threading.Event()
        threading.Timer(0.08, cancellation.set).start()
        result = self.supervisor.wait(managed, cancellation=cancellation)
        self.assertEqual(result.state, RunState.CANCELLED)
        self.assertEqual(self.store.get_run(run_id)["state"], "cancelled")

    def test_pid_start_time_verification_detects_mismatch(self):
        identity = read_process_identity(os.getpid(), sys.executable)
        wrong = ProcessIdentity(
            identity.pid, identity.start_ticks + 1, identity.process_group,
            identity.expected_executable,
        )
        self.assertFalse(verify_process_identity(wrong))

    def test_stale_missing_worker_is_interrupted_and_leases_released(self):
        task_id, run_id = self.prepared_run()
        self.store.transition_task(task_id, TaskState.QUEUED)
        self.store.transition_task(task_id, TaskState.RUNNING)
        self.store.mark_run_started(
            run_id,
            pid=999_999_999,
            process_start_ticks=1,
            process_group=999_999_999,
            expected_executable=sys.executable,
            deadline_at=None,
        )
        self.store.acquire_lease_set(
            holder_task_id=task_id, holder_run_id=run_id,
            resource_groups=(("global:0",),), ttl_seconds=10,
        )
        time.sleep(0.02)
        recovery = self.supervisor.recover_stale_runs(stale_after_seconds=0.001)
        self.assertEqual(recovery[0].status, "interrupted")
        self.assertEqual(self.store.get_run(run_id)["state"], "interrupted")
        self.assertEqual(self.store.display_task(task_id)["state"], "interrupted")
        self.assertEqual(self.store.leases_for_holder(task_id, run_id), [])

    def test_stale_live_worker_without_supervisor_is_terminated_and_interrupted(self):
        task_id, run_id = self.prepared_run()
        self.store.transition_task(task_id, TaskState.QUEUED)
        self.store.transition_task(task_id, TaskState.RUNNING)
        process = subprocess.Popen(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            cwd=self.project,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            identity = read_process_identity(process.pid, sys.executable)
            self.store.mark_run_started(
                run_id,
                pid=identity.pid,
                process_start_ticks=identity.start_ticks,
                process_group=identity.process_group,
                expected_executable=identity.expected_executable,
                deadline_at=None,
            )
            self.store.acquire_lease_set(
                holder_task_id=task_id,
                holder_run_id=run_id,
                resource_groups=(("global:0",),),
                ttl_seconds=10,
            )
            time.sleep(0.02)
            recovery = self.supervisor.recover_stale_runs(stale_after_seconds=0.001)
            self.assertEqual(recovery[0].status, "interrupted")
            self.assertEqual(self.store.get_run(run_id)["state"], "interrupted")
            self.assertEqual(self.store.display_task(task_id)["state"], "interrupted")
            self.assertEqual(self.store.leases_for_holder(task_id, run_id), [])
        finally:
            try:
                os.killpg(process.pid, 9)
            except ProcessLookupError:
                pass
            process.wait()


if __name__ == "__main__":
    unittest.main()
