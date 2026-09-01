"""Centralized cross-platform primitives used by Quattro Core."""

from .directories import config_home, data_home, state_home, runtime_home
from .executables import find_executable
from .locking import exclusive_lock
from .processes import platform_name, supports_strong_process_identity

__all__ = [
    "config_home", "data_home", "state_home", "runtime_home",
    "find_executable", "exclusive_lock", "platform_name",
    "supports_strong_process_identity",
]
