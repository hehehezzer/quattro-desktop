"""Explicit staged Herdr/OMP route, without changing legacy sessions or grants."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import os
import time

from .omp_bridge import bridge_contract, native_policy_overlay, omp_arguments


def add_parser(sub):
    parser = sub.add_parser("herdr", help="stage and inspect persistent Quattro OMP sessions")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("contract", help="show ownership, locked route and approval boundaries")
    start = actions.add_parser("start", help="create a Quattro terminal in an existing named Herdr server")
    start.add_argument("directory")
    start.add_argument("--socket", required=True)
    start.add_argument("--skills", required=True)
    start.add_argument("--confirm-native-access", action="store_true")
    status = actions.add_parser("status", help="inspect exact session without reading terminal content")
    status.add_argument("--socket", required=True)
    status.add_argument("--workspace", required=True)
    status.add_argument("--pane", required=True)


def skill_directory(value: str | None) -> Path:
    if not value:
        raise ValueError("explicit verified OMP skill catalog required")
    path = Path(value).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError("skill catalog must be an existing absolute directory")
    return path.resolve(strict=True)


def native_access(confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("OMP native access requires action-time approval: --confirm-native-access. "
                         "Writes and commands use native-user filesystem/network rights and OMP "
                         "always-ask dialogs; the working directory is not a sandbox. "
                         "Authentication remains a separate native /login action.")


def launch_omp(directory: Path, *, skills: str | None, confirmed: bool,
               environment: dict[str, str], native_session_ref: str | None = None) -> int:
    """Lock the requested target; never inherit API keys or launch default yolo."""
    native_access(confirmed)
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("workspace must be a directory")
    catalog = skill_directory(skills)
    record = None
    if native_session_ref is not None:
        from .omp_sessions import OMPSessionRegistry, OMPSessionError
        from .herdr_runtime import HerdrSession
        registry = OMPSessionRegistry(omp_registry_path())
        deadline = time.monotonic() + 5
        while True:
            record = registry.get(native_session_ref)
            if record["lifecycle"] != "launch_pending":
                break
            if time.monotonic() >= deadline:
                raise OMPSessionError("Herdr launch binding is still pending; inspect before retrying")
            time.sleep(0.05)
        handle = HerdrSession(os.environ.get("HERDR_WORKSPACE_ID", ""),
                              os.environ.get("HERDR_PANE_ID", ""))
        record = registry.verify_launch(native_session_ref,
            socket=Path(os.environ.get("HERDR_SOCKET_PATH", "")), directory=directory, handle=handle)
    executable = shutil.which("omp", path=environment.get("PATH"))
    if executable is None:
        raise RuntimeError("OMP is not installed")
    with tempfile.TemporaryDirectory(prefix="quattro-omp-") as temporary:
        overlay = Path(temporary) / "policy.json"
        overlay.write_text(json.dumps(native_policy_overlay(skill_roots=[catalog])), encoding="utf-8")
        overlay.chmod(0o600)
        command = omp_arguments(executable, config_overlay=overlay, skill_roots=[catalog])
        env = dict(environment)
        extension = Path(command[command.index("--extension") + 1])
        env["QUATTRO_OMP_OVERLAY"] = str(overlay)
        env["QUATTRO_OMP_OVERLAY_SHA256"] = hashlib.sha256(overlay.read_bytes()).hexdigest()
        env["QUATTRO_OMP_EXTENSION"] = str(extension)
        env["QUATTRO_OMP_EXTENSION_SHA256"] = hashlib.sha256(extension.read_bytes()).hexdigest()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        env["QUATTRO_OMP_PYTHON"] = sys.executable
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if record is not None:
            env["QUATTRO_OMP_REGISTRY"] = str(omp_registry_path())
            env["QUATTRO_OMP_LOGICAL_SESSION"] = native_session_ref
            env["QUATTRO_OMP_HERDR_SOCKET"] = record["socket"]
            env["QUATTRO_OMP_HERDR_WORKSPACE"] = record["workspace"]
            env["QUATTRO_OMP_HERDR_PANE"] = record["pane"]
        # The native interactive process lives until the user exits/detaches.
        # All helper/tool calls retain their independent finite bounds.
        return subprocess.run(command, cwd=directory, env=env, check=False).returncode


def omp_registry_path() -> Path:
    from .paths import state_root
    return state_root() / "private" / "omp-sessions.json"


def start_omp(directory: Path, *, skills: str | None, socket: str,
              confirmed: bool) -> int:
    """Start one explicit native session; uncertain mutations are not retried."""
    from .herdr_runtime import HerdrRuntime
    from .omp_sessions import OMPSessionRegistry
    native_access(confirmed)
    catalog = skill_directory(skills)
    directory = Path(directory).resolve(strict=True)
    runtime = HerdrRuntime(Path(socket))
    registry = OMPSessionRegistry(omp_registry_path())
    logical_id = registry.begin(socket=runtime.socket_path, directory=directory)
    try:
        handle = runtime.start([sys.executable, "-m", "quattro_agent", "launch", "omp",
                                str(directory), "--skills", str(catalog), "--confirm-native-access",
                                "--native-session-ref", logical_id], directory=directory)
        registry.created(logical_id, handle)
    except Exception:
        # A created terminal may already exist. Record uncertainty, never replay.
        try:
            registry.mark_launch_uncertain(logical_id)
        except Exception:
            pass  # Preserve the original failure and never retry the mutation.
        raise
    print(json.dumps({"logicalSessionId": logical_id, "workspace": handle.workspace_id,
                      "pane": handle.pane_id, "socket": str(runtime.socket_path),
                      "nativeIdentity": "pending_actual_native_session_start",
                      "coordinationSupported": False,
                      "route": bridge_contract()["route"]}, sort_keys=True))
    return 0


def command(args) -> int:
    from .herdr_runtime import HerdrRuntime, HerdrSession
    if args.action == "contract":
        print(json.dumps(bridge_contract(), sort_keys=True))
        return 0
    runtime = HerdrRuntime(Path(args.socket))
    if args.action == "status":
        print(json.dumps(runtime.status(HerdrSession(args.workspace, args.pane)), sort_keys=True))
        return 0
    native_access(args.confirm_native_access)
    directory = Path(args.directory).expanduser().resolve(strict=True)
    return start_omp(directory, skills=args.skills, socket=args.socket,
                     confirmed=args.confirm_native_access)
