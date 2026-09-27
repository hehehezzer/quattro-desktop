#!/usr/bin/env python3
"""Matched real managed Codex/Pi test-failure recovery probes."""
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
sys.path.insert(0, str(SOURCE / "src"))
from quattro_agent.config import load_ai_config
from quattro_agent.paths import config_path, state_root
from quattro_harness import HarnessRuntime


FIXTURE = (
    "import pathlib, time, unittest\n"
    "class Check(unittest.TestCase):\n"
    " def test_ready(self):\n"
    "  time.sleep(1)\n"
    "  marker=pathlib.Path(__file__).with_name('ready.marker')\n"
    "  if not marker.exists():\n"
    "   marker.write_text('ready')\n"
    "   self.fail('expected ready True, got False after 1.0s')\n"
)


def probe(base, agent: str, mode: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="quattro-jev-test-") as directory:
        root = Path(directory)
        project = root / "fixture"
        (project / "tests").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        (project / "tests" / "test_flaky.py").write_text(FIXTURE)
        (project / "tests" / "test_sanity.py").write_text(
            "import unittest\nclass Check(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n")
        config = json.loads(json.dumps(base))
        config["memory"].update(enabled=False, enforceOnLaunch=False)
        config["delegation"]["enabled"] = False
        config["routing"]["jev"] = {"mode": "OFF", "timeoutMs": 1200,
                                    "testRecoveryMode": mode,
                                    "experimentalTestRecovery": True}
        path = root / "ai.json"
        path.write_text(json.dumps(config))
        os.chmod(path, 0o600)
        runtime = HarnessRuntime(config_path=path, state_root=state_root(),
                                 script_path=SOURCE / "src/quattro-agent", default_workspace=SOURCE)
        profile = "workspace-write" if agent == "codex" else "full-access-explicit"
        task = runtime.create_task(agent=agent, project=project, mode="prompt", profile_name=profile,
                                   confirm_full_access=agent == "pi",
                                   prompt=("Run test_flaky.py using quattro_test first. If it fails, "
                                           "retry the test once using the same tool when appropriate. "
                                           "Do not modify test source. Report PASS only if a test run passes."))
        started = time.perf_counter()
        timer = threading.Timer(150, runtime.request_cancel, args=(task,))
        timer.start()
        try:
            code = runtime.run_task(task)
        finally:
            timer.cancel()
            timer.join()
        raw_path = runtime._child_output_path(task)
        raw = raw_path.read_text() if raw_path.is_file() else ""
        private = runtime.store.get_task(task, include_private=True).get("private_payload", {})
        target = private.get("executionTarget") if isinstance(private.get("executionTarget"), dict) else {}
        plan = private.get("executionPlan") if isinstance(private.get("executionPlan"), dict) else {}
        tools, counts, usage = [], {}, {}
        final_answer = ""
        native_tools = 0
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            event_type = str(event.get("type", ""))
            counts[event_type] = counts.get(event_type, 0) + 1
            if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
            if event_type == "message_end":
                message = event.get("message") or {}
                if message.get("role") == "assistant":
                    for key, value in (message.get("usage") or {}).items():
                        if type(value) is int:
                            usage[key] = usage.get(key, 0) + value
                    text = "".join(part.get("text", "") for part in message.get("content", [])
                                   if isinstance(part, dict) and part.get("type") == "text")
                    if text:
                        final_answer = text.strip()
            if event_type == "tool_execution_end" and event.get("toolName") == "quattro_test":
                try:
                    result = json.loads(event["result"]["content"][0]["text"])
                except (KeyError, IndexError, TypeError, ValueError):
                    result = None
                tools.append(result)
            if event_type == "item.completed":
                item = event.get("item") or {}
                if item.get("type") not in {"agent_message", "reasoning"}:
                    native_tools += 1
                if item.get("type") == "agent_message":
                    final_answer = str(item.get("text", "")).strip()
                if item.get("type") == "mcp_tool_call" and item.get("tool") == "quattro_test":
                    try:
                        result = json.loads(item["result"]["content"][0]["text"])
                    except (KeyError, IndexError, TypeError, ValueError):
                        result = None
                    if isinstance(result, dict):
                        result["probe_arguments"] = item.get("arguments")
                    tools.append(result)
        return {"agent": agent, "mode": mode, "exit_code": code,
                "task_state": runtime.store.get_task(task)["state"],
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "model_steps": counts.get("turn_start", 0) if agent == "pi" else native_tools + 1,
                "model_steps_source": "pi_turn_start_events" if agent == "pi" else "codex_serial_tool_boundaries_estimate",
                "tool_calls": len(tools), "tool_results": tools,
                "answer_pass": "PASS" in final_answer.upper(),
                "marker_exists": (project / "tests" / "ready.marker").exists(),
                "target_route": target.get("route"), "plan_id": plan.get("planId"),
                "usage": usage, "event_counts": counts,
                "errors": [row.get("payload") for row in runtime.store.display_events(task)
                           if row["type"] == "task.error"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10:
        parser.error("samples must be 1-10")
    base = load_ai_config(config_path())
    def fingerprint():
        digest = hashlib.sha256()
        for path in sorted((SOURCE / "src").rglob("*")):
            if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
                digest.update(path.relative_to(SOURCE).as_posix().encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()
    source = fingerprint()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    rows = []
    for sample in range(args.samples):
        for agent in ("codex", "pi"):
            modes = ("OFF", "COOPERATIVE") if sample % 2 == 0 else ("COOPERATIVE", "OFF")
            for mode in modes:
                row = probe(base, agent, mode)
                row["sample"] = sample + 1
                rows.append(row)
                args.output.write_text(json.dumps({"source_sha256": source, "git_head": head,
                                                   "source_unchanged": fingerprint() == source,
                                                   "rows": rows}, indent=2, allow_nan=False) + "\n")
                print(agent, mode, sample + 1, row["task_state"], round(row["elapsed_ms"]),
                      row["model_steps"], row["tool_calls"], row["answer_pass"], flush=True)


if __name__ == "__main__":
    main()
