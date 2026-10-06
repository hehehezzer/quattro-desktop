"""Opt-in native selection never turns a configured preference into approval."""
from contextlib import ExitStack
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from quattro_agent import cli
from quattro_agent.config import validate_ai_config
from quattro_agent.errors import ConfigError
from quattro_agent.interactive import choose_agent


class TtyStringIO(io.StringIO):
    def isatty(self):
        return True


NATIVE = {"preferredAgent": "omp", "skillsCatalog": "/opt/quattro/skills",
          "herdrSocket": "/run/user/1000/herdr/quattro.sock"}


class NativeConfigTests(unittest.TestCase):
    def source(self):
        return json.loads((Path(__file__).resolve().parents[1] / "examples/ai.json").read_text())

    def test_optional_section_preserves_legacy_default(self):
        source = self.source()
        self.assertNotIn("nativeSession", validate_ai_config(source))
        source["nativeSession"] = dict(NATIVE)
        result = validate_ai_config(source)
        self.assertEqual(result["nativeSession"], NATIVE)
        self.assertEqual(result["defaultAgent"], source["defaultAgent"])
        result["nativeSession"]["preferredAgent"] = "codex"
        self.assertEqual(source["nativeSession"]["preferredAgent"], "omp")

    def test_strict_native_fields_and_absolute_paths(self):
        bad_sections = [
            {**NATIVE, "preferredAgent": "pi"}, {**NATIVE, "confirmed": True},
            {**NATIVE, "preferredAgent": {}},
            {**NATIVE, "policy": "full-access"}, {**NATIVE, "skillsCatalog": "~/skills"},
            {**NATIVE, "herdrSocket": "relative.sock"},
            {**NATIVE, "herdrSocket": "/run/../private.sock"},
            {**NATIVE, "skillsCatalog": "/"},
            {"preferredAgent": "omp"},
        ]
        for section in bad_sections:
            with self.subTest(section=section):
                source = self.source()
                source["nativeSession"] = section
                with self.assertRaises(ConfigError):
                    validate_ai_config(source)
        source = self.source()
        source["defaultAgent"] = "omp"
        self.assertEqual(validate_ai_config(source)["defaultAgent"], "omp")


class NativeChooserTests(unittest.TestCase):
    def test_configured_native_chooser_retains_explicit_pi_compatibility(self):
        for selection, expected in (("\n", "omp"), ("2\n", "omp"), ("3\n", "pi")):
            output = TtyStringIO()
            self.assertEqual(choose_agent("omp", input_stream=TtyStringIO(selection),
                                         output=output, native_selection=True), expected)
            self.assertIn("OMP (native always-ask) (default)", output.getvalue())
            self.assertIn("Pi (compatibility)", output.getvalue())

    def test_native_non_terminal_default_does_not_read_stdin(self):
        stream = mock.Mock()
        stream.isatty.return_value = False
        self.assertEqual(choose_agent("omp", input_stream=stream, output=io.StringIO(),
                                     native_selection=True), "omp")
        stream.readline.assert_not_called()


