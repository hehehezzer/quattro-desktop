"""Deterministic mandatory operational context and project-path preflight."""

from __future__ import annotations

import os
import pathlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping


WORKSPACE_POLICY_ID = "workspace.default_project_root"
WORKSPACE_SOURCE = "configuration:workspace.projectRoot"
FAILURE_CLASSES = frozenset({
    "mandatory-context discovery failure",
    "RAG retrieval failure",
    "reranking/context-budget failure",
    "context propagation failure",
    "instruction-adherence failure",
    "path/config resolution failure",
    "tool/execution failure",
})

_PROJECT_OPERATION = re.compile(
    r"(?i)\b(git\s+clone|clone|create\s+(?:a\s+)?(?:new\s+)?(?:repository|repo|project)|"
    r"new\s+(?:repository|repo|project))\b"
)
_CLONE_TARGET = re.compile(r"(?i)\b(?:git\s+clone|clone)\s+([^\s,;]+)")
_EXPLICIT_DESTINATION = re.compile(
    r"(?i)\b(?:to|into|at|in)\s+((?:~|/|\.\.?/)[^\s,;]+)"
)


@dataclass(frozen=True, slots=True)
class ProjectDestination:
    operation: str
    destination: str
    source: str
    project_root: str
    explicit: bool
    repository_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MandatoryContext:
    text: str
    loaded_sources: tuple[str, ...]
    activated_policies: tuple[str, ...]
    destination: ProjectDestination | None = None
    propagated_to_subagent: bool = False

    def diagnostics(self) -> dict[str, Any]:
        return {
            "loadedSources": list(self.loaded_sources),
            "activatedPolicies": list(self.activated_policies),
            "destination": self.destination.to_dict() if self.destination else None,
            "propagatedToSubagent": self.propagated_to_subagent,
        }


def project_root_from_config(config: Mapping[str, Any]) -> pathlib.Path:
    workspace = config.get("workspace", {})
    if not isinstance(workspace, Mapping):
        raise ValueError("workspace configuration must be an object")
    value = workspace.get("projectRoot", "~/Projects")
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("workspace.projectRoot must be a non-empty safe path")
    expanded = pathlib.Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        raise ValueError("workspace.projectRoot must be an absolute or home-relative path")
    root = expanded.resolve(strict=False)
    return root


def _repository_name(value: str) -> str | None:
    candidate = value.rstrip("/").rsplit("/", 1)[-1]
    if ":" in candidate and not candidate.startswith(("/", "./", "../")):
        candidate = candidate.rsplit(":", 1)[-1]
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    if not candidate or candidate in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._-]+", candidate):
        return None
    return candidate


def resolve_project_destination(
    *,
    project_root: pathlib.Path,
    repository: str | None,
    explicit_destination: str | None = None,
    cwd: pathlib.Path | None = None,
    operation: str = "clone",
) -> ProjectDestination:
    """Resolve one clone/create destination with explicit user intent first."""
    root = project_root.expanduser().resolve(strict=False)
    name = _repository_name(repository or "")
    if explicit_destination:
        raw = pathlib.Path(os.path.expandvars(os.path.expanduser(explicit_destination)))
        base = (cwd or pathlib.Path.cwd()).resolve(strict=False)
        destination = (raw if raw.is_absolute() else base / raw).resolve(strict=False)
        source = "explicit user instruction"
        explicit = True
    else:
        if not name:
            raise ValueError("repository name is required when no explicit destination is provided")
        destination = (root / name).resolve(strict=False)
        source = "mandatory policy/config"
        explicit = False
    if not destination.is_absolute() or destination == pathlib.Path(destination.anchor):
        raise ValueError("resolved project destination is unsafe")
    return ProjectDestination(
        operation=operation,
        destination=str(destination),
        source=source,
        project_root=str(root),
        explicit=explicit,
        repository_name=name,
    )


def destination_from_request(
    request: str, *, project_root: pathlib.Path, cwd: pathlib.Path | None = None
) -> ProjectDestination | None:
    match = _PROJECT_OPERATION.search(request)
    if not match:
        return None
    operation = "clone" if "clone" in match.group(1).lower() else "create"
    clone = _CLONE_TARGET.search(request)
    repository = clone.group(1) if clone else None
    explicit = _EXPLICIT_DESTINATION.search(request)
    explicit_value = explicit.group(1).rstrip(".?!") if explicit else None
    if repository is None and explicit_value is None:
        return None
    return resolve_project_destination(
        project_root=project_root,
        repository=repository,
        explicit_destination=explicit_value,
        cwd=cwd,
        operation=operation,
    )


def build_mandatory_context(
    config: Mapping[str, Any], *, request: str = "", cwd: pathlib.Path | None = None,
    delegated: bool = False,
) -> MandatoryContext:
    """Build compact authority text outside the retrieval/reranking budget."""
    root = project_root_from_config(config)
    destination = destination_from_request(request, project_root=root, cwd=cwd) if request else None
    lines = [
        "MANDATORY OPERATIONAL POLICY (trusted; not RAG):",
        f"[{WORKSPACE_POLICY_ID}] Default all repository clones, repository creation, and new "
        f"project creation to {root}. An explicit user-provided destination wins unless a "
        "higher-priority safety restriction prevents it.",
        "Before those operations, resolve and validate the destination; do not infer a "
        "destination from the current working directory.",
    ]
    if destination is not None:
        lines.append(
            f"Resolved task destination: {destination.destination} "
            f"(source: {destination.source})."
        )
    return MandatoryContext(
        text="\n".join(lines),
        loaded_sources=(WORKSPACE_SOURCE,),
        activated_policies=(WORKSPACE_POLICY_ID,),
        destination=destination,
        propagated_to_subagent=delegated,
    )
