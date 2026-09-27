"""Single-request Quattro helper for Pi's bounded test-recovery tool."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quattro_agent.decision_service import DecisionSession
from quattro_agent.recovering_test import recovering_test


def main() -> None:
    session = None
    try:
        request = json.loads(sys.stdin.buffer.read(1025))
        if (not isinstance(request, dict) or set(request) != {"tool", "test_file"}
                or request["tool"] != "test" or os.environ.get("QUATTRO_TEST_ALLOWED") != "1"):
            raise ValueError("test unavailable")
        if os.environ.get("QUATTRO_JEV_TEST_MODE") == "COOPERATIVE":
            session = DecisionSession(mode="COOPERATIVE", timeout_ms=1200)
        result = recovering_test(Path.cwd(), request["test_file"], session)
        sys.stdout.write(json.dumps(result, allow_nan=False) + "\n")
    except Exception:
        sys.stdout.write(json.dumps({"status": "error", "offloaded": False,
                                     "fallback": "helper_failure"}) + "\n")
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    main()
