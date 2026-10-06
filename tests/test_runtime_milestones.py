"""Runtime integration fixtures; mocked provider answers are not live ROI evidence."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))
from quattro_agent.runtime_milestones import (
    MilestoneCancelled, RequiredCheck, validation_boundary_ready, run_validation_milestone,
)


class ScriptedDecision:
    MIN_CONFIDENCE = .90

    def __init__(self, **_kwargs):
        self.closed = False

    def decide(self, request, **_kwargs):
        self.request = request
        return {"selected_action": "broad_first", "confidence": .99,
                "fallback_required": False, "evidence": "native_choice_probabilities"}

    def snapshot(self):
        return {"counts": {"calls": 1}}

    def request_close(self):
        self.closed = True


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self.executed = []
        self.records = []
        self.checks = (
            RequiredCheck("targeted", lambda: self.executed.append("integrity") or "integrity-result"),
            RequiredCheck("broad", lambda: self.executed.append("suite") or "suite-result"),
        )
        self.options = {"mode": "COOPERATIVE", "experimentalValidationOrder": True}

    def run_checks(self, **kwargs):
        return run_validation_milestone(self.checks, options=self.options,
                                        is_current=kwargs.pop("is_current", lambda: True),
                                        emit=self.records.append,
                                        decision_factory=kwargs.pop("decision_factory", ScriptedDecision), **kwargs)

    def test_host_preserves_order_without_provider_question_or_omitting_checks(self):
        factory = mock.Mock(side_effect=AssertionError("fixed questionnaire"))
        self.assertEqual(self.run_checks(decision_factory=factory), ["integrity-result", "suite-result"])
        factory.assert_not_called()
        self.assertEqual(self.executed, ["integrity", "suite"])
        record = self.records[0]
        self.assertEqual(record["outcome"], "PASSTHROUGH")
        self.assertEqual(record["reason"], "model_decision_required")
        self.assertFalse(record["execution_changed"])
        self.assertFalse(record["agent_reasoning_avoided"])
        self.assertFalse(record["advisory_context_emitted"])
        self.assertEqual(record["model_turns_avoided"], 0)
        self.assertEqual(record["context_bytes"], 0)
        self.assertEqual(record["jev_calls"], 0)
        self.assertTrue(record["static_questionnaire_retired"])

    def test_experiment_configuration_is_strict_and_absent_by_default(self):
        from quattro_agent.config import validate_ai_config
        from quattro_agent.errors import ConfigError
        path = Path(__file__).parents[1] / 'examples/ai.json'
        base = validate_ai_config(json.loads(path.read_text()))
        self.assertFalse(base['routing']['jev'].get('experimentalValidationOrder', False))
        for value in (True, False):
            base['routing']['jev']['experimentalValidationOrder'] = value
            self.assertIs(validate_ai_config(base)['routing']['jev']['experimentalValidationOrder'], value)
        for value in (1, 'true', [], None):
            base['routing']['jev']['experimentalValidationOrder'] = value
            with self.assertRaises(ConfigError):
                validate_ai_config(base)

    def test_default_off_and_ineligible_do_not_create_service(self):
        for options in ({}, {"mode": "COOPERATIVE"}, {"mode": "OFF", "experimentalValidationOrder": True}):
            factory = mock.Mock(side_effect=AssertionError("must not call"))
            run_validation_milestone(self.checks, options=options, is_current=lambda: True,
                                     emit=self.records.append, decision_factory=factory)
            factory.assert_not_called()
        for event in ("tool.completed", "agent.implementation", "unknown", "retry"):
            self.assertFalse(validation_boundary_ready(event, self.checks))
        self.assertFalse(validation_boundary_ready("host.validation.ready", self.checks[:1]))
        self.assertTrue(validation_boundary_ready("host.validation.ready", self.checks))

    def test_legacy_factory_cannot_supply_a_static_or_injected_decision(self):
        service = ScriptedDecision()
        service.decide = mock.Mock(side_effect=AssertionError("fixed questionnaire"))
        factory = mock.Mock(return_value=service)
        self.run_checks(decision_factory=factory)
        factory.assert_not_called()
        service.decide.assert_not_called()
        self.assertEqual(self.executed, ["integrity", "suite"])

    def test_policy_guard_cannot_be_moved_after_a_repository_mutating_suite(self):
        state = {'dirty': True}
        policy = RequiredCheck('policy', lambda: not state['dirty'])
        suite = RequiredCheck('broad', lambda: state.update(dirty=False) or 'suite-result')
        self.checks = (self.checks[0], policy, suite)
        results = self.run_checks()
        self.assertEqual(results, ['integrity-result', False, 'suite-result'])
        self.assertEqual(self.records[0]['outcome'], 'PASSTHROUGH')

    def test_original_order_is_not_counted_as_offloaded(self):
        self.run_checks()
        self.assertEqual(self.records[0]["reason"], "model_decision_required")
        self.assertEqual(self.records[0]["outcome"], "PASSTHROUGH")

    def test_cancelled_or_stale_decision_cannot_dispatch_any_check(self):
        current = iter((True, False, False))
        with self.assertRaises(MilestoneCancelled):
            self.run_checks(is_current=lambda: next(current))
        self.assertEqual(self.executed, [])
        self.assertEqual(self.records[0]["outcome"], "PASSTHROUGH")
        self.assertEqual(self.records[0]["reason"], "stale_or_cancelled")

    def test_decision_failure_falls_back_but_check_failure_is_not_swallowed(self):
        self.run_checks(decision_factory=mock.Mock(side_effect=RuntimeError("optional")))
        self.assertEqual(self.executed, ["integrity", "suite"])
        self.checks = (RequiredCheck("targeted", mock.Mock(side_effect=RuntimeError("check"))), self.checks[1])
        with self.assertRaisesRegex(RuntimeError, "check"):
            self.run_checks()
        self.assertEqual(self.checks[0].run.call_count, 1)

    def test_zero_provider_timing_survives_the_display_privacy_boundary(self):
        from quattro_agent.privacy import display_json
        self.run_checks(decision_factory=mock.Mock(side_effect=AssertionError("provider")))
        record = self.records[0]
        display_json(record)
        self.assertEqual(record['jev_calls'], 0)
        self.assertEqual(record['timing']['blocking_ms'], 0)
        self.assertIsNone(record['timing']['rtt_ms'])

    def test_concurrent_milestones_do_not_share_plans_or_results(self):
        results = []
        factory = mock.Mock(side_effect=AssertionError("provider"))
        def work():
            records = []
            result = run_validation_milestone(self.checks, options=self.options,
                                             is_current=lambda: True, emit=records.append,
                                             decision_factory=factory)
            results.append((result, records))
        threads = [threading.Thread(target=work) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2)
        self.assertTrue(all(rows[0]["jev_calls"] == 0 for _, rows in results))
        factory.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "managed process identity is Linux-only")
class ManagedMilestoneIntegrationTests(unittest.TestCase):
    def test_manual_or_parent_validation_is_not_an_agent_completion_call(self):
        from test_harness_integration import HarnessRuntimeIntegrationTests
        from quattro_agent.models import TaskState
        fixture = HarnessRuntimeIntegrationTests()
        fixture.setUp()
        try:
            runtime, project = fixture.runtime, fixture.project
            task = runtime.create_task(agent='codex', project=project, prompt='Inspect the fixture.',
                                       mode='prompt', profile_name='audit-read-only')
            (project / '.git').mkdir()
            (project / 'tests').mkdir()
            (project / 'tests/test_fixture.py').write_text('import unittest\n')
            runtime.store.transition_task(task, TaskState.RUNNING)
            runtime.store.transition_task(task, TaskState.VALIDATING_RESULT)
            config = runtime.config()
            config['routing']['jev'] = {'mode': 'COOPERATIVE', 'timeoutMs': 750,
                                        'experimentalValidationOrder': True}
            with mock.patch.object(runtime, 'config', return_value=config), \
                 mock.patch('quattro_agent.provider_access.resolve_typesafe_credential') as factory:
                runtime.validate_task(task, project)
                factory.assert_not_called()
        finally:
            fixture.tearDown()

    def test_codex_and_standalone_pi_actual_managed_completion_intercepted(self):
        from test_harness_integration import HarnessRuntimeIntegrationTests
        for agent, cancel in (("codex", False), ("pi", False), ("codex", "boundary"),
                              ("pi", "boundary"), ("codex", "check"), ("pi", "check")):
            with self.subTest(agent=agent, cancel=cancel):
                fixture = HarnessRuntimeIntegrationTests()
                fixture.setUp()
                try:
                    project, runtime = fixture.project, fixture.runtime
                    subprocess.run(["git", "init", "-q", "-b", "test/milestone", str(project)], check=True)
                    (project / "tests").mkdir()
                    (project / "tests/test_synthetic.py").write_text("import unittest\nclass Test(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n")
                    (project / ".gitignore").write_text("__pycache__/\n")
                    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
                    subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)
                    # Keep startup routing OFF. Enable only the terminal milestone
                    # via the runtime config projection; no test provider network.
                    task = runtime.create_task(agent=agent, project=project, prompt="Inspect this fixture without changes.",
                                               mode="prompt", profile_name="audit-read-only")
                    base_config = runtime.config()
                    base_config["routing"]["jev"] = {"mode": "COOPERATIVE", "timeoutMs": 750,
                                                       "experimentalValidationOrder": True}
                    original = runtime._command_validation
                    observed = []
                    cancellation_returned = []
                    def cancel_at_boundary():
                        runtime.request_cancel(task)
                        cancellation_returned.append(True)
                        self.assertEqual(runtime.store.get_task(task)['state'], 'cancelling')
                        self.assertEqual(runtime.store.latest_run(task)['state'], 'succeeded')
                    def execute(name, command, cwd, timeout):
                        observed.append(name)
                        if cancel == 'check':
                            cancel_at_boundary()
                        return original(name, command, cwd, timeout)
                    from quattro_agent import runtime_milestones
                    original_milestone = runtime_milestones.run_validation_milestone
                    def milestone(*args, **kwargs):
                        if cancel == 'boundary':
                            cancel_at_boundary()
                        return original_milestone(*args, **kwargs)
                    # This uses real adapters, process supervision, completion and
                    # real git/unittest commands; only Jev and gateway are fixtures.
                    with mock.patch.object(runtime, "config", return_value=base_config), \
                         mock.patch.object(runtime, "_command_validation", side_effect=execute), \
                         mock.patch("quattro_agent.runtime_milestones.run_validation_milestone", side_effect=milestone), \
                         mock.patch("quattro_agent.provider_access.resolve_typesafe_credential", return_value=None):
                        self.assertEqual(runtime.run_task(task), 130 if cancel else 0)
                    records = [event["payload"] for event in runtime.store.display_events(task)
                               if event["type"] == "runtime.milestone"]
                    self.assertEqual(cancellation_returned, [True] if cancel else [])
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["agent"], agent)
                    self.assertEqual(records[0]["outcome"], "PASSTHROUGH")
                    self.assertFalse(records[0]["agent_reasoning_avoided"])
                    expected = ([] if cancel == 'boundary' else ['Git diff integrity'] if cancel == 'check'
                                else ['Git diff integrity', 'Quattro unit suite'])
                    self.assertEqual(observed, expected)
                    self.assertEqual(runtime.store.get_task(task)["state"], "cancelled" if cancel else "succeeded")
                finally:
                    fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
