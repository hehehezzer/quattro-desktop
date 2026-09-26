"""Hermetic runtime-advice contracts. No model or provider credentials required."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parent))
from quattro_agent.decision_taxonomy import ACTIONS, DETERMINISTIC, DecisionClass, classify_decision, validate_request
from quattro_agent.decision_service import DecisionSession
from quattro_agent.decision_mcp import handle, tool_spec
from quattro_agent.decision_launch import OPTIONS, NATIVE_PROXY, codex_arguments
from quattro_agent.jev import JevClient, JevFailure, MODEL
from quattro_agent.jev_shadow import lifecycle
from quattro_agent.adapters import AgentMode, CodexAdapter, RunSpec
from quattro_agent.policy import policy_profile


def request(name="validation_strategy", revision=0):
    return {"decision_type": name, "available_actions": list(ACTIONS[name]),
            "relevant_context": {"tests_available": True, "changes_present": True},
            "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
            "execution_state": {"revision": revision, "phase": "validation", "attempt": 1},
            "previous_result": "success"}


def answer(req, selected=None, confidence=0.99):
    actions = req["available_actions"]
    selected = selected or actions[0]
    return {"model": MODEL, "answers": {"decision": {
        "type": "choice", "choice": selected, "confidence": confidence,
        "probabilities": {action: 0.99 if action == selected else 0.01 / (len(actions) - 1) for action in actions},
    }}, "usage": {"input_tokens": 20, "output_tokens": 5}}


# The real subprocess/pipe lifecycle is exercised without network. The fake
# worker accepts the same bounded framing; all retained fixtures are categorical.
WORKER = r'''
import json,sys,time
setup=json.loads(sys.stdin.readline())
for line in sys.stdin:
 r=json.loads(line)
 time.sleep(DELAY)
 actions=r['available_actions']; chosen=actions[0]
 answer={'model':'jev-latest','answers':{'decision':{
 'type':'choice','choice':chosen,'confidence':CONFIDENCE,
 'probabilities':{a:0.99 if a==chosen else 0.01/(len(actions)-1) for a in actions}}},
 'usage':{'input_tokens':20,'output_tokens':5}}
 print(json.dumps({'response':answer,'jev_latency_ms':DELAY*1000,'catalog_latency_ms':0}),flush=True)
'''


class DecisionPlaneTests(unittest.TestCase):
    def session(self, *, delay=0, confidence=0.99, timeout_ms=1000, worker=None, mode="COOPERATIVE"):
        processes = []
        def popen(_argv, **kwargs):
            code = worker or WORKER.replace("DELAY", str(delay)).replace("CONFIDENCE", str(confidence))
            process = subprocess.Popen([sys.executable, "-c", code], **kwargs)
            processes.append(process)
            return process
        session = DecisionSession(mode=mode, timeout_ms=timeout_ms,
                                  credential=lambda: "synthetic", popen=popen)
        self.addCleanup(session.close)
        return session, processes

    def test_taxonomy_defaults_to_agent_and_never_selects_model(self):
        for name in DETERMINISTIC:
            self.assertEqual(classify_decision(name), DecisionClass.DETERMINISTIC)
        for name in ACTIONS:
            self.assertEqual(classify_decision(name), DecisionClass.JEV_ELIGIBLE)
        for name in ("root_cause", "new_unsupported_type", "select_omniroute_model"):
            self.assertEqual(classify_decision(name), DecisionClass.AGENT_REASONING)
        self.assertNotIn("model_selection", ACTIONS)
        self.assertNotIn("complete", {a for actions in ACTIONS.values() for a in actions})

    def test_schema_rejects_content_and_arbitrary_actions(self):
        for mutate in (
            lambda r: r.update(prompt="private text"),
            lambda r: r["relevant_context"].update(path="private path"),
            lambda r: r["available_actions"].append("shell command"),
            lambda r: r.update(decision_type="model_selection"),
            lambda r: r["execution_state"].update(revision=True),
            lambda r: r["hard_constraints"].update(retry_allowed="yes"),
        ):
            r = request()
            mutate(r)
            with self.assertRaises(JevFailure):
                validate_request(r)

    def test_one_worker_across_decisions_cache_revision_and_cleanup(self):
        session, processes = self.session()
        first = session.decide(request(), cacheable=True)
        self.assertFalse(first["fallback_required"])
        self.assertEqual(session.decide(request(), cacheable=True)["selected_action"], first["selected_action"])
        self.assertEqual(session.snapshot()["counts"]["cache_hits"], 1)
        second = session.decide(request(revision=1))
        self.assertFalse(second["fallback_required"])
        self.assertEqual(session.decide(request())["evidence"], "stale")
        self.assertEqual(len(processes), 1)
        self.assertIsNone(processes[0].poll())
        session.close()
        self.assertIsNotNone(processes[0].poll())
        session.close()
        self.assertEqual(session.decide(request(revision=2))["evidence"], "closed")

    def test_real_worker_parent_death_owner_survives_between_requests(self):
        worker_path = Path(__file__).parents[1] / 'src/quattro_agent/jev_worker.py'
        code = '''
import sys,runpy
sys.path.insert(0, DIRECTORY)
import jev
class FakeClient:
 def __init__(self,*args): pass
 def close(self): pass
 def evaluate_questions(self,state,questions,**kwargs):
  actions=state['available_actions']; choice=actions[0]
  return {'response':{'model':'jev-latest','answers':{'decision':{
   'type':'choice','choice':choice,'confidence':0.99,
   'probabilities':{a:0.99 if a==choice else 0.01/(len(actions)-1) for a in actions}}},
   'usage':{'input_tokens':1,'output_tokens':1}},'jev_latency_ms':0,'catalog_latency_ms':0}
jev.JevClient=FakeClient
sys.argv=[WORKER,'--session']
runpy.run_path(WORKER,run_name='__main__')
'''.replace('DIRECTORY', repr(str(worker_path.parent))).replace('WORKER', repr(str(worker_path)))
        session, processes = self.session(worker=code)
        self.assertFalse(session.decide(request())['fallback_required'])
        time.sleep(0.04)
        self.assertIsNone(processes[0].poll())
        self.assertFalse(session.decide(request(revision=1))['fallback_required'])
        self.assertEqual(len(processes), 1)

    def test_changed_context_invalidates_exact_request_cache(self):
        session, _ = self.session()
        session.decide(request(), cacheable=True)
        changed = request()
        changed["relevant_context"]["tests_available"] = False
        session.decide(changed, cacheable=True)
        self.assertEqual(session.snapshot()["counts"]["calls"], 2)

    def test_unverified_agent_revision_never_enables_cache(self):
        session, _ = self.session()
        session.decide(request())
        session.decide(request())
        self.assertEqual(session.snapshot()["counts"]["calls"], 2)
        self.assertNotIn("cache_hits", session.snapshot()["counts"])

    @unittest.skipUnless(os.name == 'posix', 'native turn telemetry uses POSIX ownership')
    def test_native_gate_both_frontends_and_stale_advice(self):
        from test_turn_gate import TurnGateTests
        from quattro_agent.turn_transport import TurnTransport
        from quattro_agent.decision_mcp import NativeDecisionProxy
        fixture = TurnGateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        gate = fixture.gate
        session, processes = self.session()
        gate.decisions = session
        transport = TurnTransport(gate).start()
        self.addCleanup(transport.close)
        proxy = NativeDecisionProxy()
        import http.client
        for endpoint in ('/turn', '/cancel', '/responses'):
            connection = http.client.HTTPConnection('127.0.0.1', transport.server.server_port, timeout=2)
            connection.request('POST', endpoint, '{}', {'Authorization': 'Bearer ' + transport.decision_token})
            self.assertEqual(connection.getresponse().status, 403)
            connection.close()
        connection = http.client.HTTPConnection('127.0.0.1', transport.server.server_port, timeout=2)
        connection.request('POST', '/decision', '{}', {'Authorization': 'Bearer ' + transport.token})
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()
        with mock.patch.dict('os.environ', {'QUATTRO_TURN_GATE_URL': transport.url,
                                           'QUATTRO_DECISION_TOKEN': transport.decision_token}):
            self.assertTrue(proxy.decide(request())["fallback_required"])
            for frontend in ('codex', 'pi'):
                turn = gate.begin('thread', 'Inspect the repository and run tests', frontend)
                plan = turn.plan
                self.assertFalse(proxy.decide(request())["fallback_required"])
                self.assertIs(turn.plan, plan)
                gate.finish(turn)
        self.assertEqual(len(processes), 1)
        turn = gate.begin('thread', 'Inspect the repository and run tests', 'codex')
        def become_stale(_request):
            gate.observe_runtime(turn)
            return {'selected_action': 'targeted_first', 'fallback_required': False}
        with mock.patch.object(session, 'decide', side_effect=become_stale):
            self.assertTrue(gate.decide(request())["fallback_required"])
        gate.finish(turn)

    def test_low_confidence_and_hard_policy_fall_back(self):
        session, _ = self.session(confidence=0.4)
        self.assertEqual(session.decide(request())["evidence"], "uncertain")
        session2, _ = self.session()
        self.assertEqual(session2.decide(request("retry_strategy"))["evidence"], "hard_policy")

    def test_timeout_is_bounded_and_worker_reaped(self):
        session, processes = self.session(delay=2, timeout_ms=100)
        begin = time.monotonic()
        result = session.decide(request())
        self.assertEqual(result["evidence"], "timeout")
        self.assertLess(time.monotonic() - begin, 1)
        session.close()
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(session.snapshot()["counts"]["deadline_misses"], 1)

    def test_caller_deadline_does_not_include_slow_owned_cleanup(self):
        session, processes = self.session(delay=2, timeout_ms=100)
        original = session.popen
        def delayed_wait(*args, **kwargs):
            process = original(*args, **kwargs)
            wait = process.wait
            def slow_wait(*args, **kwargs):
                time.sleep(0.4)
                return wait(*args, **kwargs)
            process.wait = slow_wait
            return process
        session.popen = delayed_wait
        started = time.monotonic()
        result = session.decide(request())
        self.assertEqual(result['evidence'], 'timeout')
        self.assertLess(time.monotonic() - started, 0.3)
        session.close()
        self.assertIsNotNone(processes[0].poll())
        self.assertFalse(session.capacity_owned)
        self.assertFalse(session.monitor.is_alive())

    def test_close_is_bounded_when_worker_wait_ignores_timeout(self):
        from quattro_agent.jev_shadow import _CAPACITY
        session, processes = self.session(delay=2, timeout_ms=100)
        release, entered = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = session.popen
        def blocking_wait(*args, **kwargs):
            process = original(*args, **kwargs)
            wait = process.wait
            def blocked(*args, **kwargs):
                entered.set()
                release.wait()
                return wait(*args, **kwargs)
            process.wait = blocked
            return process
        session.popen = blocking_wait
        with mock.patch.object(_CAPACITY, 'release', wraps=_CAPACITY.release) as capacity_release:
            self.assertEqual(session.decide(request())['evidence'], 'timeout')
            self.assertTrue(entered.wait(2))
            closer = threading.Thread(target=session.close, daemon=True)
            closer.start()
            closer.join(timeout=6)
            self.assertFalse(closer.is_alive())
            self.assertTrue(session.capacity_owned)
            self.assertEqual(session.decide(request())['evidence'], 'closed')
            self.assertEqual(len(processes), 1)
            release.set()
            session.monitor.join(timeout=2)
            self.assertFalse(session.monitor.is_alive())
            self.assertIsNone(session.process)
            self.assertFalse(session.capacity_owned)
            self.assertEqual(capacity_release.call_count, 1)

    def test_failed_wait_retains_process_until_close_reaps_it(self):
        session, processes = self.session()
        session.decide(request())
        process = processes[0]
        real_poll = process.poll
        with mock.patch.object(process, 'wait', side_effect=subprocess.TimeoutExpired('fixture', 2)), \
             mock.patch.object(process, 'poll', return_value=None):
            with self.assertRaises(subprocess.TimeoutExpired):
                session._stop_worker()
            self.assertIs(session.process, process)
            self.assertTrue(session.capacity_owned)
        session.close()
        self.assertIsNotNone(real_poll())
        self.assertFalse(session.capacity_owned)
        self.assertIsNone(session.process)

    def test_delayed_reap_is_observed_while_session_is_idle(self):
        session, processes = self.session(delay=2, timeout_ms=100)
        original = session.popen
        def delayed_death(*args, **kwargs):
            process = original(*args, **kwargs)
            poll, wait = process.poll, process.wait
            visible_death = time.monotonic() + 0.4
            process.poll = lambda: None if time.monotonic() < visible_death else poll()
            def delayed_wait(*args, **kwargs):
                if time.monotonic() < visible_death:
                    raise subprocess.TimeoutExpired('fixture', 0.1)
                return wait(*args, **kwargs)
            process.wait = delayed_wait
            return process
        session.popen = delayed_death
        self.assertEqual(session.decide(request())['evidence'], 'timeout')
        self.assertEqual(session.decide(request(revision=1))['evidence'], 'busy')
        until = time.monotonic() + 2
        while session.capacity_owned and time.monotonic() < until:
            time.sleep(0.01)
        self.assertFalse(session.capacity_owned)
        self.assertFalse(session.retiring)
        self.assertIsNone(session.process)
        self.assertEqual(len(processes), 1)

    def test_concurrency_is_single_flight_and_cancellation_interrupts(self):
        session, processes = self.session(delay=3, timeout_ms=3000)
        results = []
        thread = threading.Thread(target=lambda: results.append(session.decide(request())))
        thread.start()
        deadline = time.monotonic() + 2
        while not processes and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertTrue(processes)
        self.assertEqual(session.decide(request())["evidence"], "busy")
        session.close()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]["fallback_required"])
        self.assertIsNotNone(processes[0].poll())

    def test_malformed_worker_is_fail_open(self):
        worker = 'import sys;sys.stdin.readline();sys.stdin.readline();print("{}",flush=True)'
        session, processes = self.session(worker=worker)
        result = session.decide(request())
        self.assertTrue(result["fallback_required"])
        self.assertEqual(result["evidence"], "schema_mismatch")
        self.assertIsNotNone(processes[0].poll())

    def test_authentication_failures_open_the_existing_bounded_circuit(self):
        worker = 'import sys;sys.stdin.readline();sys.stdin.readline();print(\'{"failure_category":"authentication"}\',flush=True)'
        session, processes = self.session(worker=worker)
        for revision in range(3):
            self.assertEqual(session.decide(request(revision=revision))['evidence'], 'authentication')
        self.assertEqual(session.decide(request(revision=3))['evidence'], 'circuit_open')
        self.assertEqual(len(processes), 3)
        self.assertTrue(all(process.poll() is not None for process in processes))

    def test_off_and_missing_credential_never_launch(self):
        for mode in ("OFF", "SHADOW"):
            session = DecisionSession(mode=mode, credential=mock.Mock(), popen=mock.Mock())
            self.addCleanup(session.close)
            self.assertEqual(session.decide(request())["evidence"], "disabled")
            session.credential.assert_not_called()
            session.popen.assert_not_called()
        session = DecisionSession(mode="COOPERATIVE", credential=lambda: None, popen=mock.Mock())
        self.addCleanup(session.close)
        self.assertEqual(session.decide(request())["evidence"], "missing_credential")
        session.popen.assert_not_called()

    def test_budget_completion_and_telemetry(self):
        session, _ = self.session()
        r = request("progress_strategy")
        r["execution_state"]["phase"] = "completion"
        result = session.decide(r)
        self.assertIn(result["selected_action"], ACTIONS["progress_strategy"])
        session.MAX_CALLS = 1
        self.assertEqual(session.decide(request(revision=1))["evidence"], "budget")
        telemetry = session.snapshot()
        self.assertIsNone(telemetry["cost"])
        self.assertIsNone(telemetry["model_turns_avoided"])
        self.assertEqual(telemetry["calls_by_type"], {"progress_strategy": 1})
        self.assertEqual(telemetry["counts"]["input_tokens"], 20)
        self.assertGreater(result["timing"]["blocking_ms"], 0)
        self.assertEqual(result["timing"]["useful_overlap_ms"], 0)

    def test_catalog_verified_once_only_for_explicit_session_client(self):
        opener = mock.Mock()
        opener.open.side_effect = [io.BytesIO(json.dumps(body).encode()) for body in (
            {"models": [{"name": MODEL}]}, answer(request()), answer(request()))]
        client = JevClient("synthetic", 1, opener=opener)
        from quattro_agent.decision_taxonomy import question
        for _ in range(2):
            client.evaluate_questions(request(), question(request()), reuse_catalog=True)
        self.assertEqual(opener.open.call_count, 3)
        paths = [call.args[0].full_url for call in opener.open.call_args_list]
        self.assertEqual(paths.count("https://api.typesafe.ai/v1/models"), 1)

    def test_mcp_is_advice_only_and_handles_real_request(self):
        session, _ = self.session()
        init = handle({"id": 1, "method": "initialize"}, session)
        self.assertEqual(set(init["result"]["capabilities"]), {"tools"})
        self.assertEqual(tool_spec()["name"], "operational_decision")
        result = handle({"id": 2, "method": "tools/call", "params": {
            "name": "operational_decision", "arguments": request()}}, session)
        content = json.loads(result["result"]["content"][0]["text"])
        self.assertFalse(content["fallback_required"])
        self.assertNotIn("model", content)
        self.assertEqual(handle({"id": 3, "method": "execute"}, session)["error"]["code"], -32601)

    def test_harness_scope_registers_only_permitted_codex_tool_and_restores(self):
        # The policy's '/' read root is the current volume on Windows. Keep
        # this fixture on that volume rather than granting cross-drive access.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary).resolve()
            class Owner:
                def config(self):
                    return {"routing": {"jev": {"mode": "COOPERATIVE", "timeoutMs": 1500}}}
                @lifecycle
                def launch(self, policy_name):
                    spec = RunSpec(task_id="task", run_id="run", project_path=root,
                                   mode=AgentMode.PROMPT, policy=policy_profile(policy_name, project_root=root),
                                   account_home=root, private_input="synthetic", model_override="fixed-route")
                    return CodexAdapter().build_launch("codex", spec)
            self.assertIsNone(OPTIONS.get())
            owner = Owner()
            launch = owner.launch("workspace-write")
            self.assertTrue(any("mcp_servers.quattro_decisions" in arg for arg in launch.argv))
            self.assertIn("fixed-route", launch.argv)
            self.assertIsNone(OPTIONS.get())
            restricted = owner.launch("audit-read-only")
            self.assertFalse(any("mcp_servers.quattro_decisions" in arg for arg in restricted.argv))
            self.assertEqual(codex_arguments(policy_profile("workspace-write", project_root=root)), ())
            token = NATIVE_PROXY.set({'QUATTRO_TURN_GATE_URL': 'http://127.0.0.1:1',
                                      'QUATTRO_DECISION_TOKEN': 'synthetic-decision-only'})
            try:
                launch = owner.launch('audit-read-only')
                self.assertTrue(any('--native-proxy' in arg for arg in launch.argv))
                self.assertNotIn('QUATTRO_TURN_GATE_TOKEN', launch.environment_overrides)
                self.assertEqual(launch.environment_overrides['QUATTRO_DECISION_TOKEN'], 'synthetic-decision-only')
                self.assertNotIn('synthetic-decision-only', str(launch.argv))
            finally:
                NATIVE_PROXY.reset(token)


if __name__ == "__main__":
    unittest.main()
