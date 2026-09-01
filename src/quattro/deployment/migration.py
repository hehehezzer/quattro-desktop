"""Safe one-time migration from the legacy combined deployment manifest."""
from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

from quattro_deployment import load_manifest, validate_manifest, write_manifest_atomic


def _manifest_for_records(legacy: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
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
        "rollback": dict(legacy["rollback"]),
    }
    return validate_manifest(candidate)


def _looks_desktop(record: Mapping[str, Any], desktop_names: set[str]) -> bool:
    if record.get("name") in desktop_names:
        return True
    source = str(record.get("sourcePath", ""))
    deployed = str(record.get("deployedPath", ""))
    return source.startswith(("src/quickshell/", "src/hypr/", "src/systemd/", "src/app-theme/", "src/foot/")) or deployed.startswith((".config/quickshell/", ".config/hypr/", ".config/systemd/", ".local/share/quattro/wallpapers/"))


def migrate_legacy_manifest(
    legacy_path: Path,
    core_path: Path,
    desktop_path: Path,
    *,
    core_names: set[str],
    desktop_names: set[str],
) -> dict[str, Any]:
    """Partition, validate, archive, and retire one combined manifest.

    Runtime databases, account homes, configuration, and release snapshots are
    outside this operation.  The original manifest is archived only after all
    replacement manifests have been durably written.
    """
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
    if not core_records:
        raise ValueError("legacy deployment does not contain a Core inventory")

    if not core_path.is_file():
        write_manifest_atomic(core_path, _manifest_for_records(legacy, core_records))
    else:
        load_manifest(core_path)
    if desktop_records and not desktop_path.is_file():
        write_manifest_atomic(desktop_path, _manifest_for_records(legacy, desktop_records))
    elif desktop_path.is_file():
        load_manifest(desktop_path)

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
