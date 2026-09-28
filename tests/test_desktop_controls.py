"""Hermetic contracts for system controls; live-device checks are separate."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location("desktop_controls", Path(__file__).parents[1] / "src/quattro_desktop_controls.py")
desktop = importlib.util.module_from_spec(SPEC)
if sys.platform == "linux":
    SPEC.loader.exec_module(desktop)


@unittest.skipUnless(sys.platform == "linux", "Desktop controls require Linux")
class DesktopControlsTests(unittest.TestCase):
    def test_audio_ipc_serializes_only_stable_eq_fields(self):
        qml = (Path(__file__).parents[1] / "src/quickshell/components/panels/AudioPanel.qml").read_text()
        self.assertNotIn("eq: equalizer.snapshot}", qml)
        for field in ("active", "enabled", "degraded", "preset"):
            self.assertIn(field + ": equalizer.", qml)

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

    def test_eq_recovery_bypasses_dead_virtual_sink(self):
        sinks = [
            {"index": 10, "name": "quattro_eq"},
            {"index": 11, "name": "talker_meeting_mix"},
            {"index": 12, "name": "alsa_output.pci-hdmi"},
        ]
        streams = [{"index": 20, "sink": 10, "properties": {"node.name": "spotify"}}]
        with tempfile.TemporaryDirectory() as temp, patch.object(desktop, "CONFIG", Path(temp)), \
                patch.object(desktop, "run") as run:
            desktop.atomic(desktop.CONFIG / "equalizer.json", json.dumps({
                "enabled": True, "target": "missing-ephemeral-id", "gains": [0] * 10,
            }))
            run.side_effect = [json.dumps(sinks), "alsa_output.usb-wrong\n", "", json.dumps(streams), ""]
            result = desktop.eq_recover("test failure")
        self.assertFalse(result["enabled"])
        self.assertTrue(result["degraded"])
        self.assertEqual(result["target"], "alsa_output.pci-hdmi")
        self.assertIn((["pactl", "set-default-sink", "alsa_output.pci-hdmi"],),
                      [call.args for call in run.call_args_list])
        self.assertIn((["pactl", "move-sink-input", "20", "alsa_output.pci-hdmi"],),
                      [call.args for call in run.call_args_list])

    def test_only_alsa_outputs_are_eligible_eq_targets(self):
        sinks = [{"name": "quattro_eq"}, {"name": "talker_meeting_mix"},
                 {"name": "alsa_output.usb-speakers"}]
        self.assertEqual(desktop.physical_sinks(sinks), ["alsa_output.usb-speakers"])

    def test_eq_activation_waits_through_session_manager_startup(self):
        sinks = [{"index": 12, "name": "alsa_output.pci-hdmi"}]
        with tempfile.TemporaryDirectory() as temp, patch.object(desktop, "CONFIG", Path(temp)), \
                patch.object(desktop, "run") as run, patch.object(desktop, "eq_nodes") as nodes, \
                patch.object(desktop.time, "sleep"):
            desktop.atomic(desktop.CONFIG / "equalizer.json", json.dumps({
                "enabled": True, "target": "alsa_output.pci-hdmi", "gains": [0] * 10,
            }))
            run.side_effect = [RuntimeError("Pulse is starting"), json.dumps(sinks), "", "[]", ""]
            nodes.return_value = [{"id": 99}]
            result = desktop.eq_activate()
        self.assertTrue(result["active"])
        self.assertEqual(run.call_args_list[2].args[0],
                         ["pactl", "set-default-sink", "quattro_eq"])

    def test_weather_fresh_setup_uses_explicit_generic_manila(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(desktop, "CONFIG", Path(temp) / "config"), patch.object(desktop, "CACHE", Path(temp) / "cache"), patch.object(desktop.urllib.request, "urlopen", side_effect=OSError("offline")):
            result = desktop.weather()
            self.assertTrue(result["defaultLocation"])
            self.assertEqual(result["place"]["name"], "Manila")
            self.assertEqual(result["place"]["country_code"], "PH")
            self.assertFalse(result["available"])
            self.assertFalse((desktop.CONFIG / "weather.json").exists())

    def test_geocode_worldwide_unicode_and_bounded_request(self):
        response = MagicMock()
        place = {**desktop.DEFAULT_LOCATION, "name": "東京", "country": "Japan", "country_code": "JP"}
        response.__enter__.return_value.read.return_value = json.dumps({"results": [place] * 12}).encode()
        with patch.object(desktop.urllib.request, "urlopen", return_value=response) as request:
            result = desktop.geocode("  東京  ")
        self.assertEqual(result["query"], "東京")
        self.assertEqual(len(result["results"]), 8)
        self.assertIn("Japan", result["results"][0]["label"])
        url = request.call_args.args[0].full_url
        self.assertTrue(url.startswith("https://geocoding-api.open-meteo.com/v1/search?"))
        params = desktop.urllib.parse.parse_qs(desktop.urllib.parse.urlsplit(url).query)
        self.assertEqual(params["name"], ["東京"])
        self.assertEqual(params["count"], ["8"])
        self.assertNotIn("countryCode", params)
        self.assertEqual(request.call_args.kwargs["timeout"], 8)
        response.__enter__.return_value.read.assert_called_once_with(65536)

    def test_geocode_short_query_and_invalid_inputs(self):
        with patch.object(desktop.urllib.request, "urlopen") as request:
            self.assertEqual(desktop.geocode("x")["results"], [])
            for query in ["x" * 101, "ab\x00cd"]:
                with self.assertRaises(ValueError):
                    desktop.geocode(query)
            request.assert_not_called()

    def test_geocode_empty_and_network_failure_are_distinct(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"generationtime_ms": 1}'
        with patch.object(desktop.urllib.request, "urlopen", return_value=response):
            self.assertEqual(desktop.geocode("nowhere")["results"], [])
            self.assertNotIn("error", desktop.geocode("nowhere"))
        with patch.object(desktop.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertIn("retry", desktop.geocode("Manila")["error"])

    def test_geocode_malformed_and_out_of_range_results(self):
        for data in [[], {"results": {}}, {"results": [{"name": "bad", "latitude": 91, "longitude": 0}]}, {"results": [None]}]:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(data).encode()
            with patch.object(desktop.urllib.request, "urlopen", return_value=response):
                self.assertIn("error", desktop.geocode("query"))

    def test_location_persistence_refresh_cache_and_timezone(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(desktop, "CONFIG", Path(temp) / "config"), patch.object(desktop, "CACHE", Path(temp) / "cache"):
            place = {**desktop.DEFAULT_LOCATION, "name": "Tokyo", "country": "Japan", "country_code": "JP", "admin1": "Tokyo", "latitude": 35.6895, "longitude": 139.6917, "timezone": "Asia/Tokyo"}
            saved = desktop.save_place(place)
            self.assertEqual(saved["label"], "Tokyo, Japan")
            self.assertEqual(desktop.load(desktop.CONFIG / "weather.json", {}), saved)
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"current":{"temperature_2m":23,"weather_code":2,"is_day":1}}'
            with patch.object(desktop.urllib.request, "urlopen", return_value=response) as request:
                result = desktop.weather(True)
                self.assertFalse(result["defaultLocation"])
                self.assertEqual(result["place"], saved)
                self.assertEqual(result["temperature"], 23)
                self.assertIn("timezone=Asia%2FTokyo", request.call_args.args[0].full_url)
                self.assertTrue(desktop.weather()["cached"])
                self.assertEqual(request.call_count, 1)
                desktop.save_place(desktop.DEFAULT_LOCATION)
                result = desktop.weather()
                self.assertEqual(request.call_count, 2)
                self.assertEqual(result["place"]["name"], "Manila")

    def test_place_metadata_is_bounded_and_not_trusted_html(self):
        for value in [None, {**desktop.DEFAULT_LOCATION, "name": "x" * 161}, {**desktop.DEFAULT_LOCATION, "timezone": "Asia/Manila?bad"}]:
            with self.assertRaises(ValueError):
                desktop.normalize_place(value)
        legacy = desktop.normalize_place({"latitude": 10, "longitude": 20})
        self.assertEqual(legacy["label"], "Saved location")

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
                    self.assertEqual(stale["error"], "Showing saved conditions. Refresh when online.")
                    desktop.atomic(desktop.CONFIG / "weather.json", json.dumps({"latitude": 30, "longitude": 20}))
                    unavailable = desktop.weather(force=True)
                    self.assertFalse(unavailable["available"])
                    self.assertEqual(unavailable["error"], "Weather is unavailable. Check your connection and refresh.")

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

    def test_force_escalation_terminates_only_the_stubborn_test_process(self):
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(30)"],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            start, _ = desktop.process_identity(child.pid)
            with patch.object(desktop, "clients", return_value=[{"address": "0x123", "pid": child.pid}]):
                first = desktop.application_action("terminate", "0x123", child.pid, start)
                self.assertFalse(first["ok"])
                self.assertTrue(first["needsForce"])
                self.assertIsNone(child.poll())
                second = desktop.application_action("force", "0x123", child.pid, start)
            self.assertTrue(second["ok"])
            child.wait(timeout=3)
            self.assertEqual(child.returncode, -desktop.signal.SIGKILL)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()


if __name__ == "__main__":
    unittest.main()
