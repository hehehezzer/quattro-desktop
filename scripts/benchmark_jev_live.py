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
    "trivial_direct": "hello",
    "explanation": "Explain a Python list comprehension",
    "ambiguous_direct": "Maybe a strategy for current information and architecture trade-offs is needed",
    "simple_coding": "Write a Python function to add two numbers",
    "repository_inspection": "Inspect the repository and identify the entrypoint",
    "repository_modification": "Modify the repository parser",
    "debugging": "Debug the repository regression and reproduce the root cause",
    "frontend": "Implement an accessible React frontend with responsive navigation and tests",
    "backend": "Implement a backend endpoint with validation and database persistence",
    "research": "Research the latest Python release and verify official sources",
    "complex_coding": "Refactor the repository authentication architecture, migrate the database and verify integration tests",
    "sequence_direct_before": "What does TUI mean?",
    "sequence_delegate": "Debug the repository regression and reproduce the root cause",
    "sequence_direct_after": "What is an API gateway?",
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
    parser.add_argument("--decision-wait-ms", type=int, choices=range(0, 3001), metavar="0..3000")
    args = parser.parse_args()
    if typesafe_credential_status() != "configured":
        print(json.dumps({"status": "blocked", "reason": "credential_unavailable"}))
        return 1
    registry = load_model_registry(default_policy_path(), SRC / "quattro/omniroute-model-catalog.json")
    output = {"measurement": "LIVE TypeSafe; native routing only; no execution-model requests",
              "timeout_ms": args.timeout_ms, "decision_wait_ms": args.decision_wait_ms,
              "ordering": "alternating OFF/ON and ON/OFF pairs",
              "first_token_ms": None, "execution_total_ms": None, "cost": None, "modes": {}}
    with tempfile.TemporaryDirectory() as temporary:
        rows = {"OFF": [], "COOPERATIVE": []}
        wait_options = {} if args.decision_wait_ms is None else {"decisionWaitMs": args.decision_wait_ms}
        gates = {mode: TurnGate(session_id="live-benchmark-" + mode,
                               config={"routing": {"jev": {"mode": mode, "timeoutMs": args.timeout_ms, **wait_options}}},
                               directory=Path(temporary), telemetry_path=Path(temporary) / mode / "turns.jsonl",
                               account="account-1", registry=registry) for mode in rows}
        try:
            for sample in range(args.samples):
                order = ("OFF", "COOPERATIVE") if sample % 2 == 0 else ("COOPERATIVE", "OFF")
                for label, prompt in CASES.items():
                    for mode in order:
                        gate = gates[mode]
                        thread = "sequence" if label.startswith("sequence_") else label
                        turn = gate.begin(thread, prompt, "codex")
                        # Observe late RTT outside measured routing, without
                        # pretending this settling interval is task execution.
                        if args.decision_wait_ms is not None:
                            for run in turn.shadow_runs:
                                run.done.wait(args.timeout_ms / 1000 + 1)
                        gate.finish(turn)
                        runs = turn.shadow_runs
                        row = {"case": label, "routing_ms": turn.routing_ms,
                               "calls": sum(run.process is not None for run in runs),
                               "fusion_ms": turn.routing_evidence.get("fusion_ms", 0),
                               "route": turn.plan.target.route, "execution": turn.decision}
                        row.update({name: turn.routing_evidence.get(name) for name in
                                    ("jev_wait_ms", "local_routing_ms", "routing_critical_path_ms")})
                        if runs:
                            record = runs[0].record
                            row.update({name: record.get(name) for name in
                                        ("jev_latency_ms", "catalog_latency_ms", "jev_model", "failure_category",
                                         "input_usage", "output_usage", "jev_overlap_ms", "jev_rtt_ms",
                                         "process_creation_ms", "worker_startup_ms", "client_construction_ms")})
                        rows[mode].append(row)
        finally:
            for gate in gates.values():
                gate.cancel_all()
        for mode, samples in rows.items():
            output["modes"][mode] = {
                **{metric: distribution([r[metric] for r in samples if r.get(metric) is not None])
                   for metric in ("jev_wait_ms", "jev_overlap_ms", "local_routing_ms",
                                  "process_creation_ms", "worker_startup_ms", "client_construction_ms")},
                "routing_ms": distribution([r["routing_ms"] for r in samples]),
                "fusion_ms": distribution([r["fusion_ms"] for r in samples]),
                "jev_calls_per_turn": distribution([r["calls"] for r in samples]),
                "jev_rtt_ms": distribution([r["jev_latency_ms"] for r in samples if r.get("jev_latency_ms") is not None]),
                "catalog_rtt_ms": distribution([r["catalog_latency_ms"] for r in samples if r.get("catalog_latency_ms") is not None]),
                "models": dict(Counter(r["jev_model"] for r in samples if r.get("jev_model"))),
                "failures": dict(Counter(r["failure_category"] for r in samples if r.get("failure_category"))),
                "input_usage": sum(r.get("input_usage") or 0 for r in samples),
                "output_usage": sum(r.get("output_usage") or 0 for r in samples),
                "cases": {label: {
                    **{metric: distribution([r[metric] for r in samples
                                             if r["case"] == label and r.get(metric) is not None])
                       for metric in ("routing_ms", "jev_latency_ms", "jev_wait_ms", "jev_overlap_ms",
                                      "local_routing_ms", "fusion_ms", "routing_critical_path_ms", "calls")},
                    "routes": sorted({r["route"] for r in samples if r["case"] == label}),
                    "execution": sorted({r["execution"] for r in samples if r["case"] == label}),
                    "first_token_ms": None, "total_turn_ms": None,
                } for label in CASES},
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
