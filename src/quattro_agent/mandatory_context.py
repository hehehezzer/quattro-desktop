"""Deterministic mandatory operational context and project-path preflight."""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Mapping


WORKSPACE_POLICY_ID = "workspace.default_project_root"
WORKSPACE_SOURCE = "configuration:workspace.projectRoot"
REPOSITORY_WORKFLOW_POLICY_ID = "repository.mutation.branch_pr"
QUATTRO_DESKTOP_CLEAN_POLICY_ID = "repository.quattro_desktop.clean_worktree"
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


class WorktreeClassification(StrEnum):
    """Safety classification for existing changes before a repository write."""

    CLEAN = "CLEAN"
    CURRENT_TASK = "CURRENT_TASK"
    RECOVERED_INTERRUPTED_WORK = "RECOVERED_INTERRUPTED_WORK"
    UNRELATED_USER_WORK = "UNRELATED_USER_WORK"
    UNKNOWN = "UNKNOWN"
    UNSAFE_GIT_STATE = "UNSAFE_GIT_STATE"


@dataclass(frozen=True, slots=True)
class WorktreeInspection:
    """A bounded, non-mutating Git preflight result.

    This deliberately records evidence rather than attempting a checkout, reset,
    clean, stash, or commit.  The execution agent receives the classification and
    applies the corresponding reversible recovery workflow.
    """

    classification: WorktreeClassification
    repository_root: str | None
    branch: str | None
    head: str | None
    changed_paths: tuple[str, ...] = ()
    hard_block_reason: str | None = None

    @property
    def is_dirty(self) -> bool:
        return bool(self.changed_paths)


