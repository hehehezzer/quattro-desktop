"""Read-only desktop integration status; absence never degrades Core."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from quattro.platform.processes import platform_name


def desktop_status(manifest_path: Path | None = None) -> dict[str, Any]:
    installed = bool(manifest_path and manifest_path.is_file())
    if platform_name() != "Linux":
        return {"supported": False, "installed": False, "status": "UNSUPPORTED", "checks": {}}
    if not installed:
        return {"supported": True, "installed": False, "status": "OPTIONAL_NOT_INSTALLED", "checks": {}}
    checks = {"hyprland": shutil.which("hyprctl") is not None, "quickshell": shutil.which("qs") is not None}
    return {
        "supported": True,
        "installed": True,
        "status": "HEALTHY" if all(checks.values()) else "INCOMPLETE",
        "checks": checks,
    }
