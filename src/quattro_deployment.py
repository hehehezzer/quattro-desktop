#!/usr/bin/env python3
"""Build and validate credential-safe Quattro deployment manifests.

The manifest records provenance and source/deployed file parity without
serializing file contents, configuration values, credentials, or process
environments.  Callers provide logical file mappings relative to explicit
source and deployed roots.
"""

from __future__ import annotations

from quattro.platform.filesystem import fsync_directory

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 1
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
SENSITIVE_PATH_PARTS = {
    ".env",
    "auth.json",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "private_key",
    "recovery-codes",
    "secrets",
    "secrets.json",
    "tokens",
}


def _sensitive_path_part(value: str) -> bool:
    lowered = value.casefold()
    if lowered.startswith((".env", "auth.json", "credential", "secret", "token", "password")):
        return True
    if lowered.startswith(("id_rsa", "id_ecdsa", "id_ed25519", "id_dsa", "private_key")):
        return True
    return lowered in {".ssh", ".gnupg", "keyrings", "recovery-codes"}


class DeploymentManifestError(ValueError):
    """Raised when deployment provenance is incomplete or unsafe."""


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Return the SHA-256 digest for one regular file."""

    candidate = pathlib.Path(path)
    if not candidate.is_file():
        raise DeploymentManifestError(f"Deployment file is missing or not regular: {candidate}")
    digest = hashlib.sha256()
    with candidate.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_git_revision(source_root: str | os.PathLike[str]) -> str:
    """Resolve a full Git revision without inheriting arbitrary Git options."""

    root = pathlib.Path(source_root).resolve()
    git = shutil.which("git")
    if not git:
        raise DeploymentManifestError("Git is unavailable; provide an explicit revision")
    try:
        result = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            env={"PATH": os.defpath, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DeploymentManifestError(f"Unable to resolve Git revision: {error}") from error
    revision = result.stdout.strip().lower()
    if result.returncode != 0 or not REVISION_PATTERN.fullmatch(revision):
        raise DeploymentManifestError("Source root does not have a valid Git HEAD")
    return revision


def _validated_revision(value: str, field: str) -> str:
    revision = value.strip().lower() if isinstance(value, str) else ""
    if not REVISION_PATTERN.fullmatch(revision):
        raise DeploymentManifestError(f"{field} must be a full hexadecimal Git revision")
    return revision


def _safe_relative_path(value: str | os.PathLike[str], field: str) -> pathlib.PurePosixPath:
    if not isinstance(value, (str, os.PathLike)):
        raise DeploymentManifestError(f"{field} must be a safe relative path")
    raw = str(value).replace("\\", "/")
    candidate = pathlib.PurePosixPath(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts:
        raise DeploymentManifestError(f"{field} must be a safe relative path")
    if any(_sensitive_path_part(part) for part in candidate.parts):
        raise DeploymentManifestError(f"{field} references authentication or secret material")
    return candidate


def _rooted_file(root: pathlib.Path, relative: pathlib.PurePosixPath, field: str) -> pathlib.Path:
    try:
        resolved = (root / pathlib.Path(*relative.parts)).resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise DeploymentManifestError(f"{field} is missing or escapes its deployment root") from error
    if not resolved.is_file():
        raise DeploymentManifestError(f"{field} is not a regular file")
    return resolved


def _mapping_rows(
    mappings: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> list[tuple[str, Any]]:
    if isinstance(mappings, Mapping):
        return [(str(name), value) for name, value in mappings.items()]
    rows: list[tuple[str, Any]] = []
    for value in mappings:
        if not isinstance(value, Mapping) or not isinstance(value.get("name"), str):
            raise DeploymentManifestError("Each deployment mapping must have a logical name")
        rows.append((value["name"], value))
    return rows


def _mapping_paths(name: str, value: Any) -> tuple[pathlib.PurePosixPath, pathlib.PurePosixPath]:
    if isinstance(value, Mapping):
        source_value = value.get("source")
        deployed_value = value.get("deployed")
    elif isinstance(value, str) or isinstance(value, os.PathLike):
        source_value = deployed_value = value
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)) and len(value) == 2:
        source_value, deployed_value = value
    else:
        raise DeploymentManifestError(
            f"Mapping {name!r} must be a path, source/deployed pair, or mapping"
        )
    return (
        _safe_relative_path(source_value, f"{name}.source"),
        _safe_relative_path(deployed_value, f"{name}.deployed"),
    )


def _timestamp(value: str | None) -> str:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not isinstance(value, str):
        raise DeploymentManifestError("generatedAt must be an ISO-8601 string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeploymentManifestError("generatedAt must be an ISO-8601 string") from error
    if parsed.tzinfo is None:
        raise DeploymentManifestError("generatedAt must include a timezone")
    return value


def _validated_timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise DeploymentManifestError("generatedAt must be an ISO-8601 string")
    return _timestamp(value)


def build_manifest(
    source_root: str | os.PathLike[str],
    deployed_root: str | os.PathLike[str],
    mappings: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    revision: str | None = None,
    rollback_manifest: str | None = None,
    rollback_revision: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic, content-free source/deployed parity manifest.

    ``mappings`` accepts logical-name keys whose values are either one shared
    relative path, a ``(source, deployed)`` pair, or a mapping with ``source``
    and ``deployed`` keys.  An iterable of mappings with ``name``, ``source``,
    and ``deployed`` keys is also accepted.
    """

    source = pathlib.Path(source_root).resolve(strict=True)
    deployed = pathlib.Path(deployed_root).resolve(strict=True)
    if not source.is_dir() or not deployed.is_dir():
        raise DeploymentManifestError("Source and deployed roots must be directories")
    resolved_revision = _validated_revision(
        revision if revision is not None else resolve_git_revision(source),
        "gitRevision",
    )

    records: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for logical_name, value in sorted(_mapping_rows(mappings), key=lambda row: row[0]):
        if not logical_name.strip() or logical_name in seen_names:
            raise DeploymentManifestError("Deployment file names must be unique and non-empty")
        if any(part in logical_name.lower() for part in ("credential", "password", "secret", "token")):
            raise DeploymentManifestError("Deployment file name appears sensitive")
        seen_names.add(logical_name)
        source_relative, deployed_relative = _mapping_paths(logical_name, value)
        source_file = _rooted_file(source, source_relative, f"{logical_name}.source")
        deployed_file = _rooted_file(deployed, deployed_relative, f"{logical_name}.deployed")
        source_hash = sha256_file(source_file)
        deployed_hash = sha256_file(deployed_file)
        records.append({
            "name": logical_name,
            "sourcePath": source_relative.as_posix(),
            "deployedPath": deployed_relative.as_posix(),
            "sourceSha256": source_hash,
            "deployedSha256": deployed_hash,
            "matches": source_hash == deployed_hash,
        })

    if not records:
        raise DeploymentManifestError("A deployment manifest must contain at least one file")

    if rollback_manifest is not None:
        previous_manifest = _safe_relative_path(rollback_manifest, "rollbackManifest").as_posix()
    else:
        previous_manifest = None
    previous_revision = (
        _validated_revision(rollback_revision, "rollbackRevision")
        if rollback_revision is not None else None
    )
    if (previous_manifest is None) != (previous_revision is None):
        raise DeploymentManifestError(
            "rollback_manifest and rollback_revision must be provided together"
        )

    matched = sum(1 for record in records if record["matches"])
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _timestamp(generated_at),
        "gitRevision": resolved_revision,
        "files": records,
        "parity": {
            "allMatch": matched == len(records),
            "matched": matched,
            "mismatched": len(records) - matched,
            "total": len(records),
        },
        "rollback": {
            "available": previous_manifest is not None,
            "previousManifest": previous_manifest,
            "previousGitRevision": previous_revision,
        },
    }
    return validate_manifest(manifest)


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a manifest and return it as a plain dictionary.

    Validation is intentionally strict so callers cannot add prompt text,
    configuration contents, environment snapshots, or credential fields to
    the deployment record.
    """

    if not isinstance(manifest, Mapping):
        raise DeploymentManifestError("Manifest must be a mapping")
    expected_top = {"schemaVersion", "generatedAt", "gitRevision", "files", "parity", "rollback"}
    if set(manifest) != expected_top:
        raise DeploymentManifestError("Manifest contains missing or unsupported fields")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise DeploymentManifestError("Unsupported deployment manifest schema")
    _validated_timestamp(manifest.get("generatedAt"))
    _validated_revision(manifest.get("gitRevision"), "gitRevision")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise DeploymentManifestError("Manifest files must be a non-empty list")
    expected_file = {
        "name", "sourcePath", "deployedPath", "sourceSha256", "deployedSha256", "matches"
    }
    names: set[str] = set()
    matches = 0
    for record in files:
        if not isinstance(record, Mapping) or set(record) != expected_file:
            raise DeploymentManifestError("Manifest file record is malformed")
        name = record.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise DeploymentManifestError("Manifest file names must be unique")
        if any(part in name.lower() for part in ("credential", "password", "secret", "token")):
            raise DeploymentManifestError("Manifest file name appears sensitive")
        names.add(name)
        _safe_relative_path(record.get("sourcePath"), f"{name}.sourcePath")
        _safe_relative_path(record.get("deployedPath"), f"{name}.deployedPath")
        source_hash = record.get("sourceSha256")
        deployed_hash = record.get("deployedSha256")
        if not isinstance(source_hash, str) or not HASH_PATTERN.fullmatch(source_hash):
            raise DeploymentManifestError("Invalid source SHA-256")
        if not isinstance(deployed_hash, str) or not HASH_PATTERN.fullmatch(deployed_hash):
            raise DeploymentManifestError("Invalid deployed SHA-256")
        if not isinstance(record.get("matches"), bool) or record["matches"] != (source_hash == deployed_hash):
            raise DeploymentManifestError("File parity flag does not match its hashes")
        matches += int(record["matches"])

    parity = manifest.get("parity")
    expected_parity = {"allMatch", "matched", "mismatched", "total"}
    if not isinstance(parity, Mapping) or set(parity) != expected_parity:
        raise DeploymentManifestError("Manifest parity summary is malformed")
    expected_summary = {
        "allMatch": matches == len(files),
        "matched": matches,
        "mismatched": len(files) - matches,
        "total": len(files),
    }
    if dict(parity) != expected_summary:
        raise DeploymentManifestError("Manifest parity summary is inconsistent")

    rollback = manifest.get("rollback")
    expected_rollback = {"available", "previousManifest", "previousGitRevision"}
    if not isinstance(rollback, Mapping) or set(rollback) != expected_rollback:
        raise DeploymentManifestError("Manifest rollback record is malformed")
    available = rollback.get("available")
    previous_manifest = rollback.get("previousManifest")
    previous_revision = rollback.get("previousGitRevision")
    if not isinstance(available, bool):
        raise DeploymentManifestError("Rollback availability must be Boolean")
    if available:
        _safe_relative_path(previous_manifest, "rollback.previousManifest")
        _validated_revision(previous_revision, "rollback.previousGitRevision")
    elif previous_manifest is not None or previous_revision is not None:
        raise DeploymentManifestError("Unavailable rollback must not contain references")

    return dict(manifest)


def write_manifest_atomic(
    path: str | os.PathLike[str], manifest: Mapping[str, Any], mode: int = 0o600,
) -> pathlib.Path:
    """Validate and atomically persist a private deployment manifest."""

    validated = validate_manifest(manifest)
    target = pathlib.Path(path)
    parent_existed = target.parent.exists()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent_existed:
        os.chmod(target.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = pathlib.Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        else:
            os.chmod(temporary, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(validated, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and validate one deployment manifest."""

    try:
        with pathlib.Path(path).open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentManifestError(f"Unable to load deployment manifest: {error}") from error
    return validate_manifest(value)


