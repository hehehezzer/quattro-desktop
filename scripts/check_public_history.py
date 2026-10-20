#!/usr/bin/env python3
"""Check the commits reachable from HEAD for known private release markers."""

from __future__ import annotations

import re
import subprocess
import sys


MARKERS = (
    "/" + "home/", "work/" + "agentic", "projects/" + "projects",
    "Cefiro-" + "Org", "mark" + "3d",
)
BANNED_PARTS = {"reviews", "backups", "generated-images", "auth.json", "credentials.json"}
TOKEN_PATTERNS = (
    r"gh[opsu]_[A-Za-z0-9_]{12,}",
    r"github_pat_[A-Za-z0-9_]{12,}",
    r"(^|[^A-Za-z0-9_-])sk-[A-Za-z0-9_-]{12,}",
    r"-----BEGIN (OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY-----",
)
_HISTORICAL_SYNTHETIC_KEYS = frozenset({
    "s" + "k-" + "1234567890abcdefghijkl",
    "s" + "k-" + "synthetic-1234567890abcdefghijkl",
})
_PYTHON_SK_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{12,}")
# Owner-approved on 2026-10-21: one already-public machine-path finding.
# Acknowledgment is bound to immutable commit, path, blob, line and marker.
# Credential rules below are never exempted by this record.
ACKNOWLEDGED_HOME_PATH = (
    "a58015ac9f2a477b0864e91287bb6d89efc60f90",
    "src/restart-quickshell",
    "f6271236f5a94675534db101f38ea0255c08edda",
    19,
)


def allowed_historical_test_fixture(pattern: str, line: str) -> bool:
    """Allow only the exact synthetic sanitizer fixture committed in its test file."""
    matches = frozenset(_PYTHON_SK_TOKEN.findall(line))
    return (
        pattern == TOKEN_PATTERNS[2]
        and ":tests/test_intelligence.py:" in line
        and bool(matches)
        and matches <= _HISTORICAL_SYNTHETIC_KEYS
    )


def run(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True, stderr=subprocess.DEVNULL)


def acknowledged_historical_marker(commit: str, marker: str, lines: list[str]) -> bool:
    known_commit, path, blob, number = ACKNOWLEDGED_HOME_PATH
    if commit != known_commit or marker != MARKERS[0] or len(lines) != 1:
        return False
    if not lines[0].startswith(f"{commit}:{path}:{number}:"):
        return False
    return run("rev-parse", f"{commit}:{path}").strip() == blob

def main() -> int:
    commits = [line for line in run("rev-list", "HEAD").splitlines() if line]
    findings: list[str] = []
    for commit in commits:
        paths = run("ls-tree", "-r", "--name-only", commit).splitlines()
        for name in paths:
            if {part.casefold() for part in name.split("/")} & BANNED_PARTS:
                findings.append(f"{commit[:12]}: banned historical path {name}")
        for marker in MARKERS:
            result = subprocess.run(
                ("git", "grep", "-I", "-n", "-F", "-e", marker, commit, "--"),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                if not acknowledged_historical_marker(commit, marker, result.stdout.splitlines()):
                    findings.append(f"{commit[:12]}: private marker {marker!r}")
            elif result.returncode != 1:
                findings.append(
                    f"{commit[:12]}: private marker scan failed for marker {marker!r}"
                )
        for pattern in TOKEN_PATTERNS:
            result = subprocess.run(
                ("git", "grep", "-I", "-n", "-E", "-e", pattern, commit, "--"),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            if result.returncode not in {0, 1}:
                findings.append(
                    f"{commit[:12]}: credential scan failed for pattern {pattern!r}"
                )
                continue
            unsafe_matches = [
                line for line in result.stdout.splitlines()
                if not allowed_historical_test_fixture(pattern, line)
            ]
            if result.returncode == 0 and unsafe_matches:
                findings.append(f"{commit[:12]}: credential marker {pattern!r}")
    if findings:
        print("Public history policy: FAIL", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in sorted(set(findings))), file=sys.stderr)
        return 1
    print(f"Public history policy: PASS ({len(commits)} reachable commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
