"""Hermetic contracts for system controls; live-device checks are separate."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("desktop_controls", Path(__file__).parents[1] / "src/quattro_desktop_controls.py")
desktop = importlib.util.module_from_spec(SPEC)
if sys.platform == "linux":
    SPEC.loader.exec_module(desktop)


@unittest.skipUnless(sys.platform == "linux", "Desktop controls require Linux")
class DesktopControlsTests(unittest.TestCase):
    def test_coordinates_validate_finiteness_and_bounds(self):
        for lat, lon in [(91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))]:
            with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                desktop.coordinates(lat, lon)
        self.assertEqual(desktop.coordinates(-90, 180), (-90, 180))

    def test_eq_validation(self):
        for gains in [[0] * 9, [13] * 10, [float("nan")] * 10]:
            with self.assertRaises(ValueError):
                desktop.gains_valid(gains)
        for values in desktop.PRESETS.values():
            self.assertEqual(len(desktop.gains_valid(values)), 10)

    def test_eq_graph_and_safe_preamp(self):
        graph = desktop.eq_config([6] + [0] * 9, "sink.with-safe-name")
        self.assertIn('"Gain 1" = 0.501187', graph)
        self.assertIn('"eq9:Out"', graph)
        self.assertIn('"target.object" = "sink.with-safe-name"', graph)
        self.assertNotIn(",", graph)
        self.assertIn('"Gain 1" = 1.0', desktop.eq_config([0] * 10, "sink"))

    def test_weather_missing_location_does_not_access_network(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(desktop, "CONFIG", Path(temp)), patch.object(desktop.urllib.request, "urlopen") as urlopen:
            self.assertFalse(desktop.weather()["configured"])
            urlopen.assert_not_called()

    def test_weather_cached_location_and_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(desktop, "CONFIG", root / "config"), patch.object(desktop, "CACHE", root / "cache"):
                desktop.atomic(desktop.CONFIG / "weather.json", json.dumps({"latitude": 10, "longitude": 20}))
                record = {"location": [10, 20], "updated": desktop.time.time(), "available": True, "temperature": 5}
                desktop.atomic(desktop.CACHE / "weather.json", json.dumps(record))
                with patch.object(desktop.urllib.request, "urlopen", side_effect=OSError("offline")) as request:
                    self.assertEqual(desktop.weather()["temperature"], 5)
                    request.assert_not_called()
                    stale = desktop.weather(force=True)
                    self.assertTrue(stale["stale"])
                    self.assertTrue(stale["cached"])
                    desktop.atomic(desktop.CONFIG / "weather.json", json.dumps({"latitude": 30, "longitude": 20}))
                    self.assertFalse(desktop.weather(force=True)["available"])

    def test_atomic_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state"
            desktop.atomic(path, "{}")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_critical_processes_protected(self):
        for exe in ["quickshell", "Hyprland", "systemd", "wireplumber", "pipewire", "xdg-desktop-portal-hyprland"]:
            self.assertTrue(desktop.protected(123, exe))

    def test_stale_window_cannot_be_signalled(self):
        with patch.object(desktop, "clients", return_value=[]), patch.object(desktop.os, "pidfd_open") as open_pid:
            with self.assertRaises(ValueError):
                desktop.application_action("terminate", "0x123", 123, "456")
            open_pid.assert_not_called()

    def test_pid_identity_rechecked_before_signal(self):
        with patch.object(desktop, "clients", return_value=[{"address": "0x123", "pid": 123}]), patch.object(desktop.os, "pidfd_open", return_value=7), patch.object(desktop.os, "close"), patch.object(desktop, "process_identity", return_value=("new-start", "foot")), patch.object(desktop.signal, "pidfd_send_signal") as send:
            with self.assertRaises(ValueError):
                desktop.application_action("terminate", "0x123", 123, "old-start")
            send.assert_not_called()

    def test_exact_pid_termination_with_real_pidfd(self):
        child = subprocess.Popen(["sleep", "30"])
        try:
            start, _ = desktop.process_identity(child.pid)
            with patch.object(desktop, "clients", return_value=[{"address": "0x123", "pid": child.pid}]):
                result = desktop.application_action("terminate", "0x123", child.pid, start)
            self.assertTrue(result["ok"])
            child.wait(timeout=3)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait()

    def test_lua_window_actions_use_validated_exact_selector(self):
        with patch.object(desktop, "clients", return_value=[{"address": "0x123", "pid": 123}]), patch.object(desktop.os, "pidfd_open", return_value=7), patch.object(desktop.os, "close"), patch.object(desktop, "process_identity", return_value=("456", "test")), patch.object(desktop, "protected", return_value=False), patch.object(desktop, "run") as run:
            desktop.application_action("open", "0x123", 123, "456")
            run.assert_called_once_with(["hyprctl", "eval", 'hl.dispatch(hl.dsp.focus({window="address:0x123"}))'])
        with self.assertRaises(ValueError):
            desktop.application_action("close", '0x123"; malicious()', 123, "456")

    def test_force_requires_explicit_second_action(self):
        with patch.object(desktop, "clients", return_value=[{"address": "0x123", "pid": 123}]), patch.object(desktop.os, "pidfd_open", return_value=7), patch.object(desktop.os, "close"), patch.object(desktop, "process_identity", return_value=("456", "test")), patch.object(desktop, "protected", return_value=False), patch.object(desktop.select, "select", return_value=([], [], [])), patch.object(desktop.signal, "pidfd_send_signal") as send:
            self.assertTrue(desktop.application_action("terminate", "0x123", 123, "456")["needsForce"])
            send.assert_called_once_with(7, desktop.signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
