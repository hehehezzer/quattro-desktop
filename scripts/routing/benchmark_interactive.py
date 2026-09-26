#!/usr/bin/env python3
"""Measure the real direct transport without retaining prompt/answer content."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from quattro_agent.turn_gate import TurnGate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', default='account-1')
    parser.add_argument('--live', action='store_true', help='Send synthetic direct requests through OmniRoute')
    args = parser.parse_args()
    samples = (
        ('api_gateway', 'What is an API gateway? Answer in one sentence.'),
        ('credential_lookup', "What's my OmniRoute dashboard password?"),
        ('traceback', 'Explain this Python traceback: ValueError: invalid literal for int() with base 10: abc'),
    )
    with tempfile.TemporaryDirectory(prefix='quattro-latency-') as temporary:
        root = Path(temporary)
        gate = TurnGate(session_id='synthetic-benchmark', config={}, directory=root,
                        telemetry_path=root/'measurements.jsonl', account=args.account)
        for name, prompt in samples:
            turn = gate.begin(name, prompt, 'codex')
            status = 'completed'
            try:
                if args.live:
                    gate.direct(turn)
            except Exception:
                status = 'failed'
            finally:
                gate.finish(turn, status=status)
        rows = [json.loads(line) for line in (root/'measurements.jsonl').read_text().splitlines()]
        final = [row for row in rows if row['status'] != 'planned']
        for (name, _), row in zip(samples, final):
            row['case'] = name
            row['measurement'] = 'live' if args.live else 'routing_only'
        print(json.dumps({'schema_version': 1, 'measurements': final}, indent=2))
        return int(any(row['status'] != 'completed' for row in final))


if __name__ == '__main__':
    raise SystemExit(main())
