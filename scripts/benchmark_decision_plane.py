#!/usr/bin/env python3
"""Opt-in LIVE decision-boundary benchmark, not an end-to-end task benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from quattro_agent.decision_service import DecisionSession
from quattro_agent.decision_taxonomy import ACTIONS

# Synthetic categorical fixtures only. There is no raw request or execution data.
CASES = (
    ('trivial_question', None, {}, 'none', 'inspection'),
    ('simple_coding', 'validation_strategy', {'tests_available': True, 'changes_present': True}, 'success', 'validation'),
    ('repository_inspection', 'context_strategy', {'repository_required': True, 'context_missing': True}, 'none', 'inspection'),
    ('debugging', 'retry_strategy', {'context_missing': True}, 'unknown_failure', 'implementation'),
    ('multi_file_implementation', 'execution_strategy', {'multi_step_required': True, 'independent_steps': False}, 'success', 'implementation'),
    ('tool_heavy', 'context_strategy', {'repository_required': True, 'multi_step_required': True}, 'success', 'inspection'),
    ('skill_heavy', 'skill_selection', {}, 'none', 'inspection'),
    ('subagent_worthy', 'execution_strategy', {'independent_steps': True, 'multi_step_required': True}, 'none', 'implementation'),
    ('failing_test_repair', 'retry_strategy', {'tests_available': True, 'changes_present': True}, 'test_failure', 'validation'),
    ('research_retrieval', 'context_strategy', {'retrieval_required': True, 'context_missing': True}, 'none', 'inspection'),
    ('validation_heavy', 'progress_strategy', {'verification_required': True, 'tests_available': True, 'changes_present': True}, 'success', 'completion'),
)


def fixture(kind, flags, previous, phase, revision):
    return {'decision_type': kind, 'available_actions': list(ACTIONS.get(kind, {'agent': ''})),
            'relevant_context': flags,
            'hard_constraints': {'retry_allowed': previous == 'transient_failure',
                                 'parallel_allowed': bool(flags.get('independent_steps')),
                                 'retrieval_allowed': bool(flags.get('retrieval_required'))},
            'execution_state': {'revision': revision, 'phase': phase, 'attempt': 1},
            'previous_result': previous}


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {'samples': len(values), 'p50': statistics.median(values),
            'p95': ordered[min(len(ordered) - 1, int(len(ordered) * .95))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Authorize the fixed-origin provider calls')
    parser.add_argument('--samples', type=int, choices=range(1, 21), default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; this script spends provider tokens')
    rows = []
    sessions = []
    for sample in range(args.samples):
        for mode in (('OFF', 'COOPERATIVE') if sample % 2 == 0 else ('COOPERATIVE', 'OFF')):
            session = DecisionSession(mode=mode)
            try:
                for revision, (name, kind, flags, previous, phase) in enumerate(CASES):
                    start = time.perf_counter()
                    result = (session.decide(fixture(kind, flags, previous, phase, revision)) if kind else
                              {'selected_action': None, 'fallback_required': True, 'evidence': 'local_trivial_skip'})
                    rows.append({'sample': sample, 'mode': mode, 'case': name,
                                 'decision_boundary_ms': (time.perf_counter() - start) * 1000,
                                 'result': result})
            finally:
                session.close()
                sessions.append({'sample': sample, 'mode': mode, 'telemetry': session.snapshot()})
    summary = {}
    for mode in ('OFF', 'COOPERATIVE'):
        selected = [row for row in rows if row['mode'] == mode]
        summary[mode] = {
            'decision_boundary_ms': distribution([row['decision_boundary_ms'] for row in selected]),
            'jev_rtt_ms': distribution([row['result']['timing']['rtt_ms'] for row in selected
                                        if row['result'].get('timing', {}).get('rtt_ms') is not None]),
            'blocking_ms': distribution([row['result']['timing']['blocking_ms'] for row in selected
                                        if 'timing' in row['result']]),
            'usable_advice': sum(not row['result']['fallback_required'] for row in selected),
            'first_token_ms': None, 'total_task_ms': None, 'model_turns': None,
            'execution_tokens': None, 'cost': None, 'task_success': None,
        }
    output = {'measurement': 'LIVE decision component only; no execution model or tools run',
              'release_gate_passed': False,
              'limits': ['No task-quality gold labels; usable advice is not successful execution.',
                         'No model-token, task-wall-time, cost or routing-quality improvement established.',
                         'Skill selection is intentionally unsupported and fails open.'],
              'summary': summary, 'sessions': sessions, 'rows': rows}
    text = json.dumps(output, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
