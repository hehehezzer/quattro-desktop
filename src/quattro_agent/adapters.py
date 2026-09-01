"""Normalized runtime adapters for the only supported agents: Codex and Pi."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from .policy import ApprovalMode, NetworkAccess, PolicyProfile


class AgentMode(StrEnum):
    INTERACTIVE = "interactive"
    PROMPT = "prompt"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class AgentCapabilities:
    agent: str
    supports_resume: bool
    supports_native_approvals: bool
    supports_native_sandbox: bool
    requires_harness_containment: bool
    supported_network: frozenset[NetworkAccess]
    supported_tools: frozenset[str]


@dataclass(frozen=True, slots=True)
class RunSpec:
    task_id: str
    run_id: str
    project_path: Path
    mode: AgentMode
    policy: PolicyProfile
    account_id: str | None = None
    account_home: Path | None = None
    native_session_ref: str | None = None
    private_input: str | None = None
    delegated_worker: bool = False
    model_override: str | None = None

    def __post_init__(self) -> None:
        if not self.project_path.is_absolute():
            raise ValueError("project_path must be absolute")
        if self.private_input is not None and len(self.private_input.encode("utf-8")) > 1_048_576:
            raise ValueError("private agent input exceeds 1 MiB")
        if self.model_override is not None and (not self.model_override or len(self.model_override) > 200 or "\x00" in self.model_override):
            raise ValueError("model override is invalid")


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    agent: str
    argv: tuple[str, ...]
    cwd: Path
    stdin_text: str | None
    environment_overrides: Mapping[str, str]

    def display_dict(self) -> dict[str, object]:
        """Return only execution metadata; never input text or environment values."""
        return {
            "agent": self.agent,
            "cwd": str(self.cwd),
            "executable": self.argv[0],
            "argumentCount": len(self.argv),
            "hasPrivateInput": self.stdin_text is not None,
            "overrideCount": len(self.environment_overrides),
        }


@dataclass(frozen=True, slots=True)
class RunOutcome:
    state: str
    exit_code: int | None
    error_code: str | None = None


class AgentAdapter(ABC):
    name: str

    @property
    @abstractmethod
    def capabilities(self) -> AgentCapabilities: ...

    @abstractmethod
    def build_launch(self, binary: str, spec: RunSpec) -> LaunchPlan: ...

    def normalize_exit(self, exit_code: int) -> RunOutcome:
        return RunOutcome(
            state="succeeded" if exit_code == 0 else "failed",
            exit_code=exit_code,
            error_code=None if exit_code == 0 else "agent_exit_nonzero",
        )

    def assert_policy_supported(self, spec: RunSpec) -> None:
        """Fail closed when a requested guarantee cannot be translated."""
        capabilities = self.capabilities
        if spec.policy.network not in capabilities.supported_network:
            raise ValueError(
                f"{self.name} cannot enforce {spec.policy.network.name.lower()} network access"
            )
        unsupported = spec.policy.allowed_tools - capabilities.supported_tools
        if unsupported:
            raise ValueError(
                f"{self.name} cannot enforce requested tool capabilities: {', '.join(sorted(unsupported))}"
            )
        if spec.policy.max_commands != 1:
            raise ValueError(
                f"{self.name} can enforce only one harness-managed agent command per run"
            )
        if not spec.policy.can_read(spec.project_path):
            raise ValueError("task project is outside the policy readable roots")
        if spec.policy.writable_roots and not spec.policy.can_write(spec.project_path):
            raise ValueError("writable task project is outside the policy writable roots")


def _codex_permission_args(policy: PolicyProfile) -> tuple[str, ...]:
    if policy.approval_mode is ApprovalMode.FULL_ACCESS:
        if not policy.explicit_full_access:
            raise ValueError("Codex full access must be explicit in the task policy")
        return ("--dangerously-bypass-approvals-and-sandbox",)
    if policy.approval_mode is ApprovalMode.REVIEW_IMPORTANT:
        return ("--approve-for-me",)
    sandbox = "workspace-write" if policy.writable_roots else "read-only"
    return ("-a", "on-request", "-s", sandbox)


class CodexAdapter(AgentAdapter):
    name = "codex"

    @property
    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent=self.name,
            supports_resume=True,
            supports_native_approvals=True,
            supports_native_sandbox=True,
            requires_harness_containment=False,
            supported_network=frozenset({NetworkAccess.NONE, NetworkAccess.FULL}),
            supported_tools=frozenset(),
        )

    def build_launch(self, binary: str, spec: RunSpec) -> LaunchPlan:
        self.assert_policy_supported(spec)
        if spec.account_home is None:
            raise ValueError("Codex requires an explicit account home")
        permissions = _codex_permission_args(spec.policy)
        network_args = (
            ("-c", "sandbox_workspace_write.network_access=true")
            if spec.policy.network is NetworkAccess.FULL
            and spec.policy.approval_mode is not ApprovalMode.FULL_ACCESS
            else ()
        )
        model_args = ("-m", spec.model_override) if spec.model_override else ()
        if spec.mode is AgentMode.RESUME:
            # A resume preserves the model recorded by the native Codex session.
            resume_target = (spec.native_session_ref,) if spec.native_session_ref else ("--all",)
            argv = (binary, *network_args, *permissions, "resume", *resume_target, "-C", str(spec.project_path))
            stdin = None
        elif spec.mode is AgentMode.PROMPT:
            argv = (
                binary, *network_args, *permissions, *model_args, "exec", "-C", str(spec.project_path),
                "--skip-git-repo-check", "-",
            )
            stdin = (spec.private_input or "") + "\n"
        else:
            argv = (binary, *network_args, *permissions, *model_args, "-C", str(spec.project_path))
            stdin = None
            if spec.private_input:
                argv = (*argv, spec.private_input)
        return LaunchPlan(
            agent=self.name,
            argv=argv,
            cwd=spec.project_path,
            stdin_text=stdin,
            environment_overrides={"CODEX_HOME": str(spec.account_home)},
        )


class PiAdapter(AgentAdapter):
    name = "pi"

    @property
    def capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            agent=self.name,
            supports_resume=True,
            supports_native_approvals=False,
            supports_native_sandbox=False,
            requires_harness_containment=True,
            supported_network=frozenset({NetworkAccess.NONE}),
            supported_tools=frozenset(),
        )

    def build_launch(self, binary: str, spec: RunSpec) -> LaunchPlan:
        self.assert_policy_supported(spec)
        worker_args = (
            (
                "--provider", "omniroute", "--model", "auto", "--mode", "json",
                "--no-session", "--no-context-files", "--no-skills",
                "--no-prompt-templates",
            )
            if spec.delegated_worker else ()
        )
        if spec.delegated_worker:
            tool_args = (
                "--no-extensions", "--tools", "read,grep,find,ls", "--approve",
            )
        elif spec.policy.explicit_full_access:
            tool_args = ("--no-extensions", "--tools", "read,bash,edit,write")
        else:
            tool_args = ("--no-extensions", "--no-tools")
        if spec.mode is AgentMode.RESUME:
            argv = (binary, *worker_args, *tool_args, "-r")
        elif spec.mode is AgentMode.PROMPT:
            argv = (binary, *worker_args, *tool_args, "-p", "--", spec.private_input or "")
        else:
            argv = (binary, *worker_args, *tool_args)
            if spec.private_input:
                argv = (*argv, "--", spec.private_input)
        return LaunchPlan(
            agent=self.name,
            argv=argv,
            cwd=spec.project_path,
            stdin_text=None,
            environment_overrides={},
        )


def adapter_for(agent: str) -> AgentAdapter:
    if agent == "codex":
        return CodexAdapter()
    if agent == "pi":
        return PiAdapter()
    raise ValueError(f"unsupported agent: {agent}")
