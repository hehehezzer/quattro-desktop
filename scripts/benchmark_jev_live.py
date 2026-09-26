#!/usr/bin/env python3
"""Opt-in live TypeSafe routing benchmark; no execution-model calls or raw input logs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from quattro_agent.provider_access import typesafe_credential_status
from quattro_agent.model_registry import default_policy_path, load_model_registry
from quattro_agent.turn_gate import TurnGate

CASES = {
    "greeting": "hello",
    "definition": "What does TUI mean?",
    "debugging": "Debug the repository regression and reproduce the root cause",
    "explanation": "Explain a Python list comprehension",
    "repository_modification": "Modify the repository parser",
}


def distribution(values):
    values = sorted(values)
    return {"n": len(values), "p50": round(statistics.median(values), 3) if values else None,
            "p95": round(values[math.ceil(len(values) * .95) - 1], 3) if values else None,
            "max": round(max(values), 3) if values else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20, choices=range(10, 101), metavar="10..100")
    parser.add_argument("--timeout-ms", type=int, default=1500, choices=range(100, 3001), metavar="100..3000")
    args = parser.parse_args()
    if typesafe_credential_status() != "configured":
        print(json.dumps({"status": "blocked", "reason": "credential_unavailable"}))
        return 1
    registry = load_model_registry(default_policy_path(), SRC / "quattro/omniroute-model-catalog.json")
    output = {"measurement": "LIVE TypeSafe; native routing only; no execution-model requests",
              "timeout_ms": args.timeout_ms, "ordering": "alternating OFF/ON and ON/OFF pairs",
              "first_token_ms": None, "execution_total_ms": None, "cost": None, "modes": {}}
    with tempfile.TemporaryDirectory() as temporary:
        rows = {"OFF": [], "COOPERATIVE": []}
        gates = {mode: TurnGate(session_id="live-benchmark-" + mode,
                               config={"routing": {"jev": {"mode": mode, "timeoutMs": args.timeout_ms}}},
                               directory=Path(temporary), telemetry_path=Path(temporary) / mode / "turns.jsonl",
                               account="account-1", registry=registry) for mode in rows}
        try:
            for sample in range(args.samples):
                order = ("OFF", "COOPERATIVE") if sample % 2 == 0 else ("COOPERATIVE", "OFF")
                for label, prompt in CASES.items():
                    for mode in order:
                        gate = gates[mode]
                        turn = gate.begin(label, prompt, "codex")
                        gate.finish(turn)
                        runs = turn.shadow_runs
                        row = {"case": label, "routing_ms": turn.routing_ms,
                               "calls": sum(run.process is not None for run in runs),
                               "fusion_ms": turn.routing_evidence.get("fusion_ms", 0),
                               "route": turn.plan.target.route, "execution": turn.decision}
                        if runs:
                            record = runs[0].record
                            row.update({name: record.get(name) for name in
                                        ("jev_latency_ms", "catalog_latency_ms", "jev_model", "failure_category",
                                         "input_usage", "output_usage")})
                        rows[mode].append(row)
        finally:
            for gate in gates.values():
                gate.cancel_all()
        for mode, samples in rows.items():
            output["modes"][mode] = {
                "routing_ms": distribution([r["routing_ms"] for r in samples]),
                "fusion_ms": distribution([r["fusion_ms"] for r in samples]),
                "jev_calls_per_turn": distribution([r["calls"] for r in samples]),
                "jev_rtt_ms": distribution([r["jev_latency_ms"] for r in samples if r.get("jev_latency_ms") is not None]),
                "catalog_rtt_ms": distribution([r["catalog_latency_ms"] for r in samples if r.get("catalog_latency_ms") is not None]),
                "models": dict(Counter(r["jev_model"] for r in samples if r.get("jev_model"))),
                "failures": dict(Counter(r["failure_category"] for r in samples if r.get("failure_category"))),
                "input_usage": sum(r.get("input_usage") or 0 for r in samples),
                "output_usage": sum(r.get("output_usage") or 0 for r in samples),
                "cases": {label: {"routing_ms": distribution([r["routing_ms"] for r in samples if r["case"] == label]),
                                   "routes": sorted({r["route"] for r in samples if r["case"] == label})} for label in CASES},
            }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # Do not expose provider responses, request context or exception bodies.
        print(json.dumps({"status": "failed", "reason": "benchmark_error"}))
        raise SystemExit(1) from None
