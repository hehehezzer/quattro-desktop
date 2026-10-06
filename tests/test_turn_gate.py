"""Hermetic per-turn routing, budgets, privacy, and locked transport contracts."""
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quattro_agent.model_registry import ModelTarget
from quattro_agent.turn_gate import TurnGate
from quattro_agent.turn_transport import TurnTransport


class TurnGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        registry = tuple(ModelTarget(
            f'account-1/{name}', 'codex', 'account-1', name,
            frozenset({'conversation', 'coding', 'git', 'repository_read', 'repository_write',
                       'shell', 'tool_calling', 'reasoning', 'long_context'}),
            frozenset({tier}), 200000, rank, rank,
        ) for rank, (name, tier) in enumerate((('luna', 'FAST'), ('terra', 'STANDARD'), ('sol', 'REASONING'))))
        self.gate = TurnGate(session_id='session-test', config={}, directory=self.path,
                            telemetry_path=self.path/'events', account='account-1', registry=registry)
        self.addCleanup(self.gate.cancel_all)

    def dynamic_request(self, **changes):
        request = {
            "schema_version": "quattro-jev-decisions-v2",
            "decision_id": "inspect_uncertainty",
            "question": "Should the next step resolve the missing invariant evidence?",
            "options": [
                {"id": "examine_preconditions", "description": "Inspect the missing invariant before selecting the next action.", "effect": "inspect"},
                {"id": "native_judgement", "description": "Use native semantic reasoning when evidence is insufficient.", "effect": "agent"},
            ],
            "context": {"evidence_gap": True, "context_sufficiency": "partial"},
            "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
            "execution_state": {"revision": 123, "phase": "assessment", "attempt": 0},
            "previous_result": "missing_evidence",
        }
        request.update(changes)
        return request

    def test_model_authored_gate_request_preserves_context_and_host_revision(self):
        self.gate._decision_options = {"mode": "COOPERATIVE"}
        self.gate.decisions.close()
        service = Mock()
        service.closed = threading.Event()
        service.decide.return_value = {"selected_action": "examine_preconditions", "selected_effect": "inspect",
            "confidence": .95, "fallback_required": False}
        service.snapshot.return_value = {"counts": {"accepted": 1}}
        self.gate.decisions = service
        turn = self.gate.begin('thread', 'Inspect the repository invariant and run checks', 'pi')
        request = self.dynamic_request()
        original = json.loads(json.dumps(request))
        result = self.gate.decide(request)
        self.assertFalse(result["fallback_required"])
        sent = service.decide.call_args.args[0]
        self.assertEqual(sent["context"], original["context"])
        self.assertEqual(sent["question"], original["question"])
        self.assertEqual(sent["options"], original["options"])
        self.assertEqual(sent["execution_state"]["revision"], self.gate._decision_revision)
        self.assertNotEqual(sent["execution_state"]["revision"], 123)
        self.assertEqual(service.decide.call_args.kwargs["capabilities"], frozenset())
        self.assertIs(service.decide.call_args.kwargs["cancelled"].__self__, turn.cancel_event)
        self.assertEqual(request, original)
        self.assertEqual(turn.initial_context_reuse, 0)
        self.gate.finish(turn)
        trace = self.path.joinpath('events').read_text()
        for private in (request["question"], "examine_preconditions", "context_sufficiency"):
            self.assertNotIn(private, trace)

    def test_managed_gate_cannot_attest_an_invented_native_tool(self):
        from quattro_agent.decision_taxonomy import allowed_action
        self.gate._decision_options = {"mode": "COOPERATIVE"}
        self.gate.decisions.close()
        service = Mock()
        service.closed = threading.Event()
        def decide(request, *, capabilities, cancelled):
            permitted = allowed_action(request, "compress_status", capabilities=capabilities)
            return {"fallback_required": not permitted, "evidence": "hard_policy" if not permitted else "choice"}
        service.decide.side_effect = decide
        service.snapshot.return_value = {}
        self.gate.decisions = service
        turn = self.gate.begin('thread', 'Inspect the repository invariant and run checks', 'codex')
        request = self.dynamic_request()
        request["options"][0] = {"id": "compress_status", "description": "Use bounded compression for the available status operation.", "effect": "rtk", "capability": "rtk.git"}
        self.assertEqual(self.gate.decide(request)["evidence"], "hard_policy")
        self.gate.finish(turn)

    def test_dynamic_gate_discards_advice_after_runtime_revision_changes(self):
        self.gate._decision_options = {"mode": "COOPERATIVE"}
        self.gate.decisions.close()
        service = Mock()
        service.closed = threading.Event()
        service.snapshot.return_value = {}
        self.gate.decisions = service
        turn = self.gate.begin('thread', 'Inspect the repository invariant and run checks', 'pi')
        def decide(_request, **_kwargs):
            self.gate.observe_runtime(turn)
            return {"fallback_required": False, "selected_action": "examine_preconditions"}
        service.decide.side_effect = decide
        result = self.gate.decide(self.dynamic_request())
        self.assertTrue(result["fallback_required"])
        self.assertEqual(turn.decision_outcomes["stale"], 1)
        self.gate.finish(turn)

    def test_legacy_gate_request_is_rejected_before_decision_service(self):
        service = Mock()
        self.gate.decisions.close()
        self.gate.decisions = service
        result = self.gate.decide({
            "schema_version": "quattro-operational-decisions-v1",
            "decision_type": "test_recovery", "relevant_context": {},
        })
        self.assertTrue(result["fallback_required"])
        service.decide.assert_not_called()

    def test_requested_cases_independent_of_frontend(self):
        cases = (
            ('What is an API gateway?', 'DIRECT'),
            ("What's my OmniRoute dashboard password?", 'DIRECT'),
            ('Explain this Python traceback', 'DIRECT'),
            ('Search this repository for the auth implementation and explain why login fails', 'DELEGATE'),
            ('Fix the authentication issue, run tests, commit it and open a PR', 'DELEGATE'),
            ('What is a git commit?', 'DIRECT'),
            ('Explain how to read files', 'DIRECT'),
            ('Please explain how to run tests', 'DIRECT'),
            ('Explain this, then refactor the module', 'DELEGATE'),
        )
        for frontend in ('codex', 'pi'):
            for prompt, expected in cases:
                with self.subTest(frontend=frontend, prompt=prompt):
                    turn = self.gate.begin('thread', prompt, frontend)
                    self.assertEqual(turn.decision, expected)
                    if expected == 'DIRECT':
                        self.assertEqual(turn.plan.target.tier, 'FAST')
                        self.assertEqual(turn.plan.required_tools, ())
                        self.assertEqual(turn.plan.context.retrieval_budget_tokens, 0)
                        self.assertEqual(turn.budget, 20)
                    else:
                        self.assertIsNone(turn.budget)
                    self.gate.finish(turn)

    def test_persistent_session_refreshes_and_expires_plans(self):
        plans = []
        for prompt in ('What is an API gateway?', 'Fix the code and run tests', 'What does that mean?'):
            turn = self.gate.begin('same-thread', prompt, 'codex')
            plans.append(turn.plan)
            self.assertIs(self.gate.by_plan(turn.plan.plan_id), turn)
            self.gate.finish(turn)
            with self.assertRaises(ValueError):
                self.gate.by_plan(turn.plan.plan_id)
        self.assertEqual(len({p.plan_id for p in plans}), 3)
        self.assertEqual([p.target.tier for p in plans][::2], ['FAST', 'FAST'])
        with self.assertRaises(Exception):
            plans[0].plan_id = 'replacement'

    def test_native_context_requires_a_planned_delegate(self):
        turn = self.gate.begin(
            'thread', 'Inspect this attachment', 'codex',
            requires_native_delegate=True,
        )
        self.assertEqual(turn.decision, 'DELEGATE')
        self.assertIsNone(turn.budget)
        self.assertEqual(turn.routing_evidence['final_decision']['execution'], 'DELEGATE')
        self.gate.finish(turn)

    def test_concurrent_thread_guard_and_cancellation(self):
        first = self.gate.begin('thread', 'Hello', 'codex')
        with self.assertRaises(ValueError):
            self.gate.begin('thread', 'Another', 'codex')
        second = self.gate.begin('second', 'Hello', 'codex')
        self.gate.cancel_thread('thread')
        with self.assertRaises(TimeoutError):
            self.gate.by_plan(first.plan.plan_id)
        self.assertIs(self.gate.by_plan(second.plan.plan_id), second)
        self.gate.finish(first, status='interrupted')
        self.gate.finish(second)

    def test_sensitive_lookup_has_no_transport_or_lifecycle(self):
        turn = self.gate.begin('thread', "What's my OmniRoute dashboard password?", 'codex')
        with patch.object(self.gate, '_request', side_effect=AssertionError('transport entered')):
            self.assertIn('No approved local credential lookup', self.gate.direct(turn))
        self.gate.finish(turn)
        events = self.path.joinpath('events').read_text()
        self.assertNotIn('password', events)
        self.assertNotIn('prompt', events)
        self.assertFalse(json.loads(events.splitlines()[-1])['agent_lifecycle'])
        lookup = self.gate.begin('thread', 'Search files for my stored password', 'codex')
        self.assertEqual(lookup.decision, 'DIRECT')
        self.assertTrue(lookup.sensitive)
        self.gate.finish(lookup)

    def test_secret_values_rejected_before_persistent_delegate(self):
        with self.assertRaises(ValueError):
            self.gate.begin('thread', 'Edit the repository ' + 'api_key' + '=' + 'sk-' + 'x'*40, 'codex')
        self.assertEqual(self.gate._active, {})

    def test_budget_and_no_stale_context(self):
        turn = self.gate.begin('thread', 'Hello', 'codex')
        turn.started -= 21
        with self.assertRaises(TimeoutError):
            self.gate.remaining(turn)
        self.gate.finish(turn, status='failed')
        self.gate.remember('thread', 'What did you change?', 'Updated the login handler.')
        self.assertEqual(len(self.gate._history['thread']), 2)

        self.gate.remember('thread', 'api_key' + '=' + 'sk-' + 'x'*40, 'private')
        self.assertEqual(len(self.gate._history['thread']), 2)

    def test_stale_cancel_does_not_cancel_new_request(self):
        turn = self.gate.begin('thread', 'Hello', 'pi', params={'request_id':'new'})
        self.gate.cancel_thread('thread', 'old')
        self.assertFalse(turn.cancel_event.is_set())
        self.gate.cancel_thread('thread', 'new')
        self.assertTrue(turn.cancel_event.is_set())
        self.gate.finish(turn, status='interrupted')

    def test_receipt_pending_polls_within_budget_and_validates_final_target(self):
        turn = self.gate.begin('thread', 'Hello', 'codex')
        pending = {'plan_id': turn.plan.plan_id, 'status': 'pending'}
        final = {'plan_id': turn.plan.plan_id, 'success': True,
                 'actual_provider': turn.plan.target.provider,
                 'actual_account': turn.plan.target.account,
                 'actual_model': turn.plan.target.model,
                 'actual_route': turn.plan.target.route}
        with patch.object(self.gate, '_request', side_effect=[
            (Mock(), io.BytesIO(json.dumps(row).encode())) for row in (pending, final)
        ]) as request:
            self.gate.verify_receipt(turn)
            self.assertEqual(request.call_count, 2)
        with patch.object(self.gate, '_request', side_effect=lambda *_args: (
            Mock(), io.BytesIO(json.dumps(pending).encode())
        )) as request:
            with self.assertRaisesRegex(RuntimeError, 'receipt failed verification'):
                self.gate.verify_receipt(turn)
            self.assertEqual(request.call_count, 4)
        self.gate.finish(turn)

    def test_receipt_rejects_malformed_oversized_and_mismatched_results(self):
        turn = self.gate.begin('thread', 'Hello', 'codex')
        for raw in (b'[]', b'null', b'{', b' ' * 128001,
                    b'{"plan_id":"wrong","status":"pending"}',
                    json.dumps({'plan_id': turn.plan.plan_id, 'success': True,
                                'actual_model': 'wrong'}).encode()):
            with self.subTest(size=len(raw)), patch.object(
                self.gate, '_request', return_value=(Mock(), io.BytesIO(raw))
            ) as request:
                with self.assertRaisesRegex(RuntimeError, 'receipt failed verification'):
                    self.gate.verify_receipt(turn)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(turn.failure_code, 'locked_receipt_mismatch')
        self.gate.cancel(turn)
        with patch.object(self.gate, '_request') as request:
            with self.assertRaises(TimeoutError):
                self.gate.verify_receipt(turn)
            request.assert_not_called()
        self.gate.finish(turn, status='interrupted')

    def test_transport_uses_fixed_approved_endpoint_despite_environment_change(self):
        turn = self.gate.begin('thread', 'Hello', 'codex')
        for scheme, connection_class in (('http', 'HTTPConnection'), ('https', 'HTTPSConnection')):
            with patch('quattro_agent.turn_gate.APPROVED_BASE_URL',
                       f'{scheme}://127.0.0.1:23456/api/v1'), \
                 patch.dict(os.environ, {'QUATTRO_OMNIROUTE_BASE_URL': 'https://invalid.example/api/v1'}), \
                 patch('quattro_agent.turn_gate.http.client.' + connection_class) as factory:
                factory.return_value.getresponse.return_value.status = 200
                conn, _ = self.gate._request(turn, 'GET', '/routing/locked-receipts')
                self.assertEqual(factory.call_args.args, ('127.0.0.1', 23456))
                self.assertEqual(conn.request.call_args.args[1], '/api/v1/routing/locked-receipts')
        self.gate.finish(turn)

    def test_hard_budget_interrupts_slow_stream_without_waiting_for_newline(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Slow(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                self.send_response(200)
                self.end_headers()
                try:
                    for _ in range(100):
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        time.sleep(.02)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Slow)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with patch('quattro_agent.turn_gate.BUDGETS', {'FAST': .15}), \
             patch('quattro_agent.turn_gate.validate_omniroute_runtime_capabilities'), \
             patch('quattro_agent.turn_gate.APPROVED_BASE_URL',
                   f'http://127.0.0.1:{server.server_port}/api/v1'):
            turn = self.gate.begin('thread', 'Hello', 'codex')
            started = time.monotonic()
            with self.assertRaises((TimeoutError, OSError, RuntimeError)):
                self.gate.direct(turn)
            self.assertLess(time.monotonic() - started, 1.5)
            self.gate.finish(turn, status='failed')

    def test_transport_requires_authorization_and_cancellation_nonce(self):
        server = TurnTransport(self.gate).start()
        self.addCleanup(server.close)
        conn = http.client.HTTPConnection('127.0.0.1', server.server.server_port)
        conn.request('POST', '/turn', '{}', {'Content-Type':'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        conn.close()
        headers = {'Authorization':'Bearer '+server.token, 'Content-Type':'application/json'}
        for endpoint, body in (
            ('/cancel', {'session_id':'thread', 'request_id':'cancel-before-start'}),
            ('/turn', {'frontend':'pi', 'session_id':'thread', 'request_id':'cancel-before-start',
                       'prompt':'Fix the code and run tests'}),
        ):
            conn = http.client.HTTPConnection('127.0.0.1', server.server.server_port)
            conn.request('POST', endpoint, json.dumps(body), headers)
            response = conn.getresponse()
            self.assertEqual(response.status, 200 if endpoint == '/cancel' else 502)
            response.read()
            conn.close()
        self.assertEqual(self.gate._active, {})

    def test_failed_receipt_never_reaches_native_model_client(self):
        from unittest.mock import Mock
        turn = self.gate.begin('thread', 'Inspect this repository', 'codex')
        server = TurnTransport(self.gate).start()
        self.addCleanup(server.close)
        fake = Mock()
        fake.read1.side_effect = [b'data: secret-tool-call\n\n', b'']
        with patch('quattro_agent.turn_transport.validate_omniroute_runtime_capabilities'), \
             patch.object(self.gate, '_request', return_value=(Mock(), fake)), \
             patch.object(self.gate, 'verify_receipt', side_effect=RuntimeError('private provider detail')):
            conn = http.client.HTTPConnection('127.0.0.1', server.server.server_port)
            conn.request('POST', '/responses', '{}', {
                'Authorization':'Bearer '+server.token,
                'x-codex-turn-metadata':json.dumps({'quattro_plan_id':turn.plan.plan_id}),
            })
            response = conn.getresponse()
            self.assertEqual(response.status, 502)
            self.assertNotIn(b'secret-tool-call', response.read())
            conn.close()
        self.gate.finish(turn, status='failed', agent_lifecycle=True)


if __name__ == '__main__':
    unittest.main()
