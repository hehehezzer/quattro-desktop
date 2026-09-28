#!/usr/bin/env python3
"""Register the shared MCP in native Codex homes without touching credentials."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import stat
import tempfile
import tomllib

SERVER = "quattro_intelligence"
ACCOUNT_NAME = re.compile(r"account-[1-9][0-9]*$")


def codex_homes(home: pathlib.Path) -> list[pathlib.Path]:
    homes = [home / ".codex"]
    accounts = home / ".local/share/quattro-ai/codex/accounts"
    if accounts.is_dir():
        homes.extend(path for path in sorted(accounts.iterdir())
                     if path.is_dir() and ACCOUNT_NAME.fullmatch(path.name)
                     and (path / "config.toml").is_file())
    return homes


def _read(config_path: pathlib.Path) -> tuple[bytes, dict]:
    if config_path.is_symlink():
        raise ValueError(f"refusing symlinked Codex config: {config_path}")
    raw = config_path.read_bytes() if config_path.is_file() else b""
    try:
        existing = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"malformed Codex config: {config_path}: {error}") from error
    return raw, existing


def _append(config_path: pathlib.Path, raw: bytes, addition: str) -> None:
    updated = raw.rstrip(b"\n") + b"\n" + addition.encode()
    tomllib.loads(updated.decode("utf-8"))
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    permissions = stat.S_IMODE(config_path.stat().st_mode) if config_path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=config_path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, permissions)
        os.replace(temporary, config_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def configure(config_path: pathlib.Path, command: pathlib.Path) -> bool:
    raw, existing = _read(config_path)
    servers = existing.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"malformed MCP server table: {config_path}")
    current = servers.get(SERVER)
    if current is not None:
        tools = current.get("tools") if isinstance(current, dict) else None
        if (not isinstance(current, dict) or current.get("command") != str(command)
                or not isinstance(tools, dict)
                or not isinstance(tools.get("search_knowledge"), dict)
                or tools["search_knowledge"].get("approval_mode") != "approve"
                or not isinstance(tools.get("rtk_status"), dict)
                or tools["rtk_status"].get("approval_mode") != "approve"
                or not isinstance(tools.get("rtk_run"), dict)
                or tools["rtk_run"].get("approval_mode") != "prompt"
                or not isinstance(tools.get("refresh_history"), dict)
                or tools["refresh_history"].get("approval_mode") != "prompt"):
            raise ValueError(f"existing shared MCP configuration needs manual reconciliation: {config_path}")
        return False
    addition = (
        f'\n[mcp_servers.{SERVER}]\ncommand = {json.dumps(str(command))}\nrequired = false\ntool_timeout_sec = 200\n'
        f'\n[mcp_servers.{SERVER}.tools.search_knowledge]\napproval_mode = "approve"\n'
        f'\n[mcp_servers.{SERVER}.tools.rtk_status]\napproval_mode = "approve"\n'
        f'\n[mcp_servers.{SERVER}.tools.rtk_run]\napproval_mode = "prompt"\n'
        f'\n[mcp_servers.{SERVER}.tools.refresh_history]\napproval_mode = "prompt"\n'
    )
    _append(config_path, raw, addition)
    return True


def configure_image(config_path: pathlib.Path, command: pathlib.Path) -> bool:
    raw, existing = _read(config_path)
    servers = existing.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"malformed MCP server table: {config_path}")
    current = servers.get("quattro_images")
    if current is not None:
        if not isinstance(current, dict) or current.get("command") != str(command):
            raise ValueError(f"existing image MCP configuration needs manual reconciliation: {config_path}")
        return False
    _append(config_path, raw,
            f'\n[mcp_servers.quattro_images]\ncommand = {json.dumps(str(command))}\nrequired = false\n'
            '\n[mcp_servers.quattro_images.tools.generate_image]\napproval_mode = "prompt"\n')
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home())
    parser.add_argument("--command", type=pathlib.Path)
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    command = (args.command or home / ".local/bin/quattro-intelligence-mcp").resolve()
    if not command.is_file() or not os.access(command, os.X_OK):
        parser.error(f"MCP command is missing or not executable: {command}")
    for codex_home in codex_homes(home):
        changed = configure(codex_home / "config.toml", command)
        print(f"{codex_home}: {'configured' if changed else 'already configured'}")
        image_command = home / ".local/bin/quattro-image-mcp"
        if image_command.is_file() and os.access(image_command, os.X_OK):
            image_changed = configure_image(codex_home / "config.toml", image_command)
            print(f"{codex_home}: image MCP {'configured' if image_changed else 'already configured'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
