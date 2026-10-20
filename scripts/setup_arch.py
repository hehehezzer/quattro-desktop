#!/usr/bin/env python3
"""Provision an existing Arch Linux desktop without changing the running session."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FEATURES = {"desktop", "intelligence", "applications", "native"}
DEFAULT_FEATURES = "desktop,intelligence"
# Official repositories only; no AUR helper, GPU choice or host-specific driver.
DESKTOP_PACKAGES = (
    "hyprland", "quickshell", "ghostty", "nautilus", "hyprlock", "hyprpicker",
    "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk", "polkit-kde-agent",
    "qt6-declarative", "qt6-svg", "qt6-5compat", "qt6-multimedia", "networkmanager",
    "bluez", "bluez-utils", "python-gobject", "pipewire", "pipewire-pulse",
    "wireplumber", "libpulse", "brightnessctl", "playerctl", "wl-clipboard", "wtype",
    "grim", "slurp", "jq", "qrencode", "libnotify", "ttf-jetbrains-mono-nerd",
    "xdg-utils", "nano", "util-linux",
)
APPLICATION_PACKAGES = ("firefox", "gimp", "mpv", "file-roller")
HELPERS = (
    "quattro-menu", "quattro-theme", "quattro-pointer", "quattro-night-light",
    "quattro-session", "quattro-screenshot", "quattro-system-stats", "quattro-monitor",
    "quattro-notification-store", "quattro-lyrics", "quattro_spotify_art.py",
    "quattro_desktop_controls.py", "quattro_bluetooth.py", "quattro_native_usage.py",
    "quattro_intelligence_panel.py",
)


def regular(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Refusing symbolic-link destination: {path}")
    if path.exists() and not path.is_file() and not path.is_dir():
        raise ValueError(f"Unsupported destination: {path}")


def xdg(home: Path, name: str, fallback: str, isolated: bool) -> Path:
    value = Path(os.environ.get(name, str(home / fallback))) if not isolated else home / fallback
    if not value.is_absolute() or ".." in value.parts:
        raise ValueError(f"{name} must be an absolute path without traversal")
    regular(value)
    return value


class Files:
    """Back up every replaced file; journal before mutation, never follow links."""
    def __init__(self, backup: Path):
        self.backup = backup
        self.entries: list[dict[str, object]] = []

    def remember(self, path: Path) -> None:
        regular(path)
        if any(item["path"] == str(path) for item in self.entries):
            return
        if path.exists() and not path.is_file():
            raise ValueError(f"Expected a file: {path}")
        regular(self.backup)
        self.backup.mkdir(parents=True, mode=0o700, exist_ok=True)
        saved = str(len(self.entries)) if path.exists() else None
        if saved is not None:
            shutil.copy2(path, self.backup / saved)
            (self.backup / saved).chmod(0o600)
        self.entries.append({"path": str(path), "saved": saved,
                             "mode": path.stat().st_mode & 0o777 if path.exists() else None})
        (self.backup / "rollback.json").write_text(json.dumps(self.entries, indent=2) + "\n")
        (self.backup / "rollback.json").chmod(0o600)

    def put(self, path: Path, content: bytes, mode: int = 0o644) -> None:
        regular(path)
        if path.is_file() and path.read_bytes() == content and path.stat().st_mode & 0o777 == mode:
            return
        self.remember(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".quattro-setup-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def text(self, path: Path, content: str, mode: int = 0o644) -> None:
        self.put(path, content.encode(), mode)


def lua_version() -> None:
    result = subprocess.run(["Hyprland", "--version"], check=True, capture_output=True, text=True)
    match = re.search(r"\bv?(\d+)\.(\d+)\.(\d+)", result.stdout)
    if not match or tuple(map(int, match.groups())) < (0, 56, 2):
        raise ValueError("Desktop requires Hyprland >= 0.56.2 with Lua configuration support; no config installed")


def desktop(files: Files, config: Path, binaries: Path) -> None:
    for directory in ("hypr", "ghostty", "quickshell"):
        for source in sorted((ROOT / "src" / directory).rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            content = source.read_bytes()
            files.put(config / directory / source.relative_to(ROOT / "src" / directory), content,
                      0o755 if source.suffix == ".sh" else 0o644)
    for name in HELPERS:
        files.put(binaries / name, (ROOT / "src" / name).read_bytes(), 0o755)
    files.text(binaries / "quattro-shell", '#!/bin/sh\nexport PATH="$HOME/.local/bin:$PATH"\n: "${XDG_RUNTIME_DIR:?A logged-in user runtime directory is required}"\nexec flock -n "$XDG_RUNTIME_DIR/quattro-shell.lock" quickshell -p "${XDG_CONFIG_HOME:-$HOME/.config}/quickshell/shell.qml"\n', 0o755)
    files.text(binaries / "restart-quickshell", '#!/bin/sh\n# Run only when you explicitly request a shell restart.\nqs kill --all 2>/dev/null || true\nexec quattro-shell\n', 0o755)
    unit = ROOT / "src/systemd/quattro-equalizer.service"
    files.put(config / "systemd/user" / unit.name, unit.read_bytes())


def intelligence(files: Files, config: Path, data: Path, binaries: Path, environment: dict[str, str]) -> Path:
    destination = data / "quattro/intelligence/venv"
    regular(destination)
    subprocess.run([sys.executable, str(ROOT / "scripts/install_local.py"), "--destination", str(destination)],
                   check=True, env=environment)
    configuration = config / "quattro/intelligence.json"
    if not configuration.exists():
        files.text(configuration, json.dumps({"version": 1, "database_dir": str(data / "quattro/intelligence/state"),
            "projects": ["local"], "sources": [], "principal": "local", "writable": False,
            "can_verify": False, "embedding": "lexical"}, indent=2) + "\n", 0o600)
    else:
        regular(configuration)
    for name in ("quattro-intelligence", "quattro-intelligence-mcp", "quattro-intelligence-native"):
        command = shlex.join([str(destination / "bin" / name), "--config", str(configuration)])
        files.text(binaries / name, f'#!/bin/sh\nexec {command} "$@"\n', 0o755)
    return destination / "bin/python"


def native(files: Files, python: Path, config: Path, source: Path) -> None:
    # Import only the current standalone schema, never legacy execution modules.
    sys.path.insert(0, str(ROOT / "src"))
    from dataclasses import replace
    from quattro_core.config import Config
    from install_native_clients import install_clients
    base = Config.load(source)
    clients = config / "quattro/clients"
    for host in ("omp", "codex"):
        value = replace(base, principal=host, writable=False, can_verify=False)
        files.text(clients / f"{host}.json", json.dumps(value.projection(), indent=2) + "\n", 0o600)
    home = Path.home()
    roots = [home / ".omp/agent"]
    profiles = home / ".omp/profiles"
    if profiles.is_dir():
        regular(profiles)
        roots += [p / "agent" for p in profiles.iterdir() if p.is_dir() and not p.is_symlink()]
    for root in roots:
        if root.is_dir():
            files.remember(root / "extensions/quattro-intelligence.ts")
    accounts = home / ".local/share/quattro-ai/codex/accounts"
    codex = [home / ".codex"]
    if accounts.is_dir():
        regular(accounts)
        codex += [p for p in accounts.iterdir() if re.fullmatch(r"account-[0-9]+", p.name) and p.is_dir() and not p.is_symlink()]
    for root in codex:
        if (root / "config.toml").is_file():
            files.remember(root / "config.toml")
            files.remember(root / "hooks.json")
    result = install_clients(ROOT, python, config / "quattro")
    # omp's extension discovers this explicit runtime; never alter provider policy.
    files.text(config / "quattro/native-runtime.json", json.dumps({"python": str(python),
               "config_dir": str(config / "quattro")}) + "\n", 0o600)
    print(json.dumps(result))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features",
                        help="Exact comma-separated selection: desktop,intelligence (default), applications,native; JEV is unavailable")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without creating files or running package commands")
    parser.add_argument("--yes", action="store_true", help="Accept the printed package/config replacement plan")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Alternate home stages files only; never installs packages or native clients")
    parser.add_argument("--skip-packages", action="store_true", help="Install user files only; required packages must already be installed")
    parser.add_argument("--native-config", type=Path, help="Existing explicitly registered Intelligence config required by native")
    args = parser.parse_args()
    try:
        if os.geteuid() == 0:
            raise ValueError("Run as your ordinary desktop user, not root or sudo; only pacman uses sudo")
        selection = args.features
        if selection is None and sys.stdin.isatty() and not args.yes and not args.dry_run:
            print("Choose what to install (omit any unwanted feature):")
            print("  desktop      Hyprland, Quickshell, themes and system controls")
            print("  intelligence Local knowledge retrieval and persistent memory")
            print("  applications Firefox, GIMP, mpv and archive tools (requires desktop)")
            print("  native       Existing-client integration (requires intelligence and --native-config)")
            selection = input(f"Comma-separated features [{DEFAULT_FEATURES}]: ").strip() or DEFAULT_FEATURES
        selected = {feature.strip() for feature in (DEFAULT_FEATURES if selection is None else selection).split(",")}
        if "jev" in selected:
            raise ValueError("JEV is not implemented in this standalone project; install/manage it separately, not as Quattro routing")
        if not selected or selected - FEATURES:
            raise ValueError("Select only desktop,intelligence,applications,native")
        if "applications" in selected and "desktop" not in selected:
            raise ValueError("applications requires desktop")
        if "native" in selected and ("intelligence" not in selected or args.native_config is None):
            raise ValueError("native requires intelligence and --native-config PATH with explicit operator source registrations")
        home = args.home.expanduser().absolute()
        if ".." in home.parts:
            raise ValueError("Home must not contain traversal")
        regular(home)
        isolated = home != Path.home().absolute()
        if isolated and "native" in selected:
            raise ValueError("native is unavailable with an alternate --home; host client settings must remain untouched")
        config = xdg(home, "XDG_CONFIG_HOME", ".config", isolated)
        data = xdg(home, "XDG_DATA_HOME", ".local/share", isolated)
        state = xdg(home, "XDG_STATE_HOME", ".local/state", isolated)
        if "native" in selected:
            if config != home / ".config":
                raise ValueError("Existing native adapters require the standard ~/.config path; custom XDG native registration is not supported")
            sys.path.insert(0, str(ROOT / "src"))
            from quattro_core.config import Config
            native_config = args.native_config.expanduser().absolute()
            if not Config.load(native_config).sources:
                raise ValueError("Native setup requires at least one explicit registered source; register and review sources first")
        binaries = home / ".local/bin"
        regular(binaries)
        packages = list(DESKTOP_PACKAGES) if "desktop" in selected else []
        if "applications" in selected:
            packages += APPLICATION_PACKAGES
        if "intelligence" in selected:
            packages += ["python", "python-pip", "git"]
        install_packages = bool(packages) and not isolated and not args.skip_packages
        command = ["sudo", "pacman", "-Syu", "--needed", *packages]
        print("Features: " + ", ".join(sorted(selected)))
        print("Available: desktop, intelligence, applications, native. JEV: unavailable (no implementation).")
        print("Official packages: " + " ".join(packages))
        print(("Run: " if install_packages else "Not run (file-only staging/--skip-packages): ") + shlex.join(command))
        print(f"User config: {config}; commands: {binaries}; core runtime: {data}/quattro/intelligence/venv")
        print("Desktop requires official Hyprland >=0.56.2 (Lua). No GPU/monitor/storage assumptions or live restarts.")
        print("Existing changed files are backed up; existing Intelligence config/database/accounts are preserved.")
        print("Native is opt-in, read-only, preserves models/permissions; review the exact Codex hook in /hooks afterward.")
        if args.dry_run:
            return 0
        if not args.yes:
            if not sys.stdin.isatty() or input("Apply this plan, backing up and replacing changed user configs? [y/N] ").lower() not in {"y", "yes"}:
                raise ValueError("Not applied; use --yes only after reviewing --dry-run")
        if install_packages:
            if not Path("/etc/arch-release").is_file() or not shutil.which("pacman"):
                raise ValueError("Package provisioning requires an existing Arch Linux installation")
            subprocess.run(command, check=True)
        if "desktop" in selected and not isolated:
            lua_version()
        backup = state / "quattro/setup-backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        files = Files(backup)
        environment = os.environ.copy()
        environment.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_DATA_HOME=str(data), XDG_STATE_HOME=str(state))
        try:
            if "desktop" in selected:
                desktop(files, config, binaries)
            python = intelligence(files, config, data, binaries, environment) if "intelligence" in selected else None
            if "native" in selected:
                native(files, python, config, args.native_config.expanduser().absolute())
        finally:
            if files.entries:
                print(f"Backup journal: {backup}/rollback.json")
                print("Rollback with the desktop stopped: for each journal entry restore 'saved' from this directory to 'path' with 'mode'; remove only new files whose saved is null.")
                print("Package upgrades and the isolated core virtual environment are not rolled back by the file journal.")
        print("User files installed. No running shell/compositor/service was restarted or enabled.")
        print("Before next login: review configs; ensure NetworkManager and bluetooth services are configured for your host, and PipeWire/WirePlumber user services are available.")
        print("Log out when ready, then select Hyprland in your existing display manager (or run start-hyprland from a TTY).")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Setup failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
