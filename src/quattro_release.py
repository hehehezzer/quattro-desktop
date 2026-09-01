#!/usr/bin/env python3
"""Known-good deployment releases and bounded local rollback."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 2


class ReleaseError(RuntimeError):
    pass


def _sensitive_path_part(value: str) -> bool:
    """Reject credential stores, including common backups and suffix variants."""
    lowered = value.casefold()
    if lowered.startswith((".env", "auth.json", "credential", "secret", "token", "password")):
        return True
    if lowered.startswith(("id_rsa", "id_ecdsa", "id_ed25519", "id_dsa", "private_key")):
        return True
    return lowered in {".ssh", ".gnupg", "keyrings", "recovery-codes"}


def _safe_relative(value: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ReleaseError("release path must be relative and contained")
    if any(_sensitive_path_part(part) for part in path.parts):
        raise ReleaseError("release path references authentication material")
    return path


def _hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_file(root: pathlib.Path, relative: pathlib.PurePosixPath) -> pathlib.Path:
    """Resolve one source file without allowing it to escape its root."""
    try:
        candidate = (root / pathlib.Path(*relative.parts)).resolve(strict=True)
        candidate.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise ReleaseError(f"source release file is missing or escapes root: {relative}") from error
    if not candidate.is_file():
        raise ReleaseError(f"source release file is invalid: {relative}")
    return candidate


def _release_manifest(
    root: pathlib.Path,
    revision: str,
    rows: list[dict[str, Any]],
    absent_paths: Iterable[str],
) -> pathlib.Path:
    absent = sorted({_safe_relative(path).as_posix() for path in absent_paths})
    file_paths = {str(row["path"]) for row in rows}
    if file_paths.intersection(absent):
        raise ReleaseError("release inventory cannot contain both a file and an absent path")
    if not rows and not absent:
        raise ReleaseError("release must contain a desired path inventory")
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "revision": revision.lower(),
        "files": rows,
        "absentPaths": absent,
    }
    manifest_path = root / "release.json"
    fd, temporary_name = tempfile.mkstemp(prefix=".release.", dir=root)
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest_path


def _atomic_copy(source: pathlib.Path, target: pathlib.Path, mode: int) -> None:
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def create_release(
    release_root: pathlib.Path,
    revision: str,
    deployed_root: pathlib.Path,
    deployed_paths: Iterable[str],
    *,
    release_id: str | None = None,
) -> pathlib.Path:
    if not revision or any(character not in "0123456789abcdef" for character in revision.lower()):
        raise ReleaseError("revision must be hexadecimal")
    directory_name = revision.lower() if release_id is None else str(release_id)
    if not re.fullmatch(r"[0-9a-f]+(?:-[0-9a-f]+)*", directory_name):
        raise ReleaseError("release id must be hexadecimal components")
    root = (release_root / directory_name).resolve(strict=False)
    try:
        root.relative_to(release_root.resolve(strict=False))
    except ValueError as error:
        raise ReleaseError("release id escapes the release root") from error
    payload = root / "payload"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    payload.mkdir(mode=0o700)
    rows: list[dict[str, Any]] = []
    absent: list[str] = []
    for raw in sorted(set(deployed_paths)):
        relative = _safe_relative(raw)
        raw_source = deployed_root / pathlib.Path(*relative.parts)
        if not raw_source.exists() and not raw_source.is_symlink():
            absent.append(relative.as_posix())
            continue
        if raw_source.is_symlink():
            raise ReleaseError(f"deployed release file must not be a symlink: {relative}")
        source = raw_source.resolve(strict=True)
        try:
            source.relative_to(deployed_root.resolve())
        except ValueError as error:
            raise ReleaseError("deployed source escapes root") from error
        if not source.is_file():
            raise ReleaseError(f"deployed release file is invalid: {relative}")
        mode = source.stat().st_mode & 0o777
        target = payload / pathlib.Path(*relative.parts)
        _atomic_copy(source, target, mode)
        rows.append({"path": relative.as_posix(), "sha256": _hash(target), "mode": mode})
    if not rows and not absent:
        raise ReleaseError("release must contain a desired path inventory")
    return _release_manifest(root, revision, rows, absent)


def create_source_release(
    release_root: pathlib.Path,
    revision: str,
    source_root: pathlib.Path,
    mappings: Mapping[str, object] | Iterable[Mapping[str, object]],
    *,
    release_id: str | None = None,
    absent_paths: Iterable[str] = (),
) -> pathlib.Path:
    """Materialize a validated source tree as a restorable release payload.

    Mapping values are source/deployed pairs or mappings with ``source`` and
    ``deployed`` keys.  ``absent_paths`` is the explicit desired-state
    inventory for files retired by the source release.
    """
    if not revision or any(character not in "0123456789abcdef" for character in revision.lower()):
        raise ReleaseError("revision must be hexadecimal")
    source = source_root.resolve(strict=True)
    if not source.is_dir():
        raise ReleaseError("source release root must be a directory")
    if isinstance(mappings, Mapping):
        mapping_rows = [(str(name), value) for name, value in mappings.items()]
    else:
        mapping_rows = []
        for value in mappings:
            if not isinstance(value, Mapping) or not isinstance(value.get("name"), str):
                raise ReleaseError("each source release mapping must have a logical name")
            mapping_rows.append((str(value["name"]), value))

    directory_name = revision.lower() if release_id is None else str(release_id)
    if not re.fullmatch(r"[0-9a-f]+(?:-[0-9a-f]+)*", directory_name):
        raise ReleaseError("release id must be hexadecimal components")
    root = (release_root / directory_name).resolve(strict=False)
    try:
        root.relative_to(release_root.resolve(strict=False))
    except ValueError as error:
        raise ReleaseError("release id escapes the release root") from error
    payload = root / "payload"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    payload.mkdir(mode=0o700)
    rows: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for name, value in sorted(mapping_rows, key=lambda row: row[0]):
        if isinstance(value, Mapping):
            source_value = value.get("source")
            deployed_value = value.get("deployed")
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)) and len(value) == 2:
            source_value, deployed_value = value
        else:
            raise ReleaseError(f"mapping {name!r} must contain source and deployed paths")
        source_relative = _safe_relative(str(source_value))
        deployed_relative = _safe_relative(str(deployed_value))
        deployed_path = deployed_relative.as_posix()
        if deployed_path in seen_targets:
            raise ReleaseError(f"source release target paths must be unique: {deployed_path}")
        seen_targets.add(deployed_path)
        source_file = _source_file(source, source_relative)
        target = payload / pathlib.Path(*deployed_relative.parts)
        _atomic_copy(source_file, target, source_file.stat().st_mode & 0o777)
        rows.append({
            "path": deployed_path,
            "sha256": _hash(target),
            "mode": source_file.stat().st_mode & 0o777,
        })
    return _release_manifest(root, revision, rows, absent_paths)


def load_release(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"cannot load release: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseError("release manifest schema is invalid")
    if value.get("schemaVersion") == 1 and set(value) == {"schemaVersion", "revision", "files"}:
        value = {**value, "schemaVersion": 2, "absentPaths": []}
    if set(value) != {"schemaVersion", "revision", "files", "absentPaths"}:
        raise ReleaseError("release manifest schema is invalid")
    if value["schemaVersion"] != SCHEMA_VERSION or not isinstance(value["files"], list):
        raise ReleaseError("release manifest version or files are invalid")
    if not isinstance(value["absentPaths"], list):
        raise ReleaseError("release absent-path inventory is invalid")
    absent_paths: set[str] = set()
    for path in value["absentPaths"]:
        normalized = _safe_relative(path).as_posix()
        if normalized in absent_paths:
            raise ReleaseError("release absent-path inventory contains duplicates")
        absent_paths.add(normalized)
    file_paths: set[str] = set()
    for row in value["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "mode"}:
            raise ReleaseError("release file record is invalid")
        normalized = _safe_relative(row["path"]).as_posix()
        if normalized in file_paths:
            raise ReleaseError("release file inventory contains duplicates")
        if normalized in absent_paths:
            raise ReleaseError("release inventory cannot contain both a file and an absent path")
        file_paths.add(normalized)
        if not isinstance(row["sha256"], str) or len(row["sha256"]) != 64:
            raise ReleaseError("release hash is invalid")
        if type(row["mode"]) is not int or not 0 <= row["mode"] <= 0o777:
            raise ReleaseError("release mode is invalid")
    return value


def restore_release(
    manifest_path: pathlib.Path,
    deployed_root: pathlib.Path,
    *,
    release_root: pathlib.Path | None = None,
    expected_revision: str | None = None,
) -> list[pathlib.Path]:
    if manifest_path.is_symlink():
        raise ReleaseError("release manifest must not be a symlink")
    manifest_path = manifest_path.resolve(strict=True)
    if release_root is not None:
        try:
            manifest_path.relative_to(release_root.resolve(strict=True))
        except ValueError as error:
            raise ReleaseError("release manifest escapes the release root") from error
    manifest = load_release(manifest_path)
    if expected_revision is not None and manifest["revision"] != expected_revision.lower():
        raise ReleaseError("release revision does not match the requested revision")
    payload = manifest_path.parent / "payload"
    deployed = deployed_root.resolve(strict=True)
    prepared: list[tuple[pathlib.Path, pathlib.Path, int]] = []
    for row in manifest["files"]:
        relative = _safe_relative(row["path"])
        raw_source = payload / pathlib.Path(*relative.parts)
        if raw_source.is_symlink():
            raise ReleaseError(f"release payload must not be a symlink: {relative}")
        source = raw_source.resolve(strict=True)
        try:
            source.relative_to(payload.resolve())
        except ValueError as error:
            raise ReleaseError("release payload escapes root") from error
        if not source.is_file() or source.is_symlink() or _hash(source) != row["sha256"]:
            raise ReleaseError(f"release payload failed validation: {relative}")
        target = deployed / pathlib.Path(*relative.parts)
        probe = target.parent
        while probe != deployed and not probe.exists():
            probe = probe.parent
        if probe.is_symlink():
            raise ReleaseError(f"release target ancestor is a symlink: {relative}")
        try:
            probe.resolve(strict=True).relative_to(deployed)
        except ValueError as error:
            raise ReleaseError(f"release target escapes root: {relative}") from error
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target.is_symlink():
            raise ReleaseError(f"release target must not be a symlink: {relative}")
        prepared.append((source, target, row["mode"]))
    absent_targets: list[pathlib.Path] = []
    for raw in manifest["absentPaths"]:
        relative = _safe_relative(raw)
        target = deployed / pathlib.Path(*relative.parts)
        try:
            target.parent.resolve(strict=False).relative_to(deployed)
        except ValueError as error:
            raise ReleaseError(f"absent release target escapes root: {relative}") from error
        if target.is_symlink():
            raise ReleaseError(f"absent release target must not be a symlink: {relative}")
        absent_targets.append(target)

    restored: list[pathlib.Path] = []
    with tempfile.TemporaryDirectory(prefix="quattro-rollback-") as temporary:
        backup = pathlib.Path(temporary)
        original: list[tuple[pathlib.Path, pathlib.Path | None, int | None]] = []
        for index, (_source, target, _mode) in enumerate(prepared):
            if target.is_file():
                saved = backup / str(index)
                shutil.copy2(target, saved)
                original.append((target, saved, target.stat().st_mode & 0o777))
            else:
                original.append((target, None, None))
        offset = len(original)
        for index, target in enumerate(absent_targets, start=offset):
            if target.is_file():
                saved = backup / str(index)
                shutil.copy2(target, saved)
                original.append((target, saved, target.stat().st_mode & 0o777))
            else:
                original.append((target, None, None))
        try:
            for source, target, mode in prepared:
                _atomic_copy(source, target, mode)
                restored.append(target)
            for target in absent_targets:
                target.unlink(missing_ok=True)
                restored.append(target)
        except BaseException:
            for target, saved, mode in reversed(original):
                if saved is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_copy(saved, target, int(mode))
            raise
    return restored
