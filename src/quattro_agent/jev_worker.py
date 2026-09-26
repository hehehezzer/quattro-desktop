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


def session() -> None:
    """One anonymous-pipe owner; fixed schema and one verified TLS client."""
    if __package__:
        from .decision_taxonomy import SCHEMA_VERSION, validate_request, question
    else:
        from decision_taxonomy import SCHEMA_VERSION, validate_request, question
    client = None
    try:
        line = sys.stdin.buffer.readline(8193)
        if len(line) > 8192:
            return
        setup = json.loads(line)
        timeout = setup["timeout_seconds"]
        if type(timeout) not in (float, int) or not 0.1 <= timeout <= 3:
            return
        client = JevClient(setup["key"], timeout)
        while True:
            line = sys.stdin.buffer.readline(8193)
            if not line or len(line) > 8192:
                return
            try:
                request = validate_request(json.loads(line))
                result = client.evaluate_questions(dict(request, schema_version=SCHEMA_VERSION),
                                                   question(request), reuse_catalog=True)
                result["failure_category"] = None
            except JevFailure as error:
                result = {"failure_category": error.category}
            except Exception:
                result = {"failure_category": "worker_failure"}
            sys.stdout.write(json.dumps(result, allow_nan=False) + "\n")
            sys.stdout.flush()
            if result.get("failure_category"):
                return  # No replay/reconnect after an ambiguous POST failure.
    finally:
        if client is not None:
            client.close()


def main() -> None:
    # Linux production: an abruptly killed owner must not leave network work alive.
    if sys.platform == "linux":
        import ctypes
        parent = os.getppid()
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            return
        if parent == 1 or os.getppid() != parent:
            return
    if sys.argv[1:] == ["--session"]:
        session()
        return
    started = time.perf_counter()
    client = None
    try:
        payload = json.loads(sys.stdin.buffer.read(8192))
        construction_started = time.perf_counter()
        client = JevClient(payload["key"], payload["timeout_seconds"])
        client.timings["client_construction_ms"] = (time.perf_counter() - construction_started) * 1000
        result = client.evaluate(payload["state"])
        result["failure_category"] = None
    except JevFailure as error:
        result = {"failure_category": error.category}
    except Exception:
        result = {"failure_category": "worker_failure"}
    if client is not None:
        client.close()
        result.update(client.timings)
    result["worker_started"] = started
    result["worker_latency_ms"] = (time.perf_counter() - started) * 1000
    sys.stdout.write(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
