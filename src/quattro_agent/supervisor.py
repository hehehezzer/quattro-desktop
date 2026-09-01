"""Process-group supervision, deadlines, cancellation, and stale-run recovery."""

from __future__ import annotations

import datetime as dt
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Mapping, Sequence

from .errors import ProcessIdentityError, SupervisorError
from .models import RunState, TaskState
from .store import TaskStore


_SAFE_ENVIRONMENT_KEYS = (
    "HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "XDG_RUNTIME_DIR",
    # Interactive agents run inside the active Hyprland/Foot session. Preserve
    # only the desktop transport variables they need for Wayland clipboard and
    # browser integration; arbitrary process environment remains excluded.
    "WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
)


def minimal_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build an allowlisted child environment without serializing it anywhere."""
    result = {key: os.environ[key] for key in _SAFE_ENVIRONMENT_KEYS if key in os.environ}
    result.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    for key, value in (overrides or {}).items():
        if not isinstance(key, str) or not key or "=" in key or "\x00" in key:
            raise SupervisorError("invalid environment variable name")
        if not isinstance(value, str) or "\x00" in value:
            raise SupervisorError(f"invalid environment value for {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    process_group: int
    expected_executable: str


def _stat_fields(pid: int) -> tuple[int, int]:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError as error:
        raise ProcessIdentityError(f"process {pid} is unavailable") from error
    end = raw.rfind(")")
    if end < 0:
        raise ProcessIdentityError(f"process {pid} has malformed stat data")
    fields = raw[end + 2:].split()
    if len(fields) <= 19:
        raise ProcessIdentityError(f"process {pid} has incomplete stat data")
    return int(fields[19]), os.getpgid(pid)


def read_process_identity(pid: int, expected_executable: str | None = None) -> ProcessIdentity:
    if pid <= 0:
        raise ProcessIdentityError("PID must be positive")
    start_ticks, process_group = _stat_fields(pid)
    try:
        executable = str(Path(f"/proc/{pid}/exe").resolve(strict=True))
    except OSError as error:
        raise ProcessIdentityError(f"cannot identify process {pid}") from error
    expected = str(Path(expected_executable).resolve(strict=False)) if expected_executable else executable
    if expected_executable and executable != expected:
        raise ProcessIdentityError(
            f"process {pid} executable changed: expected {expected}, found {executable}"
        )
    return ProcessIdentity(pid, start_ticks, process_group, expected)


def verify_process_identity(identity: ProcessIdentity) -> bool:
    try:
        # Executable identity can legitimately change once when a shebang,
        # Bubblewrap, or Node shim execs the real runtime. PID start ticks and
        # process group are stable across exec and still prevent PID-reuse
        # signalling mistakes.
        current = read_process_identity(identity.pid)
    except ProcessIdentityError:
        return False
    return (
        current.start_ticks == identity.start_ticks
        and current.process_group == identity.process_group
    )


@dataclass(slots=True)
class ManagedProcess:
    run_id: str
    task_id: str
    process: subprocess.Popen[str]
    identity: ProcessIdentity
    deadline_monotonic: float | None
    heartbeat_interval: float
    lease_ttl_seconds: float


@dataclass(frozen=True, slots=True)
class ProcessResult:
    state: RunState
    exit_code: int | None
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    run_id: str
    status: str
    pid: int | None


class ProcessSupervisor:
    def __init__(
        self,
        store: TaskStore,
        *,
        heartbeat_interval: float = 1.0,
        lease_ttl_seconds: float = 30.0,
        termination_grace_seconds: float = 2.0,
    ) -> None:
        if heartbeat_interval <= 0 or lease_ttl_seconds <= 0 or termination_grace_seconds < 0:
            raise ValueError("supervisor timing values are invalid")
        self.store = store
        self.heartbeat_interval = heartbeat_interval
        self.lease_ttl_seconds = lease_ttl_seconds
        self.termination_grace_seconds = termination_grace_seconds

    def start(
        self,
        *,
        task_id: str,
        run_id: str,
        argv: Sequence[str],
        cwd: str | os.PathLike[str],
        environment_overrides: Mapping[str, str] | None = None,
        stdin_text: str | None = None,
        deadline_seconds: float | None = None,
        stdin: int | IO[str] | None = subprocess.DEVNULL,
        stdout: int | IO[str] | None = subprocess.DEVNULL,
        stderr: int | IO[str] | None = subprocess.DEVNULL,
    ) -> ManagedProcess:
        if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
            raise SupervisorError("argv must contain non-empty NUL-free strings")
        if deadline_seconds is not None and deadline_seconds <= 0:
            raise SupervisorError("deadline must be positive")
        directory = Path(cwd).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise SupervisorError(f"working directory is not a directory: {directory}")
        executable = str(Path(argv[0]).expanduser().resolve(strict=True))
        environment = minimal_environment(environment_overrides)
        self.store.transition_run(run_id, RunState.STARTING)
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=directory,
                env=environment,
                stdin=subprocess.PIPE if stdin_text is not None else stdin,
                stdout=stdout,
                stderr=stderr,
                text=True,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            self.store.transition_run(run_id, RunState.FAILED, error_code="launch_failed")
            raise
        try:
            # Script launchers (Codex/Pi Node shims and test fixtures) exec their
            # shebang interpreter, so /proc/<pid>/exe legitimately differs from
            # argv[0]. Capture the kernel-observed executable after spawn and
            # verify that stable identity for all later signalling.
            try:
                identity = read_process_identity(process.pid)
            except ProcessIdentityError:
                # Very short-lived commands can be reaped before /proc can be
                # inspected (notably on slower CI runners). The process is
                # already gone, so retain a non-signalable sentinel identity
                # and let wait() record its exit normally. Never manufacture a
                # live identity: cancellation/recovery must still fail closed.
                if process.poll() is None:
                    raise
                identity = ProcessIdentity(
                    pid=process.pid,
                    start_ticks=-1,
                    process_group=-1,
                    expected_executable=executable,
                )
            deadline_at = None
            if deadline_seconds is not None:
                deadline_at = (
                    dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=deadline_seconds)
                ).isoformat(timespec="milliseconds")
            self.store.mark_run_started(
                run_id,
                pid=identity.pid,
                process_start_ticks=identity.start_ticks,
                process_group=identity.process_group,
                expected_executable=identity.expected_executable,
                deadline_at=deadline_at,
            )
            if stdin_text is not None and process.stdin is not None:
                try:
                    process.stdin.write(stdin_text)
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            return ManagedProcess(
                run_id=run_id,
                task_id=task_id,
                process=process,
                identity=identity,
                deadline_monotonic=(time.monotonic() + deadline_seconds)
                if deadline_seconds is not None else None,
                heartbeat_interval=self.heartbeat_interval,
                lease_ttl_seconds=self.lease_ttl_seconds,
            )
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait()
            current = self.store.get_run(run_id)
            if current["state"] in {RunState.STARTING.value, RunState.RUNNING.value}:
                self.store.transition_run(run_id, RunState.INTERRUPTED, error_code="identity_failed")
            raise

    def _signal_group(self, managed: ManagedProcess, sig: signal.Signals) -> None:
        if not verify_process_identity(managed.identity):
            raise ProcessIdentityError(
                f"refusing to signal PID {managed.identity.pid}: identity mismatch"
            )
        try:
            os.killpg(managed.identity.process_group, sig)
        except ProcessLookupError:
            return

    def _terminate(self, managed: ManagedProcess, final_state: RunState) -> None:
        current = RunState(self.store.get_run(managed.run_id)["state"])
        if current is RunState.RUNNING:
            self.store.transition_run(managed.run_id, RunState.CANCELLING)
        if managed.process.poll() is None:
            try:
                self._signal_group(managed, signal.SIGTERM)
            except ProcessIdentityError:
                self.store.transition_run(
                    managed.run_id, RunState.INTERRUPTED, error_code="identity_mismatch"
                )
                self.store.release_holder_leases(managed.task_id, managed.run_id)
                raise
            try:
                managed.process.wait(timeout=self.termination_grace_seconds)
            except subprocess.TimeoutExpired:
                self._signal_group(managed, signal.SIGKILL)
                managed.process.wait()
        error = "deadline_exceeded" if final_state is RunState.TIMED_OUT else "cancelled"
        self.store.transition_run(
            managed.run_id,
            final_state,
            exit_code=managed.process.returncode,
            error_code=error,
        )
        self.store.release_holder_leases(managed.task_id, managed.run_id)

    def cancel(self, managed: ManagedProcess) -> ProcessResult:
        started = time.monotonic()
        self._terminate(managed, RunState.CANCELLED)
        return ProcessResult(RunState.CANCELLED, managed.process.returncode, time.monotonic() - started)

    def wait(
        self,
        managed: ManagedProcess,
        *,
        cancellation: threading.Event | None = None,
        heartbeat_callback: Callable[[], None] | None = None,
    ) -> ProcessResult:
        started = time.monotonic()
        next_heartbeat = started
        while True:
            now = time.monotonic()
            durable_state = RunState(self.store.get_run(managed.run_id)["state"])
            if durable_state is RunState.CANCELLING:
                self._terminate(managed, RunState.CANCELLED)
                return ProcessResult(
                    RunState.CANCELLED, managed.process.returncode, time.monotonic() - started
                )
            if durable_state in {
                RunState.CANCELLED, RunState.TIMED_OUT, RunState.INTERRUPTED,
            }:
                return ProcessResult(
                    durable_state, managed.process.poll(), time.monotonic() - started
                )
            if cancellation is not None and cancellation.is_set():
                self._terminate(managed, RunState.CANCELLED)
                return ProcessResult(
                    RunState.CANCELLED, managed.process.returncode, time.monotonic() - started
                )
            if managed.deadline_monotonic is not None and now >= managed.deadline_monotonic:
                self._terminate(managed, RunState.TIMED_OUT)
                return ProcessResult(
                    RunState.TIMED_OUT, managed.process.returncode, time.monotonic() - started
                )
            return_code = managed.process.poll()
            if return_code is not None:
                current = RunState(self.store.get_run(managed.run_id)["state"])
                if current in {
                    RunState.CANCELLED, RunState.TIMED_OUT, RunState.INTERRUPTED,
                    RunState.SUCCEEDED, RunState.FAILED,
                }:
                    self.store.release_holder_leases(managed.task_id, managed.run_id)
                    return ProcessResult(current, return_code, time.monotonic() - started)
                if current is RunState.CANCELLING:
                    state = RunState.CANCELLED
                else:
                    state = RunState.SUCCEEDED if return_code == 0 else RunState.FAILED
                self.store.transition_run(
                    managed.run_id,
                    state,
                    exit_code=return_code,
                    error_code=None if return_code == 0 else "process_exit_nonzero",
                )
                self.store.release_holder_leases(managed.task_id, managed.run_id)
                return ProcessResult(state, return_code, time.monotonic() - started)
            if now >= next_heartbeat:
                self.store.heartbeat_run(managed.run_id)
                self.store.renew_holder_leases(
                    managed.task_id,
                    managed.run_id,
                    ttl_seconds=managed.lease_ttl_seconds,
                )
                if heartbeat_callback is not None:
                    heartbeat_callback()
                next_heartbeat = now + managed.heartbeat_interval
            sleep_for = min(0.05, managed.heartbeat_interval)
            if managed.deadline_monotonic is not None:
                sleep_for = min(sleep_for, max(0.001, managed.deadline_monotonic - now))
            time.sleep(sleep_for)

    def recover_stale_runs(self, *, stale_after_seconds: float = 30.0) -> tuple[RecoveryResult, ...]:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        cutoff = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=stale_after_seconds)
        ).isoformat(timespec="milliseconds")
        results: list[RecoveryResult] = []
        for run in self.store.stale_runs(cutoff):
            pid = run["pid"]
            identity = None
            if pid and run["process_start_ticks"] is not None and run["process_group"] is not None:
                identity = ProcessIdentity(
                    pid=pid,
                    start_ticks=run["process_start_ticks"],
                    process_group=run["process_group"],
                    expected_executable=run["expected_executable"],
                )
            if identity is not None and verify_process_identity(identity):
                # The original supervisor is gone, so no trusted process can
                # determine the eventual exit code or continue validation.
                # Terminate the orphaned group and classify it as interrupted
                # instead of presenting a false recovery.
                try:
                    os.killpg(identity.process_group, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + self.termination_grace_seconds
                while time.monotonic() < deadline and verify_process_identity(identity):
                    time.sleep(0.05)
                if verify_process_identity(identity):
                    try:
                        os.killpg(identity.process_group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                current = RunState(self.store.get_run(run["run_id"])["state"])
                if current is RunState.RUNNING:
                    self.store.transition_run(
                        run["run_id"], RunState.INTERRUPTED,
                        error_code="supervisor_lost",
                    )
                self.store.release_holder_leases(run["task_id"], run["run_id"])
                try:
                    task = self.store.get_task(run["task_id"])
                    if TaskState(task["state"]) is TaskState.RUNNING:
                        self.store.transition_task(
                            run["task_id"], TaskState.INTERRUPTED,
                            terminal_code="supervisor_lost",
                            terminal_summary="The supervisor was lost; the orphan was terminated safely.",
                        )
                except (KeyError, ValueError):
                    pass
                results.append(RecoveryResult(run["run_id"], "interrupted", pid))
                continue
            current = RunState(self.store.get_run(run["run_id"])["state"])
            if current is RunState.STARTING:
                self.store.transition_run(run["run_id"], RunState.INTERRUPTED,
                                          error_code="stale_start")
            else:
                self.store.transition_run(run["run_id"], RunState.INTERRUPTED,
                                          error_code="process_missing")
            self.store.release_holder_leases(run["task_id"], run["run_id"])
            try:
                task = self.store.get_task(run["task_id"])
                if TaskState(task["state"]) is TaskState.RUNNING:
                    self.store.transition_task(
                        run["task_id"], TaskState.INTERRUPTED,
                        terminal_code="worker_lost",
                        terminal_summary="The worker process could not be recovered.",
                    )
            except (KeyError, ValueError):
                pass
            results.append(RecoveryResult(run["run_id"], "interrupted", pid))
        return tuple(results)
