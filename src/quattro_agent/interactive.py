"""Terminal-native agent selection for interactive Quattro launches."""

from __future__ import annotations

import sys
from typing import TextIO


SUPPORTED_AGENTS = ("codex", "pi")
NATIVE_AGENTS = ("codex", "omp", "pi")


def choose_agent(
    default_agent: str, *, input_stream: TextIO = sys.stdin, output: TextIO = sys.stdout,
    native_selection: bool = False,
) -> str | None:
    """Choose an agent before any durable session is created.

    Non-terminal callers receive the configured default without reading stdin.
    """
    candidates = NATIVE_AGENTS if native_selection else SUPPORTED_AGENTS
    if default_agent not in candidates:
        raise ValueError(f"unsupported configured default agent: {default_agent}")
    if not input_stream.isatty() or not output.isatty():
        return default_agent
    labels = {"codex": "Codex", "pi": "Pi (compatibility)", "omp": "OMP (native always-ask)"}
    if not native_selection:
        labels["pi"] = "Pi"
    while True:
        print("Choose agent:\n", file=output)
        for index, candidate in enumerate(candidates, start=1):
            suffix = " (default)" if candidate == default_agent else ""
            print(f"  {index}. {labels[candidate]}{suffix}", file=output)
        try:
            print(f"\nSelect [1-{len(candidates)}, Enter=default]: ", end="", file=output, flush=True)
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
        for index, candidate in enumerate(candidates, start=1):
            if selection in {str(index), candidate}:
                return candidate
        options = " or ".join(str(index) for index in range(1, len(candidates) + 1))
        print(f"Invalid selection. Choose {options}.\n", file=output, flush=True)
