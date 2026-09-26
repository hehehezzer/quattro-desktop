"""Hermetic native Pi extension contract tests; no Pi account or provider access."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "src/quattro_agent/data/pi-turn-gate.ts"


class PiTurnHookTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for the Pi extension")
    def test_input_is_always_consumed_and_sensitive_answers_are_ephemeral(self):
        # The shipped extension is valid JavaScript apart from erasable TS types.
        # Node 24 (Pi's supported runtime) executes it without extra dependencies.
        script = r'''
import assert from 'node:assert/strict';
const {default: install} = await import(process.argv[1]);
const handlers = {};
const messages = [], widgets = [], notifications = [], requests = [];
let terminal;
const pi = {on: (name, handler) => {handlers[name] = handler;},
  setActiveTools: names => assert.deepEqual(names, []),
  sendMessage: (message, opts) => {assert.equal(opts.triggerTurn, false); messages.push(message);}};
const ctx = {mode: 'tui', sessionManager: {getSessionId: () => 'native-session'},
  ui: {notify: text => notifications.push(text), setStatus: () => {},
    setWidget: (...args) => widgets.push(args),
    onTerminalInput: handler => {terminal = handler; return () => {};}}};
process.env.QUATTRO_TURN_GATE_URL = 'http://127.0.0.1:45678';
process.env.QUATTRO_TURN_GATE_TOKEN = 'test-capability';
install(pi);
await handlers.session_start({}, ctx);
let payload = {decision: 'DIRECT', response: 'Ordinary answer', sensitive: false};
globalThis.fetch = async (url, options) => {
  requests.push({url, options});
  return {ok: true, json: async () => payload};
};
for (const source of ['interactive', 'rpc', 'extension']) {
  assert.deepEqual(await handlers.input({text:'Explain this', source}, ctx), {action:'handled'});
}
assert.equal(messages.length, 3);
const firstBody = JSON.parse(requests[0].options.body);
assert.equal(typeof firstBody.request_id, 'string');
assert.deepEqual({...firstBody, request_id:undefined},
  {frontend:'pi', session_id:'native-session', request_id:undefined, prompt:'Explain this', history:[]});
assert.equal(requests[0].options.headers.Authorization, 'Bearer test-capability');
payload = {decision:'DELEGATE', response:'Done', sensitive:false};
await handlers.input({text:'Change the code', streamingBehavior:'followUp'}, ctx);
assert.equal(messages.at(-1).details.decision, 'DELEGATE');
assert.equal(messages.at(-1).details.questionChars, 'Change the code'.length);
ctx.sessionManager.getBranch = () => [{type:'custom_message', customType:'quattro-turn',
  content:'Question\n\nAnswer', details:{questionChars:8}}];
await handlers.input({text:'Follow up'}, ctx);
assert.deepEqual(JSON.parse(requests.at(-1).options.body).history,
  [{role:'user',content:'Question'}, {role:'assistant',content:'Answer'}]);
messages.pop();
ctx.sessionManager.getBranch = () => Array.from({length:8}, () => ({type:'custom_message',
  customType:'quattro-turn', content:'Question\n\nAnswer', details:{questionChars:8}}));
await handlers.input({text:'Bounded follow up'}, ctx);
assert.equal(JSON.parse(requests.at(-1).options.body).history.length,12);
messages.pop();
ctx.sessionManager.getBranch = () => [{type:'custom_message', customType:'quattro-turn',
  content:'Question\n\n'+'a'.repeat(32000), details:{questionChars:8}}];
await handlers.input({text:'Oversize history'}, ctx);
assert.deepEqual(JSON.parse(requests.at(-1).options.body).history,[]);
messages.pop();
ctx.sessionManager.getBranch = () => [];
payload = {decision:'DIRECT', response:'private answer', sensitive:true};
await handlers.input({text:'private question'}, ctx);
assert.equal(messages.length, 4);
assert.deepEqual(widgets.at(-1), ['quattro-sensitive-answer', ['private answer']]);
assert.equal(JSON.stringify(messages).includes('private'), false);
for (const invalid of [{decision:'OTHER', response:'x', sensitive:false},
  {decision:'DIRECT', response:'x'}, {decision:'DIRECT', response:42, sensitive:false}]) {
  payload = invalid;
  assert.deepEqual(await handlers.input({text:'invalid contract'}, ctx), {action:'handled'});
  assert.equal(messages.length, 4);
}
assert.deepEqual(await handlers.session_before_switch({reason:'new'}, ctx), {cancel:true});
assert.equal(await handlers.session_before_switch({reason:'resume'}, ctx), undefined);
assert.deepEqual(await handlers.session_before_fork({}, ctx), {cancel:true});
assert.deepEqual(await handlers.session_before_compact(), {cancel:true});
assert.deepEqual(await handlers.session_before_tree(), {cancel:true});
assert.equal((await handlers.tool_call()).block, true);
assert.deepEqual(await handlers.cache_warming_decision(), {action:'stop'});
const beforeImages = requests.length;
await handlers.input({text:'image', images:[{}]}, ctx);
assert.equal(requests.length, beforeImages);
globalThis.fetch = async () => {throw new Error('transport secret');};
assert.deepEqual(await handlers.input({text:'failure'}, ctx), {action:'handled'});
assert.equal(JSON.stringify(notifications).includes('transport secret'), false);
assert.equal((await handlers.user_bash({command:'arbitrary'})).result.exitCode, 1);
// A queued or steering submission cannot overlap a routed turn.
globalThis.fetch = async (url, options) => {
  if (url.endsWith('/cancel')) return {ok:true};
  return await new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });
};
const pending = handlers.input({text:'long request'}, ctx);
await Promise.resolve();
assert.deepEqual(await handlers.input({text:'steer', streamingBehavior:'steer'}, ctx), {action:'handled'});
assert.deepEqual(terminal('\x1b'), {consume:true});
assert.deepEqual(await pending, {action:'handled'});
await handlers.session_shutdown({}, ctx);
// A malformed endpoint cannot exfiltrate prompts or fall through.
process.env.QUATTRO_TURN_GATE_URL = 'https://example.com';
install(pi);
globalThis.fetch = async () => {throw new Error('must not fetch');};
assert.deepEqual(await handlers.input({text:'never send'}, ctx), {action:'handled'});
console.log('Pi turn hook contracts passed');
'''
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script, str(HOOK)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("contracts passed", result.stdout)
