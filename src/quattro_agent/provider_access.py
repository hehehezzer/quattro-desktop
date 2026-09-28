"""Narrow provider credential resolution; never serialize or log secret values.

TypeSafe uses the existing user environment.d file as its single persistent
source. Native Codex/Pi authentication and gateway provider stores stay opaque.
No shell evaluation, global environment mutation, cache, or secret copies.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from collections.abc import Mapping

from .paths import xdg_config_home

_VARIABLE = "TYPESAFE_API_KEY"
_FILENAME = "60-quattro-typesafe.conf"
_MAX_BYTES = 16_384
_VALUE = re.compile(r"[A-Za-z0-9_.:/+\-=]{1,4096}\Z")


def _validated(value: str) -> str | None:
    return value if isinstance(value, str) and _VALUE.fullmatch(value) else None


def resolve_typesafe_credential(*, environment: Mapping[str, str] | None = None,
                                config_home: Path | None = None) -> str | None:
    """Explicit environment (including empty override), then private stored key.

    Unsafe/unreadable/malformed sources are unavailable, not exceptions carrying
    provider data. This intentionally supports only a literal environment.d
    assignment, optionally quoted, not shell or systemd variable expansion.
    On POSIX reject non-owner and group/other-accessible files. On Windows the
    user's existing directory ACL remains the access boundary.
    """
    environment = os.environ if environment is None else environment
    if _VARIABLE in environment:
        return _validated(environment[_VARIABLE])
    path = (config_home if config_home is not None else xdg_config_home()) / "environment.d" / _FILENAME
    descriptor = None
    try:
        # Reject symlinks, including the directory, before opening. O_NOFOLLOW
        # closes the final-component race on platforms that support it.
        if path.is_symlink() or path.parent.is_symlink():
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                             | getattr(os, "O_NONBLOCK", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_BYTES:
            return None
        if os.name == "posix" and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            return None
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return None
        values = []
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if name.strip() != _VARIABLE:
                continue
            if not separator:
                return None
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values.append(value)
        return _validated(values[0]) if len(values) == 1 else None
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def typesafe_credential_status() -> str:
    """Metadata only: no prefix, suffix, fingerprint, source contents or errors."""
    return "configured" if resolve_typesafe_credential() else "missing"
