"""PATH-first, bounded executable discovery for supported agent tools."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterable


def _is_executable(path: Path) -> bool:
    return path.is_file() and (sys.platform == "win32" or os.access(path, os.X_OK))


def find_executable(name: str, *, extra_paths: Iterable[Path] = ()) -> str | None:
    """Resolve an executable without assuming one Node version or home layout."""
    found = shutil.which(name)
    if found:
        return found

    suffixes = (".exe", ".cmd", ".bat", "") if sys.platform == "win32" else ("",)
    for directory in extra_paths:
        for suffix in suffixes:
            candidate = Path(directory) / f"{name}{suffix}"
            if _is_executable(candidate):
                return str(candidate)

    candidates: list[Path] = []
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates.extend(appdata / "npm" / f"{name}{suffix}" for suffix in (".cmd", ".exe"))
        candidates.append(local / "Programs" / name / f"{name}.exe")
    elif name in {"codex", "pi"}:
        nvm = Path(os.environ.get("NVM_DIR", Path.home() / ".nvm")) / "versions" / "node"
        if nvm.is_dir():
            candidates.extend(path / "bin" / name for path in sorted(nvm.iterdir(), reverse=True))

    return next((str(path) for path in candidates if _is_executable(path)), None)
