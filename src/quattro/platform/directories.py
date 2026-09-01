"""Platform-aware user directories with explicit environment overrides."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _expanded(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve(strict=False)


def _environment_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return _expanded(value) if value and value.strip() else fallback.resolve(strict=False)


def config_home() -> Path:
    if sys.platform == "win32":
        return _environment_path("APPDATA", Path.home() / "AppData" / "Roaming")
    return _environment_path("XDG_CONFIG_HOME", Path.home() / ".config")


def data_home() -> Path:
    if sys.platform == "win32":
        return _environment_path("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    return _environment_path("XDG_DATA_HOME", Path.home() / ".local" / "share")


def state_home() -> Path:
    if sys.platform == "win32":
        return data_home()
    return _environment_path("XDG_STATE_HOME", Path.home() / ".local" / "state")


def runtime_home() -> Path:
    if sys.platform == "win32":
        return _environment_path("TEMP", data_home() / "Temp")
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value and value.strip():
        return _expanded(value)
    return _environment_path("TMPDIR", Path("/tmp")) / f"quattro-{getattr(os, 'getuid', lambda: 0)()}"
