"""Pure session preference resolution for the next Jev launcher integration.

This module performs no I/O and does not activate Jev. Persist only its bounded
session record, never a previous turn's signals or ExecutionPlan.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .errors import ConfigError


@dataclass(frozen=True, slots=True)
class JevPreference:
    enabled: bool
    source: str

    def session_record(self) -> dict:
        return {"schemaVersion": 1, "enabled": self.enabled}


def restore_jev_preference(record: Mapping | None) -> bool | None:
    """Absent legacy metadata is distinct from an explicitly disabled session."""
    if record is None:
        return None
    if (not isinstance(record, Mapping) or set(record) != {"schemaVersion", "enabled"}
            or type(record["schemaVersion"]) is not int or record["schemaVersion"] != 1
            or type(record["enabled"]) is not bool):
        raise ConfigError("invalid session Jev preference")
    return record["enabled"]


def resolve_jev_preference(*, cli: bool | None = None, selection: bool | None = None,
                           resumed: bool | None = None,
                           global_default: bool | None = None) -> JevPreference:
    """CLI > explicit session selection > resumed session > global > enabled.

    The selector must leave selection=None when it was not shown; otherwise a
    resume could accidentally overwrite its persisted disabled preference.
    Values are strictly booleans, not truthy strings or integer config values.
    """
    candidates = (("cli", cli), ("selection", selection), ("resume", resumed),
                  ("global", global_default))
    for source, value in candidates:
        if value is not None and type(value) is not bool:
            raise ConfigError(f"invalid {source} Jev preference")
    for source, value in candidates:
        if value is not None:
            return JevPreference(value, source)
    return JevPreference(True, "default")
