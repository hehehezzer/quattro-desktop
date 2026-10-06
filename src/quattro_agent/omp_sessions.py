"""Private metadata for staged OMP terminals; never a task or permission store.

Only trusted launch/session-start integration may populate this registry. An
observed native ID is metadata, not proof of process survival or approval.
Attachment means reconnecting to an existing pane; native restart is unsupported.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import uuid

try:
    import fcntl
except ImportError:  # Core imports remain portable; Herdr registry is Linux-only.
    fcntl = None

from .herdr_runtime import HerdrRuntime, HerdrSession

MAX_BYTES = 1_048_576
MAX_SESSIONS = 512
_STATES = {"launch_pending", "launch_uncertain", "active", "close_pending", "close_uncertain", "closed"}
_FIELDS = {"logicalSessionId", "socket", "socketIdentity", "directory", "directoryIdentity",
           "workspace", "pane", "nativeSessionId", "identityState", "lifecycle", "launchContract"}


class OMPSessionError(ValueError):
    """Display-safe invalid or uncertain session metadata."""


def _identifier(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", value):
        raise OMPSessionError("invalid session identifier")
    return value


def _absolute(value: object) -> Path:
    if (not isinstance(value, (str, Path)) or not str(value) or len(str(value)) > 4096
            or any(ord(char) < 32 for char in str(value))):
        raise OMPSessionError("bounded absolute path required")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise OMPSessionError("bounded absolute path required")
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise OMPSessionError("session paths must not contain symbolic links")
    return path


def _identity(path: Path, *, socket: bool = False) -> list[int]:
    info = path.lstat()
    if socket:
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OMPSessionError("owned private Herdr socket required")
        return [info.st_dev, info.st_ino, info.st_ctime_ns]
    if not stat.S_ISDIR(info.st_mode):
        raise OMPSessionError("existing workspace directory required")
    return [info.st_dev, info.st_ino]


def _private(info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise OMPSessionError("private owned regular registry file required")


def _row(value: object, key: str) -> dict:
    if type(value) is not dict or set(value) != _FIELDS:
        raise OMPSessionError("malformed OMP session record")
    if _identifier(key) != value["logicalSessionId"] or not key.startswith("qomp_"):
        raise OMPSessionError("logical session identity mismatch")
    for field in ("socket", "directory"):
        _absolute(value[field])
    for field, size in (("socketIdentity", 3), ("directoryIdentity", 2)):
        identity = value[field]
        if type(identity) is not list or len(identity) != size or any(type(n) is not int or n < 0 for n in identity):
            raise OMPSessionError("invalid filesystem identity")
    if value["lifecycle"] not in _STATES or value["launchContract"] != "quattro_argv_v1":
        raise OMPSessionError("unsupported session lifecycle")
    if (value["workspace"] is None) != (value["pane"] is None):
        raise OMPSessionError("partial Herdr identity")
    if value["workspace"] is not None:
        _identifier(value["workspace"])
        _identifier(value["pane"])
        if not value["pane"].startswith(value["workspace"] + ":"):
            raise OMPSessionError("Herdr pane/workspace mismatch")
    elif value["lifecycle"] not in {"launch_pending", "launch_uncertain"}:
        raise OMPSessionError("Herdr session identity required")
    if value["nativeSessionId"] is None:
        if value["identityState"] != "pending":
            raise OMPSessionError("unobserved native identity")
    else:
        _identifier(value["nativeSessionId"])
        if value["identityState"] != "observed" or value["workspace"] is None:
            raise OMPSessionError("invalid native identity provenance")
    return value


class OMPSessionRegistry:
    """Bounded, locked metadata isolated from Codex/Pi durable databases.

    Call begin before one argv-backed launch; created only after its successful
    return. Ambiguous mutations are recorded, never retried by this class.
    All tuple-binding methods require explicit caller-selected identifiers.
    """

    def __init__(self, path: Path, *, lock_timeout: float = 2.0):
        if fcntl is None:
            raise OMPSessionError("OMP Herdr registry requires Unix file locking")
        self.path = _absolute(path)
        if not 0 < lock_timeout <= 5:
            raise OMPSessionError("bounded lock timeout required")
        self.lock_timeout = lock_timeout

    @contextlib.contextmanager
    def _locked(self):
        parent = _absolute(self.path.parent)
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OMPSessionError("private owned registry directory required")
        lock = _absolute(self.path.with_name(self.path.name + ".lock"))
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            _private(os.fstat(descriptor))
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise OMPSessionError("OMP registry lock unavailable") from None
                    time.sleep(0.01)
            yield
        finally:
            os.close(descriptor)

    def _load(self) -> tuple[dict, tuple | None]:
        try:
            descriptor = os.open(_absolute(self.path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {}, None
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            _private(info)
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise OMPSessionError("OMP registry exceeds size bound")
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise OMPSessionError("duplicate registry key")
                    result[key] = value
                return result
            document = json.loads(data, object_pairs_hook=unique)
            if (type(document) is not dict or set(document) != {"schemaVersion", "sessions"}
                    or type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1
                    or type(document["sessions"]) is not dict or len(document["sessions"]) > MAX_SESSIONS):
                raise OMPSessionError("invalid OMP registry schema")
            rows = {key: _row(value, key) for key, value in document["sessions"].items()}
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise OMPSessionError("invalid OMP registry metadata") from None
        return rows, (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)

    def _write(self, rows: dict, preimage: tuple | None) -> None:
        data = (json.dumps({"schemaVersion": 1, "sessions": rows}, sort_keys=True) + "\n").encode()
        if len(data) > MAX_BYTES:
            raise OMPSessionError("OMP registry exceeds size bound")
        descriptor, temporary = tempfile.mkstemp(prefix=".omp-sessions-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                info = _absolute(self.path).lstat()
                _private(info)
                current = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
            except FileNotFoundError:
                current = None
            if current != preimage:
                raise OMPSessionError("OMP registry changed outside its lock")
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def begin(self, *, socket: Path, directory: Path) -> str:
        """Record intent only; no terminal creation or access approval occurs."""
        socket, directory = _absolute(socket), _absolute(directory)
        key = "qomp_" + uuid.uuid4().hex
        row = dict(logicalSessionId=key, socket=str(socket), socketIdentity=_identity(socket, socket=True),
                   directory=str(directory), directoryIdentity=_identity(directory), workspace=None, pane=None,
                   nativeSessionId=None, identityState="pending", lifecycle="launch_pending",
                   launchContract="quattro_argv_v1")
        with self._locked():
            rows, preimage = self._load()
            if len(rows) >= MAX_SESSIONS:
                raise OMPSessionError("OMP registry session limit reached")
            rows[key] = row
            self._write(rows, preimage)
        return key

    def get(self, logical_id: str) -> dict:
        with self._locked():
            rows, _ = self._load()
            try:
                row = dict(rows[_identifier(logical_id)])
            except KeyError:
                raise OMPSessionError("unregistered OMP session") from None
        return dict(row, coordinationSupported=False, nativeRestartResumeSupported=False)

    def _change(self, logical_id, change):
        with self._locked():
            rows, preimage = self._load()
            try:
                row = rows[_identifier(logical_id)]
            except KeyError:
                raise OMPSessionError("unregistered OMP session") from None
            change(row)
            _row(row, logical_id)
            if row["workspace"] is not None and any(
                key != logical_id and other["socketIdentity"] == row["socketIdentity"]
                and other["workspace"] == row["workspace"] and other["pane"] == row["pane"]
                for key, other in rows.items()
            ):
                raise OMPSessionError("Herdr tuple already belongs to another logical session")
            self._write(rows, preimage)

    def created(self, logical_id: str, handle: HerdrSession) -> None:
        """Bind one successful start receipt; never adopt an existing pane."""
        def change(row):
            if row["lifecycle"] != "launch_pending":
                raise OMPSessionError("launch result cannot be replayed")
            self._filesystem_matches(row)
            row.update(workspace=_identifier(handle.workspace_id), pane=_identifier(handle.pane_id), lifecycle="active")
        self._change(logical_id, change)

    def mark_launch_uncertain(self, logical_id: str) -> None:
        def change(row):
            # Atomic replacement can succeed before a directory fsync fails.
            # Preserve that identity without reporting an acknowledged launch.
            if row["lifecycle"] not in {"launch_pending", "active"}:
                raise OMPSessionError("invalid or uncertain lifecycle transition")
            row["lifecycle"] = "launch_uncertain"
        self._change(logical_id, change)

    def verify_launch(self, logical_id: str, *, socket: Path, directory: Path,
                      handle: HerdrSession) -> dict:
        """Verify the first launch binding; this never grants execution rights."""
        row = self.get(logical_id)
        self._bound(row, socket=socket, directory=directory, handle=handle)
        if row["lifecycle"] != "active" or row["nativeSessionId"] is not None:
            raise OMPSessionError("native restart/resume is unavailable; attach the existing pane")
        return row

    def _transition(self, logical_id, expected, target):
        def change(row):
            if row["lifecycle"] != expected:
                raise OMPSessionError("invalid or uncertain lifecycle transition")
            row["lifecycle"] = target
        self._change(logical_id, change)

    @staticmethod
    def _filesystem_matches(row):
        if (_identity(_absolute(row["socket"]), socket=True) != row["socketIdentity"]
                or _identity(_absolute(row["directory"])) != row["directoryIdentity"]):
            raise OMPSessionError("recorded filesystem identity changed")

    def _bound(self, row, *, socket, directory, handle):
        if (str(_absolute(socket)) != row["socket"] or str(_absolute(directory)) != row["directory"]
                or handle.workspace_id != row["workspace"] or handle.pane_id != row["pane"]):
            raise OMPSessionError("recorded OMP session tuple mismatch")
        self._filesystem_matches(row)

    def observe_native(self, logical_id: str, *, socket: Path, directory: Path,
                       handle: HerdrSession, native_session_id: str) -> None:
        """Trusted native session-start hook only; never accept model assertions."""
        native_session_id = _identifier(native_session_id)
        def change(row):
            self._bound(row, socket=socket, directory=directory, handle=handle)
            if row["lifecycle"] != "active" or row["nativeSessionId"] not in {None, native_session_id}:
                raise OMPSessionError("native identity changed or session inactive")
            row.update(nativeSessionId=native_session_id, identityState="observed")
        self._change(logical_id, change)

    def status(self, runtime: HerdrRuntime, logical_id: str, *, directory: Path, handle: HerdrSession) -> dict:
        row = self.get(logical_id)
        self._bound(row, socket=runtime.socket_path, directory=directory, handle=handle)
        if row["lifecycle"] != "active":
            raise OMPSessionError("OMP lifecycle is inactive or uncertain")
        observed = runtime.status(handle)
        if observed.get("workspace_id") != row["workspace"] or observed.get("pane_id") != row["pane"]:
            raise OMPSessionError("observed Herdr session tuple mismatch")
        self._filesystem_matches(row)
        if self.get(logical_id) != row:
            raise OMPSessionError("OMP session changed during status observation")
        state = observed.get("agent_status")
        row["agent_status"] = state if state in {"idle", "working", "blocked", "done"} else "unknown"
        return row

    def verify_attachment(self, runtime: HerdrRuntime, logical_id: str, *, directory: Path,
                          handle: HerdrSession, native_session_id: str) -> dict:
        """Authorize only existing-pane identity selection, never execution."""
        row = self.status(runtime, logical_id, directory=directory, handle=handle)
        if (row["identityState"] != "observed" or row["nativeSessionId"] != _identifier(native_session_id)
                or row["agent_status"] not in {"idle", "working", "blocked"}):
            raise OMPSessionError("live native identity is unverified; resume unavailable")
        return dict(row, attachment="existing_pane_only", approvalGranted=False)

    def begin_close(self, logical_id: str, *, socket: Path, directory: Path, handle: HerdrSession) -> None:
        """Record explicit close intent; runtime.close still requires client ownership.

        The caller must retain the creating HerdrRuntime. This registry never
        adds handles to its ownership set or closes a server/workspace itself.
        """
        def change(row):
            self._bound(row, socket=socket, directory=directory, handle=handle)
            if row["lifecycle"] != "active":
                raise OMPSessionError("close cannot replay an uncertain mutation")
            row["lifecycle"] = "close_pending"
        self._change(logical_id, change)

    def finish_close(self, logical_id: str, *, confirmed: bool) -> None:
        """Successful owning-client close is confirmed; any failure stays uncertain."""
        if type(confirmed) is not bool:
            raise OMPSessionError("explicit close outcome required")
        self._transition(logical_id, "close_pending", "closed" if confirmed else "close_uncertain")
