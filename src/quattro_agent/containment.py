"""Best-effort Linux filesystem containment for untrusted child processes.

The normal Codex sandbox controls writes, not arbitrary reads. Review workers
therefore use bubblewrap when available, with only the checkout, sanitized
runtime home, and report directory mounted into the child. Network remains
shared so a local OmniRoute endpoint can be reached; no provider credentials
are mounted into the runtime home.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class ContainmentError(RuntimeError):
    """Raised when a requested child filesystem boundary cannot be built."""


def bubblewrap_path() -> str | None:
    return shutil.which("bwrap")


def _map_path(value: str, mappings: tuple[tuple[Path, Path], ...]) -> str:
    path = Path(value)
    for source, target in mappings:
        try:
            relative = path.relative_to(source)
        except ValueError:
            continue
        return str(target / relative)
    return value


def build_bwrap_command(
    argv: list[str] | tuple[str, ...],
    *,
    project_root: Path,
    runtime_root: Path,
    report_root: Path,
    environment: dict[str, str],
) -> tuple[list[str], dict[str, str], Path]:
    """Build a contained command and its namespace-visible environment.

    Returns ``(argv, environment, visible_report_root)``. The caller must
    still use argument-safe process execution and bounded supervision.
    """
    bwrap = bubblewrap_path()
    if bwrap is None:
        raise ContainmentError("bubblewrap is unavailable; refusing an uncontained review worker")
    project = project_root.resolve(strict=True)
    runtime = runtime_root.resolve(strict=True)
    report = report_root.resolve(strict=True)
    if not project.is_dir() or not runtime.is_dir() or not report.is_dir():
        raise ContainmentError("containment roots must be existing directories")

    mappings: list[tuple[Path, Path]] = [
        (project, Path("/workspace")),
        (runtime, Path("/quattro-runtime")),
        (report, Path("/quattro-report")),
    ]
    command_binary = Path(str(argv[0])).expanduser()
    if not command_binary.is_absolute():
        raise ContainmentError("contained child executable must be an absolute path")
    if not command_binary.exists():
        raise ContainmentError("contained child executable is unavailable")

    # System runtimes can be mounted at their normal paths. User-local Node
    # installations are mounted below a neutral path so the host home path is
    # not visible inside the namespace.
    system_roots = tuple(Path(value) for value in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/opt") if Path(value).exists())
    binary_root: Path | None = None
    binary_target: Path | None = None
    if not any(command_binary.is_relative_to(root) for root in system_roots):
        nvm = next((Path(*command_binary.parts[:index + 1]) for index, part in enumerate(command_binary.parts) if part == ".nvm"), None)
        binary_root = nvm or command_binary.parent
        binary_target = Path("/quattro-nvm") if nvm else Path("/quattro-bin")
        mappings.append((binary_root, binary_target))

    command = [bwrap, "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts"]
    for root in system_roots:
        command.extend(("--ro-bind", str(root), str(root)))
    command.extend((
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--tmpfs", "/home", "--tmpfs", "/root",
        "--ro-bind", str(project), "/workspace",
        "--bind", str(runtime), "/quattro-runtime",
        "--bind", str(report), "/quattro-report",
        "--chdir", "/workspace",
    ))
    if binary_root is not None and binary_target is not None:
        command.extend(("--ro-bind", str(binary_root), str(binary_target)))

    mapped_argv = [
        _map_path(str(value), tuple(mappings)) if index else str(value)
        for index, value in enumerate(argv)
    ]
    if binary_root is not None and binary_target is not None:
        try:
            mapped_argv[0] = str(binary_target / command_binary.relative_to(binary_root))
        except ValueError as error:
            raise ContainmentError("child executable is outside its mounted root") from error
    command.extend(("--", *mapped_argv))

    visible_environment = dict(environment)
    for name in ("HOME", "CODEX_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR", "TMPDIR"):
        if name in visible_environment:
            visible_environment[name] = _map_path(visible_environment[name], tuple(mappings))
    visible_environment["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    if binary_target is not None and binary_root is not None:
        visible_environment["PATH"] = str(binary_target) + ":" + visible_environment["PATH"]
    return command, visible_environment, Path("/quattro-report")

