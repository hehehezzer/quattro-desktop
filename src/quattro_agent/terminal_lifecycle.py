"""Display-safe terminal lifecycle attribution and abnormal-exit retention."""

from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True, slots=True)
class TerminalSignalAttribution:
    """A stable, display-safe classification for a terminal worker signal."""

    number: int
    name: str
    source: str
    cancellation_reason: str
    summary: str

    def event_payload(self, *, tty_attached: bool) -> dict[str, object]:
        return {
            "signal": self.name,
            "signalNumber": self.number,
            "source": self.source,
            "ttyAttached": tty_attached,
        }


def classify_terminal_signal(signum: int) -> TerminalSignalAttribution:
    """Classify only the two signals intentionally handled by `_task-worker`."""

    if signum == signal.SIGHUP:
        return TerminalSignalAttribution(
            number=signum,
            name="SIGHUP",
            source="terminal_or_controlling_pty_closed",
            cancellation_reason="terminal_sighup",
            summary="Terminal or controlling PTY closed; the agent session was stopped safely.",
        )
    if signum == signal.SIGTERM:
        return TerminalSignalAttribution(
            number=signum,
            name="SIGTERM",
            source="worker_termination_requested",
            cancellation_reason="worker_sigterm",
            summary="Terminal worker received SIGTERM; the agent session was stopped safely.",
        )
    raise ValueError(f"unsupported terminal worker signal: {signum}")


def should_retain_after_exit(
    exit_code: int,
    attribution: TerminalSignalAttribution | None,
) -> bool:
    """Retain a visible terminal after abnormal exits when its PTY still exists."""

    if exit_code == 0:
        return False
    return attribution is None or attribution.number != signal.SIGHUP


def retain_abnormal_exit(
    exit_code: int,
    *,
    attribution: TerminalSignalAttribution | None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    """Show the exit reason and wait for acknowledgement on an attached TTY.

    Returns whether the terminal was retained. Non-interactive workers and a
    terminal whose controlling PTY already closed never block.
    """

    if not should_retain_after_exit(exit_code, attribution):
        return False
    try:
        input_is_tty = input_stream.isatty()
        output_is_tty = output_stream.isatty()
    except (AttributeError, OSError):
        return False
    if not input_is_tty or not output_is_tty:
        return False

    reason = (
        f"{attribution.name} ({attribution.source})"
        if attribution is not None
        else f"worker exit code {exit_code}"
    )
    try:
        output_stream.write(
            "\n[quattro-agent] The agent session ended unexpectedly: "
            f"{reason}.\n"
            "[quattro-agent] This terminal is being kept open so the failure "
            "remains visible. Press Enter to close it.\n"
        )
        output_stream.flush()
        input_stream.readline()
    except (BrokenPipeError, OSError):
        return False
    return True
