"""Private bounded worker for Jev; stdin/stdout are anonymous pipes, never logs."""
from __future__ import annotations

import json
import os
import signal
import sys
import time

if __package__:
    from .jev import JevClient, JevFailure
else:
    # Standalone launch deliberately avoids importing the entire harness.
    from jev import JevClient, JevFailure


def main() -> None:
    # Linux production: an abruptly killed owner must not leave network work alive.
    if sys.platform == "linux":
        import ctypes
        parent = os.getppid()
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            return
        if parent == 1 or os.getppid() != parent:
            return
    started = time.perf_counter()
    client = None
    try:
        payload = json.loads(sys.stdin.buffer.read(8192))
        client = JevClient(payload["key"], payload["timeout_seconds"])
        result = client.evaluate(payload["state"])
        result["failure_category"] = None
    except JevFailure as error:
        result = {"failure_category": error.category}
    except Exception:
        result = {"failure_category": "worker_failure"}
    if client is not None:
        result.update(client.timings)
    result["worker_latency_ms"] = (time.perf_counter() - started) * 1000
    sys.stdout.write(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
