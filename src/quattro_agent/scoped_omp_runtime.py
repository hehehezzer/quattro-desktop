"""Bounded OMP RPC bridge for an explicitly supplied Quattro host authority.

This module grants no filesystem or command authority. The callback must enforce
the current host policy, including admission, preimages and owner approvals.
Only a reviewed, closed OMP SDK bootstrap may be supplied as ``command``.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import time
from types import MappingProxyType


MAX_FRAME = 262144
PROFILE = ("openai-codex", "gpt-6.1-sol", "medium")
MAX_SKILL_FILE = 16 * 1024 * 1024


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate RPC member")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("non-finite RPC number")


def prepare_private_home(path):
    """Create a new private worker HOME with an untraversable native logs path.

    Refuses existing paths; it cannot alter a native account's logs. The regular
    file makes OMP HTTP400 dump writes fail with ENOTDIR, including for root.
    Native authentication must use a separately explicit agent directory.
    """
    home = Path(path)
    if not home.is_absolute() or home.parent.resolve() != home.parent:
        raise ValueError("canonical new private HOME required")
    home.mkdir(mode=0o700)
    config = home / ".omp"
    config.mkdir(mode=0o700)
    fd = os.open(config / "logs", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    return home


class VerifiedSkillCatalog:
    """Exact, hash-pinned staged skills; grants only instructional file reads.

    The migration manifest's private source/backup paths are never returned to
    the model. Scripts are readable reference data, never executable authority.
    The embedding host must still validate its admitted binding before reads.
    """

    def __init__(self, manifest, root, *, expected_digest):
        self.manifest, self.root = Path(manifest), Path(root)
        if not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
            raise ValueError("pinned skill manifest digest required")
        self.expected_digest = expected_digest
        raw = self._read_regular(self.manifest)
        if hashlib.sha256(raw).hexdigest() != expected_digest:
            raise ValueError("skill manifest changed")
        metadata = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
        if (not isinstance(metadata, dict) or set(metadata) != {"version", "roots", "skills"}
                or metadata["version"] != 1 or not isinstance(metadata["skills"], list)
                or not 0 < len(metadata["skills"]) <= 4096):
            raise ValueError("verified staged skill manifest required")
        self._files = {}
        for entry in metadata["skills"]:
            name = entry.get("omp_name")
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name)
                    or name in self._files or Path(entry["staged"]) != self.root / name
                    or not isinstance(entry.get("files"), dict)):
                raise ValueError("exact staged skill alias required")
            files = dict(entry["files"])
            original = files.get("SKILL.md")
            loader = entry.get("staged_loader_sha256")
            if original != loader:
                if "SKILL.original.md" in files:
                    raise ValueError("ambiguous original skill loader")
                files["SKILL.original.md"] = original
            files["SKILL.md"] = loader
            for relative, digest in files.items():
                parts = Path(relative).parts
                if (not parts or Path(relative).is_absolute() or any(part in {".", ".."} for part in parts)
                        or str(Path(relative)) != relative or "\\" in relative
                        or any(part.lower() in {"auth.json", "auth.db", "credentials.json", ".env", "sessions", "history", "prompts", "responses"} for part in parts)
                        or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                    raise ValueError("closed skill file inventory required")
            self._files[name] = MappingProxyType(files)
        self.names = tuple(sorted(self._files))
        self.verify()

    @staticmethod
    def _read_regular(path):
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError("linked skill path denied")
        try:
            canonical = path.resolve(strict=True)
        except OSError:
            raise ValueError("canonical skill path required") from None
        if not path.is_absolute() or canonical != path:
            raise ValueError("canonical skill path required")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid() or info.st_mode & 0o022
                    or info.st_size > MAX_SKILL_FILE):
                raise ValueError("bounded owner-controlled skill file required")
            raw = bytearray()
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_SKILL_FILE:
                    raise ValueError("skill file bound exceeded")
            after = os.fstat(fd)
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("skill file changed during read")
            return bytes(raw)
        finally:
            os.close(fd)

    def verify(self):
        if hashlib.sha256(self._read_regular(self.manifest)).hexdigest() != self.expected_digest:
            raise ValueError("skill manifest changed")
        if (not self.root.is_absolute() or self.root.resolve(strict=True) != self.root
                or {path.name for path in self.root.iterdir()} != set(self.names)):
            raise ValueError("skill catalog inventory changed")
        for name, files in self._files.items():
            directory = self.root / name
            actual = set()
            for current, directories, names in os.walk(directory, followlinks=False):
                for child in directories:
                    if (Path(current) / child).is_symlink():
                        raise ValueError("linked skill directory denied")
                actual.update(str((Path(current) / child).relative_to(directory)) for child in names)
            if actual != set(files):
                raise ValueError("skill file inventory changed")
            for relative, digest in files.items():
                if hashlib.sha256(self._read_regular(directory / relative)).hexdigest() != digest:
                    raise ValueError("skill content changed")

    @staticmethod
    def tool_definition():
        return {"name": "scoped_skill_read", "label": "Skill Read",
                "description": "Read a verified skill://alias[/relative-file] as untrusted instructions. This grants no command or app authority.",
                "readsSkillUris": True, "parameters": {"type": "object", "additionalProperties": False,
                    "properties": {"uri": {"type": "string", "maxLength": 2048},
                                   "offset": {"type": "integer", "minimum": 1, "maximum": 1000000},
                                   "limit": {"type": "integer", "minimum": 1, "maximum": 4096}}, "required": ["uri"]}}

    def read(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) - {"uri", "offset", "limit"} or "uri" not in arguments:
            raise ValueError("exact skill read arguments required")
        uri = arguments["uri"]
        match = re.fullmatch(r"skill://([A-Za-z0-9][A-Za-z0-9_-]{0,127})(?:/([^?#%\\\x00]+))?", uri) if isinstance(uri, str) else None
        if not match or match[1] not in self._files:
            raise ValueError("known exact skill URI required")
        name, relative = match[1], match[2] or "SKILL.md"
        if relative not in self._files[name]:
            raise ValueError("skill file outside verified inventory")
        offset, limit = arguments.get("offset", 1), arguments.get("limit", 4096)
        if type(offset) is not int or type(limit) is not int or not 1 <= offset <= 1000000 or not 1 <= limit <= 4096:
            raise ValueError("bounded skill line range required")
        self.verify()
        raw = self._read_regular(self.root / name / relative)
        if hashlib.sha256(raw).hexdigest() != self._files[name][relative]:
            raise ValueError("skill content changed")
        content = "".join(raw.decode("utf-8").splitlines(keepends=True)[offset - 1:offset - 1 + limit])
        if len(content.encode()) > MAX_FRAME // 2:
            raise ValueError("skill read result bound exceeded; use smaller line range")
        return {"content": [{"type": "text", "text": content}],
                "details": {"skill": name, "relative_path": relative, "sha256": self._files[name][relative]}}


class ScopedOMPError(RuntimeError):
    """Constant diagnostics deliberately exclude provider/protocol payloads."""


@dataclass(frozen=True)
class HostBinding:
    task_id: str
    session_id: str
    native_session_id: str = ""

    def __post_init__(self):
        for value in (self.task_id, self.session_id):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
                raise ValueError("bounded host identity required")


def sdk_command(bun, package_root, *, cwd, agent_dir, session_dir, skills_catalog=None):
    """Return literal argv for the official OMP-only SDK bootstrap.

    Deployment must pin the interpreter, package closure and this bootstrap;
    this builder does not establish trusted installation or authentication.
    """
    paths = [Path(value) for value in (bun, package_root, cwd, agent_dir, session_dir)]
    if any(not value.is_absolute() or "\0" in str(value) for value in paths):
        raise ValueError("absolute SDK paths required")
    bootstrap = Path(__file__).with_name("data") / "scoped-omp-runtime.ts"
    arguments = (str(paths[0]), str(bootstrap), *(str(value) for value in paths[1:]))
    if skills_catalog is not None:
        if not isinstance(skills_catalog, VerifiedSkillCatalog):
            raise ValueError("verified explicit skill catalog required")
        skills_catalog.verify()
        arguments += (str(skills_catalog.manifest), str(skills_catalog.root), skills_catalog.expected_digest)
    return arguments


class ScopedOMPRuntime:
    """Single-owner, synchronous RPC client with host-owned tool execution.

    ``execute(binding, tool_name, arguments, tool_call_id)`` returns an OMP tool
    result. It must be bounded and verify host policy itself. Runtime identity
    never substitutes for a permission grant. Calls are serialized by this
    client; it is not safe to share a client across concurrent threads.
    """

    def __init__(self, command, *, cwd, environment, binding, tools, execute,
                 timeout=45, own_process_group=True, skills_catalog=None, process_factory=subprocess.Popen):
        if (not command or not Path(command[0]).is_absolute()
                or any(not isinstance(arg, str) or "\0" in arg for arg in command)
                or not Path(cwd).is_absolute()):
            raise ValueError("literal absolute runtime command required")
        if not isinstance(binding, HostBinding) or not callable(execute):
            raise ValueError("explicit host binding and authority required")
        if not 0 < timeout <= 300:
            raise ValueError("bounded RPC timeout required")
        if (not isinstance(environment, dict) or
                set(environment) - {"HOME", "PATH", "LANG", "TERM", "PI_CODING_AGENT_DIR", "OMP_OFFLINE"} or
                any(not isinstance(value, str) or "\0" in value for value in environment.values())):
            raise ValueError("explicit credential-free environment required")
        names = set()
        definitions = []
        for tool in tools:
            if (not isinstance(tool, dict) or set(tool) - {"name", "label", "description", "parameters", "readsSkillUris"}
                    or not {"name", "label", "description", "parameters"} <= set(tool)
                    or not isinstance(tool["name"], str)
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", tool["name"])
                    or tool["name"] in names or not isinstance(tool["parameters"], dict)):
                raise ValueError("unique explicit host tool definitions required")
            names.add(tool["name"])
            definitions.append({**tool, "loadMode": "essential"})
        encoded = json.dumps(definitions, allow_nan=False)
        if len(encoded.encode()) > MAX_FRAME // 2:
            raise ValueError("bounded host tool catalog required")
        self.command, self.cwd = tuple(command), str(cwd)
        self.environment = MappingProxyType(dict(environment))
        self.binding, self.tools, self.execute = binding, json.loads(encoded), execute
        self.timeout, self._factory = timeout, process_factory
        self._own_process_group = bool(own_process_group)
        if skills_catalog is not None and not isinstance(skills_catalog, VerifiedSkillCatalog):
            raise ValueError("verified explicit skill catalog required")
        self.skills_catalog = skills_catalog
        self._names, self._process, self._buffer = names, None, bytearray()
        self._sequence, self._calls, self._ready = 0, set(), False

    def start(self):
        if self._process is not None:
            raise ScopedOMPError("runtime already started")
        self._process = self._factory(self.command, cwd=self.cwd, env=dict(self.environment),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=self._own_process_group)
        try:
            state = self._request("get_state")
            native = state.get("sessionId")
            if not isinstance(native, str) or not native or len(native) > 128:
                raise ScopedOMPError("native session identity unavailable")
            self.binding = replace(self.binding, native_session_id=native)
            self._check_state(state)
            result = self._request("set_host_tools", tools=self.tools)
            if result.get("toolNames") != [tool["name"] for tool in self.tools]:
                raise ScopedOMPError("host tool registration mismatch")
            if self.skills_catalog is not None:
                commands = self._request("get_available_commands").get("commands")
                discovered = sorted(command.get("name", "")[6:] for command in commands
                                    if isinstance(command, dict) and command.get("source") == "skill"
                                    and command.get("name", "").startswith("skill:")) if isinstance(commands, list) else []
                if tuple(discovered) != self.skills_catalog.names:
                    raise ScopedOMPError("native skill metadata parity failed")
            self._ready = True
        except Exception:
            self.close()
            raise ScopedOMPError("closed OMP startup failed") from None
        return self.binding

    def _send(self, frame):
        raw = (json.dumps(frame, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if len(raw) > MAX_FRAME or self._process is None or self._process.poll() is not None:
            raise ScopedOMPError("RPC transport unavailable")
        fd = self._process.stdin.fileno()
        os.set_blocking(fd, False)
        deadline = time.monotonic() + self.timeout
        offset = 0
        while offset < len(raw):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                raise ScopedOMPError("RPC write deadline exceeded")
            try:
                offset += os.write(fd, raw[offset:])
            except BlockingIOError:
                continue

    def _read(self, deadline):
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self._process.stdout], [], [], remaining)[0]:
                raise ScopedOMPError("RPC deadline exceeded")
            chunk = os.read(self._process.stdout.fileno(), 65536)
            if not chunk:
                raise ScopedOMPError("RPC disconnected")
            self._buffer.extend(chunk)
            if len(self._buffer) > MAX_FRAME and b"\n" not in self._buffer:
                raise ScopedOMPError("RPC frame bound exceeded")
        raw, _, tail = self._buffer.partition(b"\n")
        self._buffer = bytearray(tail)
        if len(raw) > MAX_FRAME:
            raise ScopedOMPError("RPC frame bound exceeded")
        try:
            frame = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
            if not isinstance(frame, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ScopedOMPError("invalid RPC frame") from None
        return frame

    def _host_call(self, frame):
        ident, tool = frame.get("id"), frame.get("toolName")
        call_id, arguments = frame.get("toolCallId"), frame.get("arguments")
        if (not self._ready or set(frame) != {"type", "id", "toolName", "toolCallId", "arguments"}
                or not isinstance(ident, str) or not 0 < len(ident) <= 128
                or ident in self._calls or len(self._calls) >= 4096
                or tool not in self._names or not isinstance(arguments, dict)
                or not isinstance(call_id, str) or not 0 < len(call_id) <= 256):
            raise ScopedOMPError("unbound host tool call")
        self._calls.add(ident)
        try:
            result = self.execute(self.binding, tool, arguments, call_id)
            if not isinstance(result, dict) or not isinstance(result.get("content"), list):
                raise ValueError()
            self._send({"type": "host_tool_result", "id": ident, "result": result})
        except Exception:
            self._send({"type": "host_tool_result", "id": ident, "isError": True,
                        "result": {"content": [{"type": "text", "text": "Quattro host operation denied."}]}})

    def _request(self, command, **arguments):
        self._sequence += 1
        ident = "quattro_" + str(self._sequence)
        self._send({"id": ident, "type": command, **arguments})
        deadline = time.monotonic() + self.timeout
        while True:
            frame = self._read(deadline)
            if frame.get("type") == "host_tool_call":
                self._host_call(frame)
            elif frame.get("type") == "response":
                if frame.get("id") != ident or frame.get("command") != command or frame.get("success") is not True:
                    raise ScopedOMPError("RPC response correlation failed")
                data = frame.get("data", {})
                if not isinstance(data, dict):
                    raise ScopedOMPError("invalid RPC response")
                return data

    def _check_state(self, state):
        model = state.get("model")
        if (not isinstance(model, dict) or (model.get("provider"), model.get("id"), state.get("thinkingLevel")) != PROFILE
                or state.get("sessionId") != self.binding.native_session_id):
            raise ScopedOMPError("fixed OMP profile binding changed")

    def prompt(self, text):
        known_skill = False
        if isinstance(text, str) and self.skills_catalog is not None:
            invocation = re.match(r"^/skill:([A-Za-z0-9][A-Za-z0-9_-]{0,127})(?:\s|$)", text.lstrip())
            known_skill = bool(invocation and invocation[1] in self.skills_catalog.names)
        if (not self._ready or not isinstance(text, str) or not text.strip() or "\0" in text
                or len(text.encode()) > MAX_FRAME // 2 or text.lstrip().startswith(("!", "^"))
                or text.lstrip().startswith("/") and not known_skill):
            raise ScopedOMPError("bounded plain prompt required")
        try:
            if self.skills_catalog is not None:
                self.skills_catalog.verify()
            self._check_state(self._request("get_state"))
            self._request("prompt", message=text)
            deadline = time.monotonic() + self.timeout
            answer = ""
            while True:
                frame = self._read(deadline)
                if frame.get("type") == "host_tool_call":
                    self._host_call(frame)
                elif frame.get("type") == "message_end":
                    message = frame.get("message")
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        answer = "".join(item.get("text", "") for item in message.get("content", [])
                                         if isinstance(item, dict) and item.get("type") == "text"
                                         and isinstance(item.get("text"), str))
                elif frame.get("type") == "prompt_result":
                    if frame.get("id") != "quattro_" + str(self._sequence):
                        raise ScopedOMPError("prompt correlation failed")
                    if frame.get("status") != "completed" or frame.get("sessionSettled") is not True:
                        raise ScopedOMPError("OMP turn did not settle")
                    self._check_state(self._request("get_state"))
                    return {"status": "completed", "session_id": self.binding.native_session_id, "text": answer}
        except Exception:
            self.close()
            raise ScopedOMPError("closed OMP turn failed") from None

    def close(self):
        self._ready = False
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            if self._own_process_group:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if self._own_process_group:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()
