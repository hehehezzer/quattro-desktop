"""Hermetic model-authored native decision and Pi host lifecycle contracts."""
from __future__ import annotations

import json
import io
import importlib
import sys
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from quattro_agent import native_intelligence as native
from quattro_agent.decision_mcp import dynamic_tool_schema
from quattro_agent.decision_taxonomy import DYNAMIC_SCHEMA_VERSION, dynamic_schema

ROOT = Path(__file__).resolve().parents[1]


def dynamic_request():
    return {
        "schema_version": DYNAMIC_SCHEMA_VERSION,
        "decision_id": "current_evidence_gap",
        "question": "Should compressed repository inspection precede broader evidence gathering?",
        "options": [
            {"id": "compressed_inspection", "description": "Inspect existing repository evidence using available compression.",
             "effect": "rtk", "capability": "rtk.git"},
            {"id": "reason_from_evidence", "description": "Use native reasoning when evidence does not support a bounded choice.", "effect": "agent"},
        ],
        "context": {"evidence_gap": True, "inspection_count": 2},
        "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": True},
        "execution_state": {"revision": 0, "phase": "evidence_reconciliation", "attempt": 0},
        "previous_result": "partial_evidence",
    }


class DynamicNativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = mock.patch.dict(os.environ, {
            "QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(self.root / "native.json"),
            "QUATTRO_NATIVE_TELEMETRY_DB": str(self.root / "events.sqlite3"),
            "QUATTRO_STATE_DIR": str(self.root / "state"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.calls = []

        class FakeSession:
            revision = -1
            def snapshot(inner):
                return {"counts": {"calls": len(self.calls)}}
            def decide(inner, request, **kwargs):
                self.calls.append((request, kwargs))
                inner.revision = request["execution_state"]["revision"]
                return {"selected_action": "compressed_inspection", "selected_effect": "rtk",
                        "confidence": .97, "evidence": "native_choice_probabilities",
                        "fallback_required": False, "called": True}
            def close(inner):
                pass

        self.session = FakeSession()
        self.context = native.NativeContext(host="pi", session_id="synthetic-session")

    def test_arbitrary_decision_phase_and_options_reach_evaluator(self):
        result = native.native_jev_advice(dynamic_request(), context=self.context,
            settings=native.NativeSettings(legacy_categories_ignored=True), decision_session=self.session,
            capabilities={"rtk.git": True, "tool.unobserved": "yes"})
        self.assertTrue(result["usageEvidence"]["accepted"])
        request, kwargs = self.calls[0]
        self.assertEqual(request["question"], dynamic_request()["question"])
        self.assertEqual(request["execution_state"]["phase"], "evidence_reconciliation")
        self.assertEqual(kwargs["capabilities"], ("rtk.git",))
        evidence = json.dumps(native.NativeTelemetry().trace("synthetic-session"))
        for private_content in ("compressed_inspection", "current_evidence_gap", "evidence_gap",
                                dynamic_request()["question"], "partial_evidence"):
            self.assertNotIn(private_content, evidence)
        self.assertIn('"selectedAction": "rtk"', evidence)

    def test_revision_binding_changes_with_full_question_and_host_capabilities(self):
        request = dynamic_request()
        for capabilities in ({"rtk.git": True}, {"rtk.git": True}, {}):
            native.native_jev_advice(request, context=self.context,
                decision_session=self.session, capabilities=capabilities)
        changed = dict(request, question="Should wider verification precede the next bounded implementation step?")
        native.native_jev_advice(changed, context=self.context,
            decision_session=self.session, capabilities={})
        self.assertEqual([item[0]["execution_state"]["revision"] for item in self.calls], [1, 1, 2, 3])

    def test_invalid_content_and_session_off_never_call_provider(self):
        invalid = dynamic_request()
        invalid["context"] = {"command": "private_data"}
        self.assertTrue(native.native_jev_advice(invalid, context=self.context,
            decision_session=self.session)["fallback_required"])
        result = native.native_jev_advice(dynamic_request(),
            context=native.NativeContext(session_enabled=False), decision_session=self.session)
        self.assertEqual(result["evidence"], "session_preference_off")
        self.assertEqual(self.calls, [])

    def test_managed_and_native_mcp_share_canonical_dynamic_schema(self):
        from quattro_intelligence_mcp import TOOLS
        spec = next(item for item in TOOLS if item["name"] == "operational_decision")
        self.assertEqual(dynamic_tool_schema(), dynamic_schema())
        self.assertEqual(spec["inputSchema"], dynamic_schema())

    def test_managed_discovery_never_claims_other_mcp_tools(self):
        from quattro_agent.decision_mcp import handle
        class NoProvider:
            def decide(self, *_args, **_kwargs):
                raise AssertionError("discovery called evaluator")
        response = handle({"id": 1, "method": "tools/call", "params": {
            "name": "decision_capabilities", "arguments": {}}}, NoProvider())
        snapshot = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(snapshot["capabilities"], {})
        self.assertFalse(snapshot["rtk"]["available"])
        self.assertFalse(snapshot["host"]["grants_permissions"])

    def test_diagnostic_probe_requires_authoring_before_any_activity(self):
        from quattro_agent import native_cli
        with (mock.patch.object(native_cli, "native_jev_advice") as evaluator,
              mock.patch.object(native_cli, "search_knowledge") as retrieval,
              mock.patch.object(native_cli, "rtk_status") as rtk,
              mock.patch.object(native_cli, "decision_capabilities") as capabilities):
            result = native_cli.native_probe(None)
        self.assertEqual(result["reason"], "native_authoring_required")
        for action in (evaluator, retrieval, rtk, capabilities):
            action.assert_not_called()

    def test_diagnostic_private_stdin_rejects_oversize_and_duplicate_keys(self):
        from quattro_agent.native_cli import read_authored_decision
        from quattro_agent.decision_taxonomy import MAX_REQUEST_BYTES
        valid = dynamic_request()
        self.assertEqual(read_authored_decision(io.BytesIO(json.dumps(valid).encode())), valid)
        for raw in (b"x" * (MAX_REQUEST_BYTES + 1),
                    b'{"schema_version":"quattro-jev-decisions-v2","schema_version":"bad"}'):
            with self.assertRaises(ValueError):
                read_authored_decision(io.BytesIO(raw))

    def test_benchmark_authored_sequence_has_no_defaults_or_retries_or_raw_report(self):
        with mock.patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
            benchmark = importlib.import_module("benchmark_jev_live")
            transport = importlib.import_module("benchmark_jev_transport")
        authored = dynamic_request()
        sequence = [authored, dict(authored, decision_id="different_evidence_gap")]
        self.assertEqual(benchmark.read_authored_decisions(io.BytesIO(json.dumps(sequence).encode())), sequence)
        for raw in (b"[]", b"{}", b"[" + b",".join([json.dumps(authored).encode()] * 65) + b"]"):
            with self.assertRaises(Exception):
                benchmark.read_authored_decisions(io.BytesIO(raw))
        calls = []
        class Session:
            def __init__(inner, **_kwargs):
                pass
            def decide(inner, request, **_kwargs):
                calls.append(request)
                return {"selected_action": "compressed_inspection", "selected_effect": "rtk",
                        "fallback_required": False, "evidence": "native_choice_probabilities", "called": True,
                        "timing": {"blocking_ms": 1, "worker_roundtrip_ms": 1}}
            def close(inner):
                pass
        output = io.StringIO()
        with (mock.patch.object(benchmark, "typesafe_credential_status", return_value="configured"),
              mock.patch.object(benchmark, "DecisionSession", Session),
              mock.patch.object(sys, "stdin", io.BytesIO(json.dumps(sequence).encode())),
              mock.patch.object(sys, "stdout", output),
              mock.patch.object(sys, "argv", ["benchmark", "--decisions-stdin"])):
            self.assertEqual(benchmark.main(), 0)
        self.assertEqual(len(calls), 2)
        report = output.getvalue()
        self.assertEqual(json.loads(report)["provider_retries"], 0)
        for content in (authored["question"], "compressed_inspection", "different_evidence_gap", "evidence_gap"):
            self.assertNotIn(content, report)
        calls.clear()
        class Client:
            def __init__(inner, *_args, **_kwargs):
                inner.connect_ms = []
                inner.versions = set()
            def evaluate(inner, request):
                calls.append(request)
                return {"jev_latency_ms": 1, "catalog_latency_ms": 1, "response": {"model": "jev-test"}}
            def close(inner):
                pass
        output = io.StringIO()
        with (mock.patch.object(transport, "resolve_typesafe_credential", return_value="synthetic"),
              mock.patch.object(transport, "JevClient", Client),
              mock.patch.object(transport, "ExperimentalClient", Client),
              mock.patch.object(sys, "stdin", io.BytesIO(json.dumps(sequence).encode())),
              mock.patch.object(sys, "stdout", output),
              mock.patch.object(sys, "argv", ["transport", "--decisions-stdin"])):
            transport.main()
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(output.getvalue())["provider_retries"], 0)
        self.assertNotIn(authored["question"], output.getvalue())

    @unittest.skipUnless(shutil.which("node"), "Node is required for Pi extension contracts")
    def test_pi_model_authors_questions_after_host_snapshot_and_at_successive_milestones(self):
        helper = self.root / "quattro-intelligence"
        request_log = self.root / "requests.jsonl"
        helper.write_text("#!/usr/bin/python3\nTEST_LOG = " + repr(str(request_log)) + "\n" + '''import json, os, sys
for line in sys.stdin:
    envelope = json.loads(line)
    with open(TEST_LOG, "a") as output:
        output.write(json.dumps(envelope) + "\\n")
    name = envelope["name"]
    arguments = envelope["arguments"]
    value = {"recorded": True}
    if name == "decision_capabilities":
        value = {"capabilities": {"rtk.git": True}, "available_tools": ["rtk_run"]}
    if name == "operational_decision":
        value = {"selected_action": arguments["options"][0]["id"], "selected_effect": "inspect",
                 "fallback_required": False, "traceId": "synthetic-advice",
                 "usageEvidence": {"requested": True, "accepted": True, "traceId": "synthetic-advice"}}
    print(json.dumps({"id": envelope["id"], "result": value}), flush=True)
''')
        helper.chmod(0o700)
        script = r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
let source = readFileSync(process.argv[1], 'utf8');
source = source.replace('import { Type } from "typebox";', 'const Type = new Proxy({}, {get: (_, name) => (...args) => ({name, args})});');
source = stripTypeScriptTypes(source, {mode:'transform'});
const {default: install} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const handlers = {}, tools = {};
const pi = {on:(name, fn) => (handlers[name] ||= []).push(fn), registerTool: t => tools[t.name] = t,
 registerCommand: () => {}, getActiveTools: () => ['operational_decision','decision_capabilities','rtk_run','read'],
 appendEntry: () => {}};
const ctx = {cwd:process.cwd(), mode:'print', sessionManager:{getSessionId:()=> 'synthetic-pi',getBranch:()=>[]},ui:{setStatus:()=>{}}};
install(pi);
assert.ok(tools.decision_capabilities);
assert.ok(tools.operational_decision.description.includes('author'));
for (const command of [['git','status'],['git','status','--short'],['git','diff','--check']]) {
 const guarded = await handlers.tool_call[0]({toolName:'rtk_run',input:{command},toolCallId:'inspection'},ctx);
 assert.equal(guarded,undefined);
}
const unsafe = await handlers.tool_call[0]({toolName:'rtk_run',input:{command:['git','status','--config=arbitrary']},toolCallId:'opaque'},ctx);
assert.equal(unsafe.block,true);
for (const fn of handlers.session_start) await fn({},ctx);
const result = await handlers.before_agent_start[0]({prompt:'Inspect relevant evidence before verifying behavior.',systemPrompt:'native'},ctx);
assert.ok(result.systemPrompt.includes('decision-specific'));
assert.ok(result.message.content[0].text.includes('rtk.git'));
const base = {schema_version:'quattro-jev-decisions-v2', decision_id:'synthetic_choice', question:'Should bounded inspection precede verification?',
 options:[{id:'inspect_first',description:'Inspect narrowly relevant evidence before verification.',effect:'inspect'},
 {id:'reason_first',description:'Use native reasoning when evidence is uncertain.',effect:'agent'}],
 context:{gap:true},hard_constraints:{retry_allowed:false,parallel_allowed:false,retrieval_allowed:false},
 execution_state:{revision:0,phase:'evidence_stage',attempt:0},previous_result:'none'};
await tools.operational_decision.execute('one',base,undefined,undefined,ctx);
await tools.operational_decision.execute('two',{...base,question:'Should verification precede the next bounded implementation?',options:[{id:'verify_now',description:'Verify the changed behavior before further implementation.',effect:'validate'},base.options[1]],execution_state:{...base.execution_state,revision:1}},undefined,undefined,ctx);
for (const fn of handlers.session_shutdown) await fn({},ctx);
console.log('dynamic lifecycle contracts passed');
'''
        environment = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ.get("PATH", ""),
                           DYNAMIC_NATIVE_TEST_LOG=str(request_log))
        completed = subprocess.run([shutil.which("node"), "--disable-warning=ExperimentalWarning", "--input-type=module", "-e", script,
                                    str(ROOT / "adapters/pi/quattro-intelligence.ts")],
                                   env=environment, capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        requests = [json.loads(line) for line in request_log.read_text().splitlines()]
        names = [item["name"] for item in requests]
        self.assertNotIn("jev_advice", names)
        authored = [item["arguments"] for item in requests if item["name"] == "operational_decision"]
        self.assertEqual(len(authored), 2)
        self.assertNotEqual(authored[0]["question"], authored[1]["question"])
        self.assertIn("rtk_run", authored[0]["__quattro_host_tools"])


if __name__ == "__main__":
    unittest.main()
