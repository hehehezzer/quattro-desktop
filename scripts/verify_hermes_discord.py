#!/usr/bin/env python3
"""Exercise real Hermes hook discovery + shared retrieval, without pretending Discord is live.

Run with the deployed Hermes venv Python after Core installation. All platform
identities are synthetic and all adapter sends are collected locally.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="quattro-hermes-contract-") as directory:
        root = Path(directory)
        home = root / "profile"
        home.mkdir(mode=0o700)
        project = root / "fixture"
        project.mkdir()
        marker = "recovery-" + uuid.uuid4().hex
        (project / "README.md").write_text("# Transport retrieval fixture\nThe recovery phrase for the transport fixture is " + marker + ".\n")
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(project), "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Retrieval fixture"], check=True)
        installed = Path.home() / ".hermes/profiles/quattro-discord/plugins/quattro-discord"
        shutil.copytree(installed, home / "plugins/quattro-discord")
        contract_config = {"plugins": {"enabled": ["quattro-discord"]},
                           "platform_toolsets": {"discord": []},
                           "agent": {"disabled_toolsets": ["hermes-discord", "hermes-cli"]},
                           "discord": {"allow_from": "123456789012345678", "allowed_channels": "223456789012345678"}}
        (home / "config.yaml").write_text(json.dumps(contract_config))
        policy = {"owner_id": "123456789012345678", "guild_ids": ["323456789012345678"],
                  "channel_ids": ["223456789012345678"], "owner_dms": True,
                  "projects": {"fixture": str(project)}}
        policy_file = home / "quattro-policy.json"
        policy_file.write_text(json.dumps(policy))
        policy_file.chmod(0o600)
        os.environ["HERMES_HOME"] = str(home)
        from hermes_cli.plugins import get_plugin_manager
        from hermes_cli.lifecycle import ainvoke_hook
        from gateway.config import Platform
        from gateway.session import SessionSource
        from gateway.platforms.event import MessageEvent
        manager = get_plugin_manager()
        manager.discover_and_load()
        from plugins.platforms.discord.adapter import _apply_yaml_config
        native_policy = _apply_yaml_config(contract_config, contract_config["discord"])
        assert native_policy["allow_from"] == policy["owner_id"]
        from hermes_cli.tools_config import _get_platform_tools
        from model_tools import get_tool_definitions
        toolsets = sorted(_get_platform_tools(contract_config, "discord"))
        assert not get_tool_definitions(enabled_toolsets=toolsets,
                                        disabled_toolsets=contract_config["agent"]["disabled_toolsets"], quiet_mode=True)
        assert any(p["name"] == "quattro-discord" and p["enabled"] and not p["error"] for p in manager.list_plugins())
        source = SessionSource(platform=Platform.DISCORD, user_id=policy["owner_id"],
                               chat_id=policy["channel_ids"][0], chat_type="channel", scope_id=policy["guild_ids"][0])
        class Adapter:
            # Exact public BasePlatformAdapter.send contract, not a permissive **kwargs mock.
            def __init__(self):
                self.sent = []
            async def send(self, chat_id, content, reply_to=None, metadata=None):
                self.sent.append((chat_id, content, metadata))
        adapter = Adapter()
        class Gateway:
            adapters = {Platform.DISCORD: adapter}
        gateway = Gateway()
        async def invoke(text, number, **kwargs):
            event = MessageEvent(text=text, source=source, message_id=str(423456789012345678 + number), **kwargs)
            results = await ainvoke_hook("pre_gateway_dispatch", event=event, gateway=gateway, session_store=None)
            return next((r for r in results if isinstance(r, dict)), None)
        async def tests():
            blocked = await ainvoke_hook("pre_tool_call", tool_name="terminal", args={"command": "untrusted"}, task_id="fixture")
            assert any(r.get("action") == "block" for r in blocked if isinstance(r, dict))
            assert (await invoke("/quattro project fixture", 1))["action"] == "skip"
            assert "Selected project: fixture" in adapter.sent[-1][1]
            result = await invoke("What is the recovery phrase in the transport retrieval fixture? Cite the project source.", 2)
            assert result["action"] == "rewrite", result
            assert marker in result["text"], "actual file-only marker absent from retrieval"
            assert "UNTRUSTED DATA" in result["text"]
            assert (await invoke("What is the recovery phrase?", 2))["reason"] == "quattro-duplicate-or-invalid-event"
            assert (await invoke("/quattro run codex fixture harmless task", 3, media_urls=["synthetic.txt"]))["reason"] == "quattro-untrusted-control-content"
            assert (await invoke("/goal run dangerous operation", 4))["reason"] == "quattro-native-command-denied"
            result = await invoke("Write an implementation prompt and /goal prompt for the fixture project", 5)
            assert result is None or result["action"] == "rewrite"
            assert (await invoke("OPENAI_API_KEY=" + "sk-" + "x" * 48, 8))["reason"] == "quattro-credential-content-denied"
            source.profile = "other-profile"
            assert (await invoke("/quattro help", 9))["reason"] == "quattro-owner-and-destination-denied"
            source.profile = None
            assert await invoke("/new", 10) is None
            count = len(adapter.sent)
            source.user_id = "523456789012345678"
            assert (await invoke("/quattro project fixture", 6))["reason"] == "quattro-owner-and-destination-denied"
            assert len(adapter.sent) == count
            source.user_id = policy["owner_id"]
            policy["owner_id"] = ""
            policy_file.write_text(json.dumps(policy))
            assert (await invoke("/quattro projects", 7))["reason"] == "quattro-owner-and-destination-denied"
        asyncio.run(tests())
        print("AUTOMATED VERIFIED: native Hermes discovery/hooks, exact adapter-send signature, owner/destination denial,")
        print("native YAML owner mapping, zero effective tools, tool veto, durable dedup, attachment/native-command denial,")
        print("prompt-only path and policy revocation.")
        print("LIVE LOCAL RETRIEVAL VERIFIED: file-only randomized fixture reached the gateway rewrite.")
        print("NOT VERIFIED: Discord transport, provider delivery/reliance, OAuth, or managed worker execution.")


if __name__ == "__main__":
    main()
