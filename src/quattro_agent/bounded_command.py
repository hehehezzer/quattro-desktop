"""Portable, bounded subprocess output for host-owned read-only/validation tools."""
from __future__ import annotations

from pathlib import Path
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Sequence


def run_bounded(argv: Sequence[str], *, cwd: Path, timeout: float,
                max_output: int = 16384) -> dict:
    started = time.perf_counter()
    output = bytearray()
    overflow = threading.Event()
    finished = threading.Event()
    try:
        command = (sys.executable, str(Path(__file__).with_name("bounded_command_worker.py")), *argv)
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=os.name == "posix",
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
    except OSError:
        return {"status": "spawn_error", "exit_code": None, "output": "", "truncated": False,
                "elapsed_ms": (time.perf_counter() - started) * 1000}

    def drain() -> None:
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    return
                room = max_output - len(output)
                if room > 0:
                    output.extend(chunk[:room])
                if len(chunk) > room:
                    overflow.set()
                    return
        finally:
            finished.set()

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    deadline = started + timeout
    timed_out = False
    def stop_tree() -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=3, check=False)
    try:
        while not finished.wait(min(0.02, max(0.0, deadline - time.perf_counter()))):
            if overflow.is_set():
                break
            if time.perf_counter() >= deadline:
                timed_out = True
                break
        if overflow.is_set() or timed_out:
            stop_tree()
        try:
            code = process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            code = process.wait(timeout=0.5)
        reader.join(timeout=0.5)
    finally:
        if process.poll() is None:
            stop_tree()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout is not None:
            process.stdout.close()
    return {"status": "timeout" if timed_out else "truncated" if overflow.is_set() else "completed",
            "exit_code": code, "output": output.decode("utf-8", "replace"),
            "truncated": overflow.is_set(), "elapsed_ms": (time.perf_counter() - started) * 1000}
