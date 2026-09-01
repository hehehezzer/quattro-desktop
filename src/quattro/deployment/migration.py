"""Safe one-time migration from the legacy combined deployment manifest."""
from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from quattro.platform.locking import exclusive_lock
from quattro_deployment import load_manifest, validate_manifest, write_manifest_atomic
from quattro_release import partition_release


def _manifest_for_records(
    legacy: Mapping[str, Any], records: list[dict[str, Any]], *,
    rollback: Mapping[str, Any], absent_paths: list[str],
) -> dict[str, Any]:
    matched = sum(1 for record in records if record["matches"])
    candidate = {
        "schemaVersion": legacy["schemaVersion"],
        "generatedAt": legacy["generatedAt"],
        "gitRevision": legacy["gitRevision"],
        "files": records,
        "parity": {
            "allMatch": matched == len(records),
            "matched": matched,
            "mismatched": len(records) - matched,
            "total": len(records),
        },
        "rollback": dict(rollback),
        "absentPaths": sorted(absent_paths),
    }
    return validate_manifest(candidate)


def _looks_desktop(record: Mapping[str, Any], desktop_names: set[str]) -> bool:
    if record.get("name") in desktop_names:
        return True
    source = str(record.get("sourcePath", ""))
    deployed = str(record.get("deployedPath", ""))
    return source.startswith(("src/quickshell/", "src/hypr/", "src/systemd/", "src/app-theme/", "src/foot/")) or deployed.startswith((".config/quickshell/", ".config/hypr/", ".config/systemd/", ".local/share/quattro/wallpapers/"))


def _partition_rollback(
    legacy: Mapping[str, Any], records: list[dict[str, Any]], *, profile: str,
    release_root: Path | None, absent_paths: list[str],
) -> dict[str, Any]:
    rollback = legacy["rollback"]
    if not rollback["available"]:
        return dict(rollback)
    if release_root is None:
        raise ValueError("legacy rollback migration requires the release root")
    previous_manifest = rollback["previousManifest"]
    previous_revision = rollback["previousGitRevision"]
    if not isinstance(previous_manifest, str) or not isinstance(previous_revision, str):
        raise ValueError("legacy rollback metadata is incomplete")
    source_manifest = release_root / Path(*Path(previous_manifest).parts)
    prefix = "c0" if profile == "core" else "de"
    release_id = f"{prefix}-{previous_revision}-{uuid.uuid4().hex}"
    partitioned = partition_release(
        source_manifest,
        release_root,
        release_id=release_id,
        allowed_paths={str(record["deployedPath"]) for record in records} | set(absent_paths),
        profile=profile,
    )
    return {
        "available": True,
        "previousManifest": partitioned.relative_to(release_root.resolve(strict=False)).as_posix(),
        "previousGitRevision": previous_revision,
    }


def migrate_legacy_manifest(
    legacy_path: Path,
    core_path: Path,
    desktop_path: Path,
    *,
    core_names: set[str],
    desktop_names: set[str],
    release_root: Path | None = None,
) -> dict[str, Any]:
    """Partition, validate, archive, and retire one combined manifest atomically."""
    lock_path = legacy_path.parent / "migration.lock"
    with exclusive_lock(lock_path):
        if not legacy_path.is_file():
            return {"status": "not-needed", "core": core_path.is_file(), "desktop": desktop_path.is_file()}
        legacy = load_manifest(legacy_path)
        core_records: list[dict[str, Any]] = []
        desktop_records: list[dict[str, Any]] = []
        for record in legacy["files"]:
            copy = dict(record)
            if _looks_desktop(copy, desktop_names):
                desktop_records.append(copy)
            else:
                core_records.append(copy)
        core_absent: list[str] = []
        desktop_absent: list[str] = []
        for path in legacy.get("absentPaths", []):
            target = desktop_absent if _looks_desktop(
                {"name": "", "sourcePath": "", "deployedPath": path}, desktop_names,
            ) else core_absent
            target.append(str(path))
        if not core_records and not core_absent:
            raise ValueError("legacy deployment does not contain a Core inventory")

        desktop_present = bool(desktop_records or desktop_absent)

        core_rollback = _partition_rollback(
            legacy, core_records, profile="core", release_root=release_root,
            absent_paths=core_absent,
        )
        desktop_rollback = (
            _partition_rollback(
                legacy, desktop_records, profile="desktop", release_root=release_root,
                absent_paths=desktop_absent,
            ) if desktop_present else {"available": False, "previousManifest": None, "previousGitRevision": None}
        )
        write_manifest_atomic(
            core_path, _manifest_for_records(
                legacy, core_records, rollback=core_rollback, absent_paths=core_absent,
            ),
        )
        if desktop_present:
            write_manifest_atomic(
                desktop_path,
                _manifest_for_records(
                    legacy, desktop_records, rollback=desktop_rollback,
                    absent_paths=desktop_absent,
                ),
            )

        archive_dir = legacy_path.parent / "legacy"
        archive_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = archive_dir / f"combined-manifest-{timestamp}-{uuid.uuid4().hex[:8]}.json"
        os.replace(legacy_path, archive)
        return {
            "status": "migrated",
            "coreFiles": len(core_records),
            "desktopFiles": len(desktop_records),
            "archive": str(archive),
        }
