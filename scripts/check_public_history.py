#!/usr/bin/env python3
"""Check the commits reachable from HEAD for known private release markers."""

from __future__ import annotations

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
    r"sk-[A-Za-z0-9_-]{12,}",
    r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY-----",
)


def run(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True, stderr=subprocess.DEVNULL)


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
                text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                findings.append(f"{commit[:12]}: private marker {marker!r}")
        for pattern in TOKEN_PATTERNS:
            result = subprocess.run(
                ("git", "grep", "-I", "-n", "-E", "-e", pattern, commit, "--"),
                text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            if result.returncode == 0:
                findings.append(f"{commit[:12]}: credential marker {pattern!r}")
    if findings:
        print("Public history policy: FAIL", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in sorted(set(findings))), file=sys.stderr)
        return 1
    print(f"Public history policy: PASS ({len(commits)} reachable commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
