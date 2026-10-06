#!/usr/bin/env python3
"""Opt-in live timing for explicit authored decisions; no task or raw-input logs."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from quattro_agent.decision_service import DecisionSession
from quattro_agent.decision_taxonomy import MAX_REQUEST_BYTES, validate_request
from quattro_agent.jev import decode
from quattro_agent.provider_access import typesafe_credential_status

MAX_DECISIONS = 64
MAX_INPUT_BYTES = MAX_DECISIONS * MAX_REQUEST_BYTES


def distribution(values):
    values = sorted(values)
    return {"n": len(values), "p50": round(statistics.median(values), 3) if values else None,
            "p95": round(values[math.ceil(len(values) * .95) - 1], 3) if values else None,
            "max": round(max(values), 3) if values else None}


def read_authored_decisions(stream: Any) -> list[dict]:
    """Private bounded stdin; no defaults, generated choices or retained content."""
    raw = stream.read(MAX_INPUT_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("authored sequence exceeds limit")
    value = decode(raw)
    values = value if isinstance(value, list) else [value]
    if not 1 <= len(values) <= MAX_DECISIONS:
        raise ValueError("bounded authored decision sequence required")
    return [validate_request(item) for item in values]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-stdin", action="store_true", required=True,
                        help="read one authored v2 envelope or up to 64 envelopes as a JSON array from private stdin")
    parser.add_argument("--timeout-ms", type=int, default=1500, choices=range(100, 3001), metavar="100..3000")
    args = parser.parse_args()
    decisions = read_authored_decisions(getattr(sys.stdin, "buffer", sys.stdin))
    if typesafe_credential_status() != "configured":
        print(json.dumps({"status": "blocked", "reason": "credential_unavailable"}))
        return 1
    rows = []
    # Each supplied envelope is evaluated once. Host capabilities are not
    # attested by this transport-only script; it cannot create an action grant.
    with_session = DecisionSession(mode="COOPERATIVE", timeout_ms=args.timeout_ms)
    try:
        for index, authored in enumerate(decisions):
            request = dict(authored, execution_state=dict(authored["execution_state"], revision=index))
            result = with_session.decide(request, cacheable=False, capabilities=())
            timing = result.get("timing", {})
            rows.append({"sequence": index, "accepted": not result["fallback_required"],
                         "selected_effect": result.get("selected_effect"),
                         "provider_attempted": result.get("called") is True,
                         "evidence": result["evidence"], "timing": timing})
    finally:
        with_session.close()
    print(json.dumps({"measurement": "LIVE authored advisory decisions; no execution-model requests",
                      "provider_retries": 0, "authored_decisions": len(decisions),
                      "provider_attempts": sum(row["provider_attempted"] for row in rows),
                      "host_capabilities": "not_attested", "timeout_ms": args.timeout_ms,
                      "accepted": sum(row["accepted"] for row in rows),
                      "evidence": dict(Counter(row["evidence"] for row in rows)),
                      "blocking_ms": distribution([row["timing"]["blocking_ms"] for row in rows
                                                   if row["timing"].get("blocking_ms") is not None]),
                      "worker_roundtrip_ms": distribution([row["timing"]["worker_roundtrip_ms"] for row in rows
                                                            if row["timing"].get("worker_roundtrip_ms") is not None]),
                      "decisions": rows}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({"status": "failed", "reason": "benchmark_error"}))
        raise SystemExit(1) from None
