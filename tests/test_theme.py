from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import pathlib
import re
import tempfile
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
APP_THEME = SRC / "app-theme"
LOADER = importlib.machinery.SourceFileLoader("quattro_theme", str(SRC / "quattro-theme"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
theme = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(theme)


class ThemeTests(unittest.TestCase):
    def test_small_text_tokens_keep_readable_contrast_on_raised_surfaces(self):
        qml = (SRC / "quickshell/theme/Theme.qml").read_text(encoding="utf-8")

        def colors(token):
            match = re.search(
                rf"property color {token}:([\s\S]*?)(?=\n\s*(?:property|readonly property) color |\n\s*Behavior on )",
                qml,
            )
            self.assertIsNotNone(match, token)
            values = re.findall(r'"(#[0-9a-fA-F]{6})"', match.group(1))
            self.assertEqual(len(values), 5, token)
            return values

        def luminance(hex_color):
            channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

        for surface, dim, muted in zip(colors("hover"), colors("textDim"), colors("textMuted")):
            with self.subTest(surface=surface):
                for text_color in (dim, muted):
                    light, dark = sorted((luminance(surface), luminance(text_color)), reverse=True)
                    self.assertGreaterEqual((light + 0.05) / (dark + 0.05), 4.5)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = pathlib.Path(self.temp.name) / "theme.json"
        self.foot_theme = pathlib.Path(self.temp.name) / "quattro-theme.ini"
        self.config_patch = mock.patch.object(theme, "CONFIG_PATH", self.config)
        self.foot_patch = mock.patch.object(theme, "FOOT_THEME_PATH", self.foot_theme)
        self.config_patch.start()
        self.foot_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.foot_patch.stop()
        self.temp.cleanup()

    def test_missing_or_invalid_config_uses_lofi_noir(self):
        self.assertEqual(theme.current_theme(), "lofi-noir")
        self.config.write_text('{"theme":"unknown"}', encoding="utf-8")
        self.assertEqual(theme.current_theme(), "lofi-noir")

    def test_write_theme_is_versioned_and_readable(self):
        theme.write_theme("terminal")
        self.assertEqual(theme.current_theme(), "terminal")
        self.assertEqual(
            json.loads(self.config.read_text(encoding="utf-8")),
            {"schemaVersion": 1, "theme": "terminal"},
        )

    def test_hyprland_apply_uses_validated_internal_palette(self):
        with mock.patch.object(theme.subprocess, "run") as run:
            theme.apply_hyprland("graphite")
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["hyprctl", "eval"])
        self.assertIn("rgba(626a75ff)", command[2])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_foot_theme_contains_matching_background_text_and_ansi_palette(self):
        theme.write_foot_theme("terminal")
        content = self.foot_theme.read_text(encoding="utf-8")
        self.assertIn("[colors-dark]", content)
        self.assertIn("background=0f1c14", content)
        self.assertIn("foreground=bfcfc3", content)
        self.assertIn("cursor=0f1c14 88a98f", content)
        self.assertIn("regular0=0d1711", content)
        self.assertIn("bright7=d9e5dc", content)

    def test_foot_reload_signals_only_foot_processes(self):
        with mock.patch.object(theme.subprocess, "run") as run:
            theme.reload_foot()
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(calls, [
            ["pkill", "-USR1", "-x", "foot"],
            ["pkill", "-USR1", "-x", "footclient"],
        ])

    def test_theme_catalog_contains_only_supported_dark_variants(self):
        self.assertEqual(
            theme.THEMES,
            (
                "lofi-noir",
                "graphite",
                "terminal",
                "cyberpunk-2077",
                "avengers-doomsday",
            ),
        )

    def test_public_distribution_uses_theme_colors_and_optional_user_artwork(self):
        background = (SRC / "quickshell/components/ThemeBackground.qml").read_text(encoding="utf-8")
        self.assertIn("QUATTRO_WALLPAPER_DIR", background)
        self.assertIn("QuattroTheme.Theme.background", background)
        self.assertFalse((SRC / "wallpapers").exists())
        self.assertFalse((SRC / "wallpaper-sources").exists())

    def test_cyberpunk_palette_coordinates_shell_terminal_and_hyprland(self):
        theme.write_foot_theme("cyberpunk-2077")
        content = self.foot_theme.read_text(encoding="utf-8")
        self.assertIn("background=101827", content)
        self.assertIn("cursor=101827 fcee09", content)
        self.assertIn("urls=00f0ff", content)
        self.assertEqual(
            theme.HYPR_BORDERS["cyberpunk-2077"],
            ("rgba(fcee09ff)", "rgba(25354aff)"),
        )

    def test_avengers_doomsday_palette_coordinates_shell_terminal_and_hyprland(self):
        theme.write_foot_theme("avengers-doomsday")
        content = self.foot_theme.read_text(encoding="utf-8")
        self.assertIn("background=0d110f", content)
        self.assertIn("cursor=0d110f 8fb99a", content)
        self.assertIn("urls=72b894", content)
        self.assertEqual(
            theme.HYPR_BORDERS["avengers-doomsday"],
            ("rgba(8fb99aff)", "rgba(33443aff)"),
        )

    def test_application_dark_mode_contract_is_tracked(self):
        gtk3 = (APP_THEME / "gtk-3.0" / "settings.ini").read_text(encoding="utf-8")
        gtk4 = (APP_THEME / "gtk-4.0" / "settings.ini").read_text(encoding="utf-8")
        obsidian = json.loads(
            (APP_THEME / "obsidian" / "appearance.json").read_text(encoding="utf-8")
        )
        brave = (APP_THEME / "brave-flags.conf").read_text(encoding="utf-8")
        files = (
            APP_THEME / "applications" / "org.gnome.Nautilus.desktop"
        ).read_text(encoding="utf-8")

        self.assertIn("gtk-application-prefer-dark-theme=1", gtk3)
        self.assertIn("gtk-application-prefer-dark-theme=1", gtk4)
        self.assertEqual(obsidian["theme"], "obsidian")
        self.assertIn("--force-dark-mode", brave)
        self.assertIn("GDK_BACKEND=x11", files)


if __name__ == "__main__":
    unittest.main()
