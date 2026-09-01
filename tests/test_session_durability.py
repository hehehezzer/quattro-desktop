from __future__ import annotations

import contextlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))

from quattro_agent.errors import LeaseConflict
from quattro_agent.models import RunState, TaskState
from quattro_agent.recovery import checkpoint_payload, recovery_packet, repository_state
from quattro_agent.scheduler import LocalScheduler
from quattro_agent.sessions import update_session_registry
from quattro_agent.store import TaskStore
from quattro_harness import HarnessRuntime


def config_value() -> dict:
    return {
        "schemaVersion": 3,
        "defaultAgent": "codex",
        "defaultCodexAccount": "account-1",
        "defaultPolicyProfile": "workspace-write",
        "fullAccessRequiresConfirmation": True,
        "deprecated": {"legacyCodexFullAccess": {"removed": True, "previouslyEnabled": False}},
        "accounts": [{
            "id": "account-1", "alias": "Account 1",
            "codexHome": "~/.local/share/quattro-ai/codex/accounts/account-1",
            "enabled": True,
        }],
        "usageRefresh": {"enabled": False, "intervalMinutes": 15},
        "crossDeviceSync": {"enabled": False, "directory": None},
        "crashCapture": {"enabled": False, "automaticDiagnosis": False},
        "dictation": {
            "engine": "whisper.cpp", "modelPath": "~/.local/share/whisper/model.bin",
            "maxRecordingSeconds": 60, "retainAudio": False,
        },
        "memory": {
            "enabled": False, "vaultPath": "~/.local/share/quattro/memory/shared",
            "projectVaultPath": "~/.local/share/quattro/memory/projects", "enforceOnLaunch": False,
        },
        "prReview": {
            "runtime": "codex", "codexAccount": "account-1", "githubAccount": None,
            "defaultRepository": None, "reviewMode": "comment",
            "automaticPublication": False, "maximumDepth": "full", "runTests": True,
            "securityScanning": True, "commentBehavior": "summary",
            "severityThreshold": "LOW", "model": None, "timeoutSeconds": 1800,
            "maxFiles": 500, "maxDiffBytes": 5_000_000,
        },
    }


class SessionDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.config = self.root / "ai.json"
        self.config.write_text(json.dumps(config_value()), encoding="utf-8")
        self.config.chmod(0o600)
        self.agent = self.root / "fake-codex"
        self.agent.write_text(
            "#!/bin/sh\n"
            "for arg in \"$@\"; do [ \"$arg\" = resume ] && exit ${FAIL_RESUME:-0}; done\n"
            "printf 'RECOVERY_AGENT_OK\\nHARNESS_VERDICT: PASS\\n'\n",
            encoding="utf-8",
        )
        self.agent.chmod(0o755)

        def resolver(name: str) -> str | None:
            return str(self.agent) if name in {"codex", "pi"} else shutil.which(name)

        self.runtime = HarnessRuntime(
            config_path=self.config,
            state_root=self.root / "state",
            script_path=self.agent,
            default_workspace=self.project,
            command_resolver=resolver,
            codex_preflight=lambda _home: None,
        )

    def tearDown(self):
        self.temp.cleanup()

    def create(self, *, native: str | None = "codex-native-1", prompt: str = "Ship durable checkpoints"):
        task = self.runtime.create_task(
            agent="codex", project=self.project, prompt=prompt,
            mode="interactive", account_id="account-1", native_session_ref=native,
        )
        logical = self.runtime.store.logical_session_for_task(task)
        self.assertIsNotNone(logical)
        return task, logical["quattro_session_id"]

    def test_accepted_intent_is_checkpointed_before_execution_and_read_back(self):
        task, logical = self.create(prompt="Accepted user intent")
        self.assertEqual(self.runtime.store.get_task(task)["state"], "queued")
        self.assertEqual(self.runtime.store.display_task(task)["title"], "Accepted user intent")
        checkpoint = self.runtime.store.current_checkpoint(logical, include_content=True)
        self.assertEqual(checkpoint["kind"], "accepted-intent")
        self.assertEqual(checkpoint["content"]["objective"], "Accepted user intent")
        self.assertEqual(self.runtime.store.runs_for_task(task), [])

    def test_session_projection_uses_secret_safe_first_prompt_title(self):
        task, logical = self.create(
            prompt=(
                "<image name='reference'>\n"
                "Implement the secure lock screen and readable session names "
                "password=must-not-display with regression coverage"
            )
        )
        projected = next(
            row for row in self.runtime.list_logical_sessions()
            if row["quattroSessionId"] == logical
        )
        self.assertTrue(projected["title"].startswith("Implement the secure lock screen"))
        self.assertIn("[REDACTED BY QUATTRO]", projected["title"])
        self.assertNotIn("must-not-display", projected["title"])
        self.assertNotEqual(projected["title"], logical)
        self.assertEqual(self.runtime.store.display_task(task)["title"], projected["title"])

    def test_empty_interactive_prompt_gets_a_readable_project_title(self):
        task, logical = self.create(prompt="")
        self.assertEqual(
            self.runtime.store.display_task(task)["title"],
            "Codex interactive · project",
        )
        projected = next(
            row for row in self.runtime.list_logical_sessions()
            if row["quattroSessionId"] == logical
        )
        self.assertEqual(projected["title"], "Codex interactive · project")

    def test_codex_native_thread_name_supersedes_generic_launcher_title(self):
        _task, logical = self.create(prompt="")
        update_session_registry(
            self.runtime.private_root / "codex-session-registry.json",
            "codex-native-1",
            {"displayTitle": "Add secure lock and readable session names"},
        )
        projected = next(
            row for row in self.runtime.list_logical_sessions()
            if row["quattroSessionId"] == logical
        )
        self.assertEqual(
            projected["title"],
            "Add secure lock and readable session names",
        )

    def test_unique_same_project_launch_time_associates_codex_title(self):
        _task, logical = self.create(native=None, prompt="")
        session = self.runtime.store.get_logical_session(logical)
        update_session_registry(
            self.runtime.private_root / "codex-session-registry.json",
            "codex-native-by-time",
            {
                "displayTitle": "Implement lock precautions and session labels",
                "projectPath": str(self.project),
                "createdAt": session["created_at"],
            },
        )
        projected = next(
            row for row in self.runtime.list_logical_sessions()
            if row["quattroSessionId"] == logical
        )
        self.assertEqual(
            projected["title"],
            "Implement lock precautions and session labels",
        )

    def test_checkpoint_round_trip_and_failed_candidate_preserves_current(self):
        task, logical = self.create()
        first = self.runtime.checkpoint_task(
            task, completed=("schema complete",), next_action="Add tests"
        )
        self.assertEqual(
            self.runtime.store.current_checkpoint(logical, include_content=True)["content"]["nextAction"],
            "Add tests",
        )
        candidate = self.runtime.store.get_checkpoint(first, include_content=True)["content"]
        candidate["relevantArtifacts"] = [{"accessToken": "must-not-persist"}]
        sanitized = self.runtime.store.create_checkpoint(logical, candidate, kind="sanitized")
        sanitized_content = self.runtime.store.get_checkpoint(sanitized, include_content=True)["content"]
        self.assertNotIn("must-not-persist", json.dumps(sanitized_content))
        first = sanitized
        with self.assertRaises(sqlite3.IntegrityError):
            self.runtime.store.create_checkpoint(
                logical, candidate, kind="broken", run_id="missing-run"
            )
        self.assertEqual(self.runtime.store.get_logical_session(logical)["current_checkpoint_id"], first)

    def test_native_resume_first_and_missing_native_falls_back(self):
        task, logical = self.create()
        native_task, path = self.runtime.prepare_resume_task(logical, native_session_available=True)
        self.assertEqual(path, "native-resume")
        native_private = self.runtime.store.get_task(native_task, include_private=True)["private_payload"]
        self.assertEqual(native_private["mode"], "resume")
        self.assertEqual(native_private["nativeSessionRef"], "codex-native-1")
        self.runtime.store.transition_task(native_task, TaskState.CANCELLED)
        recovery_task, path = self.runtime.prepare_resume_task(logical, native_session_available=False)
        self.assertEqual(path, "checkpoint-recovery")
        recovery_private = self.runtime.store.get_task(recovery_task, include_private=True)["private_payload"]
        self.assertEqual(recovery_private["mode"], "interactive")
        self.assertIn("OBJECTIVE", recovery_private["prompt"])

    def test_explicit_native_resume_failure_automatically_recovers_same_logical_session(self):
        _task, logical = self.create()
        resume_task, path = self.runtime.prepare_resume_task(logical, native_session_available=True)
        self.assertEqual(path, "native-resume")
        original = self.runtime._agent_plan

        def failing_plan(task, run_id, profile):
            argv, stdin, overrides = original(task, run_id, profile)
            if task["private_payload"].get("mode") == "resume":
                overrides = {**overrides, "FAIL_RESUME": "7"}
            return argv, stdin, overrides

        self.runtime._agent_plan = failing_plan
        self.assertEqual(self.runtime.run_task(resume_task), 0)
        session = self.runtime.store.get_logical_session(logical)
        self.assertEqual(session["quattro_session_id"], logical)
        self.assertEqual(len(self.runtime.store.recovery_history(logical)), 1)
        self.assertEqual(session["recovery_state"], "recovered")

    def test_forced_recovery_replaces_physical_but_keeps_logical_session(self):
        task, logical = self.create()
        self.assertEqual(self.runtime.run_task(task), 0)
        first = self.runtime.store.latest_physical_session(logical)
        recovery_task = self.runtime.prepare_recovery_task(logical, reason="simulated crash")
        self.assertEqual(self.runtime.run_task(recovery_task), 0)
        second = self.runtime.store.latest_physical_session(logical)
        self.assertNotEqual(first["physical_session_id"], second["physical_session_id"])
        self.assertEqual(second["replacement_for_physical_id"], first["physical_session_id"])
        self.assertEqual(
            self.runtime.store.logical_session_for_task(recovery_task)["quattro_session_id"], logical
        )

    def test_recovery_packet_is_complete_compact_and_secret_safe(self):
        task, logical = self.create(prompt="Continue feature password=do-not-store")
        self.runtime.checkpoint_task(
            task, completed=("storage implemented",),
            important_decisions=("atomic current pointer",),
            validation=("unit tests passed",), unresolved=("CLI test remains",),
            next_action="Run the CLI test",
        )
        packet, _ = self.runtime.recovery_packet_for_session(logical)
        for heading in (
            "OBJECTIVE", "REQUIREMENTS", "COMPLETED", "FILES CHANGED",
            "IMPORTANT DECISIONS", "VALIDATION", "UNRESOLVED", "NEXT ACTION",
            "REPOSITORY STATE",
        ):
            self.assertIn(heading, packet)
        self.assertNotIn("do-not-store", packet)
        self.assertIn("[REDACTED BY QUATTRO]", packet)
        self.assertLess(len(packet.encode()), 100_000)
        self.assertNotIn("institutional-memory context", packet)
        self.assertNotIn("spawn subagent", packet.lower())

    def test_logical_writer_lease_is_exclusive_and_stale_lease_recovers(self):
        first_task, logical = self.create()
        second_task = self.runtime.create_task(
            agent="codex", project=self.project, prompt="second", mode="interactive",
            logical_session_id=logical, account_id="account-1",
        )
        first_run = self.runtime.store.claim_task_for_run(first_task, account_id="account-1")
        second_run = self.runtime.store.claim_task_for_run(second_task, account_id="account-1")
        resource = self.runtime.scheduler.logical_session_resource(logical)

        def acquire(task_id, run_id):
            try:
                self.runtime.store.acquire_lease_set(
                    holder_task_id=task_id, holder_run_id=run_id,
                    resource_groups=(), fixed_resources=(resource,), ttl_seconds=0.05,
                    kind="logical-session-writer",
                )
                return "acquired"
            except LeaseConflict:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda args: acquire(*args), (
                (first_task, first_run), (second_task, second_run),
            )))
        self.assertEqual(sorted(outcomes), ["acquired", "rejected"])
        threading.Event().wait(0.08)
        self.assertEqual(self.runtime.store.purge_expired_leases(), 1)
        winner = second_task if outcomes[0] == "acquired" else first_task
        winner_run = second_run if winner == second_task else first_run
        self.assertEqual(acquire(winner, winner_run), "acquired")

    def test_restart_reconciliation_keeps_crashed_session_recoverable(self):
        task, logical = self.create()
        run = self.runtime.store.claim_task_for_run(task, account_id="account-1")
        self.runtime.store.transition_task(task, TaskState.RUNNING, expected=TaskState.READY)
        self.runtime.store.transition_run(run, RunState.STARTING)
        self.runtime.store.mark_run_started(
            run, pid=999_999_999, process_start_ticks=1, process_group=999_999_999,
            expected_executable=str(self.agent), deadline_at=None,
        )
        physical = self.runtime.store.record_physical_session(
            logical, task_id=task, run_id=run, account_id="account-1",
            provider_id="omniroute", native_codex_session_id="missing-native",
        )
        with contextlib.closing(sqlite3.connect(self.runtime.store.path)) as connection:
            connection.execute("UPDATE runs SET heartbeat_at='2000-01-01T00:00:00+00:00' WHERE run_id=?", (run,))
            connection.commit()
        restarted = HarnessRuntime(
            config_path=self.config, state_root=self.root / "state",
            script_path=self.agent, default_workspace=self.project,
            command_resolver=lambda name: str(self.agent) if name in {"codex", "pi"} else shutil.which(name),
            codex_preflight=lambda _home: None,
        )
        results = restarted.reconcile()
        self.assertTrue(any(item.get("quattro_session_id") == logical for item in results))
        session = restarted.store.get_logical_session(logical)
        self.assertEqual(session["recovery_state"], "recoverable")
        self.assertEqual(restarted.store.latest_physical_session(logical)["health"], "failed")
        self.assertTrue(any(item["quattroSessionId"] == logical for item in restarted.list_logical_sessions()))

    def test_manual_checkpoint_does_not_terminate_active_task_and_survives_restart(self):
        task, logical = self.create()
        self.runtime.store.transition_task(task, TaskState.RUNNING, expected=TaskState.QUEUED)
        checkpoint = self.runtime.checkpoint_task(
            task, kind="manual", completed=("manual save",), next_action="keep working"
        )
        self.assertEqual(self.runtime.store.get_task(task)["state"], "running")
        reopened = TaskStore(self.runtime.store.path)
        self.assertEqual(reopened.get_logical_session(logical)["current_checkpoint_id"], checkpoint)
        self.assertEqual(reopened.get_checkpoint(checkpoint, include_content=True)["content"]["nextAction"], "keep working")

    def test_repository_divergence_is_reported_without_touching_user_changes(self):
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.project, check=True)
        tracked = self.project / "tracked.txt"
        tracked.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.project, check=True)
        tracked.write_text("user edit\n", encoding="utf-8")
        task, logical = self.create(native=None)
        self.runtime.checkpoint_task(task, next_action="continue")
        worktree = pathlib.Path(self.runtime.store.get_task(task)["project_path"])
        other = worktree / "other.txt"
        other.write_text("new user work\n", encoding="utf-8")
        before = {str(p): p.read_text() for p in (tracked, other)}
        packet, differences = self.runtime.recovery_packet_for_session(logical)
        self.assertTrue(differences)
        self.assertIn("Repository divergence detected", packet)
        self.assertEqual(before, {str(p): p.read_text() for p in (tracked, other)})

    def test_legacy_task_remains_readable_after_additive_migration(self):
        store = self.runtime.store
        legacy = store.create_task(
            workflow="legacy", agent="codex", project_path=self.project,
            display_title="Legacy", policy=self.runtime.profile(
                self.runtime.config(), self.project, "workspace-write"
            ),
        )
        reopened = TaskStore(store.path)
        self.assertEqual(reopened.display_task(legacy)["title"], "Legacy")
        self.assertIsNone(reopened.logical_session_for_task(legacy))

    def test_exact_current_task_failure_simulation_requires_no_manual_reconstruction(self):
        task, logical = self.create(prompt="Implement recoverable work")
        self.runtime.checkpoint_task(
            task, completed=("meaningful progress persisted",),
            unresolved=("finish deterministic validation",),
            next_action="Run deterministic validation",
        )
        self.assertEqual(self.runtime.run_task(task), 0)
        physical = self.runtime.store.latest_physical_session(logical)
        self.runtime.store.mark_physical_session_failed(
            physical["physical_session_id"], "simulated catastrophic session loss"
        )
        restarted = HarnessRuntime(
            config_path=self.config, state_root=self.root / "state",
            script_path=self.agent, default_workspace=self.project,
            command_resolver=lambda name: str(self.agent) if name in {"codex", "pi"} else shutil.which(name),
            codex_preflight=lambda _home: None,
        )
        located = next(row for row in restarted.list_logical_sessions() if row["quattroSessionId"] == logical)
        self.assertEqual(located["recoveryState"], "recoverable")
        replacement = restarted.prepare_recovery_task(logical, reason="failure simulation")
        self.assertEqual(restarted.run_task(replacement), 0)
        packet = restarted.store.get_task(replacement, include_private=True)["private_payload"]["prompt"]
        self.assertIn("Implement recoverable work", packet)
        self.assertIn("Run deterministic validation", packet)
        self.assertEqual(restarted.store.logical_session_for_task(replacement)["quattro_session_id"], logical)


if __name__ == "__main__":
    unittest.main()
