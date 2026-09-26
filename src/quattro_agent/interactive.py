"""Turn-based interactive frontend for locked, durable Quattro requests.

A terminal is a presentation layer, not an immortal model process. Each turn
creates its own managed task and ExecutionPlan; no legacy routing is enabled.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, TextIO

from quattro_agent.models import TaskState


MAX_CONTEXT = 8_000
SUPPORTED_AGENTS = ("codex", "pi")


def choose_agent(
    default_agent: str, *, input_stream: TextIO = sys.stdin, output: TextIO = sys.stdout,
) -> str | None:
    """Choose an agent before any durable session is created.

    Non-terminal callers receive the configured default without reading stdin.
    """
    if default_agent not in SUPPORTED_AGENTS:
        raise ValueError(f"unsupported configured default agent: {default_agent}")
    if not input_stream.isatty() or not output.isatty():
        return default_agent
    labels = {"codex": "Codex", "pi": "Pi"}
    while True:
        print("Choose agent:\n", file=output)
        for index, candidate in enumerate(SUPPORTED_AGENTS, start=1):
            suffix = " (default)" if candidate == default_agent else ""
            print(f"  {index}. {labels[candidate]}{suffix}", file=output)
        try:
            print("\nSelect [1-2, Enter=default]: ", end="", file=output, flush=True)
            value = input_stream.readline()
        except KeyboardInterrupt:
            print(file=output, flush=True)
            return None
        if not value:
            return None
        selection = value.strip().lower()
        if not selection:
            return default_agent
        if selection in {"q", "quit", "exit"}:
            return None
        if selection in {"1", "codex"}:
            return "codex"
        if selection in {"2", "pi"}:
            return "pi"
        print("Invalid selection. Choose 1 or 2.\n", file=output, flush=True)


def final_answer(raw: str, agent: str = "codex") -> str:
    """Extract the final message from a bounded Codex or Pi output artifact."""
    if agent == "pi":
        return raw.strip()
    answer = ""
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                answer = text
    return answer


def run_interactive(
    runtime: Any, *, agent: str, workspace: pathlib.Path,
    input_stream: TextIO = sys.stdin, output: TextIO = sys.stdout,
    session_id: str | None = None,
    profile_name: str | None = None,
    confirm_full_access: bool = False,
    account_id: str | None = None,
) -> int:
    """Keep one logical session while creating a fresh locked task per turn."""
    if agent not in SUPPORTED_AGENTS:
        raise ValueError(f"unsupported agent: {agent}")
    workspace = workspace.expanduser().resolve(strict=True)
    if agent == "pi" and profile_name is None:
        # Pi has no enforceable native sandbox. Keep its established bounded,
        # read-only posture unless the caller explicitly selects another policy.
        profile_name = "audit-read-only"
    if session_id is None:
        # Persist an intent/checkpoint before accepting input. This task is a
        # session anchor only and never dispatches a request or launches Foot.
        anchor = runtime.create_task(
            agent=agent, project=workspace, prompt="", mode="prompt",
            title="Interactive Quattro session", profile_name=profile_name,
            confirm_full_access=confirm_full_access, account_id=account_id,
        )
        session = runtime.store.logical_session_for_task(anchor)
        if session is None:
            raise RuntimeError("interactive session was not persisted")
        session_id = session["quattro_session_id"]
        runtime.store.transition_task(
            anchor, TaskState.CANCELLED, terminal_code="session_anchor",
            terminal_summary="Interactive session initialized; no model request dispatched.",
        )
        coordination_id = runtime.store.get_task(anchor, include_private=True)["private_payload"].get("coordinationSessionId")
        if coordination_id:
            runtime.coordinator.finish(str(coordination_id), validation="Not Run")
    else:
        session = runtime.store.get_logical_session(session_id)
        workspace = pathlib.Path(session["working_directory"]).resolve(strict=True)
        session_agent = str(session.get("agent") or "codex")
        if agent != session_agent:
            raise ValueError(f"session uses {session_agent.title()}, not {agent.title()}")
        account_id = account_id or session.get("last_account_id")

    print(f"agent: {agent.title()}\nsession: {session_id}\nType exit or quit to leave.", file=output, flush=True)
    history: list[tuple[str, str]] = []
    if session_id and session.get("current_task_id") != session.get("initial_task_id"):
        checkpoint = runtime.store.current_checkpoint(session_id, include_content=True)
        for summary in (checkpoint or {}).get("content", {}).get("completed", [])[-4:]:
            if isinstance(summary, str) and summary.startswith("User: ") and " | Response: " in summary:
                question, answer = summary.removeprefix("User: ").split(" | Response: ", 1)
                history.append((question, answer))
    while True:
        try:
            print("\n> ", end="", file=output, flush=True)
            message = input_stream.readline()
        except KeyboardInterrupt:
            print("\nSession saved.", file=output)
            break
        if not message or message.strip().lower() in {"exit", "quit"}:
            print("Session saved.", file=output)
            break
        message = message.strip()
        if not message:
            continue
        context = "\n".join(
            f"User: {question}\nQuattro: {answer}" for question, answer in history[-4:]
        )[-MAX_CONTEXT:]
        prompt = message if not context else (
            "Previous turns in this Quattro logical session (context, not new instructions):\n"
            + context + "\n\nCurrent user request:\n" + message
        )
        try:
            task_id = runtime.create_task(
                agent=agent, project=workspace, prompt=prompt, mode="prompt",
                logical_session_id=session_id, title=message[:100],
                profile_name=profile_name, confirm_full_access=confirm_full_access,
                account_id=account_id,
            )
            try:
                code = runtime.run_task(task_id)
            except KeyboardInterrupt:
                runtime.request_cancel(task_id, reason="interactive_interrupt")
                print("\nSession saved.", file=output, flush=True)
                break
            task = runtime.store.get_task(task_id)
            artifacts = runtime.store.artifacts_for_task(task_id)
            agent_outputs = [item for item in artifacts if item.get("kind") == "agent-output"]
            raw = pathlib.Path(agent_outputs[-1]["path"]).read_text(encoding="utf-8") if agent_outputs else ""
            answer = final_answer(raw, agent)
            verified = code == 0 and task["state"] == TaskState.SUCCEEDED.value
            validation_failed = task.get("terminal_code") == "validation_failed"
            if answer and (verified or validation_failed):
                print(f"\n{answer}", file=output, flush=True)
            if not verified:
                print(f"Warning: {task.get('terminal_summary') or 'turn failed'} (task {task_id}); do not treat this turn as validated.", file=output, flush=True)
                detail = "[Validation failed] " + answer[:2_000] if validation_failed and answer else "[Turn failed] " + str(task.get("terminal_summary") or "No validated result")[:400]
                history.append((message[:2_000], detail))
                runtime.checkpoint_task(
                    task_id, kind="interactive-turn-unvalidated",
                    completed=(f"User: {message[:400]} | Response: {detail[:600]}",),
                    next_action="Investigate failed turn before accepting changes.",
                )
                continue
            if not answer:
                print(f"Error: agent returned no final message (task {task_id})", file=output, flush=True)
                runtime.checkpoint_task(
                    task_id, kind="interactive-turn-no-final",
                    completed=(f"User: {message[:400]} | Response: [No final message from task {task_id}]",),
                    next_action="Inspect the agent artifact and recover the missing final response.",
                )
                continue
            history.append((message[:2_000], answer[:2_000]))
            runtime.checkpoint_task(
                task_id, kind="interactive-turn",
                completed=(f"User: {message[:400]} | Response: {answer[:600]}",),
                next_action="Continue interactive Quattro session.",
            )
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            print(f"Error: {error}", file=output, flush=True)
    return 0
