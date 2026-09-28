#!/usr/bin/env python3
"""Live managed Codex AND standalone Pi completion-to-validation probes.

This does not force an agent to request Jev. The host observes completion and
runs its gated validation-order experiment. Zero avoided model reasoning is the
expected baseline; a host reordering alone is not a contribution/ROI claim.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

from benchmark_decision_tasks import SOURCE, fixture, source_hash, parse_output
sys.path.insert(0, str(SOURCE / "src"))
from quattro_agent.config import load_ai_config
from quattro_agent.models import TaskState, TERMINAL_TASK_STATES
from quattro_agent.paths import config_path, state_root
from quattro_harness import HarnessRuntime


def probe(base, root, agent, mode):
    project = root / "fixture"
    project.mkdir()
    fixture(project, "repository_inspection")
    config = json.loads(json.dumps(base))
    config["memory"].update(enabled=False, enforceOnLaunch=False)
    config["delegation"]["enabled"] = False
    config["routing"]["jev"] = {"mode": mode, "timeoutMs": 1500,
                                "experimentalValidationOrder": True}
    path = root / "ai.json"
    path.write_text(json.dumps(config))
    os.chmod(path, 0o600)
    runtime = HarnessRuntime(config_path=path, state_root=state_root(),
                             script_path=SOURCE / "src/quattro-agent", default_workspace=SOURCE)
    task = runtime.create_task(agent=agent, project=project, mode="prompt", profile_name="audit-read-only",
                               prompt="Reply exactly HOST_VALIDATION_PROBE_OK. Do not use tools, modify files, publish, or spawn workers. Quattro will run the fixture validation after your completion.")
    started = time.perf_counter()
    timer = threading.Timer(120, runtime.request_cancel, args=(task,))
    timer.start()
    try:
        code = runtime.run_task(task)
    finally:
        timer.cancel()
        timer.join()
        task_state = runtime.store.get_task(task)
        if TaskState(task_state["state"]) not in TERMINAL_TASK_STATES:
            runtime.request_cancel(task)
    output = runtime._child_output_path(task)
    if agent == "codex":
        answer = parse_output(output)[2]
    else:
        answer = output.read_text() if output.is_file() else ""
    marker = answer.strip() == "HOST_VALIDATION_PROBE_OK"
    events = runtime.store.display_events(task)
    return {"agent": agent, "mode": mode, "elapsed_ms": (time.perf_counter() - started) * 1000,
            "exit_code": code, "task_state": task_state["state"], "marker_present": marker,
            "task_success": code == 0 and marker,
            "milestones": [event["payload"] for event in events if event["type"] == "runtime.milestone"],
            "validation": [event["payload"] for event in events if event["type"] == "validation.completed"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; real native runtimes and provider calls are used")
    base = load_ai_config(config_path())
    before = source_hash()
    rows = []
    result = {"measurement": "LIVE managed completion boundary; no mid-turn interception claim",
              "source_sha256": before, "source_unchanged": None, "rows": rows,
              "limits": ["Marker task, not an implementation benchmark.",
                         "Host validation ordering does not eliminate baseline agent reasoning.",
                         "Standalone Pi uses PiAdapter, not the routed-Pi Codex delegate."]}
    for agent, modes in (("codex", ("OFF", "COOPERATIVE")), ("pi", ("COOPERATIVE", "OFF"))):
        for mode in modes:
            with tempfile.TemporaryDirectory(prefix="quattro-runtime-probe-") as temporary:
                try:
                    rows.append(probe(base, Path(temporary), agent, mode))
                except Exception as error:
                    rows.append({"agent": agent, "mode": mode, "task_success": False,
                                 "exception_type": type(error).__name__})
            result["source_unchanged"] = source_hash() == before
            args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if not result["source_unchanged"]:
        raise SystemExit("Source changed during probes; rerun affected validation")


if __name__ == "__main__":
    main()
