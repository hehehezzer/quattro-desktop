from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).parents[1] / "src"
SYSTEM_PANELS = SRC / "quickshell" / "components" / "SystemPanels.qml"
MAIN_MENU = SRC / "quickshell" / "components" / "MainMenu.qml"
BAR = SRC / "quickshell" / "components" / "Bar.qml"
SESSION = SRC / "quattro-session"


def load_script(module_name: str, filename: str):
    loader = importlib.machinery.SourceFileLoader(module_name, str(SRC / filename))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


stats = load_script("quattro_system_stats", "quattro-system-stats")
night = load_script("quattro_night_light", "quattro-night-light")


class SystemStatsTests(unittest.TestCase):
    def test_cpu_percent_uses_aggregate_counter_deltas(self):
        self.assertEqual(stats.cpu_percent((1000, 400), (1100, 440)), 60.0)
        self.assertEqual(stats.cpu_percent((1000, 400), (1000, 400)), 0.0)

    def test_snapshot_is_display_safe_and_bounded(self):
        with mock.patch.object(stats, "read_memory", return_value=(8 * 1024**3, 16 * 1024**3)):
            value = stats.snapshot((1000, 400), (1100, 440))
        self.assertEqual(value["schemaVersion"], 1)
        self.assertEqual(value["cpuPercent"], 60.0)
        self.assertEqual(value["ramPercent"], 50.0)
        self.assertEqual(value["ramUsedBytes"], 8 * 1024**3)
        self.assertNotIn("processes", value)

    def test_bar_has_distinct_cpu_and_ram_hover_tooltips(self):
        content = BAR.read_text(encoding="utf-8")
        self.assertIn("id: cpuStatsMouse", content)
        self.assertIn("id: ramStatsMouse", content)
        self.assertIn('"CPU usage · "', content)
        self.assertIn('"RAM usage · "', content)
        self.assertIn("Aggregate processor load", content)
        self.assertIn("GiB in use", content)

    def test_system_stats_tooltip_is_positioned_from_the_hovered_item(self):
        content = BAR.read_text(encoding="utf-8")
        self.assertIn("function positionSystemStatsPopup()", content)
        self.assertIn("id: cpuStatsItem", content)
        self.assertIn("id: ramStatsItem", content)
        self.assertIn("target.mapToItem(", content)
        self.assertIn("root.width - systemStatsPopup.implicitWidth - 8", content)
        self.assertIn("anchor.rect.x: Math.round(root.systemStatsPopupX)", content)
        self.assertIn("root.systemStatsPopupPositioned", content)


class NightLightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.temp.name)
        self.config_patch = mock.patch.object(night, "CONFIG_PATH", root / "night-light.json")
        self.shader_patch = mock.patch.object(night, "SHADER_DIR", root / "shaders")
        self.config_patch.start()
        self.shader_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.shader_patch.stop()
        self.temp.cleanup()

    def test_invalid_state_defaults_to_filter_off(self):
        self.assertEqual(night.current_preset(), "off")
        night.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        night.CONFIG_PATH.write_text('{"preset":"unknown"}', encoding="utf-8")
        self.assertEqual(night.current_preset(), "off")

    def test_config_is_versioned_and_presets_are_allowlisted(self):
        night.write_config("warm")
        self.assertEqual(
            json.loads(night.CONFIG_PATH.read_text(encoding="utf-8")),
            {
                "schemaVersion": 1,
                "preset": "warm",
                "label": "Warm",
                "temperature": 4200,
                "active": True,
            },
        )
        self.assertEqual(tuple(night.PRESETS), ("off", "soft", "warm", "deep"))

    def test_shader_generation_uses_modern_hyprland_contract(self):
        night.ensure_shaders()
        content = (night.SHADER_DIR / "warm.frag").read_text(encoding="utf-8")
        self.assertIn("#version 300 es", content)
        self.assertIn("uniform sampler2D tex", content)
        self.assertIn("vec3(1.0000, 0.8200, 0.6600)", content)
        self.assertIn("1.0);", content)
        self.assertNotIn("warm.frag", (night.SHADER_DIR / "soft.frag").read_text(encoding="utf-8"))

    def test_unchanged_active_shaders_are_not_replaced(self):
        night.ensure_shaders()
        with mock.patch.object(night, "atomic_write") as write:
            night.ensure_shaders()
        write.assert_not_called()

    def test_apply_uses_fixed_lua_config_without_shell(self):
        with mock.patch.object(night.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(night.apply_preset("deep"))
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["hyprctl", "eval"])
        self.assertIn("screen_shader", command[2])
        self.assertIn("deep.frag", command[2])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_off_clears_screen_shader(self):
        with mock.patch.object(night.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(night.apply_preset("off"))
        self.assertIn('screen_shader = ""', run.call_args.args[0][2])

    def test_quickshell_serializes_changes_with_a_settle_cooldown(self):
        content = SYSTEM_PANELS.read_text(encoding="utf-8")
        self.assertIn("id: nightLightCooldown", content)
        self.assertIn("interval: 900", content)
        self.assertIn("enabled: !root.nightLightBusy", content)


class SessionLockTests(unittest.TestCase):
    def test_every_desktop_lock_entry_uses_the_fail_safe_helper(self):
        for path in (MAIN_MENU, SYSTEM_PANELS):
            content = path.read_text(encoding="utf-8")
            self.assertIn('property string sessionCommand:', content)
            self.assertIn('[root.sessionCommand, "lock"]', content)
            self.assertNotIn('[\n                                "hyprlock"\n                            ]', content)

    def test_lock_helper_never_switches_vt_or_performs_an_unauthenticated_unlock(self):
        content = SESSION.read_text(encoding="utf-8")
        self.assertIn('readonly HYPRLOCK_BIN="/usr/bin/hyprlock"', content)
        self.assertIn('exec "$HYPRLOCK_BIN"', content)
        self.assertIn('auth[[:space:]]+include[[:space:]]+login', content)
        self.assertIn('readonly SUDO_PAM="/etc/pam.d/sudo"', content)
        self.assertIn('readonly SYSTEM_AUTH_PAM="/etc/pam.d/system-auth"', content)
        self.assertIn('secure_root_file "$HYPRLOCK_BIN"', content)
        self.assertIn('"$SYSTEM_LOGIN_PAM" "$SYSTEM_AUTH_PAM" "$SUDO_PAM"', content)
        self.assertIn('sudo and hyprlock do not share the expected account authentication stack', content)
        self.assertNotIn("chvt ", content)
        self.assertNotIn("loginctl unlock-session", content)
        self.assertNotIn("setsid hyprlock", content)
        self.assertNotIn("sleep 0.", content)
        self.assertNotIn("exec sudo", content)
        self.assertNotIn("/usr/bin/sudo", content)

    def test_failed_trust_preflight_never_executes_hyprlock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            binary_dir = root / "bin"
            pam_dir = root / "pam"
            binary_dir.mkdir()
            pam_dir.mkdir()
            marker = root / "hyprlock-ran"
            hyprlock = binary_dir / "hyprlock"
            hyprlock.write_text(
                f"#!/bin/sh\nprintf ran > {marker}\n",
                encoding="utf-8",
            )
            hyprlock.chmod(0o755)
            pgrep = binary_dir / "pgrep"
            pgrep.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in *Hyprland*) exit 0;; *hyprlock*) exit 1;; esac\n"
                "exit 1\n",
                encoding="utf-8",
            )
            pgrep.chmod(0o755)

            files = {
                "HYPRLOCK_PAM": (pam_dir / "hyprlock", "auth include login\n"),
                "LOGIN_PAM": (pam_dir / "login", "auth include system-local-login\n"),
                "LOCAL_LOGIN_PAM": (pam_dir / "system-local-login", "auth include system-login\n"),
                "SYSTEM_LOGIN_PAM": (pam_dir / "system-login", "auth include system-auth\n"),
                "SYSTEM_AUTH_PAM": (pam_dir / "system-auth", "auth required pam_unix.so\n"),
                "SUDO_PAM": (pam_dir / "sudo", "auth include system-auth\n"),
                "HYPRLOCK_CONFIG": (root / "hyprlock.conf", "input-field { monitor = }\n"),
            }
            for path, value in files.values():
                path.write_text(value, encoding="utf-8")
                path.chmod(0o644)

            script = SESSION.read_text(encoding="utf-8")
            script = script.replace('/usr/bin/hyprlock', str(hyprlock))
            for name, (path, _value) in files.items():
                old = next(
                    line for line in script.splitlines()
                    if line.startswith(f'readonly {name}=')
                )
                script = script.replace(old, f'readonly {name}="{path}"')
            trusted_owner = f"{hyprlock.owner()}:{hyprlock.group()}"
            script = script.replace(
                'readonly TRUSTED_OWNER="root:root"',
                f'readonly TRUSTED_OWNER="{trusted_owner}"',
            )
            helper = root / "quattro-session"
            helper.write_text(script, encoding="utf-8")
            helper.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{binary_dir}:{os.environ.get('PATH', '')}",
                "WAYLAND_DISPLAY": "wayland-test",
                "XDG_RUNTIME_DIR": str(root),
            }

            passed = subprocess.run(
                [str(helper), "lock"], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertTrue(marker.is_file())

            marker.unlink()
            files["SYSTEM_AUTH_PAM"][0].chmod(0o666)
            failed_pam = subprocess.run(
                [str(helper), "lock"], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=False,
            )
            self.assertNotEqual(failed_pam.returncode, 0)
            self.assertFalse(marker.exists())

            files["SYSTEM_AUTH_PAM"][0].chmod(0o644)
            hyprlock.chmod(0o777)
            failed_binary = subprocess.run(
                [str(helper), "lock"], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=False,
            )
            self.assertNotEqual(failed_binary.returncode, 0)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
