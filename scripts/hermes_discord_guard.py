#!/usr/bin/env python3
"""Mandatory service admission checks before the supported Hermes gateway starts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def check(home: Path) -> list[str]:
    failures = []
    for name in ("config.yaml", "quattro-policy.json", ".env", "auth.json"):
        path = home / name
        if not path.is_file() or path.is_symlink():
            failures.append(f"missing private profile {name}")
        elif path.stat().st_mode & 0o077:
            failures.append(f"{name} permissions must be 0600")
    config_file = home / "config.yaml"
    if not config_file.is_file():
        return failures
    try:
        import yaml
    except ImportError:
        # JSON is a YAML subset; hermetic Core tests need no Hermes dependency.
        config = json.loads(config_file.read_text())
    else:
        config = yaml.safe_load(config_file.read_text()) or {}
    policy_file = home / "quattro-policy.json"
    policy = json.loads(policy_file.read_text()) if policy_file.is_file() else {}
    if not policy.get("owner_id"):
        failures.append("numeric owner ID not configured")
    model = config.get("model", {})
    if model.get("provider") != "openai-codex":
        failures.append("conversation provider must be subscription openai-codex")
    if model.get("base_url") or model.get("api_key"):
        failures.append("custom model endpoint/credential refused")
    for task in config.get("auxiliary", {}).values():
        if isinstance(task, dict) and task.get("provider", "auto") not in {"auto", "openai-codex"}:
            failures.append("unapproved auxiliary provider refused")
    if config.get("auth", {}).get("adopt_external_logins") is not False:
        failures.append("external credential adoption must be disabled")
    if config.get("fallback_models") != [] or config.get("providers") or config.get("custom_providers"):
        failures.append("alternate provider/fallback configuration refused")
    if config.get("platform_toolsets", {}).get("discord") != []:
        failures.append("conversation execution/external tools must remain disabled")
    if config.get("memory", {}).get("memory_enabled") is not False:
        failures.append("automatic canonical-memory mutation must remain disabled")
    discord = config.get("discord", {})
    if discord.get("allowed_users") != policy.get("owner_id"):
        failures.append("upstream owner allowlist and transport policy differ")
    if discord.get("allowed_roles") or discord.get("allow_all_users") or discord.get("allow_bots"):
        failures.append("role/all-user/bot grants refused")
    env_path = home / ".env"
    if env_path.is_file():
        # Read only non-secret key names. Values stay inside the native dotenv loader.
        names = {line.split("=", 1)[0].strip() for line in env_path.read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith("#") and "=" in line}
        if names != {"DISCORD_BOT_TOKEN"}:
            failures.append("profile .env must contain only the dedicated bot token")
    if "quattro-discord" not in config.get("plugins", {}).get("enabled", []):
        failures.append("mandatory owner boundary plugin is disabled")
    return failures


def main() -> int:
    home = Path(os.environ.get("HERMES_HOME", ""))
    if not home.is_absolute() or home.name != "quattro-discord":
        print("BLOCKED: dedicated absolute HERMES_HOME required", file=sys.stderr)
        return 78
    try:
        failures = check(home)
        if failures:
            print("BLOCKED: " + "; ".join(failures), file=sys.stderr)
            return 78
        from hermes_cli.plugins import get_plugin_manager
        manager = get_plugin_manager()
        manager.discover()
        plugins = manager.list_plugins()
        loaded = (any(p["enabled"] and p["name"] == "quattro-discord"
                      and not p["error"] and p["hooks"] == 1 for p in plugins)
                  and manager.has_hook("pre_gateway_dispatch"))
        if not loaded:
            print("BLOCKED: mandatory owner boundary plugin did not load", file=sys.stderr)
            return 78
        # Configuration-only admission, not proof of valid OAuth/model entitlement.
        # No bearer-token or account identity is printed here.
        print("Private Hermes gateway admission checks passed (OAuth live validity still runtime-checked).")
        return 0
    except Exception:
        print("BLOCKED: private gateway admission failed; inspect local configuration", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