class NativeLaunchTests(unittest.TestCase):
    def launch(self, arguments, config, chooser=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(cli.sys, "argv", ["quattro-agent", *arguments]))
        stack.enter_context(mock.patch.object(cli, "ensure_state_dirs"))
        stack.enter_context(mock.patch.object(cli, "load_config", return_value=config))
        stack.enter_context(mock.patch.object(cli, "safe_directory", return_value=Path("/tmp")))
        stack.enter_context(mock.patch.object(cli, "tool_environment", return_value={"PATH": "/bin"}))
        stack.enter_context(mock.patch.object(cli.sys, "stdout", io.StringIO()))
        if chooser is not None:
            stack.enter_context(mock.patch("quattro_agent.interactive.choose_agent", return_value=chooser))
        return stack

    def test_default_omp_without_confirmation_never_starts_a_session(self):
        stack = self.launch(["launch"], {"defaultAgent": "codex", "nativeSession": NATIVE}, "omp")
        start = stack.enter_context(mock.patch("quattro_agent.migration_cli.start_omp"))
        handoff = stack.enter_context(mock.patch.object(cli, "native_interactive_handoff"))
        with self.assertRaises(SystemExit):
            cli.main()
        start.assert_not_called()
        handoff.assert_not_called()

    def test_chooser_omp_reaches_exact_configured_herdr_route(self):
        stack = self.launch(["launch", "--confirm-native-access"],
                            {"defaultAgent": "pi", "nativeSession": NATIVE}, "omp")
        start = stack.enter_context(mock.patch("quattro_agent.migration_cli.start_omp", return_value=0))
        handoff = stack.enter_context(mock.patch.object(cli, "native_interactive_handoff"))
        self.assertEqual(cli.main(), 0)
        start.assert_called_once_with(Path("/tmp"), skills=NATIVE["skillsCatalog"],
                                      socket=NATIVE["herdrSocket"], confirmed=True)
        handoff.assert_not_called()

    def test_explicit_catalog_and_socket_override_only_this_launch(self):
        stack = self.launch(["launch", "omp", "--confirm-native-access", "--skills", "/opt/other",
                             "--socket", "/run/private/other.sock"],
                            {"defaultAgent": "codex", "nativeSession": NATIVE})
        start = stack.enter_context(mock.patch("quattro_agent.migration_cli.start_omp", return_value=0))
        self.assertEqual(cli.main(), 0)
        start.assert_called_once_with(Path("/tmp"), skills="/opt/other",
                                      socket="/run/private/other.sock", confirmed=True)
        self.assertEqual(NATIVE["herdrSocket"], "/run/user/1000/herdr/quattro.sock")

    def test_explicit_omp_without_native_section_preserves_direct_route(self):
        stack = self.launch(["launch", "omp", "--skills", "/opt/skills", "--confirm-native-access"],
                            {"defaultAgent": "codex"})
        direct = stack.enter_context(mock.patch("quattro_agent.migration_cli.launch_omp", return_value=0))
        self.assertEqual(cli.main(), 0)
        direct.assert_called_once_with(Path("/tmp"), skills="/opt/skills", confirmed=True,
                                       environment={"PATH": "/bin"})

    def test_omp_default_without_native_section_uses_real_chooser(self):
        stack = self.launch(["launch", "--skills", "/opt/skills", "--confirm-native-access"],
                            {"defaultAgent": "omp"})
        stack.enter_context(mock.patch.object(cli.sys, "stdin", io.StringIO()))
        direct = stack.enter_context(mock.patch("quattro_agent.migration_cli.launch_omp", return_value=0))
        self.assertEqual(cli.main(), 0)
        direct.assert_called_once_with(Path("/tmp"), skills="/opt/skills", confirmed=True,
                                       environment={"PATH": "/bin"})

    def test_omp_default_without_native_section_still_requires_confirmation(self):
        stack = self.launch(["launch"], {"defaultAgent": "omp"})
        stack.enter_context(mock.patch.object(cli.sys, "stdin", io.StringIO()))
        direct = stack.enter_context(mock.patch("quattro_agent.migration_cli.launch_omp"))
        with self.assertRaises(SystemExit) as outcome:
            cli.main()
        self.assertEqual(outcome.exception.code, 1)
        direct.assert_not_called()

    def test_herdr_child_reference_reaches_verifier_without_recursive_start(self):
        stack = self.launch(["launch", "omp", "--confirm-native-access",
                             "--native-session-ref", "native-opaque"],
                            {"defaultAgent": "codex", "nativeSession": NATIVE})
        direct = stack.enter_context(mock.patch("quattro_agent.migration_cli.launch_omp", return_value=0))
        self.assertEqual(cli.main(), 0)
        direct.assert_called_once_with(Path("/tmp"), skills=NATIVE["skillsCatalog"],
                                       confirmed=True, environment={"PATH": "/bin"},
                                       native_session_ref="native-opaque")

    def test_policy_and_full_access_cannot_override_native_approval(self):
        for extra in (["--policy", "audit-read-only"], ["--confirm-full-access"]):
            with self.subTest(extra=extra):
                stack = self.launch(["launch", "omp", "--confirm-native-access", *extra],
                                    {"defaultAgent": "codex", "nativeSession": NATIVE})
                start = stack.enter_context(mock.patch("quattro_agent.migration_cli.start_omp"))
                with self.assertRaises(SystemExit):
                    cli.main()
                start.assert_not_called()
                stack.close()

    def test_native_flags_cannot_be_silently_ignored_by_codex(self):
        stack = self.launch(["launch", "codex", "--confirm-native-access"], {"defaultAgent": "codex"})
        handoff = stack.enter_context(mock.patch.object(cli, "native_interactive_handoff"))
        with self.assertRaises(SystemExit):
            cli.main()
        handoff.assert_not_called()


if __name__ == "__main__":
    unittest.main()
