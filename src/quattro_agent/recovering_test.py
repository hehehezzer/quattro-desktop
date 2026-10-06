"""One bounded host test invocation; recovery decisions belong to the model.

Failures stay available to native reasoning and its dynamic decision tool. This
helper never submits a fixed retry questionnaire or silently repeats a test.
"""
from __future__ import annotations

from pathlib import Path
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
    result["fallback"] = "model_decision_required" if session is not None else "not_admitted"
    result["needs_agent_action"] = True
    return result
