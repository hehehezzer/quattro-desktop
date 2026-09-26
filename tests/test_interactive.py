"""Terminal-native agent chooser coverage."""

import io
import unittest
from unittest import mock

from quattro_agent.interactive import choose_agent


class TtyStringIO(io.StringIO):
    def isatty(self):
        return True


class InteractiveChooserTests(unittest.TestCase):
    def test_default_numeric_invalid_and_cancel(self):
        for value, expected in (("\n", "pi"), ("1\n", "codex"), ("2\n", "pi")):
            output = TtyStringIO()
            self.assertEqual(
                choose_agent("pi", input_stream=TtyStringIO(value), output=output), expected,
            )
            self.assertIn("Pi (default)", output.getvalue())
        output = TtyStringIO()
        self.assertEqual(
            choose_agent("codex", input_stream=TtyStringIO("5\n2\n"), output=output), "pi",
        )
        self.assertIn("Invalid selection. Choose 1 or 2.", output.getvalue())
        for value in ("q\n", "quit\n", "exit\n", ""):
            self.assertIsNone(
                choose_agent("codex", input_stream=TtyStringIO(value), output=TtyStringIO())
            )

    def test_non_tty_uses_configured_default_without_reading(self):
        stream = mock.Mock()
        stream.isatty.return_value = False
        self.assertEqual(choose_agent("pi", input_stream=stream, output=io.StringIO()), "pi")
        stream.readline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
