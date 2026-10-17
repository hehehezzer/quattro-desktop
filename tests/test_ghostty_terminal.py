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
