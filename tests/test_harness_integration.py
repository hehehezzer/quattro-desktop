from __future__ import annotations

import json
import os
import pathlib
import signal
import shutil
import subprocess
import sqlite3
import contextlib
import time
import sys
import tempfile
import threading
import unittest
from unittest import mock

SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))

from quattro_harness import HarnessRuntime
from quattro_agent.policy import PolicyProfile
from quattro_agent.models import RunState, TaskState
from quattro_agent.errors import ConfigError
from quattro_agent.policy import MemoryAccess
from quattro_agent.retrieval import RetrievalStore
from quattro_agent.retrieval import RepositoryIndexer
from quattro_agent.adaptive_routing import AdaptiveRoutingDecision, CapabilityNegotiation
from quattro_agent.routing_intelligence import ModelSelection


class StandardAdaptiveClient:
    def __init__(self, _base_url: str):
        pass

    def negotiate(self):
        return CapabilityNegotiation(True, "standard", frozenset(), False), False


class HarnessRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.state = self.root / "state"
        self.fake = self.root / "fake-agent"
        self.fake.write_text("#!/bin/sh\nprintf 'FAKE_AGENT_OK\\nHARNESS_VERDICT: PASS\\n'\n", encoding="utf-8")
        self.fake.chmod(0o755)
        self.config_path = self.root / "ai.json"
        config = {
            "schemaVersion": 3,
            "defaultAgent": "codex",
            "defaultCodexAccount": "account-1",
            "defaultPolicyProfile": "workspace-write",
            "fullAccessRequiresConfirmation": True,
            "deprecated": {"legacyCodexFullAccess": {"removed": True, "previouslyEnabled": False}},
            "accounts": [{
                "id": "account-1",
                "alias": "Account 1",
                "codexHome": "~/.local/share/quattro-ai/codex/accounts/account-1",
                "enabled": True,
            }],
            "usageRefresh": {"enabled": False, "intervalMinutes": 15},
            "crossDeviceSync": {"enabled": False, "directory": None},
            "crashCapture": {"enabled": False, "automaticDiagnosis": False},
            "dictation": {
                "engine": "whisper.cpp",
                "modelPath": "~/.local/share/whisper/model.bin",
                "maxRecordingSeconds": 60,
                "retainAudio": False,
            },
            "memory": {
                "enabled": False,
                "vaultPath": "~/.local/share/quattro/memory/shared",
                "projectVaultPath": "~/.local/share/quattro/memory/projects",
                "enforceOnLaunch": False,
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
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.config_path.chmod(0o600)

        def resolver(name: str) -> str | None:
            if name in {"codex", "pi"}:
                return str(self.fake)
            return shutil.which(name)

        self.runtime = HarnessRuntime(
            config_path=self.config_path,
            state_root=self.state,
            script_path=self.fake,
            default_workspace=self.project,
            command_resolver=resolver,
            codex_preflight=lambda _home: None,
            adaptive_client_factory=StandardAdaptiveClient,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_prompt_task_retains_terminal_outcome_and_private_boundary(self):
        task_id, result = self.runtime.submit(
            agent="codex",
            project=self.project,
            prompt="Implement private objective password=must-not-project",
            mode="prompt",
        )
        self.assertEqual(result, 0)
        projection = self.runtime.task_projection(task_id)
        self.assertEqual(projection["state"], "succeeded")
        self.assertEqual(projection["validation"]["status"], "Passed")
        self.assertGreaterEqual(projection["artifacts"]["count"], 1)
        details = self.runtime.show_task(task_id)
        serialized = json.dumps(details)
        self.assertEqual(
            projection["title"],
            "Implement private objective [REDACTED BY QUATTRO]",
        )
        self.assertNotIn("must-not-project", serialized)
        self.assertNotIn("private_payload", details["task"])
        self.assertNotIn('"prompt"', serialized)
        context_events = [
            event for event in self.runtime.store.display_events(task_id)
            if event["type"] == "context.assembled"
        ]
        self.assertEqual(len(context_events), 1)
        mandatory = context_events[0]["payload"]["mandatoryContext"]
        self.assertIn("workspace.default_project_root", mandatory["activatedPolicies"])
        self.assertEqual(mandatory["loadedSources"], ["configuration:workspace.projectRoot"])
        self.assertGreater(context_events[0]["payload"]["launcherPayloadTokenEstimate"], 0)
        self.assertIn(context_events[0]["payload"]["contextClass"], {"small", "moderate", "large"})
        self.assertTrue((self.state / "private/harness.sqlite3").is_file())
        self.assertEqual((self.state / "private/harness.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_async_submit_returns_queued_task_and_spawns_worker(self):
        with mock.patch.object(self.runtime, "spawn_worker") as spawn:
            task_id, result = self.runtime.submit(
                agent="codex",
                project=self.project,
                prompt="queued objective",
                mode="prompt",
                asynchronous=True,
            )
        self.assertIsNone(result)
        self.assertEqual(self.runtime.store.display_task(task_id)["state"], "queued")
        spawn.assert_called_once_with(task_id)

    def test_direct_response_uses_omniroute_without_creating_a_task(self):
        before = self.runtime.store.list_display_tasks(limit=100)

        class Response:
            def read(self, _limit):
                return b'{"output_text":"Docker volumes persist data."}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with mock.patch("quattro_harness.urllib.request.urlopen", return_value=Response()) as open_request:
            result = self.runtime.direct_response(
                project=self.project, prompt="Explain Docker volumes",
            )

        self.assertEqual(result["decision"]["decision"], "DIRECT")
        self.assertEqual(result["response"], "Docker volumes persist data.")
        self.assertEqual(len(self.runtime.store.list_display_tasks(limit=100)), len(before))
        request = open_request.call_args.args[0]
        self.assertEqual(request.full_url, "http://localhost:20128/api/v1/responses")
        self.assertTrue(json.loads(request.data.decode("utf-8"))["model"])

    def test_simple_delegation_is_declined_without_worker(self):
        with mock.patch.object(self.runtime, "run_task") as run:
            task_id, exit_code, report = self.runtime.delegate_to_pi(
                project=self.project,
                objective="Fix a one-line typo in README",
                kind="implementation",
                parent_task_id=None,
            )
        self.assertIsNone(task_id)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "not_delegated")
        run.assert_not_called()

    def test_bounded_pi_delegation_returns_compact_omniroute_usage(self):
        worker_event = {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "provider": "omniroute",
                "model": "auto",
                "content": [{
                    "type": "text",
                    "text": (
                        "STATUS\nCOMPLETE\nFINDINGS\nLocated recovery code.\n"
                        "FILES_CHANGED\nNone\nVALIDATION\nNot Run\nRISKS\nNone\n"
                        "NEXT_ACTION\nCodex should inspect src/quattro_agent/recovery.py."
                    ),
                }],
                "usage": {"input": 90, "output": 40, "totalTokens": 130},
            },
        }
        self.fake.write_text(
            "#!/bin/sh\nprintf '%s\\n' " + json.dumps(json.dumps(worker_event)) + "\n",
            encoding="utf-8",
        )
        parent = self.runtime.create_task(
            agent="codex", project=self.project, prompt="primary", mode="interactive"
        )
        task_id, exit_code, report = self.runtime.delegate_to_pi(
            project=self.project,
            objective="Explore the repository and locate the recovery implementation",
            kind="exploration",
            parent_task_id=parent,
        )
        self.assertEqual(exit_code, 0)
        self.assertIsNotNone(task_id)
        self.assertEqual(report["worker"], "pi")
        self.assertIn("Located recovery code", report["result"])
        self.assertEqual(report["usage"]["provider"], "omniroute")
        self.assertEqual(report["usage"]["totalTokens"], 130)
        child = self.runtime.store.display_task(str(task_id))
        self.assertEqual(child["parentTaskId"], parent)
        self.assertEqual(child["workflow"], "codex-pi-delegation")
        context_event = next(
            event for event in self.runtime.store.display_events(str(task_id))
            if event["type"] == "context.assembled"
        )
        self.assertTrue(
            context_event["payload"]["mandatoryContext"]["propagatedToSubagent"]
        )

    def test_pi_worker_failure_returns_control_without_retry_loop(self):
        self.fake.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
        task_id, exit_code, report = self.runtime.delegate_to_pi(
            project=self.project,
            objective="Review the repository subsystem for a focused regression risk",
            kind="review",
            parent_task_id=None,
        )
        self.assertIsNotNone(task_id)
        self.assertEqual(exit_code, 7)
        self.assertEqual(report["status"], "failed")
        self.assertIn("Codex should inspect", report["result"])
        self.assertEqual(len(self.runtime.store.runs_for_task(str(task_id))), 1)

    def test_pi_child_cannot_delegate_recursively(self):
        parent = self.runtime.create_task(
            agent="pi", project=self.project, prompt="worker", mode="prompt",
            profile_name="audit-read-only",
        )
        with self.assertRaises(PermissionError):
            self.runtime.delegate_to_pi(
                project=self.project,
                objective="Explore the repository and locate the recovery implementation",
                kind="exploration",
                parent_task_id=parent,
            )

    def test_approval_resolution_advances_or_blocks_waiting_task(self):
        approved_task = self.runtime.create_task(
            agent="codex", project=self.project, prompt="approved", mode="prompt"
        )
        self.runtime.store.transition_task(approved_task, TaskState.AWAITING_APPROVAL)
        approval_id = self.runtime.store.request_approval(
            approved_task, scope="publish", confirmation_summary="Publish verified result"
        )
        with mock.patch.object(self.runtime, "spawn_worker") as spawn:
            result = self.runtime.resolve_approval(approval_id, approved=True)
        self.assertEqual(result["state"], "approved")
        self.assertEqual(result["taskState"], "ready")
        spawn.assert_called_once_with(approved_task)
        self.assertEqual(self.runtime.run_task(approved_task), 0)
        self.assertEqual(self.runtime.store.display_task(approved_task)["state"], "succeeded")

        rejected_task = self.runtime.create_task(
            agent="codex", project=self.project, prompt="rejected", mode="prompt"
        )
        self.runtime.store.transition_task(rejected_task, TaskState.AWAITING_APPROVAL)
        rejected_id = self.runtime.store.request_approval(
            rejected_task, scope="publish", confirmation_summary="Publish another result"
        )
        rejected = self.runtime.resolve_approval(rejected_id, approved=False)
        self.assertEqual(rejected["state"], "declined")
        self.assertEqual(rejected["taskState"], "blocked")

    def test_auto_model_uses_verified_tier_route_and_manual_model_is_preserved(self):
        account_home = self.root / "account"
        account_home.mkdir()
        (account_home / "config.toml").write_text('model = "auto"\n', encoding="utf-8")
        self.runtime.account = lambda _config, _account_id=None: {  # type: ignore[method-assign]
            "id": "account-1", "codexHome": str(account_home),
        }
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="Locate the configuration symbol", mode="prompt",
        )
        task = self.runtime.store.get_task(task_id, include_private=True)
        run_id = self.runtime.store.create_run(task_id)
        argv, _stdin, _environment = self.runtime._agent_plan(task, run_id, PolicyProfile.from_dict(task["policy"]))
        self.assertIn("auto/coding:cheap", argv)
        updated = self.runtime.store.display_task(task_id)
        self.assertEqual(updated["metadata"]["modelSelection"], "automatic")
        self.assertEqual(updated["metadata"]["modelRoute"], "auto/coding:cheap")
        self.assertEqual(updated["metadata"]["selectedModel"], "auto")
        self.assertEqual(updated["metadata"]["effectiveModelRoute"], "auto/coding:cheap")

        for explicit_route in ("auto/coding:cheap", "auto/coding", "auto/reasoning"):
            with self.subTest(explicit_route=explicit_route):
                (account_home / "config.toml").write_text(
                    f'model = "{explicit_route}"\n', encoding="utf-8"
                )
                explicit = self.runtime.store.get_task(task_id, include_private=True)
                explicit_run = self.runtime.store.create_run(task_id)
                explicit_argv, _stdin, _environment = self.runtime._agent_plan(
                    explicit, explicit_run, PolicyProfile.from_dict(explicit["policy"])
                )
                self.assertNotIn("-m", explicit_argv)
                explicit_metadata = self.runtime.store.display_task(task_id)["metadata"]
                self.assertEqual(explicit_metadata["modelSelection"], "manual")
                self.assertEqual(explicit_metadata["selectedModel"], explicit_route)
                self.assertEqual(explicit_metadata["effectiveModelRoute"], explicit_route)

        (account_home / "config.toml").write_text('model = "account-1/gpt-5.6-terra"\n', encoding="utf-8")
        manual_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="Locate another configuration symbol", mode="prompt",
        )
        manual = self.runtime.store.get_task(manual_id, include_private=True)
        manual_run = self.runtime.store.create_run(manual_id)
        manual_argv, _stdin, _environment = self.runtime._agent_plan(manual, manual_run, PolicyProfile.from_dict(manual["policy"]))
        self.assertNotIn("auto/coding:cheap", manual_argv)
        self.assertEqual(self.runtime.store.display_task(manual_id)["metadata"]["modelSelection"], "manual")

    def test_task_routing_metadata_and_codex_effort_are_display_safe(self):
        task_id = self.runtime.create_task(
            agent="codex", project=self.project,
            prompt="Locate the config symbol and summarize it", mode="prompt",
        )
        task = self.runtime.store.get_task(task_id, include_private=True)
        self.assertEqual(task["display_metadata"]["routingTier"], "FAST")
        run_id = self.runtime.store.create_run(task_id)
        argv, _stdin, environment = self.runtime._agent_plan(
            task, run_id, PolicyProfile.from_dict(task["policy"])
        )
        self.assertIn('model_reasoning_effort="low"', argv)
        self.assertEqual(environment["QUATTRO_ROUTING_TIER"], "FAST")

    def test_delegated_codex_uses_supported_dynamic_header_transport(self):
        account_home = self.root / "adaptive-account"
        account_home.mkdir()
        (account_home / "config.toml").write_text('model = "auto"\n', encoding="utf-8")
        self.runtime.account = lambda _config, _account_id=None: {  # type: ignore[method-assign]
            "id": "account-1", "codexHome": str(account_home),
        }
        task_id = self.runtime.create_task(
            agent="codex", project=self.project,
            prompt="Fix a typo in README.md", mode="prompt",
        )
        task = self.runtime.store.get_task(task_id, include_private=True)
        run_id = self.runtime.store.create_run(task_id)
        envelope = {
            "schema_version": 1,
            "requirements": {"capabilities": ["code_analysis"], "minimum_context": 3000},
            "preferred_candidates": ["codex/luna", "codex/sol"],
            "preference_mode": "balanced",
            "task_profile_id": task_id,
            "routing_policy_version": "quattro-routing-v2",
        }
        adaptive = AdaptiveRoutingDecision(
            CapabilityNegotiation(
                True, "enhanced", frozenset({"candidate_snapshot"}), True
            ),
            ModelSelection("codex", "luna", "test", ()),
            envelope,
            "test-candidates-1",
            2,
            1.5,
            False,
        )
        with mock.patch("quattro_harness.build_adaptive_decision", return_value=adaptive):
            argv, _stdin, environment = self.runtime._agent_plan(
                task, run_id, PolicyProfile.from_dict(task["policy"])
            )
        self.assertIn(
            'model_providers.omniroute.env_http_headers={"X-Quattro-Routing" = "QUATTRO_ROUTING_ENVELOPE"}',
            argv,
        )
        transported = json.loads(environment["QUATTRO_ROUTING_ENVELOPE"])
        self.assertEqual(transported, envelope)
        self.assertNotIn("Fix a typo", environment["QUATTRO_ROUTING_ENVELOPE"])

    def test_native_codex_effort_is_ignored_in_both_directions(self):
        account_home = self.root / "account-native-effort"
        account_home.mkdir()
        self.runtime.account = lambda _config, _account_id=None: {  # type: ignore[method-assign]
            "id": "account-1", "codexHome": str(account_home),
        }
        cases = (
            ("Find the README and return only its path.", "xhigh", "FAST", "low"),
            (
                "Review this small project and suggest one minor implementation improvement.",
                "xhigh", "STANDARD", "medium",
            ),
            (
                "Analyze a race condition where two workers claim the same pending job concurrently.",
                "low", "REASONING", "high",
            ),
        )
        for prompt, native_effort, tier, effective_effort in cases:
            (account_home / "config.toml").write_text(
                f'model = "auto"\nmodel_reasoning_effort = "{native_effort}"\n',
                encoding="utf-8",
            )
            task_id = self.runtime.create_task(
                agent="codex", project=self.project, prompt=prompt, mode="prompt",
            )
            task = self.runtime.store.get_task(task_id, include_private=True)
            run_id = self.runtime.store.create_run(task_id)
            argv, _stdin, _environment = self.runtime._agent_plan(
                task, run_id, PolicyProfile.from_dict(task["policy"])
            )
            self.assertIn(f'model_reasoning_effort="{effective_effort}"', argv)
            metadata = self.runtime.store.display_task(task_id)["metadata"]
            self.assertEqual(metadata["routingTier"], tier)
            self.assertEqual(metadata["reasoningEffort"], effective_effort)

    def test_manual_model_preserves_model_but_not_native_effort(self):
        account_home = self.root / "account-manual-effort"
        account_home.mkdir()
        (account_home / "config.toml").write_text(
            'model = "account-1/gpt-5.6-sol"\nmodel_reasoning_effort = "xhigh"\n',
            encoding="utf-8",
        )
        self.runtime.account = lambda _config, _account_id=None: {  # type: ignore[method-assign]
            "id": "account-1", "codexHome": str(account_home),
        }
        task_id = self.runtime.create_task(
            agent="codex", project=self.project,
            prompt="Find the README and return only its path.", mode="prompt",
        )
        task = self.runtime.store.get_task(task_id, include_private=True)
        run_id = self.runtime.store.create_run(task_id)
        argv, _stdin, _environment = self.runtime._agent_plan(
            task, run_id, PolicyProfile.from_dict(task["policy"])
        )
        self.assertNotIn("auto/coding:cheap", argv)
        self.assertIn('model_reasoning_effort="low"', argv)
        metadata = self.runtime.store.display_task(task_id)["metadata"]
        self.assertEqual(metadata["modelRoute"], "account-1/gpt-5.6-sol")
        self.assertEqual(metadata["modelSelection"], "manual")
        self.assertEqual(metadata["reasoningEffort"], "low")

    def test_codex_preflight_fails_before_child_launch(self):
        marker = self.root / "child-ran"
        self.fake.write_text(
            f"#!/bin/sh\ntouch {marker}\n",
            encoding="utf-8",
        )
        self.runtime.codex_preflight = lambda _home: (_ for _ in ()).throw(
            ConfigError("routing drift")
        )
        task_id, result = self.runtime.submit(
            agent="codex", project=self.project, prompt="private", mode="prompt"
        )
        self.assertEqual(result, 1)
        self.assertFalse(marker.exists())
        self.assertEqual(self.runtime.task_projection(task_id)["state"], "failed")

    def test_interactive_and_resume_sessions_have_no_automatic_deadline(self):
        original_start = self.runtime.supervisor.start
        observed: list[float | None] = []
        def capture_start(**kwargs):
            observed.append(kwargs.get("deadline_seconds"))
            return original_start(**kwargs)
        self.runtime.supervisor.start = capture_start  # type: ignore[method-assign]
        for mode in ("interactive", "resume"):
            task_id = self.runtime.create_task(
                agent="codex", project=self.project, prompt="", mode=mode,
                account_id="account-1", native_session_ref="native" if mode == "resume" else None,
            )
            self.assertEqual(self.runtime.run_task(task_id), 0)
        self.assertEqual(observed, [None, None])

    def test_two_interactive_sessions_can_share_one_non_git_project(self):
        self.fake.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(0.15)\n",
            encoding="utf-8",
        )
        task_ids = [
            self.runtime.create_task(
                agent="codex", project=self.project, prompt="", mode="interactive",
                account_id="account-1",
            )
            for _ in range(2)
        ]
        barrier = threading.Barrier(2)
        results: list[int] = []
        def worker(task_id: str) -> None:
            barrier.wait()
            results.append(self.runtime.run_task(task_id))
        threads = [threading.Thread(target=worker, args=(task_id,)) for task_id in task_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [0, 0])
        self.assertEqual(sorted(
            self.runtime.task_projection(task_id)["state"] for task_id in task_ids
        ), ["succeeded", "succeeded"])

    def test_git_sessions_share_requested_directory_and_peer_context(self):
        git = shutil.which("git")
        assert git is not None
        subprocess.run([git, "init", "-q", "-b", "main"], cwd=self.project, check=True)
        subprocess.run([git, "config", "user.name", "Test"], cwd=self.project, check=True)
        subprocess.run([git, "config", "user.email", "test@example.invalid"], cwd=self.project, check=True)
        (self.project / "base.txt").write_text("base\n", encoding="utf-8")
        subprocess.run([git, "add", "base.txt"], cwd=self.project, check=True)
        subprocess.run([git, "commit", "-qm", "base"], cwd=self.project, check=True)
        first = self.runtime.create_task(
            agent="codex", project=self.project, prompt="authentication lifecycle", mode="interactive",
            write_scopes=("src/auth",),
        )
        second = self.runtime.create_task(
            agent="codex", project=self.project, prompt="appointment frontend", mode="interactive",
            write_scopes=("src/appointments",),
        )
        first_task = self.runtime.store.get_task(first, include_private=True)
        second_task = self.runtime.store.get_task(second, include_private=True)
        self.assertEqual(pathlib.Path(first_task["project_path"]), self.project)
        self.assertEqual(pathlib.Path(second_task["project_path"]), self.project)
        first_coord = self.runtime.coordinator.get(first_task["private_payload"]["coordinationSessionId"])
        second_coord = self.runtime.coordinator.get(second_task["private_payload"]["coordinationSessionId"])
        self.assertEqual(first_coord["repositoryId"], second_coord["repositoryId"])
        self.assertFalse(first_coord["managedWorktree"])
        self.assertEqual(first_coord["isolationReason"], "shared_working_tree")
        context = self.runtime.coordinator.context(first_coord["sessionId"])
        self.assertIn("appointment frontend", context)
        self.assertIn("Write ownership: src/auth", context)
        child_id, child_exit, _report = self.runtime.delegate_to_pi(
            project=self.project,
            objective="Explore the repository collaboration boundary and report exact evidence",
            kind="exploration",
            parent_task_id=first,
        )
        self.assertEqual(child_exit, 0)
        child = self.runtime.store.get_task(str(child_id), include_private=True)
        self.assertEqual(pathlib.Path(child["project_path"]), self.project)
        self.assertEqual(child["private_payload"]["coordinationSessionId"], first_coord["sessionId"])

    def test_resume_session_closes_cleanly_without_output_validation(self):
        task_id, result = self.runtime.submit(
            agent="codex", project=self.project, prompt="", mode="resume",
            account_id="account-1", native_session_ref="native-session-1",
        )
        self.assertEqual(result, 0)
        projection = self.runtime.task_projection(task_id)
        self.assertEqual(projection["state"], "succeeded")
        self.assertEqual(projection["validation"]["status"], "Not Run")
        self.assertEqual(
            self.runtime.store.latest_run(task_id)["native_session_ref"],
            "native-session-1",
        )

    def test_full_access_requires_run_scoped_confirmation(self):
        with self.assertRaises(PermissionError):
            self.runtime.create_task(
                agent="codex",
                project=self.project,
                prompt="x",
                mode="prompt",
                profile_name="full-access-explicit",
            )

    def test_pi_writable_task_fails_closed_without_explicit_full_access(self):
        with self.assertRaises(PermissionError):
            self.runtime.create_task(
                agent="pi", project=self.project, prompt="write", mode="prompt",
                profile_name="workspace-write",
            )

    def test_workflow_uses_supplied_narrow_write_scopes(self):
        parent = self.runtime.create_workflow(
            count=2, project=self.project, objective="exercise auth ownership",
            write_scopes=("src/auth", "tests/auth"),
        )
        parent_task = self.runtime.store.get_task(parent, include_private=True)
        self.assertEqual(parent_task["private_payload"]["writeScopes"], ["src/auth", "tests/auth"])
        implementation = next(child for child in self.runtime.store.children(parent)
                              if child["metadata"]["role"] == "implementation")
        self.assertEqual(implementation["metadata"]["writeOwnership"], ["src/auth", "tests/auth"])

    def test_multi_agent_workflow_coordinates_dependencies_and_join(self):
        parent = self.runtime.create_workflow(
            count=3,
            project=self.project,
            objective="exercise durable coordination",
        )
        self.runtime.spawn_worker = lambda task_id: self.runtime.run_task(task_id)  # type: ignore[method-assign]
        self.assertEqual(self.runtime.run_workflow(parent), 0)
        projection = self.runtime.task_projection(parent)
        self.assertEqual(projection["state"], "succeeded")
        self.assertEqual(projection["children"], {"completed": 3, "total": 3})
        children = self.runtime.store.children(parent)
        self.assertEqual([child["state"] for child in children], ["succeeded"] * 3)

    def test_independent_verdict_requires_exact_final_line(self):
        self.assertTrue(self.runtime._review_verdict_passed("evidence\nHARNESS_VERDICT: PASS\n"))
        self.assertFalse(self.runtime._review_verdict_passed(
            "The evidence does not support HARNESS_VERDICT: PASS"
        ))

    def test_validation_failure_can_retry_without_step_collision(self):
        git = shutil.which("git")
        assert git is not None
        subprocess.run([git, "init", "-q"], cwd=self.project, check=True)
        tracked = self.project / "tracked.txt"
        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run([git, "add", "tracked.txt"], cwd=self.project, check=True)
        subprocess.run(
            [git, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "base"],
            cwd=self.project, check=True,
        )
        tracked.write_text("bad trailing space \n", encoding="utf-8")
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="first", mode="prompt"
        )
        managed = pathlib.Path(self.runtime.store.get_task(task_id)["project_path"])
        (managed / "tracked.txt").write_text("bad trailing space \n", encoding="utf-8")
        first = self.runtime.run_task(task_id)
        self.assertEqual(first, 1)
        self.assertEqual(self.runtime.task_projection(task_id)["state"], "failed")
        (managed / "tracked.txt").write_text("clean again\n", encoding="utf-8")
        self.runtime.spawn_worker = lambda value: self.runtime.run_task(value)  # type: ignore[method-assign]
        self.runtime.retry(task_id)
        projection = self.runtime.task_projection(task_id)
        self.assertEqual(projection["state"], "succeeded")
        self.assertEqual(projection["retryCount"], 1)

    def test_concurrent_workers_claim_task_once(self):
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="once", mode="prompt"
        )
        barrier = threading.Barrier(2)
        results: list[int] = []
        def worker():
            barrier.wait()
            results.append(self.runtime.run_task(task_id))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sorted(results), [0, 75])
        self.assertEqual(len(self.runtime.store.runs_for_task(task_id)), 1)
        self.assertEqual(self.runtime.task_projection(task_id)["state"], "succeeded")

    def test_abandoned_atomic_claim_is_recovered_for_retry(self):
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="recover", mode="prompt"
        )
        run_id = self.runtime.store.claim_task_for_run(task_id, agent="codex", account_id="account-1")
        with contextlib.closing(sqlite3.connect(self.runtime.store.path)) as connection:
            connection.execute(
                "UPDATE tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
                (task_id,),
            )
            connection.commit()
        results = self.runtime.reconcile()
        self.assertTrue(any(item["status"] == "claim_interrupted" for item in results))
        self.assertEqual(self.runtime.store.get_run(run_id)["state"], "interrupted")
        self.assertEqual(self.runtime.task_projection(task_id)["state"], "interrupted")

    def test_reconcile_restarts_orphaned_workflow_coordinator(self):
        parent = self.runtime.create_workflow(
            count=2, project=self.project, objective="recover coordinator"
        )
        spawned: list[str] = []
        self.runtime.spawn_workflow_worker = spawned.append  # type: ignore[method-assign]
        results = self.runtime.reconcile()
        self.assertEqual(spawned, [parent])
        self.assertTrue(any(item["status"] == "coordinator_restarted" for item in results))

    def test_reconcile_recovers_orphaned_validating_result(self):
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="validate", mode="prompt"
        )
        run_id = self.runtime.store.claim_task_for_run(task_id, agent="codex", account_id="account-1")
        self.runtime.store.transition_task(task_id, TaskState.RUNNING, expected=TaskState.READY)
        self.runtime.store.transition_run(run_id, RunState.STARTING)
        self.runtime.store.transition_run(run_id, RunState.RUNNING)
        self.runtime.store.transition_run(run_id, RunState.SUCCEEDED, exit_code=0)
        self.runtime.store.transition_task(task_id, TaskState.VALIDATING_RESULT)
        connection = self.runtime.store._connect()  # deterministic stale fixture
        try:
            connection.execute(
                "UPDATE tasks SET updated_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
                (task_id,),
            )
            connection.commit()
        finally:
            connection.close()
        results = self.runtime.reconcile()
        self.assertTrue(any(item["status"] == "validation_interrupted" for item in results))
        self.assertEqual(self.runtime.task_projection(task_id)["state"], "interrupted")

    def test_public_cancellation_escalates_and_finishes_terminal(self):
        self.fake.write_text(
            "#!/usr/bin/env python3\nimport signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n",
            encoding="utf-8",
        )
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="cancel", mode="prompt"
        )
        thread = threading.Thread(target=lambda: self.runtime.run_task(task_id))
        thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = self.runtime.store.latest_run(task_id)
            if run and run["state"] == "running":
                break
            time.sleep(0.02)
        self.runtime.request_cancel(task_id)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.runtime.task_projection(task_id)["state"], "cancelled")
        self.assertEqual(self.runtime.store.latest_run(task_id)["state"], "cancelled")

    def test_terminal_close_uses_verified_cancellation_and_leaves_no_agent(self):
        self.fake.write_text(
            "#!/usr/bin/env python3\nimport signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n",
            encoding="utf-8",
        )
        task_id = self.runtime.create_task(
            agent="codex", project=self.project, prompt="", mode="interactive",
        )
        thread = threading.Thread(target=lambda: self.runtime.run_task(task_id))
        thread.start()
        deadline = time.monotonic() + 5
        run = None
        while time.monotonic() < deadline:
            run = self.runtime.store.latest_run(task_id)
            if run and run["state"] == "running":
                break
            time.sleep(0.02)
        self.assertIsNotNone(run)
        self.assertEqual(run["state"], "running")

        self.runtime.request_cancel(task_id, reason="terminal_closed")
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        projection = self.runtime.task_projection(task_id)
        self.assertEqual(projection["state"], "cancelled")
        self.assertEqual(
            projection["terminalSummary"],
            "Terminal closed; the agent session was stopped safely.",
        )
        self.assertFalse(pathlib.Path(f"/proc/{run['pid']}").exists())

    def test_terminal_worker_installs_and_restores_lifecycle_signal_handlers(self):
        installed: dict[signal.Signals, object] = {}

        def fake_signal(current_signal, handler):
            previous = installed.get(current_signal, signal.SIG_DFL)
            installed[current_signal] = handler
            return previous

        with mock.patch("quattro_harness.signal.getsignal", return_value=signal.SIG_DFL), \
                mock.patch("quattro_harness.signal.signal", side_effect=fake_signal) as setter, \
                mock.patch.object(self.runtime, "run_task", return_value=0):
            self.assertEqual(self.runtime.run_terminal_worker("task-id"), 0)

        self.assertEqual(set(installed), {signal.SIGHUP, signal.SIGTERM})
        self.assertEqual(installed[signal.SIGHUP], signal.SIG_DFL)
        self.assertEqual(installed[signal.SIGTERM], signal.SIG_DFL)
        self.assertEqual(setter.call_count, 4)

    def test_agent_output_is_bounded_and_marked_when_truncated(self):
        self.fake.write_text(
            "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('x' * 6000000)\n",
            encoding="utf-8",
        )
        task_id, result = self.runtime.submit(
            agent="codex", project=self.project, prompt="large", mode="prompt"
        )
        self.assertEqual(result, 0)
        artifact = self.runtime.store.artifacts_for_task(task_id)[0]
        payload = pathlib.Path(artifact["path"]).read_bytes()
        self.assertLess(len(payload), 5_100_000)
        self.assertIn(b"OUTPUT TRUNCATED", payload)

    def test_agent_output_secret_is_redacted_before_persistence(self):
        self.fake.write_text(
            "#!/usr/bin/env python3\nprint('api_key=synthetic-secret-value-123456')\n",
            encoding="utf-8",
        )
        task_id, result = self.runtime.submit(
            agent="codex", project=self.project, prompt="secret fixture", mode="prompt"
        )
        self.assertEqual(result, 0)
        artifact = self.runtime.store.artifacts_for_task(task_id)[0]
        payload = pathlib.Path(artifact["path"]).read_text(encoding="utf-8")
        self.assertNotIn("synthetic-secret-value", payload)
        self.assertIn("REDACTED BY QUATTRO", payload)
        events = self.runtime.store.display_events(task_id)
        self.assertTrue(any(event["type"] == "artifact.secret_redacted" for event in events))

    def test_retrieval_respects_memory_access_policy(self):
        self.runtime._retrieval_context(
            "initialize repository index", self.project, session_id=None,
            task_id="fixture", memory_access=MemoryAccess.NONE,
        )
        with RetrievalStore(self.state / "private/retrieval.sqlite3") as store:
            store.upsert_document(
                source_type="documentation",
                content="institutional classified datum",
                repository=str(self.project.resolve()),
                origin="institutional_memory",
            )
        denied = json.loads(self.runtime._retrieval_context(
            "classified datum", self.project, session_id=None,
            task_id="fixture", memory_access=MemoryAccess.NONE,
        ))
        allowed = json.loads(self.runtime._retrieval_context(
            "classified datum", self.project, session_id=None,
            task_id="fixture", memory_access=MemoryAccess.READ,
        ))
        self.assertFalse(any(
            "institutional classified datum" in item["content"]
            for item in denied["retrievedKnowledge"]
        ))
        self.assertTrue(any(
            "institutional classified datum" in item["content"]
            for item in allowed["retrievedKnowledge"]
        ))

    def test_no_retrieval_and_live_state_skip_repository_indexing(self):
        self.runtime.create_task(
            agent="codex", project=self.project, prompt="fixture", mode="prompt",
            profile_name="audit-read-only",
        )
        with mock.patch.object(
            RepositoryIndexer, "index", side_effect=AssertionError("index should not run")
        ):
            self.assertEqual(self.runtime._retrieval_context(
                "What is 17 times 6?", self.project, session_id=None,
                task_id="fixture", memory_access=MemoryAccess.NONE,
            ), "")
            live = json.loads(self.runtime._retrieval_context(
                "Which durable tasks are blocked, failed, or interrupted?",
                self.project, session_id=None, task_id="fixture",
                memory_access=MemoryAccess.NONE,
            ))
        self.assertTrue(live["structuredState"]["recentTasks"])
        self.assertIn("logicalSessions", live["structuredState"])


if __name__ == "__main__":
    unittest.main()
