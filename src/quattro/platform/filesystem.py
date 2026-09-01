"""Portable filesystem durability helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def fsync_directory(path: Path) -> None:
    """Persist directory metadata where the platform exposes directory fds."""
    if sys.platform == "win32":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def apply_private_mode(path: Path, mode: int) -> None:
    """Apply POSIX privacy bits; ACL enforcement remains an installer concern on Windows."""
    if sys.platform != "win32":
        os.chmod(path, mode)
