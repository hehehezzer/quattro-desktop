"""Compact, secret-safe checkpoint and recovery-packet helpers."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .privacy import redact_secret_text
from .supervisor import minimal_environment


CHECKPOINT_VERSION = 1


def _safe(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secret_text(value)[0]
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_safe(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe(str(value))


def repository_state(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Capture bounded read-only Git evidence without changing the worktree."""
    directory = Path(path).expanduser().resolve(strict=False)
    state: dict[str, Any] = {
        "exists": directory.is_dir(),
        "branch": None,
        "head": None,
        "dirty": None,
        "changedPaths": [],
    }
    git = shutil.which("git")
    if not git or not directory.is_dir():
        return state
    try:
        inside = subprocess.run(
            [git, "rev-parse", "--is-inside-work-tree"], cwd=directory,
            env=minimal_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=10, check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return state
        branch = subprocess.run(
            [git, "branch", "--show-current"], cwd=directory,
            env=minimal_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=10, check=False,
        )
        head = subprocess.run(
            [git, "rev-parse", "HEAD"], cwd=directory,
            env=minimal_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=10, check=False,
        )
        status = subprocess.run(
            [git, "status", "--porcelain=v1", "-z"], cwd=directory,
            env=minimal_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return state
    state["branch"] = branch.stdout.strip() if branch.returncode == 0 else None
    state["head"] = head.stdout.strip() if head.returncode == 0 else None
    if status.returncode == 0 and len(status.stdout) <= 2_000_000:
        records = [item for item in status.stdout.decode("utf-8", errors="replace").split("\0") if item]
        changed: list[str] = []
        index = 0
        while index < len(records):
            record = records[index]
            path_value = record[3:] if len(record) >= 4 else record
            changed.append(path_value)
            if len(record) >= 2 and (record[0] in "RC" or record[1] in "RC"):
                index += 1
                if index < len(records):
                    changed.append(records[index])
            index += 1
        state["dirty"] = bool(records)
        state["changedPaths"] = sorted(dict.fromkeys(changed))[:2_000]
    return state


def divergence(recorded: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    differences: list[str] = []
    if not current.get("exists"):
        return ["Recorded repository or working directory no longer exists."]
    for key, label in (("branch", "branch"), ("head", "HEAD")):
        if recorded.get(key) != current.get(key):
            differences.append(
                f"{label} differs: checkpoint={recorded.get(key)!r}, current={current.get(key)!r}."
            )
    recorded_paths = set(recorded.get("changedPaths") or [])
    current_paths = set(current.get("changedPaths") or [])
    if recorded_paths != current_paths:
        added = sorted(current_paths - recorded_paths)
        removed = sorted(recorded_paths - current_paths)
        detail = []
        if added:
            detail.append("new dirty paths: " + ", ".join(added[:50]))
        if removed:
            detail.append("previously dirty paths no longer dirty: " + ", ".join(removed[:50]))
        differences.append("Working-tree path set differs (" + "; ".join(detail) + ").")
    return differences


def checkpoint_payload(
    *,
    objective: str,
    requirements: Sequence[str],
    repository_path: str,
    working_directory: str,
    completed: Sequence[str] = (),
    files_changed: Sequence[Mapping[str, Any] | str] = (),
    important_decisions: Sequence[str] = (),
    validation: Sequence[Mapping[str, Any] | str] = (),
    unresolved: Sequence[str] = (),
    next_action: str,
    repository_snapshot: Mapping[str, Any] | None = None,
    relevant_artifacts: Sequence[Mapping[str, Any] | str] = (),
    active_codex_session_id: str | None = None,
    previous_codex_session_ids: Sequence[str] = (),
    account_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "objective": objective,
        "requirements": list(requirements),
        "repositoryPath": repository_path,
        "workingDirectory": working_directory,
        "completed": list(completed),
        "filesChanged": list(files_changed),
        "importantDecisions": list(important_decisions),
        "validation": list(validation),
        "unresolved": list(unresolved),
        "nextAction": next_action,
        "repositoryState": dict(repository_snapshot or repository_state(working_directory)),
        "relevantArtifacts": list(relevant_artifacts),
        "activeCodexSessionId": active_codex_session_id,
        "previousCodexSessionIds": list(previous_codex_session_ids),
        "accountId": account_id,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
        "checkpointVersion": CHECKPOINT_VERSION,
    }
    return _safe(payload)


def recovery_packet(
    checkpoint: Mapping[str, Any], *, current_repository_state: Mapping[str, Any]
) -> tuple[str, list[str]]:
    recorded = checkpoint.get("repositoryState")
    recorded_state = recorded if isinstance(recorded, Mapping) else {}
    differences = divergence(recorded_state, current_repository_state)
    unresolved = list(checkpoint.get("unresolved") or [])
    if differences:
        unresolved.append("Repository divergence detected; preserve current files and inspect before editing.")
        unresolved.extend(differences)

    def lines(value: Any, empty: str = "None recorded.") -> str:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            rendered = [f"- {json.dumps(item, ensure_ascii=False) if isinstance(item, Mapping) else item}" for item in value]
            return "\n".join(rendered) if rendered else empty
        return str(value) if value not in (None, "") else empty

    packet = "\n\n".join((
        "OBJECTIVE\n" + lines(checkpoint.get("objective")),
        "REQUIREMENTS\n" + lines(checkpoint.get("requirements")),
        "COMPLETED\n" + lines(checkpoint.get("completed")),
        "FILES CHANGED\n" + lines(checkpoint.get("filesChanged")),
        "IMPORTANT DECISIONS\n" + lines(checkpoint.get("importantDecisions")),
        "VALIDATION\n" + lines(checkpoint.get("validation")),
        "UNRESOLVED\n" + lines(unresolved),
        "NEXT ACTION\n" + lines(checkpoint.get("nextAction")),
        "REPOSITORY STATE\n" + json.dumps({
            "checkpoint": recorded_state,
            "current": dict(current_repository_state),
            "divergence": differences,
        }, ensure_ascii=False, indent=2, sort_keys=True),
    )) + "\n"
    safe_packet, _ = redact_secret_text(packet)
    return safe_packet, differences
