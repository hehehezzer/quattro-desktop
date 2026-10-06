from __future__ import annotations

import importlib.machinery
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

SRC = pathlib.Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
from quattro_harness import HarnessRuntime
from quattro_agent import cli


class GhosttyLaunchTests(unittest.TestCase):
    def test_worker_arguments_preserve_identity_directory_and_process_ownership(self):
        task = {"display_title": "Task with spaces", "project_path": "/tmp/project with spaces"}
        store = mock.Mock()
        store.get_task.return_value = task
        runtime = types.SimpleNamespace(command_resolver=mock.Mock(return_value="/usr/bin/ghostty"),
                                        store=store, script_path=pathlib.Path("/tmp/quattro-agent"))
        with mock.patch("quattro_harness.subprocess.Popen") as popen:
            HarnessRuntime.launch_terminal(runtime, "exact-task")
        runtime.command_resolver.assert_called_once_with("ghostty")
        command = popen.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/ghostty", "--gtk-single-instance=false",
                                  "--class=com.quattro.ai", "--title=Task with spaces",
                                  "--working-directory=/tmp/project with spaces", "-e",
                                  "/tmp/quattro-agent", "_task-worker", "exact-task"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["cwd"], task["project_path"])
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_missing_ghostty_fails_without_spawning(self):
        runtime = types.SimpleNamespace(command_resolver=lambda _: None)
        with mock.patch("quattro_harness.subprocess.Popen") as popen:
            with self.assertRaisesRegex(FileNotFoundError, "ghostty"):
                HarnessRuntime.launch_terminal(runtime, "task")
        popen.assert_not_called()

    def test_discovery_preserves_old_sessions_and_requires_exact_worker_identity(self):
        for name in ("foot", "ghostty", "unrelated"):
            with self.subTest(executable=name), tempfile.TemporaryDirectory() as value:
                root = pathlib.Path(value)
                exe = root / name
                exe.touch()
                process = root / "321"
                process.mkdir()
                (process / "exe").symlink_to(exe)
                (process / "cmdline").write_bytes(
                    f"{exe}\0-e\0quattro-agent\0_task-worker\0task-exact\0".encode())
                expected = 321 if name in {"foot", "ghostty"} else None
                self.assertEqual(cli.session_terminal_pid({"taskId": "task-exact"}, root), expected)
                self.assertIsNone(cli.session_terminal_pid({"taskId": "task-other"}, root))


class GhosttyThemeTests(unittest.TestCase):
    def test_reload_targets_verified_ghostty_with_native_lua_dispatch(self):
        loader = importlib.machinery.SourceFileLoader("quattro_theme_reload_tests", str(SRC / "quattro-theme"))
        module = types.ModuleType(loader.name)
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as value:
            root = pathlib.Path(value)
            proc = root / "proc"
            for pid, name in ((321, "ghostty"), (322, "foot")):
                executable = root / name
                executable.touch()
                process = proc / str(pid)
                process.mkdir(parents=True)
                (process / "exe").symlink_to(executable)
            clients = [{"pid": 321, "address": "0xab12"},
                       {"pid": 322, "address": "0xab13"},
                       {"pid": 321, "address": "0xab12;unsafe"},
                       {"pid": "bad", "address": "0xab14"}]
            result = types.SimpleNamespace(returncode=0, stdout=module.json.dumps(clients))
            with mock.patch.object(module, "Path", side_effect=lambda *parts: proc if parts == ("/proc",) else pathlib.Path(*parts)), mock.patch.object(module.subprocess, "run", return_value=result) as run:
                module.reload_ghostty()
            self.assertEqual(run.call_count, 2)
            command = run.call_args_list[1].args[0]
            self.assertEqual(command, ["hyprctl", "dispatch", 'hl.dsp.send_shortcut({ mods = "CTRL SHIFT", key = "comma", window = "address:0xab12" })'])
            self.assertEqual(run.call_args_list[1].kwargs["timeout"], 2)
            self.assertNotIn("shell", run.call_args_list[1].kwargs)

    def test_reload_unavailable_compositor_is_nonfatal(self):
        loader = importlib.machinery.SourceFileLoader("quattro_theme_unavailable_tests", str(SRC / "quattro-theme"))
        module = types.ModuleType(loader.name)
        loader.exec_module(module)
        with mock.patch.object(module.subprocess, "run", side_effect=OSError("unavailable")):
            module.reload_ghostty()


    def test_palette_writer_matches_every_ansi_color_and_does_not_change_preferences(self):
        loader = importlib.machinery.SourceFileLoader("quattro_theme_ghostty_tests", str(SRC / "quattro-theme"))
        module = types.ModuleType(loader.name)
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as value:
            path = pathlib.Path(value) / "quattro-theme.conf"
            preferences = pathlib.Path(value) / "config"
            preferences.write_text("font-size = 11\n")
            with mock.patch.object(module, "GHOSTTY_THEME_PATH", path):
                for name in module.THEMES:
                    module.write_ghostty_theme(name)
                    content = path.read_text()
                    for index in range(16):
                        self.assertIn(f"palette = {index}={module.FOOT_PALETTES[name][f'color{index}']}", content)
                    self.assertIn("background = " + module.FOOT_PALETTES[name]["background"], content)
            self.assertEqual(preferences.read_text(), "font-size = 11\n")

class GhosttyArtworkTests(unittest.TestCase):
    def load_theme(self):
        loader = importlib.machinery.SourceFileLoader("quattro_theme_artwork_tests", str(SRC / "quattro-theme"))
        module = types.ModuleType(loader.name)
        loader.exec_module(module)
        return module

    def test_theme_artwork_changes_and_missing_artwork_clears_previous_image(self):
        module = self.load_theme()
        with tempfile.TemporaryDirectory() as value:
            root = pathlib.Path(value)
            artwork = root / "art with spaces"
            artwork.mkdir()
            (artwork / "instrument.png").write_bytes(b"synthetic-test-image")
            config = root / "quattro-theme.conf"
            with mock.patch.object(module, "WALLPAPER_DIR", artwork), mock.patch.object(module, "GHOSTTY_THEME_PATH", config):
                module.write_ghostty_theme("instrument")
                self.assertIn(f'background-image = "{artwork / "instrument.png"}"', config.read_text())
                module.write_ghostty_theme("instrument-paper")
                self.assertIn('background-image = ""', config.read_text())
                self.assertNotIn("instrument.png", config.read_text())

    def test_artwork_path_cannot_inject_a_config_line(self):
        module = self.load_theme()
        with tempfile.TemporaryDirectory() as value:
            root = pathlib.Path(value)
            artwork = root / "art\nfont-size = 99"
            artwork.mkdir()
            (artwork / "instrument.png").touch()
            config = root / "quattro-theme.conf"
            with mock.patch.object(module, "WALLPAPER_DIR", artwork), mock.patch.object(module, "GHOSTTY_THEME_PATH", config):
                module.write_ghostty_theme("instrument")
            self.assertIn('background-image = ""', config.read_text())
            self.assertNotIn("font-size", config.read_text())


if __name__ == "__main__":
    unittest.main()
