from __future__ import annotations

import io
import pathlib
import os
import pty
import select
import signal
import subprocess
import sys
import time
import unittest


SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))

from quattro_agent.terminal_lifecycle import (
    classify_terminal_signal,
    retain_abnormal_exit,
    should_retain_after_exit,
)


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class NonTtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return False


class TerminalLifecycleTests(unittest.TestCase):
    def test_sighup_is_attributed_to_terminal_or_pty_close(self):
        attribution = classify_terminal_signal(signal.SIGHUP)

        self.assertEqual(attribution.name, "SIGHUP")
        self.assertEqual(attribution.source, "terminal_or_controlling_pty_closed")
        self.assertEqual(attribution.cancellation_reason, "terminal_sighup")
        self.assertEqual(
            attribution.event_payload(tty_attached=False),
            {
                "signal": "SIGHUP",
                "signalNumber": signal.SIGHUP,
                "source": "terminal_or_controlling_pty_closed",
                "ttyAttached": False,
            },
        )

    def test_sigterm_is_attributed_to_external_worker_termination(self):
        attribution = classify_terminal_signal(signal.SIGTERM)

        self.assertEqual(attribution.name, "SIGTERM")
        self.assertEqual(attribution.source, "worker_termination_requested")
        self.assertEqual(attribution.cancellation_reason, "worker_sigterm")

    def test_other_signals_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported terminal worker signal"):
            classify_terminal_signal(signal.SIGINT)

    def test_only_abnormal_non_sighup_exits_are_retained(self):
        self.assertFalse(should_retain_after_exit(0, None))
        self.assertTrue(should_retain_after_exit(1, None))
        self.assertTrue(
            should_retain_after_exit(130, classify_terminal_signal(signal.SIGTERM))
        )
        self.assertFalse(
            should_retain_after_exit(130, classify_terminal_signal(signal.SIGHUP))
        )

    def test_abnormal_tty_exit_is_visible_until_acknowledged(self):
        input_stream = TtyBuffer("\n")
        output_stream = TtyBuffer()

        retained = retain_abnormal_exit(
            1,
            attribution=None,
            input_stream=input_stream,
            output_stream=output_stream,
        )

        self.assertTrue(retained)
        self.assertIn("worker exit code 1", output_stream.getvalue())
        self.assertIn("Press Enter to close", output_stream.getvalue())

    def test_non_tty_exit_never_blocks(self):
        output_stream = NonTtyBuffer()

        retained = retain_abnormal_exit(
            1,
            attribution=None,
            input_stream=NonTtyBuffer(""),
            output_stream=output_stream,
        )

        self.assertFalse(retained)
        self.assertEqual(output_stream.getvalue(), "")

    def test_sighup_never_attempts_to_retain_closed_terminal(self):
        output_stream = TtyBuffer()

        retained = retain_abnormal_exit(
            130,
            attribution=classify_terminal_signal(signal.SIGHUP),
            input_stream=TtyBuffer("\n"),
            output_stream=output_stream,
        )

        self.assertFalse(retained)
        self.assertEqual(output_stream.getvalue(), "")

    def test_process_level_abnormal_exit_waits_for_terminal_acknowledgement(self):
        master_fd, slave_fd = pty.openpty()
        script = (
            "import sys\n"
            "from quattro_agent.terminal_lifecycle import retain_abnormal_exit\n"
            "retain_abnormal_exit(7, attribution=None, input_stream=sys.stdin, "
            "output_stream=sys.stdout)\n"
            "raise SystemExit(7)\n"
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(SRC)
        process = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=environment,
            close_fds=True,
        )
        os.close(slave_fd)
        output = bytearray()
        deadline = time.monotonic() + 5
        try:
            while time.monotonic() < deadline and b"Press Enter to close" not in output:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    output.extend(os.read(master_fd, 4096))
            self.assertIn(b"worker exit code 7", output)
            self.assertIsNone(process.poll())

            os.write(master_fd, b"\n")
            self.assertEqual(process.wait(timeout=5), 7)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master_fd)


if __name__ == "__main__":
    unittest.main()
