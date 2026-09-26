"""Terminal-native agent selection for interactive Quattro launches."""

from __future__ import annotations

import sys
from typing import TextIO


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
