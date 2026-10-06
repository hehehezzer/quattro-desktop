"""Hermetic OMP launch and actual extension callback regression coverage."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from quattro_agent.omp_bridge import (bridge_contract, extension_path, native_policy_overlay,
                                      omp_arguments)


class OMPBridgeTests(unittest.TestCase):
    def test_launch_route_and_approval_are_explicit(self):
        argv = omp_arguments("/opt/omp/bin/omp", config_overlay="/tmp/policy.json")
        self.assertEqual(argv[:9], ["/opt/omp/bin/omp", "--provider", "openai-codex", "--model",
                                   "gpt-6.1-sol", "--thinking", "medium", "--approval-mode", "always-ask"])
        self.assertEqual(argv[-2:], ["--extension", str(extension_path())])
        self.assertFalse(any(flag in argv for flag in ("--yolo", "--auto-approve", "--no-skills")))

    def test_prompt_cannot_introduce_flags(self):
        prompt = "--yolo $(touch forbidden)"
        argv = omp_arguments("omp", config_overlay="/tmp/policy.json", prompt=prompt)
        self.assertEqual(argv[-2:], ["--", prompt])

    def test_invalid_executable_and_paths_are_rejected(self):
        for executable in ("", "omp --yolo", "relative/bin/omp", "omp\0"):
            with self.subTest(executable=executable), self.assertRaises(ValueError):
                omp_arguments(executable, config_overlay="/tmp/policy.json")
        for overlay in ("", "relative.json", "\0"):
            with self.subTest(overlay=overlay), self.assertRaises(ValueError):
                omp_arguments("omp", config_overlay=overlay)

    def test_skills_use_supported_native_directories(self):
        policy = native_policy_overlay(skill_roots=["/tmp/skills", "/tmp/skills", "/tmp/other"])
        self.assertEqual(policy["skills"]["customDirectories"], ["/tmp/skills", "/tmp/other"])
        self.assertTrue(policy["skills"]["enableCodexUser"])
        with self.assertRaises(ValueError):
            native_policy_overlay(skill_roots=["relative"])

    def test_native_commands_require_approval_and_subagents_stay_unavailable(self):
        policy = native_policy_overlay()["tools"]
        self.assertEqual(policy["approvalMode"], "always-ask")
        for tool in ("bash", "rtk_run"):
            self.assertEqual(policy["approval"][tool], "prompt")
        for tool in ("eval", "task", "computer"):
            self.assertEqual(policy["approval"][tool], "deny")
        contract = bridge_contract()
        self.assertEqual(contract["decisionAuthority"], "quattro")
        self.assertFalse(contract["adviceGrantsPermission"])
        self.assertEqual(contract["headlessApproval"], "required_prompt_fails_closed")

    @unittest.skipUnless(shutil.which("node"), "Node is needed for actual TypeScript callback fixture")
    def test_actual_omp_callbacks_and_private_helper(self):
        version = subprocess.run([shutil.which("node"), "--version"], capture_output=True,
                                 text=True, timeout=5, check=True).stdout
        if int(version.lstrip("v").split(".")[0]) < 24:
            self.skipTest("Node 24 supports the audited TypeScript callback fixture")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "quattro_agent"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "shared_intelligence.py").write_text('''import json, os, sys
assert sys.argv[1:] == ['--server']
assert 'QUATTRO_TEST_PRIVATE_MARKER' not in os.environ
for line in sys.stdin:
    row = json.loads(line)
    args = row['arguments']
    assert args['__quattro_context']['host'] == 'omp'
    assert args['__quattro_context']['session_id'] == 'fixture-session'
    assert 'operational_decision' in args['__quattro_host_tools']
    result = {'name': row['name'], 'helperHost': 'omp',
              'directory': args.get('directory'),
              'usageEvidence': {'requested': True, 'accepted': False},
              'recommendation': 'fallback_required', 'grantsPermission': False}
    print(json.dumps({'id': row['id'], 'result': result}), flush=True)
''')
            runner = root / "callback.mjs"
            runner.write_text('''import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {writeFileSync,symlinkSync,linkSync,mkdirSync} from 'node:fs';
const {default: factory,protectedWriteReason} = await import(pathToFileURL(process.argv[2]));
// Schema behavior is validated by Quattro's existing closed dynamic validator.
// This fixture exercises real exported extension callbacks and real stdio.
const chain = new Proxy(()=>chain, {get:()=>chain, apply:()=>chain});
const handlers = new Map(), tools = new Map(); let effort='medium';
const approval={bash:'prompt',edit:'prompt',write:'prompt',rtk_run:'prompt',refresh_history:'prompt',
 eval:'deny',task:'deny',computer:'deny'};
const settings={'tools.approvalMode':'always-ask','tools.approval':approval,'bash.patterns':[]};
const pi = {zod: chain, on:(name, callback)=>handlers.set(name, callback),
 pi:{settings:{rawValue:descriptor=>settings[descriptor.id]},getAgentDir:()=>process.cwd()+'/.omp/agent'},
 registerTool:tool=>tools.set(tool.name, tool), getThinkingLevel:()=>effort,
 getActiveTools:()=>['read',...tools.keys()]};
factory(pi);
let shutdown=0, aborted=0; const statuses=[];
const ctx = {cwd:process.cwd(), model:{id:'gpt-6.1-sol',provider:'openai-codex'},
 mode:'tui',hasUI:true,sessionManager:{getSessionId:()=> 'fixture-session'},
 ui:{setStatus:(_name,value)=>statuses.push(value)},
 shutdown:()=>shutdown++,abort:()=>aborted++};
handlers.get('session_start')({},ctx); assert.equal(shutdown,0);
assert.equal(tools.size,6);
assert.equal(tools.get('operational_decision').approval,'read');
assert.deepEqual(tools.get('rtk_run').approval,{tier:'exec',policy:'prompt'});
assert.deepEqual(tools.get('refresh_history').approval,{tier:'write',policy:'prompt'});
assert.equal(handlers.get('tool_call')({toolName:'bash',input:{command:'test'}},ctx),undefined);
assert.equal(handlers.get('before_subagent_spawn')({},ctx).block,true);
assert.equal(handlers.get('user_bash')({},ctx).result.exitCode,1);
const control=process.cwd()+'/control.json';writeFileSync(control,'{}');
symlinkSync(control,process.cwd()+'/symlink.json');linkSync(control,process.cwd()+'/hardlink.json');
for(const path of [control,'@'+control,':'+control,'symlink.json','hardlink.json'])
 assert(protectedWriteReason({toolName:'write',input:{path}},ctx,[control],process.cwd()+'/quattro_agent'));
assert(protectedWriteReason({toolName:'edit',input:{input:'*** Begin Patch\\n['+control+'#abcd]\\nPUT >1:\\n+x\\n*** End Patch'}},ctx,[control],process.cwd()+'/quattro_agent'));
assert.equal(protectedWriteReason({toolName:'edit',input:{path:'ordinary.py'}},ctx,[control],process.cwd()+'/quattro_agent'),undefined);
assert(protectedWriteReason({toolName:'edit',input:{path:'quattro_agent/shared_intelligence.py'}},ctx,[control],process.cwd()+'/quattro_agent'));
mkdirSync(process.cwd()+'/protected/subdir',{recursive:true});
const nestedControl=process.cwd()+'/protected/control.json';writeFileSync(nestedControl,'{}');
symlinkSync(process.cwd()+'/protected/subdir',process.cwd()+'/directory-link');
assert(protectedWriteReason({toolName:'write',input:{path:process.cwd()+'/directory-link/../control.json'}},ctx,[nestedControl],process.cwd()+'/quattro_agent'));
const policy=handlers.get('before_agent_start')({systemPrompt:['original']},ctx);
assert.equal(policy.systemPrompt[0],'original');assert.equal(policy.systemPrompt.length,2);
const signal = new AbortController().signal;
const search=await tools.get('search_knowledge').execute('fixture', {query:'abstract query'},signal,undefined,ctx);
const searchResult=JSON.parse(search.content[0].text);
assert.equal(searchResult.helperHost,'omp');assert.equal(searchResult.directory,ctx.cwd);
const decision=await tools.get('operational_decision').execute('fixture',{},signal,undefined,ctx);
assert.equal(JSON.parse(decision.content[0].text).grantsPermission,false);
assert.equal(decision.details.adviceGrantsPermission,false);
assert(statuses.at(-1).includes('fallback'));
const cancelled=new AbortController();cancelled.abort();
await assert.rejects(tools.get('rtk_status').execute('fixture',{},cancelled.signal,undefined,ctx),/cancelled/);
effort='high';
assert.equal(handlers.get('tool_call')({},ctx).block,true);
effort='medium'; // restoring route cannot revive an invalidated session
assert.equal(handlers.get('input')({},ctx).handled,true);
await assert.rejects(tools.get('rtk_status').execute('fixture',{},signal,undefined,ctx),/requires/);
handlers.get('before_agent_start')({systemPrompt:[]},ctx);assert.equal(aborted,1);assert.equal(shutdown,1);
handlers.get('session_shutdown')({},ctx);
handlers.get('session_start')({},ctx);assert.equal(shutdown,1);
approval.write='allow';assert.equal(handlers.get('tool_call')({},ctx).block,true);
approval.write='prompt';assert.equal(handlers.get('input')({},ctx).handled,true);
handlers.get('session_start')({},ctx);assert.equal(shutdown,1);
settings['bash.patterns']=[{match:'*',approval:'allow'}];assert.equal(handlers.get('tool_call')({},ctx).block,true);
settings['bash.patterns']=[];
writeFileSync(process.env.QUATTRO_OMP_OVERLAY,'tampered');
handlers.get('session_start')({},ctx);assert.equal(shutdown,2);
ctx.model.id='wrong-model';handlers.get('session_start')({},ctx);assert.equal(shutdown,3);
''')
            # The overlay and extension are host-pinned; model-authored content
            # cannot supply or revise these private process controls.
            overlay = root / "policy.json"
            overlay.write_text(json.dumps(native_policy_overlay()))
            env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "PYTHONPATH": tmp,
                   "QUATTRO_OMP_PYTHON": sys.executable, "QUATTRO_TEST_PRIVATE_MARKER": "must_not_inherit",
                   "QUATTRO_OMP_OVERLAY": str(overlay), "QUATTRO_OMP_EXTENSION": str(extension_path()),
                   "QUATTRO_OMP_OVERLAY_SHA256": hashlib.sha256(overlay.read_bytes()).hexdigest(),
                   "QUATTRO_OMP_EXTENSION_SHA256": hashlib.sha256(extension_path().read_bytes()).hexdigest()}
            result = subprocess.run([shutil.which("node"), "--experimental-strip-types", str(runner),
                                     str(extension_path())], cwd=tmp, env=env, capture_output=True,
                                    text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr[:2000])


if __name__ == "__main__":
    unittest.main()
