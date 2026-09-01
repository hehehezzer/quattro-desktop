"""Local cooperative session coordination for shared working trees.

The coordinator is deliberately small: one private JSON registry protected by
one advisory file lock. It supplies canonical repository identity, startup
reservations, write-scope claims, peer context, and conservative recovery.
Ordinary sessions never create a branch, checkout, or worktree; ``isolate=True``
is retained only for an explicit user-requested experiment.
"""

from __future__ import annotations

from quattro.platform.filesystem import fsync_directory

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

from .errors import LeaseConflict
from quattro.platform.locking import lock_file_descriptor


ACTIVE_SESSION_STATES = frozenset({"starting", "active", "validating", "integrating"})
TERMINAL_SESSION_STATES = frozenset({
    "completed", "completed_recoverable", "abandoned", "stale", "stale_recoverable",
})
_SESSION_ID = re.compile(r"^q-[0-9a-f]{12}$")
_BRANCH = re.compile(r"^quattro/[0-9a-f]{8}/task-[0-9a-f]{8}$")
_REPOSITORY_ID = re.compile(r"^[0-9a-f]{24}$")
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _git_environment() -> dict[str, str]:
    result = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "GIT_TERMINAL_PROMPT": "0",
    }
    for key in ("LANG", "LC_ALL", "LC_CTYPE"):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def _run_git(
    git: str,
    cwd: Path,
    *arguments: str,
    check: bool = True,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [
            git, "-C", str(cwd),
            "-c", "core.hooksPath=/dev/null",
            "-c", "commit.gpgSign=false",
            "-c", "merge.verifySignatures=false",
            *arguments,
        ],
        env=_git_environment(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        detail = " ".join(result.stderr.strip().split())[:500]
        raise RuntimeError(f"git {' '.join(arguments[:2])} failed: {detail or result.returncode}")
    return result


def _worktree_rows(git: str, cwd: Path) -> list[dict[str, str]]:
    output = _run_git(git, cwd, "worktree", "list", "--porcelain").stdout
    rows: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        rows.append(current)
    return rows


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    repository_id: str
    kind: str
    canonical_repository: Path
    requested_path: Path
    requested_worktree: Path
    common_git_dir: Path | None
    base_branch: str | None
    base_commit: str | None
    original_dirty: bool

    def projection(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("canonical_repository", "requested_path", "requested_worktree", "common_git_dir"):
            if value[key] is not None:
                value[key] = str(value[key])
        return value


def canonical_project(
    path: str | os.PathLike[str], *, git: str = "git"
) -> ProjectIdentity:
    """Resolve one identity for a Git repository and every linked worktree.

    Git identity is based on the resolved common Git directory (including its
    filesystem identity), never a caller's working-directory spelling.  A
    non-Git project uses the resolved existing directory and its inode.
    """
    requested = Path(path).expanduser().resolve(strict=True)
    if not requested.is_dir():
        raise ValueError(f"project is not a directory: {requested}")
    try:
        probe = _run_git(
            git, requested, "rev-parse", "--is-inside-work-tree", check=False,
        )
    except OSError:
        probe = None
    if probe is not None and probe.returncode == 0 and probe.stdout.strip() == "true":
        common_text = _run_git(
            git, requested, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ).stdout.strip()
        top_text = _run_git(
            git, requested, "rev-parse", "--path-format=absolute", "--show-toplevel"
        ).stdout.strip()
        common = Path(common_text).resolve(strict=True)
        worktree = Path(top_text).resolve(strict=True)
        rows = _worktree_rows(git, requested)
        main = worktree
        if rows and rows[0].get("worktree"):
            candidate = Path(rows[0]["worktree"]).resolve(strict=False)
            if candidate.is_dir():
                main = candidate.resolve(strict=True)
        branch_result = _run_git(
            git, main, "symbolic-ref", "--quiet", "--short", "HEAD", check=False,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
        if branch and branch.startswith("quattro/"):
            branch = None
        if branch is None:
            remote = _run_git(
                git, main, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD",
                check=False,
            )
            if remote.returncode == 0 and remote.stdout.strip().startswith("origin/"):
                branch = remote.stdout.strip().removeprefix("origin/")
        commit_result = _run_git(git, main, "rev-parse", "HEAD", check=False)
        commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
        dirty_result = _run_git(
            git, main, "status", "--porcelain=v1", "--untracked-files=normal", check=False,
        )
        metadata = common.stat()
        material = f"git\0{common}\0{metadata.st_dev}\0{metadata.st_ino}"
        identifier = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        return ProjectIdentity(
            repository_id=identifier,
            kind="git",
            canonical_repository=main,
            requested_path=requested,
            requested_worktree=worktree,
            common_git_dir=common,
            base_branch=branch,
            base_commit=commit,
            original_dirty=bool(dirty_result.stdout),
        )
    metadata = requested.stat()
    material = f"filesystem\0{requested}\0{metadata.st_dev}\0{metadata.st_ino}"
    identifier = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return ProjectIdentity(
        repository_id=identifier,
        kind="filesystem",
        canonical_repository=requested,
        requested_path=requested,
        requested_worktree=requested,
        common_git_dir=None,
        base_branch=None,
        base_commit=None,
        original_dirty=False,
    )


def _task_key(summary: str) -> str | None:
    compact = " ".join(summary.casefold().split())
    if not compact or compact in {"interactive", "codex interactive", "pi interactive"}:
        return None
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()[:24]


def _safe_scope(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 300 or "\x00" in value:
        raise ValueError("task scope is invalid")
    if value == "**":
        return value
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("task scope must be repository-relative")
    normalized = candidate.as_posix().strip("/")
    if not normalized or normalized == ".":
        raise ValueError("task scope is invalid")
    return normalized


def _scopes_overlap(left: str, right: str) -> bool:
    return "**" in {left, right} or left == right or left.startswith(right + "/") or right.startswith(left + "/")


class RepositoryCoordinator:
    """Private, race-safe registry for top-level Quattro sessions."""

    def __init__(
        self,
        state_root: Path,
        worktree_root: Path,
        *,
        global_limit: int = 5,
        per_repository_limit: int = 3,
        worktree_isolation: bool = False,
        git: str = "git",
        reservation_ttl_seconds: float = 30.0,
        integration_ttl_seconds: float = 300.0,
    ) -> None:
        if global_limit <= 0 or per_repository_limit <= 0:
            raise ValueError("session limits must be positive")
        if per_repository_limit > global_limit:
            raise ValueError("per-repository limit cannot exceed the global limit")
        self.root = state_root.expanduser().resolve(strict=False)
        self.worktree_root = worktree_root.expanduser().resolve(strict=False)
        if self.root == Path(self.root.anchor) or self.worktree_root == Path(self.worktree_root.anchor):
            raise ValueError("coordination roots must not be filesystem roots")
        self.global_limit = global_limit
        self.per_repository_limit = per_repository_limit
        self.worktree_isolation = worktree_isolation
        self.git = git
        self.reservation_ttl_seconds = reservation_ttl_seconds
        self.integration_ttl_seconds = integration_ttl_seconds
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            if not self.root.exists():
                raise
        try:
            self.worktree_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            if not self.worktree_root.exists():
                raise
        if self.root.is_symlink() or self.worktree_root.is_symlink():
            raise ValueError("coordination roots must not be symbolic links")
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        try:
            os.chmod(self.worktree_root, 0o700)
        except OSError:
            pass
        self.registry_path = self.root / "repository-coordination.json"
        self.lock_path = self.root / "repository-coordination.lock"

    @contextlib.contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.lock_path, flags, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            lock_file_descriptor(descriptor)
            state = self._read_state()
            self._reconcile_locked(state)
            yield state
            self._write_state(state)
        finally:
            os.close(descriptor)

    def _read_state(self) -> dict[str, Any]:
        if self.registry_path.is_symlink():
            raise RuntimeError("coordination registry must not be a symbolic link")
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = {"schemaVersion": 1, "sessions": {}, "integrationLeases": {}, "events": []}
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"coordination registry is unreadable: {error}") from error
        if not isinstance(value, dict) or value.get("schemaVersion") != 1:
            raise RuntimeError("coordination registry has an unsupported schema")
        for key, default in (
            ("sessions", {}), ("integrationLeases", {}), ("events", []),
        ):
            if not isinstance(value.get(key), type(default)):
                raise RuntimeError(f"coordination registry field is malformed: {key}")
        return value

    def _write_state(self, state: Mapping[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".repository-coordination.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.registry_path)
            fsync_directory(self.root)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    @staticmethod
    def _pid_matches(record: Mapping[str, Any]) -> bool:
        pid = record.get("pid")
        expected_ticks = record.get("processStartTicks")
        if not isinstance(pid, int) or pid <= 1 or not isinstance(expected_ticks, int):
            return False
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return False
        end = raw.rfind(")")
        if end < 0:
            return False
        fields = raw[end + 2:].split()
        return len(fields) > 19 and int(fields[19]) == expected_ticks

    def _worktree_state(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if record.get("kind") != "git":
            return {"dirty": False, "head": None, "ahead": 0, "changedFiles": []}
        path_value = record.get("worktreePath")
        base = record.get("baseCommit")
        if not isinstance(path_value, str) or not Path(path_value).is_dir():
            return {"dirty": False, "head": None, "ahead": 0, "changedFiles": []}
        path = Path(path_value)
        try:
            self._validate_git_record(record, path)
        except RuntimeError:
            # Stale coordination metadata must not make unrelated read-only UI
            # snapshots fail. Preserve the record and reconcile it as stale;
            # mutation paths still call _validate_git_record directly.
            return {"dirty": False, "head": None, "ahead": 0, "changedFiles": []}
        status = _run_git(
            self.git, path, "status", "--porcelain=v1", "--untracked-files=normal", check=False,
        )
        changed = [line[3:] for line in status.stdout.splitlines() if len(line) >= 4][:200]
        head_result = _run_git(self.git, path, "rev-parse", "HEAD", check=False)
        head = head_result.stdout.strip() if head_result.returncode == 0 else None
        ahead = 0
        if isinstance(base, str) and head:
            count = _run_git(self.git, path, "rev-list", "--count", f"{base}..{head}", check=False)
            if count.returncode == 0 and count.stdout.strip().isdigit():
                ahead = int(count.stdout.strip())
        return {"dirty": bool(status.stdout), "head": head, "ahead": ahead, "changedFiles": changed}

    def _validate_git_record(self, record: Mapping[str, Any], path: Path) -> None:
        repository_id = record.get("repositoryId")
        if not isinstance(repository_id, str) or not _REPOSITORY_ID.fullmatch(repository_id):
            raise RuntimeError("coordination repository identity is invalid")
        resolved = path.resolve(strict=True)
        if record.get("managedWorktree"):
            allowed = (self.worktree_root / repository_id).resolve(strict=False)
            try:
                resolved.relative_to(allowed)
            except ValueError as error:
                raise RuntimeError("managed worktree escaped its repository root") from error
            branch = record.get("branch")
            if not isinstance(branch, str) or not _BRANCH.fullmatch(branch):
                raise RuntimeError("managed branch metadata is invalid")
        identity = canonical_project(resolved, git=self.git)
        if identity.repository_id != repository_id:
            raise RuntimeError("worktree no longer belongs to its recorded repository")
        original = record.get("originalRepository")
        if not isinstance(original, str) or identity.canonical_repository != Path(original).resolve(strict=True):
            raise RuntimeError("canonical repository metadata changed")
        if record.get("managedWorktree"):
            branch = record.get("branch")
            if branch:
                actual = _run_git(
                    self.git, resolved, "symbolic-ref", "--quiet", "--short", "HEAD", check=False,
                )
                if actual.returncode != 0 or actual.stdout.strip() != branch:
                    raise RuntimeError("worktree branch no longer matches coordination metadata")

    def _reconcile_locked(self, state: dict[str, Any]) -> list[str]:
        changed: list[str] = []
        now = dt.datetime.now(dt.timezone.utc)
        for session_id, record in list(state["sessions"].items()):
            if not _SESSION_ID.fullmatch(session_id) or not isinstance(record, dict):
                continue
            status = record.get("status")
            if status not in ACTIVE_SESSION_STATES:
                continue
            stale = False
            if isinstance(record.get("pid"), int):
                stale = not self._pid_matches(record)
            else:
                started = _parse_time(record.get("startedAt"))
                stale = started is None or (now - started).total_seconds() > self.reservation_ttl_seconds
            if not stale:
                continue
            work = self._worktree_state(record)
            recoverable = bool(work["dirty"] or work["ahead"] > 0)
            record.update({
                "status": "stale_recoverable" if recoverable else "stale",
                "lastHeartbeat": _now(),
                "pid": None,
                "processStartTicks": None,
                "finalCommit": work["head"],
                "dirty": work["dirty"],
                "aheadBy": work["ahead"],
                "changedFiles": work["changedFiles"],
                "recoveryReason": "process_missing_or_reused",
            })
            changed.append(session_id)
        for repository_id, lease in list(state["integrationLeases"].items()):
            expires = _parse_time(lease.get("expiresAt")) if isinstance(lease, dict) else None
            if expires is None or expires <= now:
                state["integrationLeases"].pop(repository_id, None)
        return changed

    def reserve(
        self,
        project: str | os.PathLike[str],
        *,
        task_summary: str,
        task_scope: Sequence[str] = (),
        isolate: bool | None = None,
    ) -> dict[str, Any]:
        identity = canonical_project(project, git=self.git)
        scopes = tuple(_safe_scope(item) for item in task_scope)
        claim_key = _task_key(task_summary)
        session_id = f"q-{uuid.uuid4().hex[:12]}"
        task_digest = hashlib.sha256((task_summary or session_id).encode("utf-8")).hexdigest()[:8]
        branch = f"quattro/{session_id[2:10]}/task-{task_digest}"
        assert _BRANCH.fullmatch(branch)
        with self._locked() as state:
            active = [
                row for row in state["sessions"].values()
                if isinstance(row, dict) and row.get("status") in ACTIVE_SESSION_STATES
            ]
            same = [row for row in active if row.get("repositoryId") == identity.repository_id]
            if len(active) >= self.global_limit:
                raise LeaseConflict(f"Global Quattro session limit reached: {len(active)}/{self.global_limit}")
            if len(same) >= self.per_repository_limit:
                details = ", ".join(
                    f"{row.get('sessionId')} — {row.get('taskSummary') or 'unclaimed'}"
                    for row in same
                )
                raise LeaseConflict(
                    f"Repository Quattro limit reached: {len(same)}/{self.per_repository_limit}. "
                    f"Active sessions: {details}"
                )
            if claim_key:
                duplicate = next((
                    row for row in same if row.get("taskKey") == claim_key
                ), None)
                if duplicate:
                    raise LeaseConflict(
                        f"Task is already claimed by {duplicate.get('sessionId')}: "
                        f"{duplicate.get('taskSummary')}"
                    )
            for scope in scopes:
                for peer in same:
                    for existing in peer.get("taskScope", []):
                        if isinstance(existing, str) and _scopes_overlap(scope, existing):
                            raise LeaseConflict(
                                f"Task scope {scope} overlaps {existing} owned by {peer.get('sessionId')}"
                            )
            # Shared working trees are the default. No configuration value can
            # silently change a session directory; isolation is exact opt-in.
            use_isolation = isolate is True
            worktree = identity.requested_worktree
            working_directory = identity.requested_path
            managed = False
            branch = identity.base_branch if identity.kind == "git" else None
            isolation_reason = "shared_working_tree"
            if identity.kind == "git" and use_isolation and identity.base_commit:
                repository_root = self.worktree_root / identity.repository_id
                if repository_root.is_symlink():
                    raise RuntimeError("managed repository worktree root must not be a symlink")
                repository_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chmod(repository_root, 0o700)
                worktree = repository_root / session_id
                if worktree.exists() or worktree.is_symlink():
                    raise RuntimeError("managed worktree path unexpectedly exists")
                branch = f"quattro/{session_id[2:10]}/task-{task_digest}"
                _run_git(
                    self.git, identity.canonical_repository,
                    "worktree", "add", "--quiet", "-b", branch, str(worktree), identity.base_commit,
                    timeout=120,
                )
                managed = True
                isolation_reason = "explicit_managed_worktree"
                relative_directory = identity.requested_path.relative_to(identity.requested_worktree)
                working_directory = worktree / relative_directory
            record = {
                "schemaVersion": 1,
                "sessionId": session_id,
                "repositoryId": identity.repository_id,
                "kind": identity.kind,
                "originalRepository": str(identity.canonical_repository),
                "requestedPath": str(identity.requested_path),
                "worktreePath": str(worktree),
                "workingDirectory": str(working_directory),
                "managedWorktree": managed,
                "isolationReason": isolation_reason,
                "branch": branch,
                "baseBranch": identity.base_branch,
                "baseCommit": identity.base_commit,
                "originalDirty": identity.original_dirty,
                "taskSummary": " ".join(task_summary.split())[:200],
                "taskKey": claim_key,
                "taskScope": list(scopes),
                "dependencies": [],
                "status": "starting",
                "pid": None,
                "processStartTicks": None,
                "taskId": None,
                "logicalSessionId": None,
                "startedAt": _now(),
                "lastHeartbeat": _now(),
                "finalCommit": None,
                "validation": "Not Run",
                "dirty": False,
                "aheadBy": 0,
                "changedFiles": [],
                "integratedInto": [],
            }
            state["sessions"][session_id] = record
            self._event(state, "session.reserved", session_id, identity.repository_id)
            return dict(record)

    def adopt_legacy(
        self,
        project: str | os.PathLike[str],
        *,
        task_id: str,
        logical_session_id: str | None,
        pid: int,
        process_start_ticks: int,
        task_summary: str,
    ) -> dict[str, Any]:
        """Register one already-running pre-cooperation top-level task.

        Adoption is atomic with the same limit state as ordinary reservation,
        but deliberately does not move the live process or fabricate a managed
        branch. It exists only for rolling activation compatibility.
        """
        identity = canonical_project(project, git=self.git)
        with self._locked() as state:
            for record in state["sessions"].values():
                if isinstance(record, dict) and record.get("taskId") == task_id:
                    return dict(record)
            active = [
                row for row in state["sessions"].values()
                if isinstance(row, dict) and row.get("status") in ACTIVE_SESSION_STATES
            ]
            same = [row for row in active if row.get("repositoryId") == identity.repository_id]
            if len(active) >= self.global_limit or len(same) >= self.per_repository_limit:
                raise LeaseConflict("legacy session cannot be adopted because cooperative capacity is full")
            session_id = f"q-{uuid.uuid4().hex[:12]}"
            branch_result = _run_git(
                self.git, identity.requested_worktree,
                "symbolic-ref", "--quiet", "--short", "HEAD", check=False,
            ) if identity.kind == "git" else None
            branch = (
                branch_result.stdout.strip()
                if branch_result is not None and branch_result.returncode == 0 else None
            )
            record = {
                "schemaVersion": 1,
                "sessionId": session_id,
                "repositoryId": identity.repository_id,
                "kind": identity.kind,
                "originalRepository": str(identity.canonical_repository),
                "requestedPath": str(identity.requested_path),
                "worktreePath": str(identity.requested_worktree),
                "workingDirectory": str(identity.requested_path),
                "managedWorktree": False,
                "isolationReason": "adopted_legacy_session",
                "branch": branch,
                "baseBranch": identity.base_branch,
                "baseCommit": identity.base_commit,
                "originalDirty": identity.original_dirty,
                "taskSummary": " ".join(task_summary.split())[:200],
                "taskKey": None,
                "taskScope": [],
                "dependencies": [],
                "status": "active",
                "pid": pid,
                "processStartTicks": process_start_ticks,
                "taskId": task_id,
                "logicalSessionId": logical_session_id,
                "startedAt": _now(),
                "lastHeartbeat": _now(),
                "finalCommit": None,
                "validation": "Not Run",
                "dirty": False,
                "aheadBy": 0,
                "changedFiles": [],
                "integratedInto": [],
            }
            state["sessions"][session_id] = record
            self._event(state, "session.legacy_adopted", session_id, identity.repository_id)
            return dict(record)

    def rollback_reservation(self, session_id: str) -> None:
        with self._locked() as state:
            record = self._record(state, session_id)
            if record.get("status") != "starting" or record.get("pid") is not None:
                raise RuntimeError("only an unused startup reservation can be rolled back")
            if record.get("managedWorktree"):
                self._remove_managed_worktree(record, delete_branch=True)
            state["sessions"].pop(session_id, None)
            self._event(state, "session.reservation_rolled_back", session_id, record["repositoryId"])

    def bind(self, session_id: str, *, task_id: str, logical_session_id: str) -> dict[str, Any]:
        with self._locked() as state:
            record = self._record(state, session_id)
            record["taskId"] = task_id
            record["logicalSessionId"] = logical_session_id
            record["lastHeartbeat"] = _now()
            return dict(record)

    def resume(self, session_id: str, *, task_summary: str | None = None) -> dict[str, Any]:
        with self._locked() as state:
            record = self._record(state, session_id)
            if record.get("status") in ACTIVE_SESSION_STATES:
                if record.get("status") == "starting" and record.get("pid") is None:
                    if task_summary:
                        record["taskSummary"] = " ".join(task_summary.split())[:200]
                    record["lastHeartbeat"] = _now()
                    return dict(record)
                raise LeaseConflict(f"Quattro session is already active: {session_id}")
            active = [
                row for row in state["sessions"].values()
                if isinstance(row, dict) and row.get("status") in ACTIVE_SESSION_STATES
            ]
            same = [row for row in active if row.get("repositoryId") == record.get("repositoryId")]
            if len(active) >= self.global_limit:
                raise LeaseConflict(f"Global Quattro session limit reached: {len(active)}/{self.global_limit}")
            if len(same) >= self.per_repository_limit:
                raise LeaseConflict(
                    f"Repository Quattro limit reached: {len(same)}/{self.per_repository_limit}"
                )
            if not Path(str(record.get("worktreePath"))).is_dir():
                raise RuntimeError("recoverable Quattro working directory is unavailable")
            record.update({
                "status": "starting", "pid": None, "processStartTicks": None,
                "lastHeartbeat": _now(), "startedAt": _now(),
            })
            if task_summary:
                record["taskSummary"] = " ".join(task_summary.split())[:200]
            self._event(state, "session.resumed", session_id, record["repositoryId"])
            return dict(record)

    def activate(
        self,
        session_id: str,
        *,
        pid: int,
        process_start_ticks: int,
        task_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        if status not in {"active", "validating", "integrating"}:
            raise ValueError("invalid active session status")
        with self._locked() as state:
            record = self._record(state, session_id)
            record.update({
                "status": status,
                "pid": pid,
                "processStartTicks": process_start_ticks,
                "taskId": task_id or record.get("taskId"),
                "lastHeartbeat": _now(),
            })
            return dict(record)

    def heartbeat(self, session_id: str, *, status: str | None = None) -> None:
        with self._locked() as state:
            record = self._record(state, session_id)
            if status:
                if status not in ACTIVE_SESSION_STATES:
                    raise ValueError("invalid heartbeat status")
                record["status"] = status
            record["lastHeartbeat"] = _now()

    def finish(self, session_id: str, *, validation: str, abandoned: bool = False) -> dict[str, Any]:
        with self._locked() as state:
            record = self._record(state, session_id)
            work = self._worktree_state(record)
            recoverable = bool(work["dirty"] or work["ahead"] > 0)
            if abandoned:
                status = "stale_recoverable" if recoverable else "abandoned"
            else:
                status = "completed_recoverable" if recoverable else "completed"
            record.update({
                "status": status,
                "pid": None,
                "processStartTicks": None,
                "lastHeartbeat": _now(),
                "finalCommit": work["head"],
                "validation": validation[:120],
                "dirty": work["dirty"],
                "aheadBy": work["ahead"],
                "changedFiles": work["changedFiles"],
            })
            self._event(state, "session.finished", session_id, record["repositoryId"])
            return dict(record)

    def claim(self, session_id: str, *, summary: str, scopes: Sequence[str] = ()) -> dict[str, Any]:
        normalized = tuple(_safe_scope(item) for item in scopes)
        key = _task_key(summary)
        with self._locked() as state:
            record = self._record(state, session_id)
            peers = [
                row for sid, row in state["sessions"].items()
                if sid != session_id and isinstance(row, dict)
                and row.get("repositoryId") == record.get("repositoryId")
                and row.get("status") in ACTIVE_SESSION_STATES
            ]
            for peer in peers:
                if key and peer.get("taskKey") == key:
                    raise LeaseConflict(f"Task is already claimed by {peer.get('sessionId')}")
                for scope in normalized:
                    for existing in peer.get("taskScope", []):
                        if isinstance(existing, str) and _scopes_overlap(scope, existing):
                            raise LeaseConflict(
                                f"Task scope {scope} overlaps {existing} owned by {peer.get('sessionId')}"
                            )
            record.update({
                "taskSummary": " ".join(summary.split())[:200],
                "taskKey": key,
                "taskScope": list(normalized),
                "lastHeartbeat": _now(),
            })
            self._event(state, "task.claimed", session_id, record["repositoryId"])
            return dict(record)

    def add_dependency(self, session_id: str, dependency_session_id: str) -> dict[str, Any]:
        if session_id == dependency_session_id:
            raise ValueError("a session cannot depend on itself")
        with self._locked() as state:
            record = self._record(state, session_id)
            dependency = self._record(state, dependency_session_id)
            if record.get("repositoryId") != dependency.get("repositoryId"):
                raise ValueError("dependencies must belong to the same repository")
            values = list(record.get("dependencies", []))
            if dependency_session_id not in values:
                values.append(dependency_session_id)
            record["dependencies"] = values
            self._event(state, "dependency.added", session_id, record["repositoryId"])
            return dict(record)

    def context(self, session_id: str) -> str:
        with self._locked() as state:
            record = self._record(state, session_id)
            peers = [
                row for sid, row in state["sessions"].items()
                if sid != session_id and isinstance(row, dict)
                and row.get("repositoryId") == record.get("repositoryId")
                and row.get("status") in ACTIVE_SESSION_STATES
            ]
            lines = [
                "QUATTRO COOPERATIVE SESSION CONTEXT (trusted local coordination):",
                f"Canonical repository: {record.get('originalRepository')}",
                f"Repository identity: {record.get('repositoryId')}",
                f"Current session: {session_id}",
                f"Current branch: {record.get('branch') or 'not applicable'}",
                f"Current working directory: {record.get('workingDirectory') or record.get('worktreePath')}",
                f"Write ownership: {', '.join(record.get('taskScope') or []) or 'scope not declared'}",
            ]
            lines.append(f"Isolation: {record.get('isolationReason') or 'shared_working_tree'}")
            if record.get("originalDirty"):
                lines.append(
                    "Uncommitted changes existed at startup. They remain shared state: preserve them, "
                    "never reset, clean, stash, discard, or overwrite unknown modifications."
                )
            lines.append("Other active same-repository sessions:")
            if not peers:
                lines.append("- None")
            for peer in peers:
                scope = ", ".join(peer.get("taskScope", [])) or "scope not declared"
                lines.extend([
                    f"- {peer.get('sessionId')}: {peer.get('taskSummary') or 'task not yet claimed'}",
                    f"  branch: {peer.get('branch') or 'not applicable'}",
                    f"  working directory: {peer.get('workingDirectory') or peer.get('worktreePath')}",
                    f"  scope: {scope}",
                ])
            lines.append(
                "Before writing, determine and claim repository-relative file or directory scopes. "
                "Do not overlap active claims; serialize conflicting edits and preserve unknown changes."
            )
            return "\n".join(lines)

    def acquire_integration(self, session_id: str) -> str:
        token = uuid.uuid4().hex
        with self._locked() as state:
            record = self._record(state, session_id)
            repository_id = record["repositoryId"]
            existing = state["integrationLeases"].get(repository_id)
            if isinstance(existing, dict):
                raise LeaseConflict(
                    f"repository integration is owned by {existing.get('holderSessionId')}"
                )
            expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
                seconds=self.integration_ttl_seconds
            )
            state["integrationLeases"][repository_id] = {
                "holderSessionId": session_id,
                "token": token,
                "acquiredAt": _now(),
                "expiresAt": expires.isoformat(timespec="milliseconds"),
            }
            record["status"] = "integrating"
            self._event(state, "integration.acquired", session_id, repository_id)
            return token

    def release_integration(self, session_id: str, token: str) -> None:
        with self._locked() as state:
            record = self._record(state, session_id)
            repository_id = record["repositoryId"]
            lease = state["integrationLeases"].get(repository_id)
            if not isinstance(lease, dict) or lease.get("holderSessionId") != session_id \
                    or lease.get("token") != token:
                raise LeaseConflict("integration lease ownership changed")
            state["integrationLeases"].pop(repository_id, None)
            if record.get("status") == "integrating":
                record["status"] = "active" if record.get("pid") else "completed_recoverable"
            self._event(state, "integration.released", session_id, repository_id)

    def integrate(self, target_session_id: str, source_session_id: str, *, strategy: str) -> dict[str, Any]:
        if strategy not in {"merge", "cherry-pick"}:
            raise ValueError("integration strategy must be merge or cherry-pick")
        with self._locked() as state:
            target = dict(self._record(state, target_session_id))
            source = dict(self._record(state, source_session_id))
            if not target.get("managedWorktree") or not source.get("managedWorktree"):
                raise RuntimeError("shared-working-tree sessions are already integrated; use ownership handoff instead")
            if target["repositoryId"] != source["repositoryId"] or target["kind"] != "git":
                raise ValueError("integration requires two sessions from one Git repository")
            if source.get("status") in ACTIVE_SESSION_STATES:
                raise RuntimeError("source session must complete before integration")
            source_commit = source.get("finalCommit")
            if not isinstance(source_commit, str) or not _COMMIT.fullmatch(source_commit):
                raise RuntimeError("source session has no completed commit")
            source_branch = source.get("branch")
            if not isinstance(source_branch, str) or not _BRANCH.fullmatch(source_branch):
                raise RuntimeError("source branch metadata is invalid")
            target_path = Path(str(target["worktreePath"]))
            self._validate_git_record(target, target_path)
            self._validate_git_record(source, Path(str(source["worktreePath"])))
            if self._worktree_state(target)["dirty"]:
                raise RuntimeError("target worktree must be clean before integration")
        token = self.acquire_integration(target_session_id)
        command = (
            ("merge", "--no-ff", "--no-edit", source_branch)
            if strategy == "merge"
            else ("cherry-pick", str(source_commit))
        )
        try:
            result = _run_git(self.git, target_path, *command, check=False, timeout=120)
            if result.returncode != 0:
                conflict = _run_git(
                    self.git, target_path, "diff", "--name-only", "--diff-filter=U", check=False,
                ).stdout.splitlines()
                abort = ("merge", "--abort") if strategy == "merge" else ("cherry-pick", "--abort")
                _run_git(self.git, target_path, *abort, check=False)
                with self._locked() as state:
                    self._event(
                        state, "integration.conflict", target_session_id, target["repositoryId"],
                        {"sourceSessionId": source_session_id, "files": conflict[:100]},
                    )
                raise RuntimeError(
                    "integration conflict requires semantic resolution: "
                    + (", ".join(conflict[:20]) or "Git rejected the operation")
                )
            head = _run_git(self.git, target_path, "rev-parse", "HEAD").stdout.strip()
            with self._locked() as state:
                source_record = self._record(state, source_session_id)
                integrated = list(source_record.get("integratedInto", []))
                integrated.append({
                    "sessionId": target_session_id,
                    "commit": head,
                    "strategy": strategy,
                    "at": _now(),
                })
                source_record["integratedInto"] = integrated[-20:]
                self._event(
                    state, "integration.completed", target_session_id, target["repositoryId"],
                    {"sourceSessionId": source_session_id, "strategy": strategy, "commit": head},
                )
            return {
                "sourceSessionId": source_session_id,
                "targetSessionId": target_session_id,
                "strategy": strategy,
                "commit": head,
                "validation": "Not Run",
            }
        finally:
            self.release_integration(target_session_id, token)

    def cleanup(self, session_id: str) -> dict[str, Any]:
        with self._locked() as state:
            record = self._record(state, session_id)
            if record.get("status") in ACTIVE_SESSION_STATES:
                raise RuntimeError("cannot clean an active Quattro session")
            if not record.get("managedWorktree"):
                raise RuntimeError("session does not own a managed worktree")
            work = self._worktree_state(record)
            if work["dirty"]:
                raise RuntimeError("managed worktree has uncommitted changes and was preserved")
            if work["ahead"] > 0 and not record.get("integratedInto"):
                raise RuntimeError("managed branch contains unintegrated commits and was preserved")
            force_branch_delete = False
            if work["ahead"] > 0:
                source_commit = record.get("finalCommit") or work.get("head")
                proofs = [
                    item.get("commit") for item in record.get("integratedInto", [])
                    if isinstance(item, dict) and isinstance(item.get("commit"), str)
                ]
                original = Path(str(record.get("originalRepository"))).resolve(strict=True)
                force_branch_delete = bool(source_commit and any(
                    _run_git(
                        self.git, original, "merge-base", "--is-ancestor",
                        str(source_commit), proof, check=False,
                    ).returncode == 0
                    for proof in proofs
                ))
                if not force_branch_delete:
                    raise RuntimeError("integration ancestry could not be proven; branch was preserved")
            worktree = record["worktreePath"]
            branch = record["branch"]
            self._remove_managed_worktree(
                record, delete_branch=True, force_branch_delete=force_branch_delete
            )
            record.update({
                "status": "abandoned" if record.get("status") == "stale" else "completed",
                "worktreeRemoved": True,
                "worktreePath": worktree,
                "branchRemoved": branch,
                "lastHeartbeat": _now(),
            })
            self._event(state, "session.cleaned", session_id, record["repositoryId"])
            return dict(record)

    def _remove_managed_worktree(
        self, record: Mapping[str, Any], *, delete_branch: bool,
        force_branch_delete: bool = False,
    ) -> None:
        path = Path(str(record.get("worktreePath"))).resolve(strict=False)
        repository_root = (self.worktree_root / str(record.get("repositoryId"))).resolve(strict=False)
        try:
            path.relative_to(repository_root)
        except ValueError as error:
            raise RuntimeError("refusing to remove a path outside the managed worktree root") from error
        original = Path(str(record.get("originalRepository"))).resolve(strict=True)
        result = _run_git(self.git, original, "worktree", "remove", str(path), check=False, timeout=120)
        if result.returncode != 0:
            raise RuntimeError("git refused safe managed worktree removal")
        branch = record.get("branch")
        if delete_branch and isinstance(branch, str) and _BRANCH.fullmatch(branch):
            flag = "-D" if force_branch_delete else "-d"
            result = _run_git(self.git, original, "branch", flag, branch, check=False)
            if result.returncode != 0:
                raise RuntimeError("Git preserved a branch that is not safely deletable")

    def reconcile(self) -> list[str]:
        with self._locked() as state:
            # _locked already reconciled. Return the currently stale identities
            # so callers can surface recoverable work without deleting it.
            return [
                sid for sid, row in state["sessions"].items()
                if isinstance(row, dict) and row.get("status") in {"stale", "stale_recoverable"}
            ]

    def find_by_logical_session(self, logical_session_id: str) -> dict[str, Any] | None:
        with self._locked() as state:
            for record in state["sessions"].values():
                if isinstance(record, dict) and record.get("logicalSessionId") == logical_session_id:
                    return dict(record)
        return None

    def get(self, session_id: str) -> dict[str, Any]:
        with self._locked() as state:
            return dict(self._record(state, session_id))

    def status(self) -> dict[str, Any]:
        with self._locked() as state:
            sessions = [dict(row) for row in state["sessions"].values() if isinstance(row, dict)]
            active = [row for row in sessions if row.get("status") in ACTIVE_SESSION_STATES]
            repositories: dict[str, dict[str, Any]] = {}
            for row in sessions:
                repository_id = str(row.get("repositoryId"))
                entry = repositories.setdefault(repository_id, {
                    "repositoryId": repository_id,
                    "name": Path(str(row.get("originalRepository"))).name,
                    "canonicalRepository": row.get("originalRepository"),
                    "active": 0,
                    "limit": self.per_repository_limit,
                    "sessions": [],
                })
                if row.get("status") in ACTIVE_SESSION_STATES:
                    entry["active"] += 1
                entry["sessions"].append(row)
            return {
                "schemaVersion": 1,
                "global": {"active": len(active), "limit": self.global_limit},
                "repositories": sorted(
                    repositories.values(), key=lambda item: str(item["canonicalRepository"])
                ),
                "integrationLeases": [
                    {
                        "holderSessionId": lease.get("holderSessionId"),
                        "acquiredAt": lease.get("acquiredAt"),
                        "expiresAt": lease.get("expiresAt"),
                    }
                    for lease in state["integrationLeases"].values()
                    if isinstance(lease, dict)
                ],
            }

    @staticmethod
    def _record(state: Mapping[str, Any], session_id: str) -> dict[str, Any]:
        if not _SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid Quattro coordination session id")
        record = state["sessions"].get(session_id)
        if not isinstance(record, dict):
            raise KeyError(session_id)
        return record

    @staticmethod
    def _event(
        state: dict[str, Any], event_type: str, session_id: str, repository_id: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        state["events"].append({
            "type": event_type,
            "sessionId": session_id,
            "repositoryId": repository_id,
            "at": _now(),
            "details": dict(details or {}),
        })
        state["events"] = state["events"][-200:]
