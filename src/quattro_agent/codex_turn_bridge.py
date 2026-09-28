"""Native Codex app-server boundary: gate user turns before agent generation.

The frontend remains Codex's own TUI. This bridge uses its newline-delimited
JSON backend transport and WebSocket Unix frontend, not model HTTP transport.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import tempfile
import socket
import subprocess
import struct
import threading
import time
import uuid
from typing import Any, Mapping, Sequence

from .privacy import redact_secret_text

MAX_FRAME = 16 * 1024 * 1024

# Classify native app-server requests by capability, not by caller or prefix.
# The remote TUI and model turns share this connection, so unknown requests must
# fail closed rather than inherit authority from the Codex process.
CONTROL_PLANE_METHODS = frozenset({
    "initialize", "initialized", "server/diagnostics",
    "userVerification/status", "userVerification/enroll", "userVerification/delete",
    "userVerification/verify", "userVerification/cancel",
    "thread/start", "thread/resume", "thread/fork", "thread/archive",
    "thread/delete", "thread/unsubscribe", "thread/increment_elicitation",
    "thread/decrement_elicitation", "thread/name/set",
    "thread/goal/get", "thread/goal/clear", "thread/metadata/update",
    "thread/attachment/add", "thread/attachment/list", "thread/attachment/remove",
    "thread/section/move", "thread/unarchive", "thread/approveGuardianDeniedAction",
    "thread/revert", "thread/list",
    "threadSection/list", "threadSection/create", "threadSection/update",
    "threadSection/delete", "thread/loaded/list", "thread/read",
    "thread/turns/list", "thread/items/list", "thread/settings/update",
    "thread/queue/list", "thread/queue/delete", "thread/queue/reorder",
    "thread/memoryMode/set", "memory/status", "memory/reset",
    "thread/backgroundTerminals/list", "thread/search", "thread/searchOccurrences",
    "thread/timeline/list", "thread/realtime/listVoices",
    "project/list", "project/read", "project/create", "project/import",
    "project/update", "project/move", "project/delete",
    "skills/list", "skills/extraRoots/set", "skills/config/write", "hooks/list",
    "marketplace/add", "marketplace/remove", "marketplace/upgrade",
    "plugin/list", "plugin/search", "plugin/installed", "plugin/reconcile", "plugin/read",
    "plugin/skill/read", "plugin/install", "plugin/uninstall",
    "plugin/share/save", "plugin/share/updateTargets", "plugin/share/list",
    "plugin/share/checkout", "plugin/share/delete",
    "app/read", "app/list", "app/installed", "model/list", "collaborationMode/list",
    "modelProvider/capabilities/read", "experimentalFeature/list",
    "experimentalFeature/enablement/set", "permissionProfile/list",
    "mcpServer/oauth/login", "config/mcpServer/reload", "mcpServerStatus/list",
    "mcpServer/resource/read", "mcpServer/event/stream/start",
    "mcpServer/event/stream/stop",
    "account/gatewayOAuth/read", "account/gatewayOAuth/login",
    "account/gatewayOAuth/cancel", "account/login/start", "account/login/cancel",
    "account/logout", "account/bedrock/discover", "account/bedrock/setup",
    "account/rateLimits/read", "account/rateLimitResetCredit/consume", "account/usage/read",
    "account/workspaceMessages/read", "account/sendAddCreditsNudgeEmail",
    "account/read", "config/read", "config/value/write", "config/batchWrite",
    "configRequirements/read", "externalAgentConfig/detect",
    "externalAgentConfig/import", "externalAgentConfig/import/recordHistory",
    "externalAgentConfig/import/readHistories", "feedback/upload",
    "windowsSandbox/setupStart", "windowsSandbox/readiness", "fuzzyFileSearch",
    "fuzzyFileSearch/sessionStart", "fuzzyFileSearch/sessionUpdate",
    "fuzzyFileSearch/sessionStop", "getConversationSummary", "gitDiffToRemote",
    "getAuthStatus", "environment/info", "environment/status",
    "fs/readFile", "fs/getMetadata", "fs/readDirectory", "fs/watch", "fs/unwatch",
})

# These methods execute a model, tool, or host command outside the normal user
# turn boundary. `turn/settings/update` can mutate a running turn's target and
# therefore remains execution-plane even though its name resembles settings.
EXECUTION_PLANE_METHODS = frozenset({
    "thread/queue/start", "thread/queue/add", "thread/queue/update",
    "thread/goal/set", "thread/compact/start", "review/start", "userInput",
    "userInputWithAttachments", "sendUserMessage", "sendUserTurn",
    "execOneOffCommand", "thread/shellCommand", "thread/realtime/start",
    "thread/realtime/appendAudio", "thread/realtime/appendText",
    "thread/realtime/appendSpeech", "turn/settings/update", "command/exec",
    "command/exec/write", "command/exec/terminate", "command/exec/resize",
    "process/spawn", "process/writeStdin", "process/kill", "process/resizePty",
    "mcpServer/tool/call", "thread/inject_items", "rollout/compress",
    "thread/backgroundTerminals/clean", "thread/backgroundTerminals/terminate",
    "thread/realtime/stop", "environment/add", "fs/writeFile", "fs/createDirectory",
    "fs/remove", "fs/copy", "remoteControl/enable", "remoteControl/disable",
    "remoteControl/status/read", "remoteControl/pairing/start",
    "remoteControl/pairing/status", "remoteControl/client/list",
    "remoteControl/client/revoke", "mock/experimentalMethod",
})


class _WebSocket:
    """RFC 6455 server framing used by Codex's Unix remote endpoint."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.write_lock = threading.Lock()
        headers = bytearray()
        while not headers.endswith(b"\r\n\r\n"):
            byte = stream.read(1)
            if not byte or len(headers) >= 16384:
                raise ValueError("invalid websocket handshake")
            headers.extend(byte)
        lines = headers.decode("ascii").split("\r\n")
        fields = dict(line.lower().split(":", 1) for line in lines[1:] if ":" in line)
        # Preserve the case-sensitive base64 key, unlike HTTP header names.
        key = next((line.split(":", 1)[1].strip() for line in lines[1:]
                    if line.lower().startswith("sec-websocket-key:")), "")
        if (lines[0] != "GET /rpc HTTP/1.1" or fields.get("upgrade", "").strip() != "websocket"
                or fields.get("sec-websocket-version", "").strip() != "13"
                or len(base64.b64decode(key, validate=True)) != 16):
            raise ValueError("unsupported websocket handshake")
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        stream.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                     b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        stream.flush()

    def _exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self.stream.read(size - len(data))
            if not chunk:
                raise OSError("websocket disconnected")
            data.extend(chunk)
        return bytes(data)

    def _frame(self, opcode: int, data: bytes) -> None:
        length = len(data)
        header = bytes([0x80 | opcode])
        header += (bytes([length]) if length < 126 else
                   b"\x7e" + struct.pack("!H", length) if length <= 65535 else
                   b"\x7f" + struct.pack("!Q", length))
        with self.write_lock:
            self.stream.write(header + data)
            self.stream.flush()

    def readline(self, limit: int) -> bytes:
        message = bytearray()
        fragmented = False
        while True:
            first, second = self._exact(2)
            opcode, final = first & 15, bool(first & 128)
            if first & 112 or not second & 128:
                raise ValueError("invalid client websocket frame")
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self._exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._exact(8))[0]
            if size > limit or len(message) + size > limit:
                raise ValueError("websocket message exceeds limit")
            if opcode >= 8 and (not final or size > 125):
                raise ValueError("invalid websocket control frame")
            mask = self._exact(4)
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(self._exact(size)))
            if opcode == 8:
                return b""
            if opcode == 9:
                self._frame(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 1 and not fragmented:
                fragmented = not final
            elif opcode != 0 or not fragmented:
                raise ValueError("unsupported websocket data frame")
            message.extend(payload)
            if final:
                return bytes(message) + b"\n"

    def write(self, data: bytes) -> None:
        self._frame(1, data.rstrip(b"\n"))

    def flush(self) -> None:
        self.stream.flush()

    def close(self) -> None:
        self.stream.close()


class CodexTurnBridge:
    """One native frontend connection and its private native backend process."""

    def __init__(self, socket_path: Path, backend_command: Sequence[str],
                 backend_env: Mapping[str, str], gate: Any, history_root: Path | None = None) -> None:
        self.socket_path = Path(socket_path)
        self.backend_command = list(backend_command)
        self.backend_env = dict(backend_env)
        self.gate = gate
        self.history_root = Path(history_root) if history_root is not None else None
        self._views: dict[Any, tuple[str, dict[str, Any]]] = {}
        self._history_lock = threading.Lock()
        self._page_seen: dict[tuple[str, str, str], set[str]] = {}
        self.ready = threading.Event()
        self.closed = threading.Event()
        self._front_lock = threading.Lock()
        self._back_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._active: dict[str, dict[str, Any]] = {}
        self._internal: dict[str, queue.Queue[Any]] = {}
        self._delegate_requests: dict[Any, str] = {}
        self._frontend_requests: set[Any] = set()
        # method, requested thread, generation, same-thread resume rollback.
        # A rollback is identity only; turns remain blocked while the request is pending.
        self._lifecycle_requests: dict[Any, tuple[str, str | None, int, str | None]] = {}
        self._lifecycle_generation = 0
        self._current_thread_id: str | None = None
        self._front: Any = None
        self._backend: Any = None
        self._connection: socket.socket | None = None

    def _history_path(self, thread_id: str) -> Path | None:
        if self.history_root is None:
            return None
        # Native Codex thread IDs are UUIDs; never use frontend paths as filenames.
        try:
            canonical = str(uuid.UUID(thread_id))
        except (ValueError, TypeError, AttributeError):
            return None
        root = self.history_root
        if root.is_symlink() or any(part.is_symlink() for part in root.parents):
            raise ValueError("history directory must not be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        return root / (canonical + ".json")

    def _history(self, thread_id: str) -> list[dict[str, Any]]:
        path = self._history_path(thread_id)
        if path is None or not path.exists():
            return []
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            raw = source.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("history exceeds bound")
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("invalid direct history")
        for row in rows:
            if (not isinstance(row, dict) or row.get("status") != "completed"
                    or not isinstance(row.get("id"), str)
                    or not isinstance(row.get("startedAt"), (int, float))
                    or not isinstance(row.get("items"), list) or len(row["items"]) != 2):
                raise ValueError("invalid direct history turn")
            uuid.UUID(row["id"])
            user, answer = row["items"]
            if (user.get("type") != "userMessage" or answer.get("type") != "agentMessage"
                    or not isinstance(answer.get("text"), str)
                    or not isinstance(user.get("content"), list)):
                raise ValueError("invalid direct history items")
        return rows

    def _save_history(self, thread_id: str, wire_turn: dict[str, Any], prompt: str) -> None:
        path = self._history_path(thread_id)
        if path is None:
            return
        row = copy.deepcopy(wire_turn)
        row["items"].insert(0, {"type": "userMessage", "id": uuid.uuid4().hex,
                               "content": [{"type": "text", "text": prompt, "text_elements": []}]})
        with self._history_lock:
            rows = self._history(thread_id)
            rows.append(row)
            rows = rows[-100:]
            while rows and len(json.dumps(rows).encode()) > 1_048_576:
                rows.pop(0)
            fd, name = tempfile.mkstemp(prefix=".direct-", dir=path.parent)
            try:
                with os.fdopen(fd, "w") as output:
                    json.dump(rows, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(name, 0o600)
                os.replace(name, path)
            finally:
                Path(name).unlink(missing_ok=True)

    def _merge_history(self, method: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        thread_id = params.get("threadId") or result.get("thread", {}).get("id")
        rows = self._history(thread_id)
        page_kind = method + ":" + str(params.get("sortDirection") or ("desc" if method == "thread/turns/list" else "asc")) + ":" + str(params.get("turnId") or "")
        if not rows:
            return
        def merge(native: list[dict[str, Any]], direct: list[dict[str, Any]], descending=False):
            ids = {row.get("id") for row in native}
            return sorted(native + [row for row in direct if row["id"] not in ids],
                          key=lambda row: (row.get("startedAt") or 0, row["id"]), reverse=descending)
        if method in {"thread/read", "thread/resume"}:
            thread = result.get("thread")
            if isinstance(thread, dict):
                thread["turns"] = merge(thread.get("turns", []), rows)
            page = result.get("initialTurnsPage")
            if isinstance(page, dict):
                page["data"] = merge(page.get("data", []), rows, True)
        elif method == "thread/turns/list":
            native = result.get("data", [])
            descending = params.get("sortDirection", "desc") == "desc"
            seen_key = (page_kind, thread_id, str(params.get("cursor") or ""))
            seen = self._page_seen.get(seen_key, set())
            candidates = [row for row in rows if row["id"] not in seen]
            timestamps = [row.get("startedAt") for row in native if row.get("startedAt") is not None]
            if result.get("nextCursor") and timestamps:
                boundary = min(timestamps) if descending else max(timestamps)
                candidates = [row for row in candidates if
                              (row["startedAt"] >= boundary if descending else row["startedAt"] <= boundary)]
            result["data"] = merge(native, candidates, descending)
            if result.get("nextCursor"):
                if len(self._page_seen) >= 200:
                    self._page_seen.clear()
                self._page_seen[(page_kind, thread_id, result["nextCursor"])] = seen | {row["id"] for row in candidates}
        elif method == "thread/items/list":
            entries = [{"turnId": row["id"], "item": item,
                        "startedAtMs": int(row["startedAt"] * 1000),
                        "completedAtMs": int(row["completedAt"] * 1000)}
                       for row in rows if not params.get("turnId") or params["turnId"] == row["id"]
                       for item in row["items"]]
            native = result.get("data", [])
            seen_key = (page_kind, thread_id, str(params.get("cursor") or ""))
            seen = self._page_seen.get(seen_key, set())
            entries = [entry for entry in entries if entry["item"]["id"] not in seen]
            descending = params.get("sortDirection", "asc") == "desc"
            timestamps = [entry.get("startedAtMs") for entry in native if entry.get("startedAtMs") is not None]
            if result.get("nextCursor") and timestamps:
                boundary = min(timestamps) if descending else max(timestamps)
                entries = [entry for entry in entries if
                           (entry["startedAtMs"] >= boundary if descending else entry["startedAtMs"] <= boundary)]
            if result.get("nextCursor"):
                if len(self._page_seen) >= 200:
                    self._page_seen.clear()
                self._page_seen[(page_kind, thread_id, result["nextCursor"])] = seen | {entry["item"]["id"] for entry in entries}
            ids = {entry.get("item", {}).get("id") for entry in native}
            result["data"] = sorted(native + [entry for entry in entries if entry["item"]["id"] not in ids],
                                    key=lambda entry: entry.get("startedAtMs") or 0,
                                    reverse=params.get("sortDirection", "asc") == "desc")

    @staticmethod
    def _read(stream: Any) -> dict[str, Any] | None:
        raw = stream.readline(MAX_FRAME + 1)
        if not raw:
            return None
        if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
            raise ValueError("invalid app-server frame")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid app-server message")
        return value

    @staticmethod
    def _write(stream: Any, lock: Any, value: dict[str, Any]) -> None:
        raw = json.dumps(value, separators=(",", ":")).encode() + b"\n"
        if len(raw) > MAX_FRAME:
            raise ValueError("app-server frame exceeds limit")
        with lock:
            stream.write(raw)
            stream.flush()

    def _send(self, value: dict[str, Any]) -> None:
        if not self.closed.is_set():
            self._write(self._front, self._front_lock, value)

    def _forward(self, value: dict[str, Any]) -> None:
        self._write(self._backend.stdin, self._back_lock, value)

    def _error(self, request_id: Any, message: str) -> None:
        self._send({"id": request_id, "error": {"code": -32000, "message": message}})

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _rpc(self, method: str, params: dict[str, Any], timeout: float = 5) -> Any:
        request_id = "quattro-internal-" + uuid.uuid4().hex
        result: queue.Queue[Any] = queue.Queue(maxsize=1)
        with self._state_lock:
            self._internal[request_id] = result
        try:
            self._forward({"id": request_id, "method": method, "params": params})
            answer = result.get(timeout=timeout)
            if "error" in answer:
                raise RuntimeError("native history update failed")
            return answer.get("result")
        finally:
            with self._state_lock:
                self._internal.pop(request_id, None)

    def _finish(self, thread_id: str, state: dict[str, Any], status: str) -> None:
        with self._state_lock:
            if state.get("finished"):
                return
            state["finished"] = True
            if self._active.get(thread_id) is state:
                self._active.pop(thread_id, None)
        if state.get("turn") is not None:
            self.gate.finish(state["turn"], status=status,
                             tools_used=state.get("tools_used", False),
                             agent_lifecycle=state.get("delegated", False))

    @staticmethod
    def _canonical_thread_id(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            return None

    def _bind_lifecycle_response(self, request_id: Any, message: dict[str, Any]) -> None:
        """Bind only an identity returned by a successful native lifecycle RPC."""
        with self._state_lock:
            lifecycle = self._lifecycle_requests.pop(request_id, None)
        if lifecycle is None:
            return
        method, requested, generation, rollback = lifecycle
        if "error" in message:
            with self._state_lock:
                if generation == self._lifecycle_generation and rollback is not None:
                    self._current_thread_id = rollback
            return
        result = message.get("result")
        thread = result.get("thread") if isinstance(result, dict) else None
        canonical = self._canonical_thread_id(thread.get("id") if isinstance(thread, dict) else None)
        if canonical is None:
            return
        requested_canonical = self._canonical_thread_id(requested)
        if method == "thread/resume" and requested_canonical != canonical:
            return
        with self._state_lock:
            if generation != self._lifecycle_generation:
                return
            self._current_thread_id = canonical

    @staticmethod
    def _user_turn_input(items: Any) -> tuple[str, bool]:
        """Validate the bounded Codex 0.158 user-input union without rewriting it."""
        if not isinstance(items, list) or not items or len(items) > 64:
            raise ValueError("Quattro requires a non-empty bounded user input")
        text, native = [], False
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Quattro received malformed native user input")
            kind = item.get("type")
            if kind == "text":
                value = item.get("text")
                if not isinstance(value, str) or "\x00" in value:
                    raise ValueError("Quattro received malformed native text input")
                elements = item.get("text_elements", [])
                if not isinstance(elements, list) or len(elements) > 64:
                    raise ValueError("Quattro received malformed native text elements")
                byte_length = len(value.encode("utf-8"))
                for element in elements:
                    byte_range = element.get("byteRange") if isinstance(element, dict) else None
                    start = byte_range.get("start") if isinstance(byte_range, dict) else None
                    end = byte_range.get("end") if isinstance(byte_range, dict) else None
                    placeholder = element.get("placeholder") if isinstance(element, dict) else None
                    if (not isinstance(start, int) or isinstance(start, bool)
                            or not isinstance(end, int) or isinstance(end, bool)
                            or start < 0 or start > end or end > byte_length
                            or (placeholder is not None and (
                                not isinstance(placeholder, str) or len(placeholder) > 512
                                or "\x00" in placeholder))):
                        raise ValueError("Quattro received malformed native text elements")
                text.append(value)
                continue
            native = True
            if kind == "image":
                url, file_id = item.get("url"), item.get("fileId")
                valid_url = isinstance(url, str) and 0 < len(url) <= 16_384 and "\x00" not in url
                valid_file = (isinstance(file_id, str) and 0 < len(file_id) <= 1_024
                              and "\x00" not in file_id)
                if (not (valid_url or valid_file)
                        or url is not None and not valid_url
                        or file_id is not None and not valid_file
                        or item.get("detail", "auto") not in {None, "auto", "low", "high", "original"}):
                    raise ValueError("Quattro received malformed native image input")
            elif kind == "localImage":
                path = item.get("path")
                if (not isinstance(path, str) or not path or len(path) > 4_096 or "\x00" in path
                        or item.get("detail", "auto") not in {None, "auto", "low", "high", "original"}):
                    raise ValueError("Quattro received malformed native image input")
            elif kind in {"skill", "mention"}:
                name, path = item.get("name"), item.get("path")
                if (not isinstance(name, str) or not name or len(name) > 512 or "\x00" in name
                        or not isinstance(path, str) or not path or len(path) > 4_096
                        or "\x00" in path):
                    raise ValueError("Quattro received malformed native context input")
            elif kind in {"audio", "localAudio"}:
                raise ValueError("Quattro does not yet support native audio turns")
            else:
                raise ValueError("Quattro received an unsupported native user input type")
        prompt = "\n".join(text)
        if not prompt.strip() or len(prompt) > 64_000:
            raise ValueError("Quattro requires bounded text with native user input")
        return prompt, native

    def _backend_reader(self) -> None:
        try:
            while not self.closed.is_set():
                message = self._read(self._backend.stdout)
                if message is None:
                    break
                request_id = message.get("id")
                if "method" not in message:
                    self._bind_lifecycle_response(request_id, message)
                with self._state_lock:
                    if "method" not in message:
                        self._frontend_requests.discard(request_id)
                    internal = self._internal.get(request_id)
                    owner = self._delegate_requests.pop(request_id, None) if "method" not in message else None
                with self._state_lock:
                    view = self._views.pop(request_id, None) if "method" not in message else None
                if view and isinstance(message.get("result"), dict):
                    self._merge_history(view[0], view[1], message["result"])
                    if hasattr(self.gate, "hydrate"):
                        result = message["result"]
                        native_thread = result.get("thread", {})
                        history_thread = view[1].get("threadId") or native_thread.get("id")
                        turns = native_thread.get("turns", [])
                        if view[0] == "thread/resume" and isinstance(result.get("initialTurnsPage"), dict):
                            combined = turns + result["initialTurnsPage"].get("data", [])
                            turns = list({row["id"]: row for row in combined}.values())
                        if view[0] == "thread/turns/list":
                            turns = (result.get("data", []) if not view[1].get("cursor")
                                     and view[1].get("sortDirection", "desc") == "desc" else [])
                        if history_thread and turns:
                            self.gate.hydrate(history_thread, sorted(turns, key=lambda row: row.get("startedAt") or 0))
                if internal is not None and "method" not in message:
                    internal.put(message)
                    continue
                params = message.get("params") or {}
                thread_id = params.get("threadId")
                with self._state_lock:
                    state = self._active.get(thread_id)
                    failed_state = self._active.get(owner) if owner else None
                if failed_state and "error" in message:
                    self._finish(owner, failed_state, "failed")
                if state and state.get("delegated"):
                    item = params.get("item", {})
                    if message.get("method") == "item/started" and item.get("type") in {
                        "commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch",
                    }:
                        state["tools_used"] = True
                    if (message.get("method") in {"item/started", "item/completed"}
                            and item.get("type") in {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch"}
                            and hasattr(self.gate, "observe_runtime")):
                        self.gate.observe_runtime(state["turn"])
                    if (message.get("method") == "item/completed" and item.get("type") == "agentMessage"
                            and item.get("phase") in {None, "final_answer"} and hasattr(self.gate, "remember")):
                        self.gate.remember(thread_id, state.get("prompt", ""), item.get("text", ""))
                    if message.get("method") == "turn/completed":
                        self._finish(thread_id, state, params.get("turn", {}).get("status", "completed"))
                self._send(message)
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            self.closed.set()
            if self._connection is not None:
                try:
                    self._connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _direct(self, request: dict[str, Any], thread_id: str, state: dict[str, Any]) -> None:
        turn = state["turn"]
        turn_id = str(turn.turn_id)
        wire_turn = {"id": turn_id, "status": "inProgress", "items": [], "error": None,
                     "startedAt": int(time.time()), "completedAt": None}
        with self._state_lock:
            self._frontend_requests.discard(request["id"])
        self._send({"id": request["id"], "result": {"turn": wire_turn}})
        state["accepted"] = True
        self._notify("turn/started", {"threadId": thread_id, "turn": wire_turn})
        answer = self.gate.direct(turn)
        if state["cancelled"].is_set():
            wire_turn["status"] = "interrupted"
        else:
            # Native history persistence is deliberately excluded for sensitive turns.
            safe_to_persist = not turn.sensitive and not redact_secret_text(answer)[1]
            if safe_to_persist:
                remaining = self.gate.remaining(turn) if hasattr(self.gate, "remaining") else 5
                if remaining <= 0:
                    raise TimeoutError("direct turn budget exhausted")
                self._rpc("thread/inject_items", {"threadId": thread_id, "items": [
                    {"type": "message", "role": "user", "content": [
                        {"type": "input_text", "text": state["prompt"]}]},
                    {"type": "message", "role": "assistant", "content": [
                        {"type": "output_text", "text": answer}]},
                ]}, timeout=min(5, remaining))
            if hasattr(self.gate, "remaining"):
                self.gate.remaining(turn)
            if state["cancelled"].is_set():
                wire_turn["status"] = "interrupted"
            else:
                item = {"type": "agentMessage", "id": uuid.uuid4().hex,
                        "text": "", "phase": "final_answer"}
                common = {"threadId": thread_id, "turnId": turn_id}
                self._notify("item/started", dict(common, item=item, startedAtMs=int(time.time() * 1000)))
                self._notify("item/agentMessage/delta", dict(common, itemId=item["id"], delta=answer))
                item["text"] = answer
                self._notify("item/completed", dict(common, item=item, completedAtMs=int(time.time() * 1000)))
                wire_turn.update(status="completed", items=[item], completedAt=int(time.time()))
                if safe_to_persist:
                    self._save_history(thread_id, wire_turn, state["prompt"])
        self._notify("turn/completed", {"threadId": thread_id, "turn": wire_turn})
        self._finish(thread_id, state, wire_turn["status"])

    def _start(self, request: dict[str, Any], thread_id: str, state: dict[str, Any]) -> None:
        try:
            params = request["params"]
            prompt = state["prompt"]
            state["prompt"] = prompt
            turn = self.gate.begin(
                thread_id, prompt, "codex", params=params,
                requires_native_delegate=state["requires_native_delegate"],
            )
            state["turn"] = turn
            if state["cancelled"].is_set():
                with self._state_lock:
                    self._frontend_requests.discard(request["id"])
                self._error(request["id"], "Quattro turn cancelled before agent execution")
                self._finish(thread_id, state, "interrupted")
                return
            if str(turn.decision) == "DIRECT":
                self._direct(request, thread_id, state)
                return
            if str(turn.decision) != "DELEGATE":
                raise ValueError("unsupported Quattro decision")
            outgoing = copy.deepcopy(request)
            locked = outgoing["params"]
            locked["model"] = turn.plan.target.route
            locked["effort"] = turn.plan.reasoning_effort
            metadata = locked.setdefault("responsesapiClientMetadata", {}) or {}
            metadata["quattro_plan_id"] = turn.plan.plan_id
            locked["responsesapiClientMetadata"] = metadata
            mode = locked.get("collaborationMode")
            if isinstance(mode, dict):
                settings = mode.setdefault("settings", {})
                settings["model"] = turn.plan.target.route
                settings["reasoning_effort"] = turn.plan.reasoning_effort
            with self._state_lock:
                if state["cancelled"].is_set():
                    self._frontend_requests.discard(request["id"])
                    self._error(request["id"], "Quattro turn cancelled before agent execution")
                    self._finish(thread_id, state, "interrupted")
                    return
                state["delegated"] = True
                self._delegate_requests[request["id"]] = thread_id
                self._forward(outgoing)
        except Exception:
            # User interruption closes the real provider connection and may
            # raise while direct() is blocked. Preserve interruption semantics;
            # unrelated provider/budget failures remain failures.
            status = "interrupted" if state["cancelled"].is_set() else "failed"
            if state.get("accepted"):
                self._notify("turn/completed", {"threadId": thread_id, "turn": {
                    "id": str(state["turn"].turn_id), "status": status, "items": [],
                    "error": None if status == "interrupted" else {
                        "message": "Quattro direct turn failed", "codexErrorInfo": None,
                        "additionalDetails": None}}})
            else:
                with self._state_lock:
                    self._frontend_requests.discard(request["id"])
                    self._delegate_requests.pop(request["id"], None)
                self._error(request["id"], "Quattro could not authorize or execute this turn")
            self._finish(thread_id, state, status)

    def handle(self, request: dict[str, Any]) -> None:
        method = request.get("method")
        params = request.get("params") or {}
        thread_id = params.get("threadId")
        # Approval and user-input answers are JSON-RPC response frames rather
        # than method calls. They complete backend-originated native requests
        # and cannot initiate execution by themselves.
        if method is None and "id" in request and ("result" in request or "error" in request):
            self._forward(request)
            return
        lifecycle_admitted = False
        if method in {"thread/start", "thread/resume", "thread/fork"}:
            request = copy.deepcopy(request)
            params = request["params"]
            for key in ("config", "modelProvider", "model_provider"):
                params.pop(key, None)
            with self._state_lock:
                lifecycle_id = request.get("id")
                if lifecycle_id is None or lifecycle_id in self._lifecycle_requests:
                    # Invalidate any pending rollback carried by a colliding ID.
                    self._lifecycle_generation += 1
                    self._current_thread_id = None
                    self._error(lifecycle_id, "Native Codex lifecycle request ID is missing or already pending")
                    return
                if (lifecycle_id in self._views or lifecycle_id in self._delegate_requests
                        or lifecycle_id in self._internal or lifecycle_id in self._frontend_requests):
                    self._error(lifecycle_id, "Native Codex request ID is already pending")
                    return
                if self._active:
                    self._error(lifecycle_id, "Native Codex lifecycle changes require the active turn to finish")
                    return
                self._lifecycle_generation += 1
                requested_canonical = self._canonical_thread_id(params.get("threadId"))
                rollback = None
                if (method == "thread/resume"
                        and requested_canonical == self._current_thread_id
                        and not params.get("history") and not params.get("path")):
                    rollback = self._current_thread_id
                # Block turns until lifecycle settlement. A failed unambiguous
                # same-thread refresh may restore only its own prior binding.
                self._current_thread_id = None
                self._lifecycle_requests[lifecycle_id] = (
                    method, params.get("threadId"), self._lifecycle_generation, rollback,
                )
                lifecycle_admitted = True
        if method in {"thread/read", "thread/resume", "thread/turns/list", "thread/items/list"}:
            view_id = request.get("id")
            with self._state_lock:
                if (not lifecycle_admitted and (view_id is None
                        or view_id in self._lifecycle_requests or view_id in self._views
                        or view_id in self._delegate_requests or view_id in self._internal
                        or view_id in self._frontend_requests)):
                    self._error(view_id, "Native Codex request ID is missing or already pending")
                    return
                self._views[view_id] = (method, copy.deepcopy(params))
            if method == "thread/items/list" and params.get("turnId"):
                rows = self._history(thread_id)
                if any(row["id"] == params["turnId"] for row in rows):
                    result = {"data": [], "nextCursor": None, "backwardsCursor": None}
                    self._merge_history(method, params, result)
                    with self._state_lock:
                        self._views.pop(view_id, None)
                    self._send({"id": view_id, "result": result})
                    return
        if method in EXECUTION_PLANE_METHODS:
            self._error(request.get("id"), "This native operation requires a Quattro execution plan; submit a normal turn")
            return
        if method == "turn/steer":
            self._error(request.get("id"), "Quattro requires a fresh plan; submit after the active turn completes")
            return
        if method == "turn/start":
            supplied_thread_id = self._canonical_thread_id(thread_id)
            with self._state_lock:
                bound_thread_id = self._current_thread_id
            if supplied_thread_id is None and (not isinstance(thread_id, str) or not thread_id):
                supplied_thread_id = bound_thread_id
            if supplied_thread_id is not None and supplied_thread_id == bound_thread_id:
                thread_id = supplied_thread_id
                request = copy.deepcopy(request)
                params = request["params"]
                params["threadId"] = thread_id
            else:
                thread_id = None
            if not isinstance(thread_id, str) or not thread_id:
                self._error(request.get("id"), "Quattro has no matching canonical thread binding")
                return
            if params.get("toolOutput") is not None:
                self._error(request.get("id"), "Quattro does not authorize tool-output turns without a fresh plan")
                return
            try:
                prompt, requires_native_delegate = self._user_turn_input(params.get("input"))
            except ValueError as error:
                self._error(request.get("id"), str(error))
                return
            with self._state_lock:
                turn_request_id = request.get("id")
                if (turn_request_id is None or turn_request_id in self._frontend_requests
                        or turn_request_id in self._lifecycle_requests
                        or turn_request_id in self._views or turn_request_id in self._delegate_requests
                        or turn_request_id in self._internal):
                    self._error(turn_request_id, "Native Codex request ID is missing or already pending")
                    return
                if thread_id in self._active:
                    self._error(request.get("id"), "Wait for the current Quattro turn before submitting another")
                    return
                state: dict[str, Any] = {
                    "cancelled": threading.Event(), "prompt": prompt,
                    "requires_native_delegate": requires_native_delegate,
                }
                self._active[thread_id] = state
                self._frontend_requests.add(turn_request_id)
            threading.Thread(target=self._start, args=(request, thread_id, state), daemon=True).start()
            return
        if method == "turn/interrupt":
            with self._state_lock:
                state = self._active.get(thread_id)
                if state:
                    state["cancelled"].set()
                    turn = state.get("turn")
                    if turn is not None and hasattr(self.gate, "cancel"):
                        self.gate.cancel(turn)
                    if not state.get("delegated"):
                        self._send({"id": request.get("id"), "result": {}})
                        return
            self._forward(request)
            return
        if method in CONTROL_PLANE_METHODS:
            self._forward(request)
            return
        self._error(request.get("id"), "Unsupported native Codex protocol operation")

    def stop(self) -> None:
        """Wake an idle listener/frontend so launcher failures cannot orphan backend."""
        self.closed.set()
        if self._connection is not None:
            try:
                self._connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def run(self) -> None:
        """Block until the native frontend disconnects; never reuse an existing socket."""
        self._connection: socket.socket | None = None
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound = False
        try:
            listener.bind(str(self.socket_path))
            bound = True
            os.chmod(self.socket_path, 0o600)
            listener.listen(1)
            self._backend = subprocess.Popen(self.backend_command, env=self.backend_env,
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL)
            self.ready.set()
            listener.settimeout(0.2)
            while not self.closed.is_set():
                try:
                    self._connection, _ = listener.accept()
                    break
                except socket.timeout:
                    if self._backend.poll() is not None:
                        raise RuntimeError("native backend exited before frontend connected")
            if self._connection is None:
                return
            self._connection.settimeout(10)
            self._front = _WebSocket(self._connection.makefile("rwb", buffering=0))
            self._connection.settimeout(None)
            threading.Thread(target=self._backend_reader, daemon=True).start()
            while not self.closed.is_set():
                try:
                    message = self._read(self._front)
                except OSError:
                    break
                if message is None:
                    break
                self.handle(message)
        finally:
            self.closed.set()
            with self._state_lock:
                active = list(self._active.items())
            for thread_id, state in active:
                state["cancelled"].set()
                if state.get("turn") is not None and hasattr(self.gate, "cancel"):
                    self.gate.cancel(state["turn"])
                self._finish(thread_id, state, "interrupted")
            if self._backend is not None:
                self._backend.terminate()
                try:
                    self._backend.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._backend.kill()
                    self._backend.wait(timeout=5)
                self._backend.stdin.close()
                self._backend.stdout.close()
            if self._front is not None:
                self._front.close()
            if self._connection is not None:
                self._connection.close()
            listener.close()
            if bound:
                self.socket_path.unlink(missing_ok=True)
