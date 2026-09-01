"""Central platform capability declarations for process supervision."""
from __future__ import annotations

import sys


def platform_name() -> str:
    if sys.platform == "win32":
        return "Windows"
    if sys.platform.startswith("linux"):
        return "Linux"
    if sys.platform == "darwin":
        return "macOS"
    return sys.platform


def supports_strong_process_identity() -> bool:
    """Whether PID start-time and executable identity can be verified safely.

    Current mature supervision uses Linux procfs/process groups. Windows Core
    imports, persistence, routing, locking, and configuration are portable,
    while managed process recovery remains explicitly unverified.
    """
    return sys.platform.startswith("linux")
