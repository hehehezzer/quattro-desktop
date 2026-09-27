"""Host-owned bounded unit-test failure recovery for managed agent tools."""
from __future__ import annotations

from pathlib import Path
import hashlib
import re
import sys

from .bounded_command import run_bounded
from .decision_service import DecisionSession

MAX_TEST_OUTPUT = 16384
TEST_TIMEOUT = 20.0


def _test_file(root: Path, name: str) -> Path | None:
    if isinstance(name, str) and name.startswith("tests/"):
        name = name.removeprefix("tests/")
    if (not isinstance(name, str) or not re.fullmatch(r"test_[A-Za-z0-9_]{1,60}\.py", name)
            or not (root / "tests").is_dir()):
        return None
    directory = (root / "tests").resolve(strict=True)
    if not directory.is_relative_to(root) or (root / "tests").is_symlink():
        return None
    path = directory / name
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True).parent != directory:
        return None
    return path


def _run(root: Path, pattern: str) -> dict:
    return run_bounded([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern],
                       cwd=root, timeout=TEST_TIMEOUT, max_output=MAX_TEST_OUTPUT)


def _summary(output: str) -> str | None:
    # Only a fixed category crosses the provider boundary. Assertion payloads
    # can contain private fixture data even when they match no secret regex.
    for line in reversed(output.splitlines()):
        if (line.strip().startswith("AssertionError:")
                and re.search(r"\bread(?:y|iness)\b", line, re.I)
                and re.search(r"\bafter\s+(?:wait|\d+(?:\.\d+)?s)\b", line, re.I)):
            return "readiness_assertion_after_wait"
    return None


def _snapshot(root: Path) -> bytes | None:
    """Check relevant code/config metadata without opening repository content."""
    digest = hashlib.sha256()
    count = 0
    try:
        for path in sorted(root.rglob("*")):
            if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in path.relative_to(root).parts):
                continue
            if not (path.suffix == ".py" or path.name in {"pyproject.toml", "pytest.ini", "setup.cfg"}):
                continue
            if path.is_symlink():
                return None
            if not path.is_file():
                continue
            count += 1
            if count > 4000:
                return None
            stat = path.stat()
            digest.update(path.relative_to(root).as_posix().encode())
            for value in (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                digest.update(value.to_bytes(16, "big", signed=False))
    except OSError:
        return None
    return digest.digest()


def recovering_test(root: Path, name: str, session: DecisionSession | None) -> dict:
    if sys.platform != "linux":
        return {"status": "unsupported", "offloaded": False, "fallback": "platform_unsupported"}
    root = root.resolve(strict=True)
    path = _test_file(root, name)
    if path is None:
        return {"status": "invalid", "offloaded": False, "fallback": "invalid_test_file"}
    name = path.name
    first = _run(root, name)
    result = {"status": "passed" if first["status"] == "completed" and first["exit_code"] == 0 else "failed",
              "initial_exit_code": first["exit_code"], "initial_ms": first["elapsed_ms"],
              "initial_output": first["output"], "offloaded": False, "useful_result": False,
              "action": None, "fallback": None}
    if result["status"] == "passed":
        return result
    summary = _summary(first["output"])
    if (session is None or first["status"] != "completed" or first["truncated"]
            or not 500 <= first["elapsed_ms"] <= 10000 or summary is None):
        result["fallback"] = "not_admitted"
        return result
    snapshot = _snapshot(root)
    if snapshot is None:
        result["fallback"] = "snapshot_unavailable"
        return result
    actions = ["retry_exact", "agent"]
    request = {"decision_type": "test_recovery", "failure_summary": summary,
               "available_actions": actions,
               "relevant_context": {"test_duration": "slow" if first["elapsed_ms"] >= 2000 else "moderate"},
               "hard_constraints": {"retry_allowed": True, "parallel_allowed": False,
                                    "retrieval_allowed": False},
               "execution_state": {"revision": 0, "phase": "validation", "attempt": 1},
               "previous_result": "test_failure"}
    advice = session.decide(request)
    result["jev"] = {"called": advice.get("timing", {}).get("rtt_ms") is not None,
                     "confidence": advice.get("confidence"),
                     "blocking_ms": advice.get("timing", {}).get("blocking_ms"),
                     "rtt_ms": advice.get("timing", {}).get("rtt_ms"),
                     "request_body_bytes": advice.get("timing", {}).get("request_body_bytes")}
    if advice.get("fallback_required"):
        result["fallback"] = advice.get("evidence", "unavailable")
        return result
    if _snapshot(root) != snapshot:
        result["fallback"] = "stale"
        return result
    action = advice.get("selected_action")
    if action == "retry_exact":
        second = _run(root, name)
    else:
        result["fallback"] = "invalid_action"
        return result
    result["offloaded"] = True
    result["action"] = action
    result["recovery_ms"] = second["elapsed_ms"]
    result["recovery_exit_code"] = second["exit_code"]
    result["recovery_output"] = second["output"]
    result["useful_result"] = second["status"] == "completed" and second["exit_code"] == 0
    if action == "retry_exact" and result["useful_result"]:
        result["status"] = "recovered"
        result["initial_summary"] = summary
        result["initial_output"] = ""
        result["recovery_output"] = ""
        result["needs_agent_action"] = False
    return result
