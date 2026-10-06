"""Actual Pi callbacks request fresh authorship without automatic provider decisions."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(os.environ.get("QUATTRO_TEST_NATIVE_BUNDLE", "/nonexistent"))
PACKAGE = BUNDLE / "node_modules/@earendil-works/pi-coding-agent"
LOADER = PACKAGE / "dist/core/extensions/loader.js"


@unittest.skipUnless(LOADER.is_file() and (BUNDLE / "bin/node").is_file(),
                     "set QUATTRO_TEST_NATIVE_BUNDLE for audited Pi fixture dependencies")
class PiCheckpointTests(unittest.TestCase):
    def test_actual_callbacks_request_authorship_without_provider_projection(self):
        self._callbacks(config_enabled=False, environment="1")

    def test_persisted_opt_in_and_explicit_environment_disable(self):
        self._callbacks(config_enabled=True, environment=None)
        self._callbacks(config_enabled=True, environment="0", expected=False)

    def _callbacks(self, *, config_enabled, environment, expected=True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "native.json"
            config.write_text(json.dumps(dict(enabled=True, operationalEnabled=True,
                                              checkpointsEnabled=config_enabled)))
            helper = root / "quattro-intelligence"
            helper.write_text("#!/bin/sh\nexit 125\n")
            helper.chmod(0o700)
            runner = root / "run.mjs"
            runner.write_text('''import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {PassThrough} from 'node:stream';
import {EventEmitter} from 'node:events';
import {pathToFileURL} from 'node:url';
let helperCalls=0,guardRequests=0;
childProcess.spawn=(command,argv,options)=>{
 assert.equal(command,'quattro-intelligence');assert.deepEqual(argv,['--server']);assert.equal(options.shell,false);
 helperCalls++;
 const child=new EventEmitter();child.stdin=new PassThrough();child.stdout=new PassThrough();child.kill=()=>child.emit('close');
 let pending='';child.stdin.on('data',chunk=>{
  pending+=chunk.toString();let newline;
  while((newline=pending.indexOf('\\n'))>=0){
   const request=JSON.parse(pending.slice(0,newline));pending=pending.slice(newline+1);
   assert.equal(request.name,'operational_guard');assert.equal(request.arguments.operation,'feedback');
   assert(!Object.hasOwn(request.arguments,'checkpoint'));assert(!Object.hasOwn(request.arguments,'decision'));
   guardRequests++;
   child.stdout.write(JSON.stringify({id:request.id,result:{accepted:false,recommendation:'continue',reason:'guard_only'}})+'\\n');
  }
 });child.stdin.once('finish',()=>{child.stdout.end();child.emit('close')});return child;
};
syncBuiltinESMExports();
const {loadExtensions,createExtensionRuntime}=await import(pathToFileURL(process.argv[2]));
const runtime=createExtensionRuntime();runtime.getActiveTools=()=>['read'];
const result=await loadExtensions([process.argv[3]],process.cwd(),undefined,runtime);
assert.equal(result.errors.length,0);assert.equal(result.extensions.length,1);
const extension=result.extensions[0];
const callbacks=extension.handlers.get('tool_result');assert(callbacks?.length);
const ctx={cwd:process.cwd(),mode:'api',sessionManager:{getSessionId:()=> 'synthetic',getBranch:()=>[]}};
for(let index=0;index<100;index++){
 const event={toolName:'read',toolCallId:'synthetic-'+index,input:{path:'fixture-'+index},isError:index>0,
   content:[{type:'text',text:'synthetic-'+index}]};
 const replies=[];
 for(const callback of callbacks){const reply=await callback(event,ctx);if(reply)replies.push(reply);}
 const guidance=replies.flatMap(reply=>reply.content||[]).filter(part=>part.text?.startsWith('Evidence changed at revision'));
 assert.equal(guidance.length,Number(process.env.EXPECT_CHECKPOINTS));
 if(guidance.length){
  assert(guidance[0].text.includes('Author the next relevant decision-specific question and options through operational_decision'));
  assert(!guidance[0].text.includes('available_actions'));
  assert(!guidance[0].text.includes('synthetic-'+index));
  assert(!guidance[0].text.includes('fixture-'+index));
 }
}
for(const callback of extension.handlers.get('session_shutdown')||[])await callback({},ctx);
assert.equal(helperCalls,1);assert.equal(guardRequests,100);
console.log(JSON.stringify({callbacks:100,fresh_authorship_guidance:process.env.EXPECT_CHECKPOINTS==='1',host_guard_requests:100,automatic_decision_requests:0,provider_calls:0}));
''')
            env = {"PATH": str(root), "HOME": str(root), "EXPECT_CHECKPOINTS": "1" if expected else "0",
                   "QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(config)}
            if environment is not None:
                env["QUATTRO_JEV_CHECKPOINTS"] = environment
            result = subprocess.run([str(BUNDLE / "bin/node"), str(runner), str(LOADER),
                str(ROOT / "adapters/pi/quattro-intelligence.ts")], cwd=root, env=env,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, "native callback fixture failed")
            self.assertLessEqual(len(result.stdout), 4096)
            self.assertEqual(json.loads(result.stdout), dict(callbacks=100,
                fresh_authorship_guidance=expected, host_guard_requests=100, automatic_decision_requests=0, provider_calls=0))
