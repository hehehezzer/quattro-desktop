"""Dormant native owner boundary through the actual audited Pi TS loader.

UI replies are synthetic: these tests establish binding, never human acceptance.
No provider, real shell, credential, or persistent configuration is used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(os.environ.get("QUATTRO_TEST_NATIVE_BUNDLE", "/nonexistent"))
LOADER = BUNDLE / "node_modules/@earendil-works/pi-coding-agent/dist/core/extensions/loader.js"


@unittest.skipUnless(LOADER.is_file() and (BUNDLE / "bin/node").is_file(),
                     "set QUATTRO_TEST_NATIVE_BUNDLE for audited Pi fixture dependencies")
class NativeShellConfirmationTests(unittest.TestCase):
    def test_actual_loader_one_use_exact_tui_binding(self):
        self._run("binding")

    def test_actual_callbacks_invalidate_and_keep_guard_when_advisory_off(self):
        self._run("callbacks")

    def test_actual_callbacks_protect_control_file_despite_disabled_helper(self):
        self._run("controlwrites")

    def _run(self, scenario):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "fixture.ts"
            wrapper.write_text(
                "import extension, {createNativeShellOwnerGate} from "
                + json.dumps(str(ROOT / "adapters/pi/quattro-intelligence.ts"))
                + ";\nexport default function(pi) { globalThis.fixtureGateFactory = createNativeShellOwnerGate; extension(pi); }\n"
            )
            runner = root / "fixture.mjs"
            runner.write_text(NODE_FIXTURE)
            config = root / "native.json"
            config.write_text('{"enabled":false,"operationalEnabled":true}')
            result = subprocess.run(
                [str(BUNDLE / "bin/node"), str(runner), str(LOADER), str(wrapper), scenario],
                cwd=root, env={"HOME": str(root), "PATH": str(root),
                    "QUATTRO_NATIVE_INTELLIGENCE_CONFIG": str(config)},
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertLessEqual(len(result.stdout), 4096)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence["scenario"], scenario)
            self.assertEqual(evidence["provider_calls"], 0)
            self.assertEqual(evidence["shell_executions"], 0)
            self.assertFalse(evidence["actual_human_acceptance"])


NODE_FIXTURE = r'''
import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {PassThrough} from 'node:stream';
import {EventEmitter} from 'node:events';
import {pathToFileURL} from 'node:url';
import {mkdirSync,writeFileSync,symlinkSync,linkSync} from 'node:fs';
import {join,relative} from 'node:path';
let requests=[], replyHook;
childProcess.spawn=(command,argv,options)=>{
 assert.equal(command,'quattro-intelligence');assert.deepEqual(argv,['--server']);assert.equal(options.shell,false);
 const child=new EventEmitter();child.stdin=new PassThrough();child.stdout=new PassThrough();child.kill=()=>child.emit('close');
 let pending='';child.stdin.on('data',chunk=>{
  pending+=chunk.toString();let newline;
  while((newline=pending.indexOf('\n'))>=0){
   const request=JSON.parse(pending.slice(0,newline));pending=pending.slice(newline+1);requests.push(request);
   assert(['native_event','operational_guard'].includes(request.name));
   let result={recorded:true};
   if(request.name==='operational_guard')result=request.arguments.operation==='feedback'
    ?{recommendation:'change_plan',reason:'repeated_failure',traceId:'synthetic-trace'}:{recommendation:'ask_owner',reason:'opaque_operation',traceId:'synthetic-trace'};
   if(replyHook)result=replyHook(request,result);
   child.stdout.write(JSON.stringify({id:request.id,result})+'\n');
  }
 });child.stdin.once('finish',()=>{child.stdout.end();child.emit('close')});return child;
};
syncBuiltinESMExports();
const {loadExtensions,createExtensionRuntime}=await import(pathToFileURL(process.argv[2]));
const runtime=createExtensionRuntime();runtime.getActiveTools=()=>['bash'];runtime.getThinkingLevel=()=> 'medium';
const result=await loadExtensions([process.argv[3]],process.cwd(),undefined,runtime);
assert.equal(result.errors.length,0);assert.equal(result.extensions.length,1);
const extension=result.extensions[0],factory=globalThis.fixtureGateFactory;
const advice={recommendation:'ask_owner',reason:'opaque_operation'};
let serial=0, marks=0, dialogs=0;
function setup(flag=true){
 for(const [name,value] of Object.entries({isTTY:true,columns:120,rows:50}))Object.defineProperty(process.stdout,name,{value,writable:true,configurable:true});
 let clock=0;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true});
 let enabled=flag, sid='synthetic-session', thinking='medium', dialog=async()=>true, tools=['bash'],trusted=true;
 const pi={registerFlag:(name,spec)=>{assert.equal(name,'quattro-shell-confirm');assert.equal(spec.default,false)},
  getFlag:()=>enabled,getThinkingLevel:()=>thinking,getActiveTools:()=>tools};
 const gate=factory(pi);gate.start();
 const controller=new AbortController();
 const ctx={cwd:process.cwd(),mode:'tui',hasUI:true,signal:controller.signal,
  model:{id:'synthetic-model',provider:'synthetic-provider',api:'synthetic-api'},isProjectTrusted:()=>trusted,
  sessionManager:{getSessionId:()=>sid},ui:{confirm:async(title,text,options)=>{
   dialogs++;assert(title.includes('exact'));assert(text.includes('NOT a sandbox'));assert(text.includes('filesystem and network rights'));
   assert.equal(options.signal,ctx.signal);assert.equal(options.timeout,60000);return dialog();}}};
 const event={toolName:'bash',toolCallId:'synthetic-'+serial++,input:{command:'synthetic inspection',timeout:10}};
 const record=async digest=>{marks++;assert.match(digest,/^[a-f0-9]{64}$/)};
 return {gate,ctx,event,record,controller,setDialog:value=>dialog=value,setFlag:value=>enabled=value,
  setSession:value=>sid=value,setThinking:value=>thinking=value,setTools:value=>tools=value,setTrust:value=>trusted=value,
  setClock:value=>clock=value};
}
let assertions=0;
async function denies(change,{during=false,after=false}={}){
 const f=setup();const d=dialogs;
 if(during)f.setDialog(async()=>{change(f);return true});else change(f);
 const ok=await f.gate.confirm(f.event,f.ctx,advice,after?async()=>change(f):f.record);
 assert.equal(ok,false);if(!during&&!after)assert.equal(dialogs,d);assertions++;
}
if(process.argv[4]==='controlwrites'){
 const ctx={cwd:process.cwd(),mode:'print',sessionManager:{getSessionId:()=> 'synthetic',getBranch:()=>[]},ui:{setStatus:()=>{}}};
 async function check(path,blocked=true){
  for(const toolName of ['write','edit']){
   const prior=requests.length;
   const event={toolName,toolCallId:'control-'+serial++,input:{path,content:'synthetic',oldText:'synthetic',newText:'synthetic'}};
   let reply;for(const callback of extension.handlers.get('tool_call')){const value=await callback(event,ctx);if(value)reply=value;}
   assert.equal(reply?.block===true,blocked);
   if(blocked)assert.equal(requests.length,prior);else assert(requests.length>prior);
   assertions++;
  }
 }
 replyHook=(request,result)=>request.name==='operational_guard'?{reason:'disabled',recommendation:'continue'}:result;
 const config=process.env.QUATTRO_NATIVE_INTELLIGENCE_CONFIG;
 await check(config);await check(relative(process.cwd(),config));await check('@'+relative(process.cwd(),config));
 await check('~/'+relative(process.env.HOME,config));await check(pathToFileURL(config).href);
 const alias=join(process.cwd(),'config-symlink.json');symlinkSync(config,alias);await check(alias);
 const hardlink=join(process.cwd(),'config-hardlink.json');linkSync(config,hardlink);await check(hardlink);
 const parentAlias=join(process.cwd(),'parent-alias');symlinkSync(process.cwd(),parentAlias);await check(join(parentAlias,'native.json'));
 // Existing ancestor aliases cover creation of a missing default control file.
 delete process.env.QUATTRO_NATIVE_INTELLIGENCE_CONFIG;
 process.env.XDG_CONFIG_HOME=join(process.cwd(),'xdg');mkdirSync(process.env.XDG_CONFIG_HOME);
 const xdgAlias=join(process.cwd(),'xdg-alias');symlinkSync(process.env.XDG_CONFIG_HOME,xdgAlias);
 await check(join(xdgAlias,'quattro','native-intelligence.json'));
 delete process.env.XDG_CONFIG_HOME;await check('~/.config/quattro/native-intelligence.json');
 const spaced=join(process.cwd(),'control dir');mkdirSync(spaced);const spacedConfig=join(spaced,'native.json');writeFileSync(spacedConfig,'{}');
 process.env.QUATTRO_NATIVE_INTELLIGENCE_CONFIG=spacedConfig;
 await check(spacedConfig.replaceAll(' ','\u00a0'));
 // A dangling metadata alias must not create a missing control file either.
 const absent=join(process.cwd(),'absent-control.json');process.env.QUATTRO_NATIVE_INTELLIGENCE_CONFIG=absent;
 const dangling=join(process.cwd(),'dangling-alias.json');symlinkSync(absent,dangling);await check(dangling);
 await check(join(process.cwd(),'ordinary-source.txt'),false);
 for(const callback of extension.handlers.get('session_shutdown')||[])await callback({},ctx);
 assert.equal(requests.filter(x=>x.name==='operational_guard').length,2);
}else if(process.argv[4]==='binding'){
 const f=setup();assert.equal(await f.gate.confirm(f.event,f.ctx,advice,f.record),true);
 assert(Object.isFrozen(f.event.input));assert(Object.isFrozen(f.event));
 assert.throws(()=>{f.event.input.command='changed'});assert.throws(()=>{f.event.input={command:'changed',timeout:10}});
 const d=dialogs;assert.equal(await f.gate.confirm(f.event,f.ctx,advice,f.record),false);assert.equal(dialogs,d);assertions++;
 f.gate.nextTurn();assert.equal(await f.gate.confirm(f.event,f.ctx,advice,f.record),false);assert.equal(dialogs,d);assertions++;
 await denies(f=>f.setFlag(false));await denies(f=>f.ctx.mode='rpc');await denies(f=>f.ctx.mode='print');
 await denies(f=>f.ctx.hasUI=false);await denies(f=>delete f.ctx.signal);await denies(f=>f.controller.abort());
 await denies(f=>delete f.event.input.timeout);await denies(f=>f.event.input.timeout=301);
 await denies(f=>f.event.input.timeout=0);await denies(f=>f.event.input.timeout=1.5);
 await denies(f=>f.event.input.extra=true);await denies(f=>f.event.input.command='x\0y');
 await denies(f=>f.event.input.command='x'.repeat(8193));await denies(f=>f.event.toolName='write');
 await denies(f=>f.event.toolCallId='');await denies(f=>f.setSession('unknown'));
 await denies(f=>f.setTools([]));await denies(f=>f.setTools(null));await denies(f=>f.setTools([42]));
 await denies(f=>f.setTrust(false));await denies(f=>delete f.ctx.isProjectTrusted);
 await denies(f=>f.ctx.isProjectTrusted=()=>{throw new Error('synthetic')});
 await denies(f=>process.stdout.isTTY=false);await denies(f=>process.stdout.columns=undefined);
 await denies(f=>process.stdout.columns=79);await denies(f=>process.stdout.rows=23);
 await denies(f=>{process.stdout.columns=80;process.stdout.rows=24;f.event.input.command='x'.repeat(2048)});
 await denies(f=>Object.defineProperty(f.event.input,'command',{get:()=> 'synthetic',enumerable:true}));
 for(const mutate of [f=>f.event.input.command='changed',f=>f.event.input.timeout=11,
  f=>f.event.input={...f.event.input},f=>f.event.toolCallId+='changed',f=>f.ctx.model.id+='changed',
  f=>f.ctx.model.provider+='changed',f=>f.ctx.model.api+='changed',f=>f.setSession('changed'),
  f=>f.setThinking('high'),f=>f.ctx.cwd='/missing-synthetic-cwd',f=>f.setFlag(false),
  f=>f.controller.abort(),f=>f.ctx.signal=new AbortController().signal,
  f=>f.gate.invalidate(),f=>f.gate.nextTurn(),f=>f.gate.start(),f=>f.setTrust(false),
  f=>f.setTools([]),f=>process.stdout.columns=100,f=>process.stdout.rows=40,
  f=>f.setClock(60_000)])await denies(mutate,{during:true});
 const denied=setup();denied.setDialog(async()=>false);assert.equal(await denied.gate.confirm(denied.event,denied.ctx,advice,denied.record),false);
 denied.setDialog(async()=>true);const prior=dialogs;assert.equal(await denied.gate.confirm(denied.event,denied.ctx,advice,denied.record),false);assert.equal(dialogs,prior);
 for(const value of [false,undefined,'true',1]){const f=setup();f.setDialog(async()=>value);assert.equal(await f.gate.confirm(f.event,f.ctx,advice,f.record),false);assertions++;}
 for(const reason of ['host_denied','scope_denied','sensitive','owner_required','disabled','repeated_failure']){
  const f=setup(),prior=dialogs;assert.equal(await f.gate.confirm(f.event,f.ctx,{...advice,reason},f.record),false);assert.equal(dialogs,prior);assertions++;}
 const changed=setup();assert.equal(await changed.gate.confirm(changed.event,changed.ctx,advice,async()=>changed.gate.nextTurn()),false);
 const expired=setup();assert.equal(await expired.gate.confirm(expired.event,expired.ctx,advice,async()=>expired.setClock(60_001)),false);
 const missing=factory({});missing.start();assert.equal(await missing.confirm(setup().event,setup().ctx,advice,async()=>{}),false);
 // Denials also consume IDs; capacity is bounded without replay-enabling eviction.
 const capacity=setup();capacity.setDialog(async()=>false);
 for(let index=0;index<4096;index++)assert.equal(await capacity.gate.confirm({...capacity.event,toolCallId:'capacity-'+index},capacity.ctx,advice,capacity.record),false);
 const count=dialogs;assert.equal(await capacity.gate.confirm({...capacity.event,toolCallId:'capacity-overflow'},capacity.ctx,advice,capacity.record),false);assert.equal(dialogs,count);
}else{
 for(const [name,value] of Object.entries({isTTY:true,columns:120,rows:50}))Object.defineProperty(process.stdout,name,{value,writable:true,configurable:true});
 async function emit(name,event,ctx){let reply;for(const callback of extension.handlers.get(name)||[]){const value=await callback(event,ctx);if(value)reply=value;}return reply;}
 const ctx={cwd:process.cwd(),mode:'tui',hasUI:true,signal:new AbortController().signal,
  model:{id:'synthetic-model',provider:'synthetic-provider',api:'synthetic-api'},isProjectTrusted:()=>true,
  sessionManager:{getSessionId:()=> 'synthetic',getBranch:()=>[{type:'custom',customType:'quattro_jev_preference',data:{enabled:false}}]},
  ui:{setStatus:()=>{},confirm:async()=>true}};
 await emit('session_start',{},ctx);runtime.flagValues.set('quattro-shell-confirm',true);
 const guidance=await emit('before_agent_start',{prompt:'synthetic long task instruction',systemPrompt:'synthetic'},ctx);
 assert(guidance.systemPrompt.includes('explicit integer timeout'));assert(guidance.systemPrompt.includes('actual human confirmation'));
 const event=()=>({toolName:'bash',toolCallId:'callback-'+serial++,input:{command:'synthetic',timeout:10}});
 const approved=event();assert.equal(await emit('tool_call',approved,ctx),undefined);assert(Object.isFrozen(approved.input));
 const owner=requests.find(x=>x.name==='native_event'&&x.arguments.stage==='owner_confirmation');
 assert.equal(owner.arguments.kind,'instrumentation');assert.equal(owner.arguments.metadata.providerAcceptance,'NOT_APPLICABLE');
 assert.equal(owner.arguments.metadata.actionApplied,'UNKNOWN');assert(!JSON.stringify(owner).includes('synthetic inspection'));
 for(const stale of [undefined,{reason:'disabled',recommendation:'continue'},
  {reason:'host_denied',recommendation:'stop'},{reason:'owner_required',recommendation:'ask_owner'}]){
  let afterDialog=false;ctx.ui.confirm=async()=>{afterDialog=true;return true};
  replyHook=(request,result)=>request.name==='operational_guard'&&request.arguments.operation==='preflight'&&afterDialog
   ?stale:result;
  assert.equal((await emit('tool_call',event(),ctx)).block,true);assertions++;
 }
 replyHook=undefined;
 for(const lifecycle of ['turn_start','session_before_switch','session_before_fork','session_shutdown']){
  await emit('session_start',{},ctx);
  ctx.ui.confirm=async()=>{await emit(lifecycle,{turnIndex:1},ctx);return true};
  assert.equal((await emit('tool_call',event(),ctx)).block,true);assertions++;
 }
 await emit('session_start',{},ctx);ctx.mode='print';
 assert.equal((await emit('tool_call',event(),ctx)).block,true);
 const same=event();await emit('tool_result',{...same,isError:true,content:[{type:'text',text:'synthetic failure'}]},ctx);
 const prior=requests.length;assert.equal((await emit('tool_call',same,ctx)).block,true);assert.equal(requests.length,prior);
 // No raw command crosses either deterministic guard or native telemetry.
 for(const request of requests)if(request.name==='operational_guard')assert(!Object.hasOwn(request.arguments,'command'));
 await emit('session_shutdown',{},ctx);
 assert(requests.some(x=>x.name==='operational_guard'&&x.arguments.operation==='preflight'&&x.arguments.__quattro_context?.session_enabled===false));
 assert(requests.some(x=>x.name==='operational_guard'&&x.arguments.operation==='feedback'));
 assert(!requests.some(x=>x.name==='operational_decision'));assertions+=3;
}
console.log(JSON.stringify({scenario:process.argv[4],assertions,provider_calls:0,shell_executions:0,actual_human_acceptance:false}));
'''
