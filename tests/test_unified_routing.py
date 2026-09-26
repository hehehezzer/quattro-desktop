"""Invariants spanning native UI, canonical routing, and downstream plan ingestion."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from quattro_agent import turn_routing
from quattro_agent.intelligence.classical import DirectDelegateModel, ALGORITHM
from quattro_agent.intelligence.store import FEATURE_SCHEMA_VERSION
from quattro_agent.jev_shadow import ShadowRun
from quattro_agent.turn_gate import TurnGate
from quattro_agent.model_registry import load_model_registry, default_policy_path
from test_jev import FakeProcess, response, options

SRC = Path(__file__).parents[1] / 'src'


class UnifiedRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = load_model_registry(default_policy_path(), SRC / 'quattro/omniroute-model-catalog.json')
        self.gate = TurnGate(session_id='unified', config=options('COOPERATIVE'), directory=self.root,
                             telemetry_path=self.root / 'turns.jsonl', account='account-1', registry=self.registry)
        self.addCleanup(self.gate.cancel_all)

    def test_normalization_is_not_secret_detection(self):
        for prompt in ('Explain this log: \x1b[31merror', 'Explain ' + 'x' * 33_000):
            with self.subTest(length=len(prompt)):
                self.assertFalse(turn_routing.extract_turn_features(prompt).sensitive)
        secret_assignment = 'password=' + secrets.token_hex(16)
        for prompt in (secret_assignment, 'Bearer ' + secrets.token_hex(16),
                       'https://' + 'fixture:example' + '@example.test',
                       'Explain ' + 'x' * 33_000 + ' ' + secret_assignment):
            self.assertTrue(turn_routing.extract_turn_features(prompt).sensitive)

    def test_low_complexity_guard_prevents_shadow_start(self):
        from dataclasses import replace
        features = turn_routing.extract_turn_features('Modify the repository parser')
        profile = json.loads(features.profile_json)
        profile.update(complexity='low', tier='STANDARD')
        features = replace(features, profile_json=json.dumps(profile))
        with mock.patch('quattro_agent.routing_signals.start_shadow') as start:
            routed = turn_routing.route_turn(
                request=features.request, features=features, config=options('COOPERATIVE'),
                registry=self.registry, account='account-1', database=self.root / 'unused',
            )
        self.assertEqual(routed.fast_guard, 'conclusive_requirements')
        start.assert_not_called()

    def test_uncomputed_signal_does_not_suppress_telemetry_shadow(self):
        from quattro_agent.jev_shadow import lifecycle, annotate, current_learned_signal
        @lifecycle
        def check(error):
            annotate(learned_signal={'error': error})
            return current_learned_signal()
        self.assertIsNone(check('off'))
        self.assertIsNone(check('fast_guard'))
        self.assertEqual(check('model_unavailable'), {'error': 'model_unavailable'})

    def test_signal_eligibility_is_checked_before_spawning(self):
        from dataclasses import replace
        from quattro_agent.routing_signals import classify_with_signals
        from quattro_agent.routing_intelligence import make_pre_routing_input
        from quattro_agent.routing import RoutingDecision, RoutingTier
        original = turn_routing.extract_turn_features('Modify the repository parser')
        for complexity, model, tier in [('low', 'auto', RoutingTier.STANDARD),
                                        ('high', 'manual', RoutingTier.STANDARD),
                                        ('high', 'auto', RoutingTier.REASONING)]:
            state = json.loads(original.state_json)
            state['complexity'] = complexity
            features = replace(original, state_json=json.dumps(state))
            baseline = RoutingDecision(tier, 'fixture', 'medium',
                                       task_profile=json.loads(original.profile_json))
            request = make_pre_routing_input(
                request=original.request, working_directory='', repository_present=False,
                explicit_model=model, routing_mode='auto', agent='codex',
                workflow='prompt', policy_name='workspace-write',
            )
            for mode in ('SHADOW', 'COOPERATIVE'):
                with mock.patch('quattro_agent.routing_signals.start_shadow') as start:
                    result = classify_with_signals(
                        pre_routing_input=request, config=options(mode), database=self.root / 'unused',
                        execution='DELEGATE', baseline_override=baseline, canonical_features=features,
                    )
                start.assert_not_called()
                self.assertEqual(result, baseline)

    def test_each_turn_extracts_and_builds_exactly_once(self):
        for prompt in ('What does TUI mean?', 'Modify the repository parser', 'Explain this traceback'):
            with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}), \
                 mock.patch.object(turn_routing, 'extract_turn_features', wraps=turn_routing.extract_turn_features) as extract, \
                 mock.patch.object(turn_routing, 'extract_decision_features', wraps=turn_routing.extract_decision_features) as signals, \
                 mock.patch.object(turn_routing, 'profile_task', wraps=turn_routing.profile_task) as profile, \
                 mock.patch.object(turn_routing, 'classify_task_request', wraps=turn_routing.classify_task_request) as gate, \
                 mock.patch.object(turn_routing, 'build_execution_plan', wraps=turn_routing.build_execution_plan) as build:
                turn = self.gate.begin('thread', prompt, 'codex')
                self.gate.finish(turn)
                self.assertEqual((extract.call_count, signals.call_count, profile.call_count, gate.call_count, build.call_count),
                                 (1, 1, 1, 1, 1))

    def test_conclusive_direct_never_calls_jev_or_learned_in_any_mode(self):
        for mode in ('OFF', 'SHADOW', 'COOPERATIVE'):
            self.gate.config = options(mode)
            for frontend in ('codex', 'pi'):
                for prompt in ('Hi', 'What does TUI mean?', 'What is an API gateway?',
                               'Explain this traceback', "What's my dashboard password?"):
                    with self.subTest(mode=mode, frontend=frontend, prompt=prompt), \
                         mock.patch.object(ShadowRun, 'start', side_effect=AssertionError('remote classification')) as start, \
                         mock.patch('quattro_agent.routing_signals.learned_signal', side_effect=AssertionError('local inference')) as local:
                        turn = self.gate.begin('thread', prompt, frontend)
                        self.assertEqual(turn.decision, 'DIRECT')
                        self.assertEqual(turn.plan.required_tools, ())
                        self.assertEqual(turn.plan.context.retrieval_budget_tokens, 0)
                        self.assertEqual(turn.shadow_runs, ())
                        self.gate.finish(turn)
                        start.assert_not_called()
                        local.assert_not_called()
        self.assertFalse((self.root / 'intelligence').exists())

    def test_resume_and_direct_delegate_direct_use_fresh_plans(self):
        self.gate.config = options('OFF')
        self.gate.import_history('thread', [{'role': 'user', 'content': 'Earlier work'},
                                          {'role': 'assistant', 'content': 'Earlier answer'}])
        plans = []
        for prompt, expected in [('What does TUI mean?', 'DIRECT'), ('Modify the repository parser', 'DELEGATE'),
                                 ('What is an API gateway?', 'DIRECT')]:
            turn = self.gate.begin('thread', prompt, 'pi')
            self.assertEqual(turn.decision, expected)
            plans.append(turn.plan)
            self.gate.finish(turn, tools_used=expected == 'DELEGATE', agent_lifecycle=expected == 'DELEGATE')
            with self.assertRaises(ValueError):
                self.gate.by_plan(turn.plan.plan_id)
        self.assertEqual(len({p.plan_id for p in plans}), 3)
        with self.assertRaises(FrozenInstanceError):
            plans[0].reasoning_effort = 'high'
        rows = [json.loads(line) for line in self.gate.telemetry_path.read_text().splitlines()]
        completed = [r for r in rows if r['status'] == 'completed']
        self.assertEqual([r['agent_lifecycle'] for r in completed], [False, True, False])
        for row in completed:
            self.assertEqual(row['plan_id'], row['routing']['plan_id'])
            self.assertIn('feature_extraction_ms', row['routing'])
            self.assertIn('fast_guard_result', row['routing'])
            self.assertIn('target_selection_ms', row['routing'])
            self.assertNotIn('Earlier answer', json.dumps(row))

    def test_feature_projection_is_immutable_and_local_model_does_not_reextract(self):
        features = turn_routing.extract_turn_features('Modify the repository parser')
        with self.assertRaises(FrozenInstanceError):
            features.state_json = '{}'
        projection = features.local_projection()
        projection['complexity'] = 'high'
        self.assertNotEqual(projection, features.local_projection())
        model = DirectDelegateModel({
            'algorithm': ALGORITHM, 'feature_version': FEATURE_SCHEMA_VERSION,
            'feature_set': 'safe_metadata', 'vocabulary': {}, 'idf': [],
            'weights': [0] * 10, 'intercept': 1, 'numeric_means': [0] * 10,
            'numeric_scales': [1] * 10,
        })
        with mock.patch('quattro_agent.intelligence.classical.project_model_input', side_effect=AssertionError('double extraction')):
            prediction = model.predict(features.local_projection()['request_text'], model_input=features.local_projection())
        self.assertEqual(prediction['prediction'], 'DELEGATE')
        for name in ('production_decision', 'selected_model', 'selected_worker', 'reasoning_effort', 'outcome'):
            self.assertNotIn(name, features.state_json)
            self.assertNotIn(name, features.local_projection())

    def test_ambiguous_direct_can_receive_capability_signal_without_becoming_agent(self):
        original = ShadowRun.__init__
        class DirectHigh(FakeProcess):
            result = {'response': response(execution='DIRECT', complexity='HIGH', capability='STRONG'),
                      'failure_category': None, 'jev_latency_ms': 12.0}
        def init(run, **kwargs):
            original(run, **kwargs, popen=DirectHigh)
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': secrets.token_hex(24)}), \
             mock.patch.object(ShadowRun, '__init__', init):
            turn = self.gate.begin('thread', 'Maybe a strategy for current information and architecture trade-offs is needed', 'codex')
            self.assertEqual(turn.decision, 'DIRECT')
            self.assertEqual(turn.routing_evidence['fast_guard_result'], 'eligible')
            self.assertEqual(turn.plan.target.tier, 'REASONING')
            self.assertEqual(turn.plan.required_tools, ())
            self.assertEqual(len(turn.shadow_runs), 1)
            self.gate.finish(turn)

    def test_supplied_plan_is_consumed_without_any_request_classifier(self):
        import test_harness_integration as fixtures
        fixture = fixtures.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.gate.config = options('OFF')
        turn = self.gate.begin('thread', 'Inspect the repository files', 'pi')
        with mock.patch.object(turn_routing, 'extract_turn_features', side_effect=AssertionError('duplicate extraction')), \
             mock.patch('quattro_harness.extract_turn_features', side_effect=AssertionError('duplicate extraction')), \
             mock.patch('quattro_harness.profile_task', side_effect=AssertionError('duplicate profile')), \
             mock.patch('quattro_harness.route_turn', side_effect=AssertionError('duplicate routing')), \
             mock.patch('quattro_harness.record_routing_telemetry', side_effect=AssertionError('duplicate observation')):
            task_id = fixture.runtime.create_task(
                agent='codex', project=fixture.project, prompt=turn.prompt, mode='prompt',
                profile_name='audit-read-only', turn_execution_plan=turn.plan,
            )
        stored = fixture.runtime.store.get_task(task_id, include_private=True)
        self.assertEqual(stored['private_payload']['executionPlan'], turn.plan.to_dict())
        self.gate.finish(turn)

    def test_off_eligible_turn_does_not_add_native_learned_inference(self):
        self.gate.config = options('OFF')
        with mock.patch('quattro_agent.routing_signals.learned_signal', side_effect=AssertionError('OFF inference')):
            turn = self.gate.begin('thread', 'Debug the repository regression and reproduce the root cause', 'codex')
            self.assertEqual(turn.routing_evidence['learned_signal']['error'], 'off')
            self.gate.finish(turn)

    def test_explicit_target_cannot_bypass_account_health(self):
        from quattro_agent.errors import ConfigError
        with self.assertRaises(ConfigError):
            turn_routing.route_turn(request='Hello', config=options('OFF'), database=self.root / 'unused',
                registry=self.registry, account='account-1', selected_model='account-1/gpt-5.6-luna',
                unavailable_routes=frozenset({'account-1/gpt-5.6-luna'}))

    def test_all_disabled_accounts_are_not_reenabled_by_default(self):
        from quattro_agent.errors import ConfigError
        config = options('OFF')
        config['accounts'] = [{'id': 'account-1', 'enabled': False}]
        with self.assertRaises(ConfigError):
            turn_routing.route_turn(request='Hello', config=config, database=self.root / 'unused',
                registry=self.registry, account='account-1')

    def test_native_turn_reads_existing_health_without_heavy_runtime(self):
        self.gate.config = options('OFF')
        first = self.gate.begin('thread', 'Hello', 'codex')
        failed_route = first.plan.target.route
        self.gate.finish(first)
        health = self.root / 'routing/account-health.json'
        health.parent.mkdir()
        health.write_text(json.dumps({'routes': {failed_route: {'expiresAt': '2099-01-01T00:00:00+00:00'}}}))
        second = self.gate.begin('thread', 'Hello', 'codex')
        self.assertNotEqual(first.plan.target.route, second.plan.target.route)
        self.gate.finish(second)
        self.assertEqual(len(turn_routing.active_account_health(health)), 1)

    def test_harness_direct_keeps_minimal_semantics_and_no_eager_fallback_plan(self):
        import test_harness_integration as fixtures
        fixture = fixtures.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with mock.patch.object(fixture.runtime, '_send_omniroute_response', return_value=(
                {'output_text': 'Hello', 'usage': {}},
                {'provider': 'cx', 'account': 'account-1', 'model': 'gpt-5.6-luna',
                 'route': 'account-1/gpt-5.6-luna', 'cost': None})), \
             mock.patch.object(fixture.runtime, '_locked_target_receipt',
                               side_effect=fixture._direct_locked_receipt('account-1/gpt-5.6-luna')), \
             mock.patch.object(fixture.runtime, '_fallback_plan', side_effect=AssertionError('eager fallback')), \
             mock.patch.object(fixture.runtime, '_retrieval_context', side_effect=AssertionError('DIRECT retrieval')), \
             mock.patch.object(turn_routing, 'build_execution_plan', wraps=turn_routing.build_execution_plan) as build, \
             mock.patch('quattro_agent.intelligence.telemetry.shadow_predict',
                        return_value={'error': 'model_unavailable'}) as shadow:
            result = fixture.runtime.direct_response(project=fixture.project, prompt='Hello')
        shadow.assert_called_once()
        self.assertEqual(build.call_count, 1)
        plan = result['routingSnapshot']['execution_plan']
        self.assertEqual(plan['executionType'], 'DIRECT')
        self.assertEqual(plan['tools']['required'], [])
        self.assertEqual(plan['context']['retrievalBudgetTokens'], 0)

    def test_pre_route_failure_releases_only_owned_coordination(self):
        import test_harness_integration as fixtures
        from quattro_agent.errors import ConfigError
        fixture = fixtures.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        runtime = fixture.runtime
        task_id = runtime.create_task(agent='codex', project=fixture.project,
                                      prompt='Inspect repository files', mode='prompt')
        private = runtime.store.get_task(task_id, include_private=True)['private_payload']
        session = private['coordinationSessionId']
        runtime.coordinator.finish(session, validation='Not Run', abandoned=True)
        for extra, expected in [({}, 'rollback'),
                                ({'logical_session_id': private['logicalSessionId']}, 'finish'),
                                ({'parent_task_id': task_id}, 'neither')]:
            error = ConfigError('fixture routing failure')
            with mock.patch.object(runtime, '_pre_route', side_effect=error), \
                 mock.patch.object(runtime.coordinator, 'rollback_reservation',
                                   wraps=runtime.coordinator.rollback_reservation) as rollback, \
                 mock.patch.object(runtime.coordinator, 'finish',
                                   wraps=runtime.coordinator.finish) as finish:
                with self.assertRaises(ConfigError) as caught:
                    runtime.create_task(agent='codex', project=fixture.project,
                                        prompt='Inspect repository files', mode='prompt', **extra)
                self.assertIs(caught.exception, error)
                self.assertEqual(rollback.call_count, int(expected == 'rollback'))
                self.assertEqual(finish.call_count, int(expected == 'finish'))

    def test_credential_rejection_precedes_reservation(self):
        import test_harness_integration as fixtures
        from quattro_agent.errors import ConfigError
        fixture = fixtures.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with mock.patch.object(fixture.runtime.coordinator, 'reserve') as reserve:
            with self.assertRaises(ConfigError):
                fixture.runtime.create_task(agent='codex', project=fixture.project,
                                            prompt='find the API key in the config', mode='prompt')
            reserve.assert_not_called()

    def test_harness_protected_request_stays_local(self):
        import test_harness_integration as fixtures
        fixture = fixtures.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        with mock.patch.object(fixture.runtime, '_send_omniroute_response', side_effect=AssertionError('credential dispatch')), \
             mock.patch.object(fixture.runtime, 'codex_preflight', side_effect=AssertionError('credential preflight')), \
             mock.patch('quattro_harness.build_adaptive_decision', side_effect=AssertionError('credential filter')):
            result = fixture.runtime.direct_response(project=fixture.project, prompt="What's my dashboard password?")
        self.assertTrue(result['localHandling'])
        self.assertIsNone(result['model'])
        self.assertEqual(fixture.runtime.store.list_display_tasks(), [])

    def test_native_delegation_rejects_consumed_and_expired_plans(self):
        from quattro_agent import native_session
        self.gate.config = options('OFF')
        runtime = mock.Mock()
        runtime.create_task.return_value = 'task-one'
        runtime.run_task.return_value = 0
        runtime._child_output_path.return_value = self.root / 'missing-output'
        factory = mock.Mock(return_value=runtime)
        turn = self.gate.begin('thread', 'Inspect repository files', 'pi')
        def wait(*args, **kwargs):
            self.gate.delegate(turn)
            with self.assertRaises(ValueError):
                self.gate.delegate(turn)
            self.gate.finish(turn)
            with self.assertRaises(ValueError):
                self.gate.delegate(turn)
            return 0
        child = mock.Mock()
        child.wait.side_effect = wait
        child.poll.return_value = 0
        with mock.patch.object(native_session, 'TurnGate', return_value=self.gate), \
             mock.patch.object(native_session, 'TurnTransport'), \
             mock.patch.object(native_session.subprocess, 'Popen', return_value=child):
            code = native_session.launch_routed_native(agent='pi', binary='pi', command=['pi'], env={},
                config=self.gate.config, directory=self.root, session_id='smoke', account='account-1',
                state_root=self.root, runtime_factory=factory)
        self.assertEqual(code, 0)
        factory.assert_called_once()
        runtime.create_task.assert_called_once()
        runtime.run_task.assert_called_once()

    def test_prompt_feature_handoff_is_not_reanalyzed(self):
        import test_harness_integration as fixtures
        fixture = fixtures.HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        features = turn_routing.extract_turn_features('Modify the repository parser')
        with mock.patch('quattro_harness.extract_turn_features', side_effect=AssertionError('duplicate extraction')), \
             mock.patch.object(turn_routing, 'extract_turn_features', side_effect=AssertionError('duplicate extraction')), \
             mock.patch.object(turn_routing, 'build_execution_plan', wraps=turn_routing.build_execution_plan) as build:
            task_id = fixture.runtime.create_task(agent='codex', project=fixture.project,
                prompt=features.request, mode='prompt', routing_features=features)
        self.assertEqual(build.call_count, 1)
        self.assertIsNotNone(fixture.runtime.store.get_task(task_id))


if __name__ == '__main__':
    unittest.main()
