#!/usr/bin/env python3
"""Fail when tracked content violates the public-artifact policy.

This intentionally checks the Git index rather than the whole working tree:
ignored local state is allowed during development but cannot be published.
It is a small release guard, not a replacement for a secret manager or review.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


BANNED_PARTS = {
    ".env", ".env.local", ".env.production", ".env.development",
    ".git", ".venv", "__pycache__", "backups", "generated-images", "reviews",
    "runtime", "tasks", "snapshots", "crashes", "dictation", "credentials",
    "secrets", "auth.json", "cookies", ".netrc", ".npmrc",
}
BANNED_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".db-shm", ".db-wal", ".log")
PRIVATE_MARKERS = (
    "/" + "home/", "work/" + "agentic", "projects/" + "projects",
    "Cefiro-" + "Org", "mark" + "3d",
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[opsu]_|github_pat_|sk-)[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|"
        r"client[_-]?secret)\s*[:=]\s*[\"']?([^\s\"'`]+)"
    ),
)
SAFE_SENTINELS = (
    "<redacted>", "synthetic", "must-not", "opaque-secret", "quattro-local-only",
    "example", "placeholder", "not-a-secret", "test-value", "do-not",
    "abcdefghijklmnopqrstuvwxyz",
)


def tracked_entries() -> list[tuple[str, str]]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    entries: list[tuple[str, str]] = []
    for raw in result.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not raw:
            continue
        metadata, path = raw.split("\t", 1)
        entries.append((metadata.split(" ", 1)[0], path))
    return entries


def scan() -> list[str]:
    findings: list[str] = []
    for mode, name in tracked_entries():
        path = Path(name)
        parts = {part.lower() for part in path.parts}
        if mode == "120000":
            findings.append(f"{name}: symbolic links are not publishable")
        if parts & BANNED_PARTS or name.lower().endswith(BANNED_SUFFIXES):
            if name != ".env.example":
                findings.append(f"{name}: runtime, credential, or generated artifact")
        try:
            data = path.read_bytes()
        except OSError as error:
            findings.append(f"{name}: cannot read tracked file ({error})")
            continue
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        lowered = text.lower()
        for marker in PRIVATE_MARKERS:
            if marker.lower() in lowered:
                findings.append(f"{name}: private or maintainer-specific marker {marker!r}")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1).lower() if match.lastindex else match.group(0).lower()
                if match.lastindex and re.fullmatch(r"[a-z_][a-z0-9_.]*", value):
                    # Code assignments such as ``password = state.password``
                    # name a variable; they do not embed a credential.
                    continue
                if any(sentinel in value for sentinel in SAFE_SENTINELS):
                    continue
                findings.append(f"{name}: credential-shaped value near byte {match.start()}")
    return sorted(set(findings))


def main() -> int:
    findings = scan()
    if findings:
        print("Public artifact policy: FAIL", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in findings), file=sys.stderr)
        return 1
    print("Public artifact policy: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