def _git_output(directory: pathlib.Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_TERMINAL_PROMPT": "0"},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return str(getattr(result, "stdout", "")) if getattr(result, "returncode", 1) == 0 else None


def _scope_covers(path: str, scopes: tuple[str, ...]) -> bool:
    return any(scope == "**" or path == scope or path.startswith(scope.rstrip("/") + "/") for scope in scopes)


def inspect_worktree(
    directory: pathlib.Path,
    *,
    current_task_paths: tuple[str, ...] = (),
    recovered_interrupted_paths: tuple[str, ...] = (),
    unrelated_user_paths: tuple[str, ...] = (),
) -> WorktreeInspection | None:
    """Inspect a Git worktree without mutation and classify every dirty tree.

    Callers can supply file/scope provenance recorded for the active task or a
    stale Quattro session.  Lack of provenance intentionally becomes UNKNOWN,
    never permission to clean up somebody else's work.
    """
    root = _git_output(directory, "rev-parse", "--show-toplevel")
    if root is None:
        return None
    branch = _git_output(directory, "branch", "--show-current")
    head = _git_output(directory, "rev-parse", "HEAD")
    status = _git_output(directory, "status", "--porcelain=v1", "--untracked-files=all")
    if status is None:
        return WorktreeInspection(
            WorktreeClassification.UNSAFE_GIT_STATE, root.strip(), branch.strip() if branch else None,
            head.strip() if head else None, hard_block_reason="Git status could not be read safely",
        )
    changed = tuple(line[3:] for line in status.splitlines() if len(line) >= 4)
    unresolved = _git_output(directory, "diff", "--name-only", "--diff-filter=U")
    git_dir = _git_output(directory, "rev-parse", "--git-dir")
    dangerous_state = bool(unresolved and unresolved.strip())
    if git_dir:
        state_root = (directory / git_dir.strip()).resolve(strict=False)
        dangerous_state = dangerous_state or any(
            (state_root / marker).exists()
            for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply")
        )
    if dangerous_state:
        return WorktreeInspection(
            WorktreeClassification.UNSAFE_GIT_STATE, root.strip(), branch.strip() if branch else None,
            head.strip() if head else None, changed,
            "unresolved merge, rebase, cherry-pick, or conflict state",
        )
    if not changed:
        return WorktreeInspection(
            WorktreeClassification.CLEAN, root.strip(), branch.strip() if branch else None,
            head.strip() if head else None,
        )
    if recovered_interrupted_paths and all(_scope_covers(path, recovered_interrupted_paths) for path in changed):
        kind = WorktreeClassification.RECOVERED_INTERRUPTED_WORK
    elif current_task_paths and all(_scope_covers(path, current_task_paths) for path in changed):
        kind = WorktreeClassification.CURRENT_TASK
    elif unrelated_user_paths and all(_scope_covers(path, unrelated_user_paths) for path in changed):
        kind = WorktreeClassification.UNRELATED_USER_WORK
    else:
        kind = WorktreeClassification.UNKNOWN
    return WorktreeInspection(
        kind, root.strip(), branch.strip() if branch else None,
        head.strip() if head else None, changed,
    )


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
    delegated: bool = False, current_task_paths: tuple[str, ...] = (),
    recovered_interrupted_paths: tuple[str, ...] = (),
    unrelated_user_paths: tuple[str, ...] = (),
) -> MandatoryContext:
    """Build compact authority text outside the retrieval/reranking budget."""
    root = project_root_from_config(config)
    destination = destination_from_request(request, project_root=root, cwd=cwd) if request else None
    current_root = cwd.resolve(strict=False) if cwd is not None else None
    quattro_desktop = (
        str(current_root)
        if current_root is not None and current_root.name == "quattro-desktop"
        else "the Quattro Desktop repository"
    )
    inspection = (
        inspect_worktree(
            current_root,
            current_task_paths=current_task_paths,
            recovered_interrupted_paths=recovered_interrupted_paths,
            unrelated_user_paths=unrelated_user_paths,
        )
        if current_root is not None else None
    )
    lines = [
        "MANDATORY OPERATIONAL POLICY (trusted; not RAG):",
        f"[{WORKSPACE_POLICY_ID}] Default all repository clones, repository creation, and new "
        f"project creation to {root}. An explicit user-provided destination wins unless a "
        "higher-priority safety restriction prevents it.",
        "Before those operations, resolve and validate the destination; do not infer a "
        "destination from the current working directory.",
        f"[{REPOSITORY_WORKFLOW_POLICY_ID}] Repository mutation invariant: inspect the "
        "repository root, git status, current branch, remotes, and HEAD before the first "
        "file edit. Make changes only on a dedicated non-main branch; preserve unrelated "
        "work; validate and review the scoped diff; commit only intended files; push and "
        "verify the remote branch; then create a PR targeting main. Never push "
        "implementation commits directly to main. Merge only with explicit user "
        "authorization or when an established repository workflow explicitly permits "
        "autonomous merge after all required checks and reviews pass; never merge failing "
        "CI. An explicit user override for a specific task may replace this workflow. If "
        "no repository files change, no branch or PR is required.",
        f"[{QUATTRO_DESKTOP_CLEAN_POLICY_ID}] Before modifying {quattro_desktop}, inspect "
        "Git status, branch, HEAD, remotes, conflict state, and the diff. A dirty worktree "
        "is not automatically a blocker: classify every changed path as CURRENT_TASK, "
        "RECOVERED_INTERRUPTED_WORK, UNRELATED_USER_WORK, or UNKNOWN. For CURRENT_TASK "
        "and provenance-verified RECOVERED_INTERRUPTED_WORK, inspect, validate, repair if "
        "needed, stage only intended files on a non-main feature branch, commit, push, "
        "verify the remote, and verify the worktree is clean before continuing. A stale "
        "Quattro session is authorization to recover only its provenance-matched files. "
        "For UNRELATED_USER_WORK or UNKNOWN, never discard, reset, clean, force-push, or "
        "mix it into the task: record paths, original branch, and HEAD, then preserve it "
        "using an isolated clean worktree, a preservation branch, or a descriptive stash "
        "only when safe and reversible. Dirty main requires a feature branch or isolated "
        "worktree before a task commit. Unresolved merge/rebase/cherry-pick conflicts, "
        "corruption, secrets risk, or divergence requiring force push remain hard blocks.",
    ]
    if inspection is not None:
        if inspection.classification is WorktreeClassification.UNSAFE_GIT_STATE:
            lines.append(
                "Git preflight: UNSAFE_GIT_STATE; do not mutate until "
                f"resolved ({inspection.hard_block_reason})."
            )
        elif inspection.classification is WorktreeClassification.CLEAN:
            lines.append("Git preflight: CLEAN; normal branch workflow may continue.")
        else:
            lines.append(
                f"Git preflight: {inspection.classification.value}; changed paths: "
                f"{', '.join(inspection.changed_paths)}; original branch: "
                f"{inspection.branch or 'detached'}; original HEAD: {inspection.head or 'unknown'}."
            )
    if destination is not None:
        lines.append(
            f"Resolved task destination: {destination.destination} "
            f"(source: {destination.source})."
        )
    return MandatoryContext(
        text="\n".join(lines),
        loaded_sources=(WORKSPACE_SOURCE,),
        activated_policies=(
            WORKSPACE_POLICY_ID,
            REPOSITORY_WORKFLOW_POLICY_ID,
            QUATTRO_DESKTOP_CLEAN_POLICY_ID,
        ),
        destination=destination,
        propagated_to_subagent=delegated,
    )
