"""Quattro-owned Codex session namespace with account-isolated credentials."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import datetime as dt
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ConfigError


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _same_file(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    digest = lambda path: hashlib.sha256(path.read_bytes()).digest()
    return digest(left) == digest(right)


def _rollout_metadata(path: Path) -> tuple[str, str] | None:
    try:
        with path.open("r", encoding="utf-8") as stream:
            first = json.loads(stream.readline(1_048_577))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    payload = first.get("payload") if isinstance(first, dict) else None
    value = payload.get("id") if first.get("type") == "session_meta" and isinstance(payload, dict) else None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return (value, cwd) if isinstance(value, str) and value and isinstance(cwd, str) else None


def prepare_shared_session_namespace(
    accounts: Iterable[Mapping[str, Any]], shared_root: Path, registry_path: Path
) -> dict[str, Any]:
    """Migrate only rollout files, then link each isolated home to the namespace.

    Account homes, configuration, and authentication files remain separate.
    A conflicting rollout path fails closed; no source is deleted until every
    file has been copied and verified.
    """
    shared_root = shared_root.expanduser().resolve(strict=False)
    shared_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(shared_root, 0o700)
    registry_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    migrated = 0
    linked = 0
    try:
        with os.fdopen(descriptor, "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                registry = {"schemaVersion": 1, "sessions": {}}
            sessions = registry.get("sessions")
            if not isinstance(sessions, dict):
                raise ConfigError("Codex session registry is malformed")
            for account in accounts:
                if not account.get("enabled", True):
                    continue
                account_id = account.get("id")
                home_value = account.get("codexHome")
                if not isinstance(account_id, str) or not isinstance(home_value, str):
                    raise ConfigError("Codex account record is incomplete")
                home = Path(os.path.expandvars(os.path.expanduser(home_value)))
                if home.is_symlink():
                    raise ConfigError("Codex account home must not be a symlink")
                home = home.resolve(strict=True)
                source = home / "sessions"
                backup = home / "sessions.pre-quattro-shared"
                if source.is_symlink():
                    if source.resolve(strict=True) != shared_root.resolve(strict=True):
                        raise ConfigError(f"{account_id} sessions link targets an unapproved path")
                    continue
                recovering = backup.is_dir() and not source.exists()
                if backup.exists() and not recovering:
                    raise ConfigError(f"ambiguous preserved session directory for {account_id}")
                migration_source = backup if recovering else source
                migration_source.mkdir(mode=0o700, parents=True, exist_ok=True)
                for candidate in migration_source.rglob("*.jsonl"):
                    if candidate.is_symlink() or not candidate.is_file():
                        raise ConfigError("Codex session namespace contains an unsafe rollout path")
                    relative = candidate.relative_to(migration_source)
                    target = shared_root / relative
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    if target.exists():
                        if target.is_symlink() or not _same_file(candidate, target):
                            raise ConfigError(f"conflicting Codex rollout path: {relative}")
                    else:
                        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
                        shutil.copyfile(candidate, temporary)
                        os.chmod(temporary, 0o600)
                        os.replace(temporary, target)
                        migrated += 1
                    metadata = _rollout_metadata(candidate)
                    if metadata:
                        rollout_id, cwd = metadata
                        modified = dt.datetime.fromtimestamp(
                            candidate.stat().st_mtime, dt.timezone.utc
                        ).isoformat(timespec="seconds")
                        sessions.setdefault(rollout_id, {
                            "originatingAccount": account_id,
                            "mostRecentlyUsedAccount": account_id,
                            "providerId": "omniroute",
                            "projectPath": cwd,
                            "createdAt": modified,
                            "updatedAt": modified,
                        })
                if not recovering:
                    os.replace(source, backup)
                os.symlink(shared_root, source, target_is_directory=True)
                linked += 1
            _atomic_json(registry_path, {"schemaVersion": 1, "sessions": sessions})
    finally:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
    return {"migrated": migrated, "linkedAccounts": linked}


def load_session_registry(path: Path) -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    sessions = value.get("sessions") if isinstance(value, dict) else None
    return sessions if isinstance(sessions, dict) else {}


def update_session_registry(path: Path, session_id: str, values: Mapping[str, Any]) -> None:
    lock_path = path.with_suffix(path.suffix + ".lock")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        sessions = load_session_registry(path)
        current = sessions.get(session_id, {})
        sessions[session_id] = {**current, **dict(values)}
        _atomic_json(path, {"schemaVersion": 1, "sessions": sessions})
