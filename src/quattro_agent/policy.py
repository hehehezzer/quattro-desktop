"""Task-scoped capability profiles with enforceable child non-escalation."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Iterable

from .errors import PolicyEscalationError


class NetworkAccess(IntEnum):
    NONE = 0
    LOOPBACK = 1
    FULL = 2


class MemoryAccess(IntEnum):
    NONE = 0
    READ = 1
    WRITE = 2


class ApprovalMode(StrEnum):
    ALWAYS_ASK = "always_ask"
    ASK_BEFORE_WRITES = "ask_before_writes"
    REVIEW_IMPORTANT = "review_important_actions"
    FULL_ACCESS = "full_access"


_APPROVAL_AUTHORITY = {
    ApprovalMode.ALWAYS_ASK: 0,
    ApprovalMode.ASK_BEFORE_WRITES: 1,
    ApprovalMode.REVIEW_IMPORTANT: 2,
    ApprovalMode.FULL_ACCESS: 3,
}


def _normal_path(value: str | os.PathLike[str]) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _within(path: str, roots: tuple[str, ...]) -> bool:
    candidate = Path(path)
    for root in roots:
        try:
            candidate.relative_to(Path(root))
            return True
        except ValueError:
            continue
    return False


@dataclass(frozen=True, slots=True)
class PolicyProfile:
    """A complete authority envelope for one task or child task."""

    name: str
    readable_roots: tuple[str, ...] = ()
    writable_roots: tuple[str, ...] = ()
    network: NetworkAccess = NetworkAccess.NONE
    allowed_tools: frozenset[str] = frozenset()
    approval_mode: ApprovalMode = ApprovalMode.ALWAYS_ASK
    max_seconds: int = 900
    max_commands: int = 100
    memory_access: MemoryAccess = MemoryAccess.NONE
    external_effects: frozenset[str] = frozenset()
    explicit_full_access: bool = False

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 80:
            raise ValueError("policy name must contain 1-80 characters")
        if self.max_seconds <= 0 or self.max_seconds > 86_400:
            raise ValueError("max_seconds must be between 1 and 86400")
        if self.max_commands <= 0 or self.max_commands > 100_000:
            raise ValueError("max_commands must be between 1 and 100000")
        readable = tuple(sorted({_normal_path(path) for path in self.readable_roots}))
        writable = tuple(sorted({_normal_path(path) for path in self.writable_roots}))
        object.__setattr__(self, "readable_roots", readable)
        object.__setattr__(self, "writable_roots", writable)
        for root in writable:
            if not _within(root, readable):
                raise ValueError(f"writable root is not readable: {root}")
        if self.approval_mode is ApprovalMode.FULL_ACCESS and not self.explicit_full_access:
            raise ValueError("full-access approval mode requires explicit_full_access")
        if self.explicit_full_access and self.approval_mode is not ApprovalMode.FULL_ACCESS:
            raise ValueError("explicit_full_access requires full-access approval mode")

    def assert_child(self, child: "PolicyProfile") -> None:
        """Reject any child policy that expands the parent's authority."""
        errors: list[str] = []
        for root in child.readable_roots:
            if not _within(root, self.readable_roots):
                errors.append(f"read root {root}")
        for root in child.writable_roots:
            if not _within(root, self.writable_roots):
                errors.append(f"write root {root}")
        if child.network > self.network:
            errors.append("network access")
        if not child.allowed_tools.issubset(self.allowed_tools):
            errors.append("tool allowlist")
        if _APPROVAL_AUTHORITY[child.approval_mode] > _APPROVAL_AUTHORITY[self.approval_mode]:
            errors.append("approval authority")
        if child.max_seconds > self.max_seconds:
            errors.append("time budget")
        if child.max_commands > self.max_commands:
            errors.append("command budget")
        if child.memory_access > self.memory_access:
            errors.append("memory access")
        if not child.external_effects.issubset(self.external_effects):
            errors.append("external effects")
        if child.explicit_full_access and not self.explicit_full_access:
            errors.append("full access")
        if errors:
            raise PolicyEscalationError(
                f"child policy {child.name!r} escalates: {', '.join(errors)}"
            )

    def child(self, *, name: str, **changes: Any) -> "PolicyProfile":
        child = replace(self, name=name, **changes)
        self.assert_child(child)
        return child

    def can_read(self, path: str | os.PathLike[str]) -> bool:
        return _within(_normal_path(path), self.readable_roots)

    def can_write(self, path: str | os.PathLike[str]) -> bool:
        return _within(_normal_path(path), self.writable_roots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "readableRoots": list(self.readable_roots),
            "writableRoots": list(self.writable_roots),
            "network": self.network.name.lower(),
            "allowedTools": sorted(self.allowed_tools),
            "approvalMode": self.approval_mode.value,
            "maxSeconds": self.max_seconds,
            "maxCommands": self.max_commands,
            "memoryAccess": self.memory_access.name.lower(),
            "externalEffects": sorted(self.external_effects),
            "explicitFullAccess": self.explicit_full_access,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PolicyProfile":
        return cls(
            name=str(value["name"]),
            readable_roots=tuple(value.get("readableRoots", ())),
            writable_roots=tuple(value.get("writableRoots", ())),
            network=NetworkAccess[str(value.get("network", "none")).upper()],
            allowed_tools=frozenset(value.get("allowedTools", ())),
            approval_mode=ApprovalMode(value.get("approvalMode", ApprovalMode.ALWAYS_ASK.value)),
            max_seconds=int(value.get("maxSeconds", 900)),
            max_commands=int(value.get("maxCommands", 100)),
            memory_access=MemoryAccess[str(value.get("memoryAccess", "none")).upper()],
            external_effects=frozenset(value.get("externalEffects", ())),
            explicit_full_access=value.get("explicitFullAccess") is True,
        )


def _roots(values: Iterable[str | os.PathLike[str]]) -> tuple[str, ...]:
    return tuple(_normal_path(value) for value in values)


def policy_profile(
    name: str,
    *,
    project_root: str | os.PathLike[str],
    memory_roots: Iterable[str | os.PathLike[str]] = (),
    desktop_roots: Iterable[str | os.PathLike[str]] = (),
) -> PolicyProfile:
    """Build one of the supported default profiles for concrete roots."""
    project = _normal_path(project_root)
    memory = _roots(memory_roots)
    desktop = _roots(desktop_roots)
    # Agent-internal tool and shell-command allowlists are not enforceable by
    # the current Codex/Pi CLIs. Supported profiles therefore request no such
    # guarantee. ``max_commands`` counts the one harness-managed agent process,
    # not opaque commands the model may execute inside that process.
    common_read_tools: frozenset[str] = frozenset()
    # Codex sandbox modes constrain writes, not arbitrary host reads. Declare
    # the effective readable surface rather than promising an unenforceable
    # per-root read sandbox. Sensitive account material remains protected by
    # separate sanitized homes and explicit no-secret data paths.
    effective_reads = (str(Path("/").resolve()),)

    if name == "audit-read-only":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            allowed_tools=common_read_tools,
            approval_mode=ApprovalMode.ALWAYS_ASK,
            memory_access=MemoryAccess.READ if memory else MemoryAccess.NONE,
            max_seconds=1_800,
            max_commands=1,
        )
    if name == "review-untrusted":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            writable_roots=(project,),
            allowed_tools=common_read_tools,
            approval_mode=ApprovalMode.ASK_BEFORE_WRITES,
            memory_access=MemoryAccess.READ if memory else MemoryAccess.NONE,
            max_seconds=1_800,
            max_commands=1,
        )
    if name == "workspace-write":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            writable_roots=(project, *memory),
            network=NetworkAccess.FULL,
            allowed_tools=common_read_tools,
            approval_mode=ApprovalMode.ASK_BEFORE_WRITES,
            memory_access=MemoryAccess.WRITE if memory else MemoryAccess.NONE,
            max_seconds=3_600,
            max_commands=1,
        )
    if name == "desktop-config-write":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            writable_roots=(project, *desktop),
            network=NetworkAccess.LOOPBACK,
            allowed_tools=common_read_tools,
            approval_mode=ApprovalMode.ASK_BEFORE_WRITES,
            memory_access=MemoryAccess.READ if memory else MemoryAccess.NONE,
            max_seconds=3_600,
            max_commands=1,
        )
    if name == "network-restricted":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            writable_roots=(project,),
            network=NetworkAccess.LOOPBACK,
            allowed_tools=common_read_tools,
            approval_mode=ApprovalMode.ASK_BEFORE_WRITES,
            memory_access=MemoryAccess.READ if memory else MemoryAccess.NONE,
            max_seconds=3_600,
            max_commands=1,
        )
    if name == "publication-capable":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            writable_roots=(project,),
            network=NetworkAccess.FULL,
            allowed_tools=common_read_tools,
            approval_mode=ApprovalMode.ASK_BEFORE_WRITES,
            memory_access=MemoryAccess.READ if memory else MemoryAccess.NONE,
            external_effects=frozenset({"github.comment", "github.review"}),
            max_seconds=3_600,
            max_commands=1,
        )
    if name == "full-access-explicit":
        return PolicyProfile(
            name=name,
            readable_roots=effective_reads,
            writable_roots=(project, *desktop, *memory),
            network=NetworkAccess.FULL,
            allowed_tools=frozenset(),
            approval_mode=ApprovalMode.FULL_ACCESS,
            memory_access=MemoryAccess.WRITE if memory else MemoryAccess.NONE,
            external_effects=frozenset({"github.comment", "github.review"}),
            explicit_full_access=True,
            max_seconds=7_200,
            max_commands=1,
        )
    raise ValueError(f"unknown policy profile: {name}")
