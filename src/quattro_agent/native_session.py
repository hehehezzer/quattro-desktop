"""Supervise real native interfaces with a Quattro gate below the UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from .codex_turn_bridge import CodexTurnBridge
from .turn_gate import TurnGate
from .turn_transport import TurnTransport


def _codex_remote_arguments(command):
    """Move local-only roots to the server and mirror the selected access policy."""
    frontend, backend, roots = [command[0]], [], []
    policy_flags = {'-s': 'sandbox_mode', '--sandbox': 'sandbox_mode',
                    '-a': 'approval_policy', '--ask-for-approval': 'approval_policy'}
    index = 1
    while index < len(command):
        arg = command[index]
        if arg == '--':
            frontend.extend(command[index:])
            break
        flag, separator, inline = arg.partition('=')
        if flag == '--add-dir' or flag in policy_flags or flag in {'-c', '--config'}:
            if separator:
                value, consumed = inline, 1
            else:
                if index + 1 >= len(command):
                    raise ValueError(f'{flag} requires a value')
                value, consumed = command[index + 1], 2
            if flag == '--add-dir':
                if not value:
                    raise ValueError('--add-dir requires a nonempty directory')
                if value not in roots:
                    roots.append(value)
            else:
                frontend.extend(command[index:index + consumed])
                if flag in policy_flags:
                    backend.extend(['-c', f'{policy_flags[flag]}={json.dumps(value, ensure_ascii=False)}'])
                elif value.startswith('developer_instructions='):
                    backend.extend(['-c', value])
            index += consumed
            continue
        frontend.append(arg)
        if arg == '--dangerously-bypass-approvals-and-sandbox':
            # This flag is emitted only after the caller's explicit confirmation.
            backend.extend(['-c', 'sandbox_mode="danger-full-access"',
                            '-c', 'approval_policy="never"'])
        index += 1
    if roots:
        backend.extend(['-c', 'sandbox_workspace_write.writable_roots=' +
                        json.dumps(roots, ensure_ascii=False)])
    return frontend, backend


def launch_routed_native(*, agent, binary, command, env, config, directory,
                         session_id, account, state_root, runtime_factory,
                         profile_name=None, confirm_full_access=False):
    """Keep the actual TUI on inherited terminal handles; own only its backend."""
    delegate_lock = threading.Lock()
    runtime_holder = []
    gate = TurnGate(session_id=session_id, config=config, directory=directory,
                    telemetry_path=state_root / 'private' / 'interactive-turns.jsonl', account=account)

    def delegate(turn):
        # Instantiate the heavyweight harness only after the gate selected DELEGATE.
        with delegate_lock:
            if gate.by_plan(turn.plan.plan_id) is not turn or turn.task_id is not None:
                raise ValueError('turn plan is stale or already consumed')
            if not runtime_holder:
                runtime_holder.append(runtime_factory())
            runtime = runtime_holder[0]
            task_id = runtime.create_task(
                agent='codex', project=directory, prompt=turn.prompt, mode='prompt',
                profile_name=profile_name, account_id=turn.plan.target.account,
                confirm_full_access=confirm_full_access,
                turn_execution_plan=turn.plan, turn_context=gate.conversation_context(turn),
            )
            turn.task_id = task_id
        if turn.cancel_event.is_set():
            runtime.request_cancel(task_id)
            raise RuntimeError('turn cancelled')
        code = runtime.run_task(task_id)
        if code:
            raise RuntimeError('delegated task failed')
        output_path = runtime._child_output_path(task_id)
        text = output_path.read_text(encoding='utf-8')[:1_000_000] if output_path.is_file() else ''
        answer = ''
        for line in text.splitlines():
            try:
                item = json.loads(line).get('item', {})
                if item.get('type') == 'agent_message':
                    answer = item.get('text', '')
            except (ValueError, AttributeError):
                continue
        return answer or 'Delegated task completed. Its result is available in Quattro tasks.'

    gate.delegate = delegate
    original_cancel = gate.cancel

    def cancel(turn):
        original_cancel(turn)
        if turn.task_id and runtime_holder:
            runtime_holder[0].request_cancel(turn.task_id)

    gate.cancel = cancel
    transport = TurnTransport(gate).start()
    bridge = None
    thread = None
    child = None
    # Unix socket paths have a small kernel limit; private short temporary root.
    with tempfile.TemporaryDirectory(prefix='quattro-turn-') as temporary:
        try:
            child_env = dict(env)
            child_env['QUATTRO_TURN_GATE_URL'] = transport.url
            child_env['QUATTRO_TURN_GATE_TOKEN'] = transport.token
            if agent == 'codex':
                child_env['QUATTRO_TURN_GATE_AUTH'] = 'Bearer ' + transport.token
                overrides = [
                    '-c', f'model_providers.omniroute.base_url={json.dumps(transport.url)}',
                    '-c', 'model_providers.omniroute.env_http_headers={Authorization="QUATTRO_TURN_GATE_AUTH"}',
                    '-c', 'model_providers.omniroute.requires_openai_auth=false',
                    '-c', 'model_providers.omniroute.supports_websockets=false',
                    '-c', 'model_provider="omniroute"',
                    '-c', 'model="auto"',
                    '-c', 'history.persistence="none"',
                    '-c', 'analytics.enabled=false',
                    '-c', 'otel.log_user_prompt=false',
                ]
                socket_path = Path(temporary) / 'rpc.sock'
                # Remote TUI rejects --add-dir; workspace grants belong to its server.
                command, policy_overrides = _codex_remote_arguments(command)
                backend = [binary, *overrides, *policy_overrides, 'app-server', '--stdio']
                bridge = CodexTurnBridge(socket_path, backend, child_env, gate,
                                         history_root=state_root / "private" / "interactive-history")
                thread = threading.Thread(target=bridge.run, daemon=True)
                thread.start()
                if not bridge.ready.wait(timeout=10) or bridge.closed.is_set():
                    raise RuntimeError('native Codex turn bridge did not start')
                command = [*command[:1], *overrides, '--remote', f'unix://{socket_path}', *command[1:]]
            else:
                extension = Path(__file__).with_name('data') / 'pi-turn-gate.ts'
                command = [*command, '-e', str(extension)]
                if '--session' not in command and '-r' not in command:
                    # Pi initializes an existing empty file through its native
                    # SessionManager, then persists custom direct messages.
                    session_directory = state_root / 'private' / 'pi-sessions'
                    session_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                    session_file = session_directory / (session_id + '.jsonl')
                    descriptor = os.open(session_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(descriptor)
                    command.extend(['--session', str(session_file)])
            child = subprocess.Popen(command, env=child_env, cwd=directory)
            try:
                return child.wait()
            except KeyboardInterrupt:
                return child.wait(timeout=10)
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            transport.close()
            if bridge:
                bridge.stop()
            if thread:
                thread.join(timeout=10)
