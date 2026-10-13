#!/usr/bin/python3
"""Display-only Codex quotas from omp's supported usage API; no session control."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

HOME = Path.home()
CACHE = HOME / ".local/state/quattro/agents/usage/native-omp.json"
MAX_AGE_SECONDS = 900


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalize(payload):
    reports = [report for report in payload.get("reports", [])
               if isinstance(report, dict) and report.get("provider") == "openai-codex"]
    # Never attribute an arbitrary pooled account to the legacy desktop selection.
    if len(reports) != 1:
        raise ValueError("ambiguous or unavailable native account")
    report = reports[0]
    fetched = report.get("fetchedAt")
    if not number(fetched) or fetched <= 0 or fetched > (time.time() + 60) * 1000:
        raise ValueError("invalid refresh time")
    windows = []
    for limit in report.get("limits", []):
        if not isinstance(limit, dict) or limit.get("id") not in (
            "openai-codex:primary", "openai-codex:secondary"
        ):
            continue
        amount = limit.get("amount") or {}
        window = limit.get("window") or {}
        fraction = amount.get("usedFraction")
        if not number(fraction):
            used, total = amount.get("used"), amount.get("limit")
            if not number(used) or not number(total) or total <= 0:
                continue
            fraction = used / total
        if not 0 <= fraction <= 1:
            continue
        duration = window.get("durationMs")
        if not number(duration) or duration <= 0:
            continue
        minutes = duration / 60000
        reset = window.get("resetsAt")
        windows.append({
            "usedPercent": round(fraction * 100, 1),
            "resetAt": reset / 1000 if number(reset) and reset > 0 else None,
            "windowMinutes": minutes,
            "label": {300: "5h", 1440: "D", 10080: "W"}.get(minutes, "Usage"),
        })
    if not windows:
        raise ValueError("no reported limit windows")
    windows.sort(key=lambda item: item["windowMinutes"])
    plan = (report.get("metadata") or {}).get("planType")
    if not isinstance(plan, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", plan):
        plan = None
    return {
        "schemaVersion": 1, "source": "omp", "alias": "omp · Codex",
        "loggedIn": True, "authenticationRequired": False, "plan": plan,
        "primary": windows[0], "secondary": windows[1] if len(windows) > 1 else None,
        "lastSuccessfulRefresh": dt.datetime.fromtimestamp(fetched / 1000, dt.timezone.utc).isoformat(),
        "fetchedAt": fetched,
    }


def publish(snapshot):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".native-omp-", dir=CACHE.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(snapshot, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CACHE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def saved():
    try:
        data = CACHE.read_bytes()
        if len(data) > 16384:
            return {}
        value = json.loads(data)
        return value if isinstance(value, dict) and value.get("source") == "omp" else {}
    except (OSError, ValueError):
        return {}


def main():
    snapshot = saved()
    error = ""
    try:
        search_path = str(HOME / ".local/bin") + os.pathsep + os.environ.get("PATH", os.defpath)
        command = shutil.which("omp", path=search_path)
        if command is None:
            raise FileNotFoundError("omp")
        result = subprocess.run(
            [command, "usage", "--json", "--redact",
             "--no-extensions", "--provider", "openai-codex"],
            cwd=HOME, env={"HOME": str(HOME),
                          "PATH": str(Path(command).parent) + os.pathsep + os.defpath,
                          "LANG": "C.UTF-8"},
            capture_output=True, timeout=35, check=True,
        )
        if len(result.stdout) > 1048576:
            raise ValueError("oversized quota response")
        snapshot = normalize(json.loads(result.stdout))
        publish(snapshot)
    except subprocess.TimeoutExpired:
        error = "Native usage refresh timed out."
    except (OSError, ValueError, TypeError, AttributeError, subprocess.CalledProcessError):
        # Raw provider output and credential/account metadata never reach QML or disk.
        error = "Native Codex limits unavailable. Check omp /usage."
    fetched = snapshot.get("fetchedAt")
    stale = bool(error) or not number(fetched) or time.time() * 1000 - fetched > MAX_AGE_SECONDS * 1000
    if any(number(window.get("resetAt")) and window["resetAt"] < time.time()
           for window in (snapshot.get("primary"), snapshot.get("secondary")) if isinstance(window, dict)):
        stale = True
    has_limits = isinstance(snapshot.get("primary"), dict)
    snapshot.update({
        "schemaVersion": 1, "stale": stale,
        "status": "stale" if has_limits and stale else "live" if has_limits else "unavailable",
        "message": error or ("Showing saved native limits." if stale else "Native omp Codex limits"),
    })
    print(json.dumps(snapshot, allow_nan=False))


if __name__ == "__main__":
    main()
