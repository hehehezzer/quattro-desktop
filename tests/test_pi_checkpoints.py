"""Real Pi extension callbacks with the shared helper and a synthetic evaluator."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(os.environ.get("QUATTRO_TEST_NATIVE_BUNDLE", "/nonexistent"))
JITI = BUNDLE / "node_modules/@earendil-works/pi-coding-agent/node_modules/jiti/lib/jiti.cjs"


@unittest.skipUnless(JITI.is_file() and (BUNDLE / "bin/node").is_file(), "set QUATTRO_TEST_NATIVE_BUNDLE for audited Pi fixture dependencies")
class PiCheckpointTests(unittest.TestCase):
    def test_100_distinct_real_callbacks_and_helper_projection(self):
        self._callbacks(config_enabled=False, environment="1")

    def test_persisted_opt_in_and_explicit_environment_disable(self):
        self._callbacks(config_enabled=True, environment=None)
        self._callbacks(config_enabled=True, environment="0", expected=0)

    def _callbacks(self, *, config_enabled, environment, expected=100):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stub = root / "typebox.cjs"
            stub.write_text("exports.Type = new Proxy({}, { get: () => (...args) => ({}) });")
            config = root / "native.json"
            config.write_text(json.dumps(dict(enabled=True, operationalEnabled=True, checkpointsEnabled=config_enabled)))
            helper = root / "quattro-intelligence"
            helper.write_text('''#!/usr/bin/python3
import json,sys
from pathlib import Path
sys.path.insert(0, SOURCE)
from quattro_agent import operational_native
from quattro_agent.shared_intelligence import server_main
def evaluate(request, **kwargs):
    with open(RECORD, "a") as stream:
        stream.write(json.dumps(request) + "\\n")
    return dict(selected_action=request["available_actions"][0], confidence=.99,
                called=True, evidence="native_choice_probabilities", fallback_required=False)
operational_native.native_jev_advice = evaluate
raise SystemExit(server_main())
'''.replace("SOURCE", repr(str(ROOT / "src"))).replace("RECORD", repr(str(root / "requests.jsonl"))))
            helper.chmod(0o700)
            runner = root / "run.cjs"
            runner.write_text('''const assert = require('node:assert/strict');
const {createJiti} = require(process.argv[2]);
const jiti = createJiti(__filename,{alias:{typebox:process.argv[4]},fsCache:false,moduleCache:false});
const hooks={};
const pi={on:(n,cb)=>(hooks[n]??=[]).push(cb),registerTool:()=>{},registerCommand:()=>{},appendEntry:()=>{}};
const ctx={cwd:process.cwd(),mode:'api',sessionManager:{getSessionId:()=> 'synthetic',getBranch:()=>[]}};
jiti(process.argv[3]).default(pi);
(async()=>{try {
 for(let i=0;i<100;i++) {
  const event={toolName:'read',toolCallId:'synthetic-'+i,input:{path:'fixture-'+i},isError:i>0,
    content:[{type:'text',text:'synthetic-'+i}]};
  const replies=[];
  for(const cb of hooks.tool_result) {const r=await cb(event,ctx);if(r) replies.push(r);}
  assert.equal(replies.filter(r=>r.content?.some(p=>p.text?.startsWith('Optional checkpoint advice:'))).length,Number(process.env.EXPECT_CHECKPOINTS));
 }
 console.log('100 Pi callbacks and shared-helper consultations passed');
} finally {for(const cb of hooks.session_shutdown) await cb({},ctx);}})().catch(e=>{console.error(e);process.exitCode=1});
''')
            env = {"PATH": str(root), "HOME": str(root), "EXPECT_CHECKPOINTS": "1" if expected else "0",
                   "QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(config), "QUATTRO_NATIVE_TELEMETRY_DB": str(root / "trace.sqlite3")}
            if environment is not None:
                env["QUATTRO_JEV_CHECKPOINTS"] = environment
            result = subprocess.run([str(BUNDLE / "bin/node"), str(runner), str(JITI),
                str(ROOT / "adapters/pi/quattro-intelligence.ts"), str(stub)], cwd=root, env=env,
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            if not expected:
                self.assertFalse((root / "requests.jsonl").exists())
                return
            requests = [json.loads(line) for line in (root / "requests.jsonl").read_text().splitlines()]
            self.assertEqual(len(requests), 100)
            self.assertEqual(len({r["execution_state"]["revision"] for r in requests}), 100)
            self.assertEqual(requests[0]["decision_type"], "progress_strategy")
            self.assertTrue(all(r["decision_type"] == "retry_strategy" for r in requests[1:]))
            self.assertNotIn("fixture-", json.dumps(requests))
            self.assertNotIn("scope_id", json.dumps(requests))
