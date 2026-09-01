"""A bounded local scheduler backed by transactional SQLite leases."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .store import SUPPORTED_AGENTS, TaskStore
from .errors import LeaseConflict
from .collaboration import canonical_project


def _slot_group(prefix: str, count: int) -> tuple[str, ...]:
    if count <= 0:
        raise ValueError(f"scheduler limit for {prefix} must be positive")
    return tuple(f"{prefix}:{index}" for index in range(count))


@dataclass(frozen=True, slots=True)
class SchedulerLimits:
    max_total: int = 5
    per_agent: dict[str, int] = field(default_factory=lambda: {"codex": 5, "pi": 5})
    per_account: int = 5
    max_delegated_workers: int = 3
    per_repository: int = 3
    lease_ttl_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (self.max_total <= 0 or self.per_account <= 0 or self.per_repository <= 0
                or self.max_delegated_workers <= 0 or self.lease_ttl_seconds <= 0):
            raise ValueError("scheduler limits and lease TTL must be positive")
        if set(self.per_agent) - SUPPORTED_AGENTS:
            raise ValueError("scheduler contains an unsupported agent")
        if any(value <= 0 for value in self.per_agent.values()):
            raise ValueError("per-agent scheduler limits must be positive")


@dataclass(frozen=True, slots=True)
class ScheduleLease:
    task_id: str
    run_id: str
    resources: tuple[str, ...]
    expires_at: str


class LocalScheduler:
    """Atomically acquires top-level global/account/repository capacity."""

    def __init__(self, store: TaskStore, limits: SchedulerLimits | None = None) -> None:
        self.store = store
        self.limits = limits or SchedulerLimits()

    @staticmethod
    def project_resource(project_path: str | os.PathLike[str]) -> str:
        identity = canonical_project(project_path)
        return f"repository:{identity.repository_id}"

    @staticmethod
    def session_resource(session_id: str) -> str:
        if not session_id or len(session_id) > 200 or "\x00" in session_id:
            raise ValueError("native session id is invalid")
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
        return f"codex-session-writer:{digest}"

    @staticmethod
    def logical_session_resource(quattro_session_id: str) -> str:
        if not quattro_session_id or len(quattro_session_id) > 200 or "\x00" in quattro_session_id:
            raise ValueError("logical session id is invalid")
        digest = hashlib.sha256(quattro_session_id.encode("utf-8")).hexdigest()[:32]
        return f"quattro-session-writer:{digest}"

    def try_acquire(
        self,
        *,
        task_id: str,
        run_id: str,
        agent: str,
        account_id: str | None,
        project_path: str | os.PathLike[str],
        delegated_worker: bool = False,
        subagent_worker: bool = False,
        native_session_ref: str | None = None,
        quattro_session_id: str | None = None,
    ) -> ScheduleLease:
        if agent not in SUPPORTED_AGENTS:
            raise ValueError(f"unsupported agent: {agent}")
        agent_limit = self.limits.per_agent.get(agent)
        if agent_limit is None:
            raise ValueError(f"no scheduler capacity configured for {agent}")
        project_key = self.project_resource(project_path)
        top_level = not delegated_worker and not subagent_worker
        groups = []
        if top_level:
            groups.extend([
                _slot_group("global", self.limits.max_total),
                _slot_group(f"agent:{agent}", agent_limit),
                _slot_group(project_key, self.limits.per_repository),
            ])
            if agent == "codex" and account_id:
                groups.append(_slot_group(f"account:{account_id}", self.limits.per_account))
        if delegated_worker:
            groups.append(_slot_group("delegated-worker", self.limits.max_delegated_workers))
        fixed = [f"subagent:{task_id}"] if subagent_worker and not delegated_worker else []
        if top_level and agent == "codex" and native_session_ref:
            fixed.append(self.session_resource(native_session_ref))
        if top_level and agent == "codex" and quattro_session_id:
            fixed.append(self.logical_session_resource(quattro_session_id))
        leases = self.store.acquire_lease_set(
            holder_task_id=task_id,
            holder_run_id=run_id,
            resource_groups=groups,
            fixed_resources=fixed,
            ttl_seconds=self.limits.lease_ttl_seconds,
            kind="scheduler",
        )
        return ScheduleLease(
            task_id=task_id,
            run_id=run_id,
            resources=tuple(item["resourceKey"] for item in leases),
            expires_at=leases[0]["expiresAt"],
        )

    def heartbeat(self, lease: ScheduleLease) -> int:
        return self.store.renew_holder_leases(
            lease.task_id,
            lease.run_id,
            ttl_seconds=self.limits.lease_ttl_seconds,
        )

    def release(self, lease: ScheduleLease) -> int:
        return self.store.release_holder_leases(lease.task_id, lease.run_id)
