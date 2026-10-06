"""Supported Hermes plugin; no upstream patches or alternative agent runtime."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from hermes_constants import get_hermes_home

# Installed Quattro Core is the single intelligence implementation. No launcher
# subprocess, model router, vault copy, or alternate RAG database is introduced.
_CORE = Path.home() / ".local/bin"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
from quattro_agent.hermes_bridge import Bridge, HELP

_bridge = None


def bridge():
    global _bridge
    home = get_hermes_home()
    policy_file = home / "quattro-policy.json"
    if policy_file.is_symlink() or policy_file.stat().st_mode & 0o077:
        raise PermissionError("quattro-policy.json must be a private regular file")
    policy = json.loads(policy_file.read_text())
    if _bridge is None or _bridge.policy != policy:
        _bridge = Bridge(policy, home / "quattro/transport.sqlite3")
    return _bridge


async def _reply(event, gateway, text):
    # Re-read owner policy immediately before delivery: stale async operations
    # cannot deliver after a local owner/destination policy change.
    if not bridge().authorized(event.source):
        return
    from quattro_agent.privacy import redact_secret_text
    text = redact_secret_text(text)[0]
    adapter = gateway.adapters.get(event.source.platform)
    if adapter is None:
        return
    # Let the official Discord adapter handle formatting/Discord message limits.
    await adapter.send(event.source.chat_id, text[:16000],
                       reply_to=event.message_id,
                       metadata={"thread_id": event.source.thread_id} if event.source.thread_id else None)


async def intake(event, gateway, **kwargs):
    """Authorize and deduplicate before retrieval, session creation, or inference.

    Upstream hooks fall through on exceptions, so all our failure paths return
    skip. Service startup separately requires this mandatory plugin to load.
    """
    try:
        b = bridge()
        if not b.authorized(event.source):
            return {"action": "skip", "reason": "quattro-owner-and-destination-denied"}
        if not b.admit(event.source, str(event.message_id)):
            return {"action": "skip", "reason": "quattro-duplicate-or-invalid-event"}
        from hermes_constants import get_default_hermes_root, get_hermes_home
        global_home = get_default_hermes_root()
        if global_home.resolve() != get_hermes_home().resolve() and (global_home / "auth.json").exists():
            await _reply(event, gateway, "BLOCKED: upstream global auth inheritance needs verified account isolation. "
                         "Do not delete or copy another account's credentials to unblock it.")
            return {"action": "skip", "reason": "quattro-global-auth-isolation-blocked"}
        text = event.text or ""
        from quattro_agent.privacy import redact_secret_text
        if redact_secret_text(text)[1]:
            await _reply(event, gateway, "Credential-shaped content refused before inference/retrieval. "
                         "Use secure local setup, never Discord, for credentials.")
            return {"action": "skip", "reason": "quattro-credential-content-denied"}
        # Hermes can inline attachment text into event.text. Such content must
        # never enter our control parser, even when sent by the owner.
        control_safe = (getattr(event, "allow_gateway_control", False)
                        and not getattr(event, "media_urls", [])
                        and not getattr(event, "media_types", [])
                        and not getattr(event, "reply_to_text", None))
        if not control_safe:
            await _reply(event, gateway, "Attachment/quoted/proactive content cannot authorize Quattro actions. "
                         "Send a fresh plain-text message; no task was started.")
            return {"action": "skip", "reason": "quattro-untrusted-control-content"}
        # No attachment/quoted/retrieved text is parsed for approval or execution.
        if any(text == prefix or text.startswith(prefix + " ") for prefix in ("/quattro", "/q")):
            try:
                response = await asyncio.to_thread(b.command, event.source, text)
            except (ValueError, PermissionError, KeyError) as exc:
                response = str(exc)
            await _reply(event, gateway, response)
            return {"action": "skip", "reason": "quattro-command-handled"}
        # Keep native conversation reset/stop usable, but expire old proposals
        # when their originating conversation is reset.
        if text.strip() in {"/new", "/reset", "/stop"}:
            if text.strip() != "/stop":
                with b.connection() as db:
                    db.execute("UPDATE requests SET state='cancelled' WHERE scope=? AND state='pending'",
                               (b.scope(event.source),))
            return None
        # Do not let native /goal persist or execute a request for a /goal prompt.
        # Native profile/model/terminal/skill mutations are intentionally unavailable.
        if text.lstrip().startswith("/"):
            await _reply(event, gateway, "Native mutation/agent commands are disabled in this private profile. "
                         "Use /quattro help, or ask in ordinary text for a prompt or /goal prompt.")
            return {"action": "skip", "reason": "quattro-native-command-denied"}
        match = re.match(r"^Use (Codex|Pi|auto) in project ([a-z][a-z0-9_-]*) to (.+)$", text, re.I | re.S)
        if match:
            response = b.propose(event.source, match[1].lower(), match[2], match[3])
            await _reply(event, gateway, response)
            return {"action": "skip", "reason": "quattro-execution-proposed-not-started"}
        context = await asyncio.to_thread(b.chat_context, event.source, text)
        if context:
            return {"action": "rewrite", "text": text + "\n\n" + context}
        return None
    except Exception:
        # No private error details or input text in gateway logs; deterministic
        # fail-closed even if RAG, local policy, filesystem, or runtime fails.
        try:
            await _reply(event, gateway, "Quattro boundary/retrieval unavailable. "
                         "No inference or execution was authorized for this message; inspect local service status.")
        except Exception:
            pass
        return {"action": "skip", "reason": "quattro-boundary-unavailable"}


def deny_tools(**kwargs):
    return {"action": "block", "message": "Private Hermes conversation tools are disabled. "
            "Controlled execution is available only after the Quattro worker gates pass."}


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", intake)
    ctx.register_hook("pre_tool_call", deny_tools)
    ctx.register_command("quattro", handler=lambda raw_args: HELP,
                         description="Owner-scoped Quattro transport; use /quattro help")
