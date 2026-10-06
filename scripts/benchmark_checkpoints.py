#!/usr/bin/env python3
"""Matched synthetic authored-decision fixtures; no provider or task benchmark.

Questions, options and scalar parameters here are test inputs. This script
measures local plumbing, never native model authorship, Jev quality or speed.
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


def authored_fixture(index, scenario, revision):
    effect = "inspect" if scenario in {"inspection", "missing_context"} else "advise"
    return {"schema_version": "quattro-jev-decisions-v2",
            "decision_id": f"compare_{scenario}_evidence_{index}",
            "question": f"Which bounded next step fits the observed {scenario.replace('_', ' ')} evidence?",
            "options": [{"id": f"evaluate_observed_gap_{index}",
                "description": "Evaluate the bounded observed gap before deciding the next action.", "effect": effect},
                {"id": f"reason_about_remaining_uncertainty_{index}",
                "description": "Return the remaining uncertainty to native reasoning.", "effect": "agent"}],
            "context": {f"{scenario}_evidence_count": index + 1, "remaining_uncertainty": True},
            "hard_constraints": {"retry_allowed": False, "parallel_allowed": False, "retrieval_allowed": False},
            "execution_state": {"revision": revision, "phase": f"compare_{scenario}_evidence", "attempt": 0},
            "previous_result": "synthetic_observation"}


def run(pairs=30):
    if type(pairs) is not int or not 30 <= pairs <= 10000:
        raise ValueError("at least 30 and at most 10000 synthetic pairs required")
    rows = []
    for index in range(pairs):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        envelope = CheckpointTracker("synthetic").observe(inspection=True)
        envelope["state_revision"] = index
        envelope["decision"] = authored_fixture(index, scenario, index)
        selected = envelope["decision"]["options"][0]
        arms = {}
        for arm in ("agent_fixture", "local_rule", "jev_fixture"):
            started = time.perf_counter()
            accepted = False
            if arm == "jev_fixture":
                result = consult(envelope, lambda request: dict(selected_action=request["options"][0]["id"],
                    confidence=.99, called=True, evidence="native_choice_probabilities", fallback_required=False))
                action, accepted = result["recommendation"], result["accepted"]
            else:
                action = selected["effect"]
            arms[arm] = {"recommendation_effect": action, "fixture_accepted": accepted,
                         "local_elapsed_ms": (time.perf_counter() - started) * 1000}
        rows.append({"pair": index, "scenario": scenario, "arms": arms,
                     "mandatory_admission": "unchanged", "task_correctness": "NOT_MEASURED"})
    return {"schema_version": 2, "mode": "synthetic_only", "pairs": pairs, "provider_calls": 0,
            "native_authorship": "NOT_MEASURED", "real_task_benefit": "NOT_MEASURED", "cost": "UNKNOWN",
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
