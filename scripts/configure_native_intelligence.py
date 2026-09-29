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
NATIVE_TOOL_APPROVAL = "approve"
NATIVE_CONFIG_NAME = "native-intelligence.json"
NATIVE_CATEGORIES = (
    "context_strategy", "execution_strategy", "validation_strategy",
    "retry_strategy", "progress_strategy",
)


def codex_homes(home: pathlib.Path) -> list[pathlib.Path]:
    homes: list[pathlib.Path] = []
    configured = os.environ.get("CODEX_HOME")
    if configured:
        homes.append(pathlib.Path(os.path.expandvars(os.path.expanduser(configured))).resolve())
    homes.append(home / ".codex")
    accounts = home / ".local/share/quattro-ai/codex/accounts"
    if accounts.is_dir():
        homes.extend(path for path in sorted(accounts.iterdir())
                     if path.is_dir() and ACCOUNT_NAME.fullmatch(path.name)
                     and (path / "config.toml").is_file())
    result = []
    for path in homes:
        path = path.expanduser().resolve()
        if path not in result:
            result.append(path)
    return result


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
        if (not isinstance(current, dict) or current.get("command") != str(command)):
            raise ValueError(f"existing shared MCP configuration needs manual reconciliation: {config_path}")
        if tools is not None and not isinstance(tools, dict):
            raise ValueError(f"malformed MCP tool table: {config_path}")
        additions = []
        expected = {
            "search_knowledge": "approve",
            "rtk_status": "approve",
            "rtk_run": "prompt",
            "refresh_history": "prompt",
            "operational_decision": NATIVE_TOOL_APPROVAL,
        }
        for name, approval in expected.items():
            if not isinstance(tools, dict) or name not in tools:
                additions.append(
                    f'\n[mcp_servers.{SERVER}.tools.{name}]\napproval_mode = {json.dumps(approval)}\n'
                )
        if additions:
            _append(config_path, raw, "".join(additions))
            return True
        return False
    addition = (
        f'\n[mcp_servers.{SERVER}]\ncommand = {json.dumps(str(command))}\nrequired = false\ntool_timeout_sec = 200\n'
        f'\n[mcp_servers.{SERVER}.tools.search_knowledge]\napproval_mode = "approve"\n'
        f'\n[mcp_servers.{SERVER}.tools.rtk_status]\napproval_mode = "approve"\n'
        f'\n[mcp_servers.{SERVER}.tools.rtk_run]\napproval_mode = "prompt"\n'
        f'\n[mcp_servers.{SERVER}.tools.refresh_history]\napproval_mode = "prompt"\n'
        f'\n[mcp_servers.{SERVER}.tools.operational_decision]\napproval_mode = "{NATIVE_TOOL_APPROVAL}"\n'
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


def pi_agent_dir(home: pathlib.Path) -> pathlib.Path:
    configured = os.environ.get("PI_CODING_AGENT_DIR")
    if configured:
        return pathlib.Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
    return home / ".pi/agent"


def _atomic_copy(source: pathlib.Path, destination: pathlib.Path) -> bool:
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"Pi extension source is missing or symlinked: {source}")
    payload = source.read_bytes()
    if destination.is_file() and not destination.is_symlink() and destination.read_bytes() == payload:
        return False
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    permissions = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o644
    descriptor, temporary = tempfile.mkstemp(prefix=".quattro-intelligence-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, permissions)
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return True


def configure_pi(home: pathlib.Path, source: pathlib.Path) -> bool:
    target = pi_agent_dir(home) / "extensions/quattro-intelligence.ts"
    return _atomic_copy(source, target)


def configure_native_defaults(home: pathlib.Path) -> bool:
    configured = os.environ.get("QUATTRO_NATIVE_INTELLIGENCE_CONFIG")
    path = (pathlib.Path(os.path.expandvars(os.path.expanduser(configured))).resolve()
            if configured else home / ".config/quattro" / NATIVE_CONFIG_NAME)
    if path.is_symlink():
        raise ValueError(f"refusing symlinked native intelligence configuration: {path}")
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"malformed native intelligence configuration: {path}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"native intelligence configuration must be an object: {path}")
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "enabled": True,
        "categories": list(NATIVE_CATEGORIES),
        "timeoutMs": 1500,
        "retrievalEnabled": True,
        "rtkEnabled": True,
        "telemetryEnabled": True,
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".native-intelligence-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
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
    native_changed = configure_native_defaults(home)
    print(f"native intelligence settings: {'configured' if native_changed else 'preserved'}")
    for codex_home in codex_homes(home):
        changed = configure(codex_home / "config.toml", command)
        print(f"{codex_home}: {'configured' if changed else 'already configured'}")
        image_command = home / ".local/bin/quattro-image-mcp"
        if image_command.is_file() and os.access(image_command, os.X_OK):
            image_changed = configure_image(codex_home / "config.toml", image_command)
            print(f"{codex_home}: image MCP {'configured' if image_changed else 'already configured'}")
    extension_source = pathlib.Path(__file__).resolve().parents[1] / "adapters/pi/quattro-intelligence.ts"
    pi_changed = configure_pi(home, extension_source)
    print(f"{pi_agent_dir(home)}: Pi extension {'configured' if pi_changed else 'already configured'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
