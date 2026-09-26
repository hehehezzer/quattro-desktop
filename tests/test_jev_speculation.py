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
from quattro_agent.jev import JevClient, JevFailure, MODEL, serialize_state
from test_jev import response
from quattro_agent.jev_shadow import ShadowRun, current_evidence, lifecycle
from quattro_agent.model_registry import default_policy_path, load_model_registry


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

    def test_worker_starts_before_health_and_learned_work_without_duplicate(self):
        order = []
        completed = threading.Event()
        run = mock.Mock(started=time.perf_counter(), timeout_ms=100, done=completed,
                        record={'status': 'failed'})
        def start(**kwargs):
            order.append('jev')
            return run
        def health(baseline):
            self.assertEqual(order, ['jev'])
            order.append('health')
            completed.set()
            return ()
        def learned(*args):
            order.append('learned')
            return {'error': 'model_unavailable'}
        select = turn_routing.select_execution_target
        def candidate(*args, **kwargs):
            order.append('candidate')
            return select(*args, **kwargs)
        with mock.patch.object(routing_signals, 'start_shadow', side_effect=start) as start_mock, \
             mock.patch.object(turn_routing, 'select_execution_target', side_effect=candidate), \
             mock.patch.object(routing_signals, 'learned_signal', side_effect=learned):
            routed = self.route(runtime_filter=health)
        self.assertEqual(order, ['jev', 'health', 'candidate', 'learned'])
        self.assertEqual(start_mock.call_count, 1)
        self.assertEqual(routed.decision.decision, 'DELEGATE')
        run.close.assert_not_called()

    def test_failed_start_is_not_retried_at_fusion(self):
        with mock.patch.object(routing_signals, 'start_shadow', return_value=None) as start:
            self.route()
        self.assertEqual(start.call_count, 1)

    def test_local_runtime_failure_is_not_swallowed_by_optional_signals(self):
        with mock.patch.object(routing_signals, 'start_shadow', return_value=None), \
             self.assertRaisesRegex(ValueError, 'runtime failed'):
            self.route(runtime_filter=mock.Mock(side_effect=ValueError('runtime failed')))

    def test_request_deadline_is_not_restarted_after_local_preparation(self):
        done = mock.Mock()
        done.wait.return_value = False
        run = mock.Mock(started=time.perf_counter() - 1, timeout_ms=100, done=done,
                        record={'status': 'failed'})
        with mock.patch.object(routing_signals, 'start_shadow', return_value=run):
            self.route()
        done.wait.assert_called_once_with(0)
        run.close.assert_not_called()

    def test_dispatch_budget_can_expire_without_provider_timeout(self):
        done = mock.Mock()
        done.wait.return_value = False
        run = mock.Mock(started=time.perf_counter(), timeout_ms=1500, done=done,
                        record={'status': 'pending'})
        @lifecycle
        def route():
            config = {'routing': {'jev': {'mode': 'COOPERATIVE', 'timeoutMs': 1500,
                                         'decisionWaitMs': 0}}}
            with mock.patch.object(routing_signals, 'start_shadow', return_value=run):
                turn_routing.route_turn(
                    request='Debug the repository regression and reproduce the root cause',
                    config=config, registry=self.registry, account='account-1', database=self.root / 'unused')
            return current_evidence()
        evidence = route()
        done.wait.assert_called_once_with(0)
        run.close.assert_not_called()
        self.assertTrue(evidence['jev_wait_budget_expired'])
        self.assertEqual(run.record['status'], 'pending')

    def test_routing_wall_time_is_not_reported_as_jev_rtt(self):
        @lifecycle
        def route():
            result = self.route()
            return result, current_evidence()
        with mock.patch.object(routing_signals, 'start_shadow', return_value=None):
            result, evidence = route()
        self.assertAlmostEqual(evidence['routing_critical_path_ms'],
            evidence['local_routing_ms'] + evidence['jev_wait_ms'] + evidence['fusion_ms'])
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
                client.evaluate(serialize_state('hello'))
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
            result = client.evaluate(serialize_state('hello'))
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
                    client.evaluate(serialize_state('hello'))
                client.close()
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()

    def test_overlap_is_actual_interval_intersection_not_elapsed_minus_wait(self):
        run = ShadowRun(database=self.root / 'evidence', request='', decision='DELEGATE',
                        record_id=None, source_task_id=None, authoritative_tier=None, timeout_ms=100)
        run.done.set()
        run.thread = mock.Mock()
        run.record.update(jev_request_started=10.0, jev_request_finished=10.4)
        run.annotations.update(local_preparation_started=9.0, local_preparation_finished=10.1)
        with mock.patch('quattro_agent.jev_shadow.persist', return_value=True):
            run.close()
        self.assertAlmostEqual(run.record['jev_overlap_ms'], 100)
        self.assertLessEqual(run.record['jev_overlap_ms'], 400)


if __name__ == '__main__':
    unittest.main()
