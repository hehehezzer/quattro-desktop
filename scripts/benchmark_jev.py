#!/usr/bin/env python3
"""Hermetic OFF/SHADOW/COOPERATIVE benchmark; NOT a TypeSafe service benchmark.

Real supervised child processes, simulated 20 ms evaluations, actual local
feature/policy/registry/SQLite code. No external network or installed state.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from quattro_agent.delegation import classify_task_request
from quattro_agent.errors import ConfigError
from quattro_agent.jev_shadow import ShadowRun, annotate, lifecycle, mark_dispatch
from quattro_agent.model_registry import default_policy_path, load_model_registry, select_execution_target
from quattro_agent.routing_intelligence import make_pre_routing_input, task_profile_from_dict
from quattro_agent.routing_signals import classify_with_signals
from quattro_agent.turn_gate import TurnGate

TASKS = {
    "informational": "Hello",
    "coding_question": "Explain a Python list comprehension",
    "repository_modification": "Modify the repository parser",
    "frontend": "Implement accessible frontend controls and verify tests",
    "debugging": "Debug the repository regression and reproduce the root cause",
    "research": "Research current official documentation with sources",
    "complex_coding": "First inspect repository architecture then implement migration and verify tests",
    "review": "Review the repository for security issues without modifying files",
}
WORKER = '''
import json, sys, time
from jev import CHOICES, MODEL
payload = json.load(sys.stdin)
state = json.loads(payload["state"])
start = time.perf_counter()
time.sleep(0.020)
execution = "DELEGATE" if state["tool_required"] else "DIRECT"
complexity = state["complexity"].upper()
selected = {"execution": execution, "complexity": complexity,
            "capability": "STRONG" if complexity == "HIGH" else "CHEAP",
            "task_type": state["category"].upper()}
response = {"model": MODEL, "answers": {
    name: {"type": "choice", "choice": selected[name], "confidence": .96,
           "probabilities": {choice: .96 if choice == selected[name] else .04/(len(choices)-1)
                             for choice in choices}}
    for name, choices in CHOICES.items()}, "usage": {"input_tokens": 0, "output_tokens": 0}}
print(json.dumps({"response": response, "failure_category": None,
                  "jev_latency_ms": (time.perf_counter()-start)*1000,
                  "catalog_latency_ms": 0.0}))
'''


def distribution(values):
    if not values:
        return {"n": 0, "p50_ms": None, "p95_ms": None}
    values = sorted(values)
    return {"n": len(values), "p50_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[math.ceil(len(values) * .95) - 1], 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--native", action="store_true", help="Benchmark latency-fixed native TurnGate")
    args = parser.parse_args()
    registry = load_model_registry(default_policy_path(), SRC / "quattro/omniroute-model-catalog.json")
    original_init = ShadowRun.__init__
    def popen(_args, **kwargs):
        return subprocess.Popen([sys.executable, "-c", WORKER], **kwargs)
    def init(run, **kwargs):
        original_init(run, **kwargs, popen=popen)
    output = {"entrypoint": "native TurnGate" if args.native else "harness routing boundary",
              "transport": "simulated; real child process; no external calls",
              "provider_usage": "unavailable; fixture zero counts are not real usage",
              "learned_model": "no active artifact in isolated benchmark store",
              "modes": {}}
    with tempfile.TemporaryDirectory() as temporary, \
         mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": secrets.token_hex(24)}), \
         mock.patch.object(ShadowRun, "__init__", init):
        database = Path(temporary) / "intelligence.sqlite3"
        for mode in ("OFF", "SHADOW", "COOPERATIVE"):
            samples, models, categories = [], Counter(), {}
            gate = TurnGate(
                session_id="benchmark", config={"routing": {"jev": {"mode": mode, "timeoutMs": 300}}},
                directory=Path(temporary), telemetry_path=Path(temporary) / "turns.jsonl",
                account="account-1", registry=registry,
            ) if args.native else None
            @lifecycle
            def route(label, prompt):
                started = time.perf_counter()
                if gate is not None:
                    try:
                        turn = gate.begin(label, prompt, "codex")
                    except ConfigError:
                        return (time.perf_counter() - started) * 1000, "no_eligible_target"
                    critical_ms = (time.perf_counter() - started) * 1000
                    for run in turn.shadow_runs:
                        run.annotations["benchmark_category"] = label
                    time.sleep(.080)
                    gate.finish(turn)
                    return critical_ms, turn.plan.target.model
                execution = classify_task_request(prompt)
                boundary = make_pre_routing_input(
                    request=prompt, working_directory=temporary, repository_present=True,
                    explicit_model="auto", routing_mode="auto", selected_account="account-1",
                    agent="codex", workflow="prompt", policy_name="workspace-write",
                )
                def select(proposed):
                    try:
                        return select_execution_target(task_profile_from_dict(proposed.task_profile), registry,
                                                       preferred_account="account-1")
                    except ConfigError:
                        return None
                routing = classify_with_signals(
                    pre_routing_input=boundary, config={"routing": {"jev": {"mode": mode, "timeoutMs": 300}}},
                    database=database, execution=execution.decision, can_select=lambda proposed: bool(select(proposed)),
                )
                target = select(routing)
                annotate(final_decision={"execution": execution.decision, "worker": execution.required_agent,
                                         "model": target.model if target else None,
                                         "provider": target.provider if target else None,
                                         "account": target.account if target else None,
                                         "target_status": "selected" if target else "no_eligible_target",
                                         "reasoning_effort": routing.reasoning_effort},
                         benchmark_category=label)
                mark_dispatch()
                critical_ms = (time.perf_counter() - started) * 1000
                # Simulate useful execution so SHADOW can finish without extending routing.
                time.sleep(.080)
                return critical_ms, target.model if target else "no_eligible_target"
            for _ in range(args.repetitions):
                for label, prompt in TASKS.items():
                    latency, model = route(label, prompt)
                    samples.append(latency)
                    categories.setdefault(label, []).append(latency)
                    models[model] += 1
            rows = []
            evidence_path = (Path(temporary) / "intelligence" / "jev-shadow.sqlite3"
                             if args.native else database.with_name("jev-shadow.sqlite3"))
            if evidence_path.exists():
                with closing(sqlite3.connect(evidence_path)) as connection:
                    rows = [json.loads(row[0]) for row in connection.execute("SELECT evidence FROM jev_shadow")]
                rows = [row for row in rows if row.get("mode") == mode]
            output["modes"][mode] = {
                "critical_path": distribution(samples),
                "per_task_type": {name: distribution(values) for name, values in categories.items()},
                "components": {name: distribution([row[name] for row in rows if row.get(name) is not None])
                               for name in ("jev_latency_ms", "quattro_learned_ms", "fusion_ms", "feature_extraction_ms", "critical_path_wait_ms")},
                "timeout_rate": sum(row["timeout_count"] for row in rows) / len(rows) if rows else None,
                "failure_rate": sum(row["status"] != "success" for row in rows) / len(rows) if rows else None,
                "agreement": dict(Counter(str(row["agreement"]) for row in rows)),
                "models": dict(models),
                "examples": [{name: row.get(name) for name in ("benchmark_category", "answers", "learned_signal", "fusion_reason", "final_decision")}
                             for row in rows[:len(TASKS)]],
            }
    baseline = output["modes"]["OFF"]["critical_path"]["p50_ms"]
    for mode in ("SHADOW", "COOPERATIVE"):
        output["modes"][mode]["added_p50_critical_path_ms"] = round(output["modes"][mode]["critical_path"]["p50_ms"] - baseline, 3)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
