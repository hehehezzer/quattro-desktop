"""Speculation preserves local authority, ownership and single-evaluation semantics."""
from pathlib import Path
import sys
import http.client
import json
import secrets
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from quattro_agent import routing_signals, turn_routing
from quattro_agent.jev import JevClient, JevFailure, MODEL
from quattro_agent.jev_shadow import current_evidence, lifecycle
from quattro_agent.model_registry import default_policy_path, load_model_registry


def authored_request():
    return {'schema_version': 'quattro-jev-decisions-v2', 'decision_id': 'inspect_context',
            'question': 'Should evidence be inspected before the next adjustment?',
            'options': [
                {'id': 'inspect_evidence', 'description': 'Inspect the available abstract evidence.', 'effect': 'inspect'},
                {'id': 'reason_locally', 'description': 'Use native reasoning to determine the next step.', 'effect': 'agent'}],
            'context': {'evidence_complete': False},
            'hard_constraints': {'retry_allowed': False, 'parallel_allowed': False, 'retrieval_allowed': False},
            'execution_state': {'revision': 1, 'phase': 'implementation', 'attempt': 0},
            'previous_result': 'none'}


def response():
    return {'model': MODEL, 'answers': {'decision': {
        'type': 'choice', 'choice': 'inspect_evidence', 'confidence': .96,
        'probabilities': {'inspect_evidence': .96, 'reason_locally': .04}}},
        'usage': {'input_tokens': 10, 'output_tokens': 2}}


class SpeculationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = load_model_registry(default_policy_path(),
            Path(__file__).parents[1] / 'src/quattro/omniroute-model-catalog.json')

    def route(self, **kwargs):
        return turn_routing.route_turn(
            request='Debug the repository regression and reproduce the root cause',
            config={'routing': {'jev': {'mode': 'COOPERATIVE', 'timeoutMs': 100}}},
            registry=self.registry, account='account-1', database=self.root / 'unused', **kwargs)

    def test_bootstrap_preserves_health_and_learned_work_without_provider(self):
        order = []
        def health(baseline):
            order.append('health')
            return ()
        def learned(*args):
            order.append('learned')
            return {'error': 'model_unavailable'}
        select = turn_routing.select_execution_target
        def candidate(*args, **kwargs):
            order.append('candidate')
            return select(*args, **kwargs)
        with mock.patch.object(JevClient, 'evaluate', side_effect=AssertionError('fixed provider question')) as start, \
             mock.patch.object(turn_routing, 'select_execution_target', side_effect=candidate), \
             mock.patch.object(routing_signals, 'learned_signal', side_effect=learned):
            routed = self.route(runtime_filter=health)
        self.assertEqual(order, ['health', 'candidate', 'learned'])
        start.assert_not_called()
        self.assertEqual(routed.decision.decision, 'DELEGATE')

    def test_static_shadow_provider_api_has_been_removed(self):
        from quattro_agent import jev_shadow
        for name in ('ShadowRun', 'start_shadow'):
            self.assertFalse(hasattr(jev_shadow, name))
        for name in ('start_signal_run', 'fuse'):
            self.assertFalse(hasattr(routing_signals, name))

    def test_local_runtime_failure_is_not_swallowed_by_optional_signals(self):
        with self.assertRaisesRegex(ValueError, 'runtime failed'):
            self.route(runtime_filter=mock.Mock(side_effect=ValueError('runtime failed')))

    def test_learned_evidence_cannot_change_host_bootstrap_plan(self):
        from test_jev import boundary, options
        from quattro_agent.routing import classify_pre_routing
        request = boundary()
        baseline = classify_pre_routing(pre_routing_input=request, config={})
        learned = {'prediction': 'DELEGATE', 'confidence': 1.0,
                   'model_version': 'synthetic_observation'}
        with mock.patch.object(routing_signals, 'learned_signal', return_value=learned):
            result = routing_signals.classify_with_signals(pre_routing_input=request,
                config=options(), database=self.root / 'unused', execution='DELEGATE',
                baseline_override=baseline)
        self.assertEqual(result, baseline)

    def test_routing_wall_time_has_no_provider_wait_or_claimed_rtt(self):
        @lifecycle
        def route():
            result = self.route()
            return result, current_evidence()
        result, evidence = route()
        self.assertEqual(evidence['jev_wait_ms'], 0)
        self.assertEqual(evidence['fusion_ms'], 0)
        self.assertFalse(evidence['jev_requested'])
        self.assertTrue(evidence['static_questionnaire_retired'])
        self.assertEqual(evidence['decision_boundary'], 'native_model_authored_operational')
        self.assertAlmostEqual(evidence['routing_critical_path_ms'], evidence['local_routing_ms'])
        self.assertLessEqual(evidence['routing_critical_path_ms'], result.routing_ms)
        self.assertNotIn('jev_rtt_ms', evidence)

    def test_request_timeout_and_decision_budget_validate_independently(self):
        from quattro_agent.config import validate_ai_config
        from quattro_agent.errors import ConfigError
        from test_harness_integration import HarnessRuntimeIntegrationTests
        fixture = HarnessRuntimeIntegrationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        config = fixture.runtime.config()
        config['routing'].pop('jev')
        normalized = validate_ai_config(config)
        self.assertEqual(normalized['routing']['jev']['timeoutMs'], 1500)
        for budget in (0, 25, 100, 3000):
            config['routing']['jev'] = {'mode': 'COOPERATIVE', 'timeoutMs': 1500, 'decisionWaitMs': budget}
            self.assertEqual(validate_ai_config(config)['routing']['jev']['decisionWaitMs'], budget)
        for budget in (-1, 3001, True, 1.5, '25'):
            config['routing']['jev']['decisionWaitMs'] = budget
            with self.assertRaises(ConfigError):
                validate_ai_config(config)

    def test_redirect_is_rejected_without_a_second_origin_request(self):
        connection = mock.Mock()
        reply = mock.MagicMock(status=302)
        reply.__enter__.return_value = reply
        connection.getresponse.return_value = reply
        with mock.patch('quattro_agent.jev.http.client.HTTPSConnection', return_value=connection):
            client = JevClient(secrets.token_hex(24), 1.5)
            with self.assertRaisesRegex(JevFailure, 'http_error'):
                client.evaluate(authored_request())
            client.close()
        self.assertEqual(connection.request.call_count, 1)
        reply.read.assert_not_called()
        connection.close.assert_called_once()

    def test_native_http_client_reuses_connection_and_closes_explicitly(self):
        connection = mock.Mock()
        def reply(body, status=200):
            result = mock.MagicMock(status=status)
            result.__enter__.return_value = result
            result.read.return_value = json.dumps(body).encode()
            return result
        connection.getresponse.side_effect = [reply({'models': [{'name': MODEL}]}), reply(response())]
        with mock.patch('quattro_agent.jev.http.client.HTTPSConnection', return_value=connection) as create:
            client = JevClient(secrets.token_hex(24), 1.5)
            result = client.evaluate(authored_request())
            client.close()
        create.assert_called_once_with('api.typesafe.ai', timeout=1.5)
        self.assertEqual(connection.request.call_count, 2)
        connection.close.assert_called_once()
        self.assertEqual(result['response']['model'], MODEL)

    def test_stale_connection_fails_without_duplicate_post_or_redirect(self):
        for failure in (http.client.RemoteDisconnected(), OSError()):
            connection = mock.Mock()
            connection.request.side_effect = failure
            with mock.patch('quattro_agent.jev.http.client.HTTPSConnection', return_value=connection):
                client = JevClient(secrets.token_hex(24), 1.5)
                with self.assertRaisesRegex(JevFailure, 'connection'):
                    client.evaluate(authored_request())
                client.close()
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()

    def test_lifecycle_restores_evidence_on_exception(self):
        from quattro_agent.jev_shadow import annotate, mark_dispatch, take_scope
        @lifecycle
        def fail():
            annotate(safe_marker=True)
            mark_dispatch()
            self.assertTrue(current_evidence()['dispatch_boundary_observed'])
            self.assertEqual(take_scope(), ())
            raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):
            fail()
        self.assertEqual(current_evidence(), {})


if __name__ == '__main__':
    unittest.main()
