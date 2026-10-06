"""Private bounded worker for Jev; stdin/stdout are anonymous pipes, never logs."""
from __future__ import annotations

import json
import os
import signal
import sys
import time

if __package__:
    from .jev import JevClient, JevFailure, decode
else:
    # Standalone launch deliberately avoids importing the entire harness.
    from jev import JevClient, JevFailure, decode


def _validate_setup(value: object, required: set[str]) -> None:
    if (not isinstance(value, dict) or set(value) != required
            or not isinstance(value["key"], str) or len(value["key"]) > 1024
            or type(value["timeout_seconds"]) not in (float, int)
            or not 0.1 <= value["timeout_seconds"] <= 3):
        raise JevFailure("invalid_state")
    if not value["key"]:
        raise JevFailure("missing_credential")


def session() -> None:
    """One anonymous-pipe owner; bounded typed decisions and one TLS client."""
    if __package__:
        from .decision_taxonomy import MAX_REQUEST_BYTES, validate_request, question
    else:
        from decision_taxonomy import MAX_REQUEST_BYTES, validate_request, question
    client = None
    try:
        line = sys.stdin.buffer.readline(2049)
        if len(line.removesuffix(b"\n")) > 2048:
            return
        try:
            setup = decode(line)
            _validate_setup(setup, {"key", "timeout_seconds"})
        except JevFailure:
            return
        client = JevClient(setup["key"], setup["timeout_seconds"])
        while True:
            line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 2)
            if not line or len(line.removesuffix(b"\n")) > MAX_REQUEST_BYTES:
                return
            try:
                request = validate_request(decode(line))
                result = client.evaluate_questions(request, question(request), reuse_catalog=True)
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
        if __package__:
            from .decision_taxonomy import MAX_REQUEST_BYTES, validate_request
        else:
            from decision_taxonomy import MAX_REQUEST_BYTES, validate_request
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 2049)
        if len(raw) > MAX_REQUEST_BYTES + 2048:
            raise JevFailure("invalid_state")
        payload = decode(raw)
        _validate_setup(payload, {"key", "timeout_seconds", "state"})
        state = validate_request(payload["state"])
        construction_started = time.perf_counter()
        client = JevClient(payload["key"], payload["timeout_seconds"])
        client.timings["client_construction_ms"] = (time.perf_counter() - construction_started) * 1000
        result = client.evaluate(state)
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
