#!/usr/bin/env python3
"""Thirty matched synthetic pairs; no providers, native tools or private replay.

This validates experimental plumbing, not real Jev quality or speed. Actual
task benchmarking needs separate bounded approval and judged correctness.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent.decision_checkpoint import CheckpointTracker, consult

SCENARIOS = ("inspection", "editing", "missing_context", "transient_failure",
             "deterministic_failure", "no_progress")


def run(pairs=30):
    rows = []
    for index in range(pairs):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        failure = scenario in SCENARIOS[3:]
        envelope = CheckpointTracker("synthetic").observe(inspection=True)
        envelope.update(state_revision=index, checkpoint="failure_no_progress" if failure else "after_inspection",
                        phase="implementation" if scenario == "editing" else "inspection",
                        previous_result="transient_failure" if scenario == "transient_failure" else "unknown_failure" if failure else "success")
        envelope["features"]["context_missing"] = scenario == "missing_context"
        envelope["provenance"]["context_missing"] = "host_observed"
        selected = "change_strategy" if failure else "more_context" if scenario == "missing_context" else "continue"
        arms = {}
        # Both control policies use the exact same categorical fixture inputs.
        for arm in ("agent_fixture", "local_rule", "jev_fixture"):
            started = time.perf_counter()
            if arm == "jev_fixture":
                result = consult(envelope, lambda _: dict(selected_action=selected,
                    confidence=.99, called=True, evidence="native_choice_probabilities", fallback_required=False))
                action = result["recommendation"]
            else:
                action = "change_plan" if failure else "gather_context" if envelope["features"]["context_missing"] else "continue_plan"
            arms[arm] = {"recommendation": action, "local_elapsed_ms": (time.perf_counter() - started) * 1000}
        rows.append({"pair": index, "scenario": scenario, "arms": arms,
                     "mandatory_admission": "unchanged", "task_correctness": "NOT_MEASURED"})
    return {"schema_version": 1, "mode": "synthetic_only", "pairs": pairs, "provider_calls": 0,
            "real_task_benefit": "NOT_MEASURED", "cost": "UNKNOWN",
            "matched_model_and_effort": "synthetic_only", "rows": rows,
            "median_local_fixture_ms": {arm: statistics.median(row["arms"][arm]["local_elapsed_ms"] for row in rows)
                                        for arm in ("agent_fixture", "local_rule", "jev_fixture")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 30 <= args.pairs <= 10000:
        parser.error("at least 30 and at most 10000 synthetic pairs required")
    rendered = json.dumps(run(args.pairs), indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