def verify_manifest_files(
    manifest: Mapping[str, Any],
    source_root: str | os.PathLike[str],
    deployed_root: str | os.PathLike[str],
) -> dict[str, Any]:
    """Recompute current source/deployed hashes and detect post-deploy drift."""
    validated = validate_manifest(manifest)
    source = pathlib.Path(source_root).resolve(strict=True)
    deployed = pathlib.Path(deployed_root).resolve(strict=True)
    drift: list[dict[str, Any]] = []
    for record in validated["files"]:
        source_relative = _safe_relative_path(record["sourcePath"], "sourcePath")
        deployed_relative = _safe_relative_path(record["deployedPath"], "deployedPath")
        try:
            source_file = _rooted_file(source, source_relative, "sourcePath")
            deployed_file = _rooted_file(deployed, deployed_relative, "deployedPath")
            source_hash = sha256_file(source_file)
            deployed_hash = sha256_file(deployed_file)
            matches_manifest = (
                source_hash == record["sourceSha256"]
                and deployed_hash == record["deployedSha256"]
            )
            matches_each_other = source_hash == deployed_hash
        except DeploymentManifestError:
            source_hash = deployed_hash = None
            matches_manifest = matches_each_other = False
        if not matches_manifest or not matches_each_other:
            drift.append({
                "name": record["name"],
                "sourceMatchesManifest": source_hash == record["sourceSha256"],
                "deployedMatchesManifest": deployed_hash == record["deployedSha256"],
                "sourceMatchesDeployed": matches_each_other,
            })
    return {
        "allMatch": not drift,
        "checked": len(validated["files"]),
        "driftCount": len(drift),
        "drift": drift,
    }


# Descriptive aliases for callers that prefer the full deployment terminology.
build_deployment_manifest = build_manifest
validate_deployment_manifest = validate_manifest
atomic_write_manifest = write_manifest_atomic
