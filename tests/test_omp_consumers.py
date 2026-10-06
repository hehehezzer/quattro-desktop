"""Hermetic consumer contracts for selected durable OMP work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import test_harness_integration as integration
from quattro_agent import cli
from quattro_agent.config import ConfigError, validate_ai_config
from quattro_agent.delegation import classify_task_request, select_execution_agent, worker_prompt
from quattro_agent.policy import PolicyProfile
from quattro_harness import compact_omp_output


class OMPConsumerTests(unittest.TestCase):
    def setUp(self):
        fixture = integration.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.runtime, self.project, self.root = fixture.runtime, fixture.project, fixture.root
        config = self.runtime.config()
        config["defaultAgent"] = "codex"
        config["delegation"]["workerAgent"] = "omp"
        self.runtime.config_path.write_text(json.dumps(config))
        self.runtime.omp_runtime_pin = (self.root / "manifest.json", "a" * 64)
        self.runtime.omp_sdk_paths = (self.root / "bun", self.root / "sdk")
        self.runtime.omp_agent_dir = self.root / "native-quattro-agent"
        self.runtime.omp_agent_dir.mkdir()

    def task(self, **kwargs):
        return self.runtime.create_task(agent="omp", project=self.project,
                                        prompt="Inspect repository files for regressions",
                                        mode="prompt", profile_name="audit-read-only", **kwargs)

    def test_specialist_configuration_preserves_codex_primary_and_legacy_defaults(self):
        config = self.runtime.config()
        self.assertEqual(config["defaultAgent"], "codex")
        self.assertEqual(config["delegation"]["workerAgent"], "omp")
        for primary, expected in (("codex", "pi"), ("pi", "pi"), ("omp", "omp")):
            config["defaultAgent"] = primary
            config["delegation"].pop("workerAgent", None)
            self.assertEqual(validate_ai_config(config)["delegation"]["workerAgent"], expected)
        config["delegation"]["workerAgent"] = "codex"
        with self.assertRaises(ConfigError):
            validate_ai_config(config)
        config["delegation"] = {"workerAgent": "omp", "enabled": True}
        with self.assertRaises(ConfigError):
            validate_ai_config(config)

    def test_omp_specialists_leave_primary_workspace_tasks_writable(self):
        task_id = self.runtime.create_task(agent=self.runtime.config()["defaultAgent"],
                                          project=self.project, prompt="Implement repository regression fix",
                                          mode="prompt")
        task = self.runtime.store.get_task(task_id)
        self.assertEqual(task["agent"], "codex")
        self.assertEqual(task["policy"]["name"], "workspace-write")

    def test_selected_specialist_instructions_and_workflow_retain_codex_primary(self):
        parent_id = self.runtime.create_workflow(count=2, project=self.project,
                                                objective="Implement repository regression fix")
        parent = self.runtime.store.get_task(parent_id, include_private=True)
        self.assertEqual(parent["agent"], "codex")
        self.assertEqual(parent["policy"]["name"], "workspace-write")
        children = self.runtime.store.children(parent_id)
        roles = {row["metadata"]["role"]: row for row in children}
        self.assertEqual(roles["implementation"]["agent"], "codex")
        self.assertEqual(roles["review"]["agent"], "omp")
        review = self.runtime.store.get_task(roles["review"]["taskId"], include_private=True)
        self.assertIsNone(review["private_payload"]["executionPlan"])
        run_id = self.runtime.store.create_run(parent_id, agent="codex")
        argv, _stdin, _env = self.runtime._agent_plan(parent, run_id, PolicyProfile.from_dict(parent["policy"]))
        instructions = "\n".join(argv)
        self.assertIn("OMP returns focused evidence", instructions)
        self.assertNotIn("Pi returns focused evidence", instructions)

    def test_selected_omp_preserves_classifier_identity(self):
        self.assertEqual(classify_task_request("Inspect repository files", preferred_agent="omp").required_agent, "omp")
        self.assertEqual(select_execution_agent("workflow", requested="omp"), "omp")
        self.assertIn("OMP specialist", worker_prompt("Inspect repository files", "review", agent="omp"))

    def test_create_without_pi_or_omniroute_dependencies(self):
        with mock.patch.object(self.runtime, "account", side_effect=AssertionError("account accessed")), \
             mock.patch.object(self.runtime, "_pre_route", side_effect=AssertionError("gateway accessed")):
            task_id = self.task()
        task = self.runtime.store.get_task(task_id, include_private=True)
        self.assertEqual(task["agent"], "omp")
        self.assertIsNone(task["private_payload"]["executionPlan"])
        self.assertIsNone(task["private_payload"]["accountId"])
        self.assertEqual(task["display_metadata"]["actualProvider"], "openai-codex")
        self.assertEqual(self.runtime.store.logical_session_for_task(task_id)["agent"], "omp")

    def test_write_and_resume_reject_before_repository_reservation(self):
        with mock.patch.object(self.runtime.coordinator, "reserve", side_effect=AssertionError("reserved")):
            with self.assertRaises(PermissionError):
                self.runtime.create_task(agent="omp", project=self.project, prompt="Edit file", mode="prompt")
            with self.assertRaises(PermissionError):
                self.runtime.create_task(agent="omp", project=self.project, prompt="Inspect files", mode="resume",
                                         profile_name="audit-read-only")

    def test_closed_plan_uses_native_dir_and_private_stdin(self):
        task_id = self.task()
        task = self.runtime.store.get_task(task_id, include_private=True)
        run_id = self.runtime.store.create_run(task_id, agent="omp")
        with mock.patch.object(self.runtime, "_retrieval_context", return_value="bounded evidence"):
            argv, stdin, env = self.runtime._agent_plan(task, run_id, PolicyProfile.from_dict(task["policy"]))
        self.assertIn(str(self.runtime.omp_agent_dir), argv)
        self.assertNotIn(task["private_payload"]["prompt"], argv)
        self.assertIn("bounded evidence", stdin)
        self.assertNotIn("CODEX_HOME", env)
        self.assertNotIn("PI_CODING_AGENT_DIR", env)
        self.assertEqual(self.runtime.store.get_task(task_id)["display_metadata"]["executedBy"], "OMP")

    def test_recovery_retains_omp_identity_without_native_resume(self):
        task_id = self.task()
        logical = self.runtime.store.logical_session_for_task(task_id)
        recovered, path = self.runtime.prepare_resume_task(logical["quattro_session_id"],
                                                          native_session_available=True, prompt="Continue")
        self.assertEqual(path, "checkpoint-recovery")
        task = self.runtime.store.get_task(recovered, include_private=True)
        self.assertEqual(task["agent"], "omp")
        self.assertEqual(task["policy"]["name"], "audit-read-only")
        self.assertIsNone(task["private_payload"]["nativeSessionRef"])

    def test_result_contract_rejects_native_or_unsettled_output(self):
        value = {"type": "quattro.omp.result", "status": "completed", "session_id": "native-1", "text": "Evidence"}
        self.assertEqual(compact_omp_output(json.dumps(value)), ("Evidence\n", "native-1"))
        for bad in ("plain answer", json.dumps(value | {"status": "busy"}), json.dumps(value | {"session_id": "bad\nidentity"})):
            with self.assertRaises(RuntimeError):
                compact_omp_output(bad)

    def test_supervised_omp_completion_records_checkpoint_and_native_receipt(self):
        task_id = self.task()
        envelope = json.dumps({"type": "quattro.omp.result", "status": "completed",
                               "session_id": "native-1", "text": "Concrete repository evidence"})
        command = (sys.executable, "-I", "-c", "import sys; sys.stdin.read(); print(" + repr(envelope) + ")")
        with mock.patch.object(self.runtime, "_omp_agent_plan", return_value=(command, "bounded prompt", {})):
            result = self.runtime.run_task(task_id)
        self.assertEqual(result, 0)
        self.assertEqual(self.runtime.store.get_task(task_id)["state"], "succeeded")
        self.assertTrue(any(event["type"] == "omp.turn_completed"
                            for event in self.runtime.store.display_events(task_id)))
        logical = self.runtime.store.logical_session_for_task(task_id)
        self.assertIsNotNone(self.runtime.store.current_checkpoint(logical["quattro_session_id"]))
        self.assertIsNone(logical["current_codex_session_id"])
        self.assertEqual(self.runtime.store.leases_for_holder(task_id), [])

    def test_cli_allows_selected_omp_consumers(self):
        parser = cli.build_parser()
        self.assertEqual(parser.parse_args(["submit", "--agent", "omp", "--prompt", "Inspect files"] ).agent, "omp")
        self.assertEqual(parser.parse_args(["new-task", "--agent", "omp", "--mode", "prompt", "--prompt", "Inspect files"]).agent, "omp")

    def test_selected_delegation_uses_already_queued_omp_task(self):
        with mock.patch.object(self.runtime, "run_task", return_value=0) as run, \
             mock.patch.object(self.runtime, "_resolved_agent_binary", side_effect=AssertionError("Pi executable accessed")):
            task_id, code, result = self.runtime.delegate_to_pi(
                project=self.project, objective="Inspect repository files for an independent review",
                kind="review", parent_task_id=None)
        self.assertIsNotNone(task_id)
        run.assert_called_once_with(task_id)
        self.assertEqual(code, 0)
        self.assertEqual(result["worker"], "omp")
        self.assertEqual(self.runtime.config()["defaultAgent"], "codex")
        task = self.runtime.store.get_task(task_id)
        self.assertEqual(task["agent"], "omp")
        self.assertEqual(task["state"], "queued")


if __name__ == "__main__":
    unittest.main()
