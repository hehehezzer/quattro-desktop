"""Bounded Unix socket integration for Herdr-owned Quattro terminals.

Herdr owns PTYs, Quattro owns routing, and native harnesses own approvals.
No shell input, model prompt, transcript, or credential is handled here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import time
from dataclasses import dataclass
from uuid import uuid4


class HerdrError(RuntimeError):
    """A display-safe runtime or protocol failure; mutations are never retried."""


@dataclass(frozen=True)
class HerdrSession:
    workspace_id: str
    pane_id: str


_ALLOWED_ENV = frozenset({
    "HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "COLORTERM",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
    "XDG_RUNTIME_DIR", "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
    "HERDR_SOCKET_PATH", "HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID",
    "HERDR_PANE_ID", "HERDR_BIN_PATH", "TERM_PROGRAM", "TERM_PROGRAM_VERSION",
    "QUATTRO_CONFIG", "QUATTRO_STATE_DIR", "QUATTRO_DATA_DIR",
    "QUATTRO_CODEX_HOME_ROOT", "QUATTRO_MODEL_CATALOG", "QUATTRO_WORKSPACE",
    "QUATTRO_OMNIROUTE_BASE_URL",
})


def sanitized_terminal_environment() -> dict[str, str]:
    """Retain explicit desktop/native-store paths, never API keys or hook injection."""
    result = {key: value for key, value in os.environ.items() if key in _ALLOWED_ENV}
    result["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    return result


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", value):
        raise HerdrError("invalid Herdr identifier")
    return value


class HerdrRuntime:
    """Explicit-session client, with ownership-scoped cleanup and bounded I/O."""

    def __init__(self, socket_path: Path, *, timeout: float = 5.0,
                 max_bytes: int = 1024 * 1024):
        self.socket_path = Path(socket_path)
        if not self.socket_path.is_absolute():
            raise ValueError("Herdr socket path must be absolute")
        if not 0 < timeout <= 30 or not 1024 <= max_bytes <= 4 * 1024 * 1024:
            raise ValueError("invalid Herdr I/O bounds")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._owned: set[str] = set()

    def _request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        """Send once; an uncertain mutation must be inspected before retrying."""
        try:
            info = self.socket_path.stat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise HerdrError("Herdr socket is not an owned Unix socket")
            if info.st_mode & 0o077:
                raise HerdrError("Herdr socket permissions must be private")
            request_id = uuid4().hex
            wire = json.dumps({"id": request_id, "method": method, "params": params},
                              separators=(",", ":")).encode() + b"\n"
            if len(wire) > self.max_bytes:
                raise HerdrError("Herdr request exceeds size limit")
            deadline = time.monotonic() + self.timeout
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(str(self.socket_path))
                connection.sendall(wire)
                data = bytearray()
                while b"\n" not in data:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise HerdrError("Herdr request timed out; outcome may be uncertain")
                    connection.settimeout(remaining)
                    chunk = connection.recv(min(65536, self.max_bytes + 1 - len(data)))
                    if not chunk:
                        raise HerdrError("Herdr connection closed; outcome may be uncertain")
                    data.extend(chunk)
                    if len(data) > self.max_bytes:
                        raise HerdrError("Herdr response exceeds size limit")
            response = json.loads(data.split(b"\n", 1)[0])
            if not isinstance(response, dict) or response.get("id") != request_id:
                raise HerdrError("Herdr response identity mismatch")
            if "error" in response:
                error = response["error"]
                code = error.get("code") if isinstance(error, dict) else None
                safe = code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,64}", code) else "unknown"
                raise HerdrError(f"Herdr rejected operation: {safe}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise HerdrError("invalid Herdr result")
            return result
        except (OSError, ValueError, UnicodeError) as exc:
            raise HerdrError("Herdr unavailable or invalid response; outcome may be uncertain") from exc

    def ping(self) -> bool:
        return self._request("ping", {}).get("type") == "pong"

    def start(self, argv: list[str], *, directory: Path,
              label: str = "Quattro OMP") -> HerdrSession:
        """Launch an authorized Quattro command in a new private workspace.

        This grants no execution permission itself. The supplied entrypoint must
        enforce Quattro's policies and native approval rules. argv is never shell text.
        """
        directory = Path(directory).resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("terminal working directory must be a directory")
        if not argv or len(argv) > 128 or any(
                not isinstance(arg, str) or not arg or "\x00" in arg or len(arg) > 8192
                for arg in argv):
            raise ValueError("invalid terminal argument vector")
        if not Path(argv[0]).is_absolute():
            raise ValueError("terminal executable must be absolute")
        if not label or len(label) > 80 or any(ord(char) < 32 for char in label):
            raise ValueError("invalid terminal label")
        result = self._request("workspace.create", {
            "cwd": str(directory), "label": label, "focus": False,
        })
        workspace = result.get("workspace")
        if not isinstance(workspace, dict):
            raise HerdrError("Herdr omitted created workspace")
        workspace_id = _identifier(workspace.get("workspace_id"))
        self._owned.add(workspace_id)
        # The helper removes arbitrary server environment before exec. Herdr's
        # injected pane identity survives so native lifecycle hooks still work.
        command = [sys.executable, str(Path(__file__).resolve()), "--exec", *argv]
        applied = self._request("layout.apply", {
            "workspace_id": workspace_id, "tab_label": label, "focus": False,
            "root": {"type": "pane", "label": label, "cwd": str(directory),
                     "command": command},
        })
        layout = applied.get("layout")
        if not isinstance(layout, dict):
            raise HerdrError("Herdr omitted launched layout; inspect workspace before retrying")
        pane_id = _identifier(layout.get("focused_pane_id"))
        return HerdrSession(workspace_id, pane_id)

    def status(self, session: HerdrSession) -> dict[str, object]:
        """Return only display-safe identity/state, never process argv or output."""
        result = self._request("pane.get", {"pane_id": _identifier(session.pane_id)})
        pane = result.get("pane")
        if not isinstance(pane, dict) or pane.get("pane_id") != session.pane_id:
            raise HerdrError("Herdr pane identity mismatch")
        status = pane.get("agent_status", "unknown")
        if status not in {"idle", "working", "blocked", "done", "unknown"}:
            status = "unknown"
        return {"workspace_id": session.workspace_id, "pane_id": session.pane_id,
                "agent_status": status, "persistent_terminal": True}

    def close(self, session: HerdrSession) -> None:
        """Close only a workspace created by this client, on explicit caller intent."""
        if session.workspace_id not in self._owned:
            raise HerdrError("refusing to close an unowned Herdr workspace")
        self._request("workspace.close", {"workspace_id": session.workspace_id})
        self._owned.remove(session.workspace_id)


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--exec":
        raise SystemExit("internal Herdr terminal launcher requires --exec argv")
    os.execvpe(sys.argv[2], sys.argv[2:], sanitized_terminal_environment())
