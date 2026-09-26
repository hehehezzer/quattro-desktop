#!/usr/bin/env python3
"""Opt-in real Quattro/Codex task smoke matrix. Uses approved native stores in place.

Creates disposable prepared Git fixtures; does not copy accounts, mutate live
configuration, publish changes, or treat one paired sample as a speed claim.
Only allowlisted aggregate metadata is exported, never model/tool output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'src'))
from quattro_agent.config import load_ai_config
from quattro_agent.paths import config_path, state_root
from quattro_agent.models import TaskState, TERMINAL_TASK_STATES
from quattro_agent.turn_gate import TurnGate
from quattro_harness import HarnessRuntime

CASES = {
    'trivial_question': 'What is 2 plus 2? Answer with only the numeral.',
    'simple_coding': 'Repair calc.add so its existing tests pass.',
    'repository_inspection': 'Inspect calc.py and report the name of the function that adds two numbers. Do not modify files.',
    'debugging': 'Reproduce and repair the off-by-one defect in calc.add. Verify negative and zero inputs as well.',
    'multi_file_implementation': 'Repair both calc.add and display.render to meet their existing tests.',
    'tool_heavy': 'Search the docs tree and report the value marked anchor in the one file containing that key. Do not modify files.',
    'skill_heavy': 'Follow skills/repair/SKILL.md to repair calc.add and validate it.',
    'subagent_candidate': 'Repair calc.add and stats.mean. Their implementations and tests are independent; choose an appropriate execution strategy. Do not spawn workers because this benchmark has a one-worker budget.',
    'failing_test_repair': 'Run the existing tests, classify the failure, repair calc.add, then rerun tests to demonstrate the repair.',
    'research_retrieval': 'Retrieve the identifier from knowledge/rules.md, cross-check it with docs/reference.md and report it. Do not modify files.',
    'validation_heavy': 'Repair calc.add, run all existing tests, and run Python compilation and Git diff integrity checks.',
}
READ_ONLY = {'repository_inspection': 'add', 'tool_heavy': '217', 'research_retrieval': 'QDP-417'}


def source_hash():
    digest = hashlib.sha256()
    for path in sorted((SOURCE / 'src').rglob('*')):
        if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts:
            digest.update(path.relative_to(SOURCE).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def fixture(project, case):
    (project / 'tests').mkdir()
    expression = 'a+b' if case in READ_ONLY else 'a+b+1' if case == 'debugging' else 'a-b'
    (project / 'calc.py').write_text(f'def add(a,b):\n    return {expression}\n')
    tests = ('import unittest\nfrom calc import add\nclass Tests(unittest.TestCase):\n'
             ' def test_positive(self): self.assertEqual(add(2,3),5)\n'
             ' def test_zero(self): self.assertEqual(add(0,0),0)\n'
             ' def test_negative(self): self.assertEqual(add(-2,-3),-5)\n')
    if case == 'multi_file_implementation':
        (project / 'display.py').write_text('def render(value):\n    return str(value)\n')
        tests += ' def test_display(self):\n  from display import render\n  self.assertEqual(render(5),"sum=5")\n'
    if case == 'subagent_candidate':
        (project / 'stats.py').write_text('def mean(values):\n    return sum(values)\n')
        tests += ' def test_mean(self):\n  from stats import mean\n  self.assertEqual(mean([2,4]),3)\n'
    (project / 'tests/test_calc.py').write_text(tests)
    (project / 'docs').mkdir()
    for index in range(20):
        (project / 'docs' / f'row-{index}.txt').write_text('anchor=217\n' if index == 13 else f'row={index}\n')
    (project / 'knowledge').mkdir()
    (project / 'knowledge/rules.md').write_text('The fixture identifier is QDP-417.\n')
    (project / 'docs/reference.md').write_text('Reference fixture identifier: QDP-417.\n')
    skill = project / 'skills/repair'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# Fixture repair\nInspect the implementation, repair the arithmetic, then run all unittest tests. Do not publish or change Git metadata.\n')
    (project / '.gitignore').write_text('__pycache__/\n*.pyc\n')
    subprocess.run(['git', 'init', '-q', '-b', 'benchmark/decision-plane', str(project)], check=True)
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(project), '-c', 'user.name=Synthetic Benchmark',
                    '-c', 'user.email=benchmark@example.invalid', 'commit', '-qm', 'fixture'], check=True)


def parse_output(path):
    usage, decisions, answer, reasoning = None, [], '', 0
    if not path.is_file():
        return usage, decisions, answer, reasoning
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'turn.completed':
            usage = {name: value for name, value in (event.get('usage') or {}).items()
                     if name in {'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'}
                     and type(value) is int}
        item = event.get('item', {})
        if event.get('type') != 'item.completed':
            continue
        reasoning += int(item.get('type') == 'reasoning')
        if item.get('type') == 'agent_message':
            answer = item.get('text', '')  # Ephemeral fixture assertion; never exported.
        if item.get('type') == 'mcp_tool_call' and item.get('server') == 'quattro_decisions':
            observation = {'status': item.get('status')}
            for part in (item.get('result') or {}).get('content', []):
                if part.get('type') == 'text':
                    try:
                        result = json.loads(part['text'])
                        observation.update({name: result.get(name) for name in
                                            ('selected_action', 'confidence', 'fallback_required', 'timing')})
                    except (ValueError, AttributeError):
                        pass
            decisions.append(observation)
    return usage, decisions, answer, reasoning


def run_case(base, mode, case, root, timeout):
    project = root / 'fixture'
    project.mkdir()
    fixture(project, case)
    config = json.loads(json.dumps(base))
    config['memory'].update(enabled=False, enforceOnLaunch=False)
    config['delegation']['enabled'] = False
    config['routing']['jev'] = {'mode': mode, 'timeoutMs': 1500}
    path = root / 'ai.json'
    path.write_text(json.dumps(config))
    os.chmod(path, 0o600)
    started = time.perf_counter()
    if case == 'trivial_question':
        gate = TurnGate(session_id='synthetic', config=config, directory=project,
                        telemetry_path=root/'turns.jsonl', account=config['defaultCodexAccount'])
        try:
            turn = gate.begin('thread', CASES[case], 'codex')
            answer = gate.direct(turn)
            gate.finish(turn)
            return {'case': case, 'mode': mode, 'total_task_ms': (time.perf_counter()-started)*1000,
                    'task_success': answer.strip() == '4', 'validation_success': None,
                    'first_token_ms_from_dispatch': turn.first_token_ms,
                    'usage': None, 'runtime_decisions': [], 'model_turns': None, 'cost': None}
        finally:
            gate.cancel_all()
    runtime = HarnessRuntime(config_path=path, state_root=state_root(),
                             script_path=SOURCE/'src/quattro-agent', default_workspace=SOURCE)
    prompt = ('Synthetic disposable benchmark on the prepared benchmark/decision-plane branch. '
              'Work only in this fixture. Do not create branches, commit, publish, or spawn workers. '
              + CASES[case])
    task = runtime.create_task(agent='codex', project=project, prompt=prompt,
                               mode='prompt', profile_name='workspace-write')
    timer = threading.Timer(max(0, timeout - (time.perf_counter()-started)), runtime.request_cancel, args=(task,))
    timer.start()
    try:
        code = runtime.run_task(task)
    finally:
        timer.cancel()
        timer.join()
        state = runtime.store.get_task(task)
        if TaskState(state['state']) not in TERMINAL_TASK_STATES:
            runtime.request_cancel(task)
    wall = (time.perf_counter()-started)*1000
    usage, decisions, answer, reasoning = parse_output(runtime._child_output_path(task))
    tested = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                            cwd=project, capture_output=True, timeout=30).returncode == 0
    success = code == 0 and tested
    if case in READ_ONLY:
        success = success and READ_ONLY[case].lower() in answer.lower()
        success = success and not subprocess.check_output(['git', '-C', str(project), 'diff', '--name-only']).strip()
    return {'case': case, 'mode': mode, 'total_task_ms': wall, 'task_success': success,
            'exit_code': code, 'state_before_cleanup': state['state'],
            'validation_success': tested, 'terminal_code': state.get('terminal_code'),
            'first_token_ms': None, 'usage': usage, 'runtime_decisions': decisions,
            'observed_reasoning_items': reasoning, 'model_turns': None, 'cost': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--case', choices=tuple(CASES), action='append')
    parser.add_argument('--task-timeout', type=int, default=180,
                        help='Safety ceiling; exploratory successful pilot maximum was 86 seconds')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; real models and native task stores are used')
    if not 60 <= args.task_timeout <= 600:
        parser.error('--task-timeout must be between 60 and 600 seconds')
    base = load_ai_config(config_path())
    digest = source_hash()
    rows = []
    output = {'measurement': 'LIVE synthetic task smoke matrix; one pair per scenario, not statistical quality evidence',
              'source_sha256': digest, 'source_unchanged': None, 'rows': rows,
              'limits': ['No price data or model-turn counter.', 'No causal speed attribution; provider caching and load vary.',
                         'Subagent candidate respects the one-worker hard budget; it does not benchmark spawning.']}
    for index, case in enumerate(args.case or CASES):
        for mode in (('OFF', 'COOPERATIVE') if index % 2 == 0 else ('COOPERATIVE', 'OFF')):
            with tempfile.TemporaryDirectory(prefix='quattro-task-benchmark-') as temporary:
                try:
                    rows.append(run_case(base, mode, case, Path(temporary), args.task_timeout))
                except Exception as error:
                    trace = error.__traceback__
                    while trace is not None and trace.tb_next is not None:
                        trace = trace.tb_next
                    rows.append({'case': case, 'mode': mode, 'task_success': False,
                                 'failure_category': 'benchmark_execution_failed',
                                 'exception_type': type(error).__name__,
                                 'failure_function': trace.tb_frame.f_code.co_name if trace else None})
            output['source_unchanged'] = source_hash() == digest
            args.output.write_text(json.dumps(output, indent=2, allow_nan=False) + '\n')
    if not output['source_unchanged']:
        raise SystemExit('Source changed during benchmark; results are exploratory only')


if __name__ == '__main__':
    main()
