from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / "src" / "quattro-monitor"
loader = importlib.machinery.SourceFileLoader("quattro_monitor", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
monitor = importlib.util.module_from_spec(spec)
loader.exec_module(monitor)


def stat(name="worker", ticks=20, start=5, rss=2, state="S"):
    fields = [state] + ["0"] * 21
    fields[11], fields[12], fields[19], fields[21] = str(ticks), "0", str(start), str(rss)
    return "123 (" + name + ") " + " ".join(fields)


class MonitorMetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.proc, self.sysfs = self.root / "proc", self.root / "sys"
        self.proc.mkdir()
        self.sysfs.mkdir()
        self.sampler = monitor.Sampler(self.proc, self.sysfs)

    def put(self, root, path, text):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

    def fixture(self, cpu="cpu 100 0 50 850 0 0 0 0\ncpu0 100 0 50 850 0 0 0 0\n", rx=100, tx=200):
        self.put(self.proc, "stat", cpu)
        self.put(self.proc, "meminfo", "MemTotal: 100 kB\nMemAvailable: 40 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
        self.put(self.proc, "uptime", "123.5 200.0\n")
        self.put(self.proc, "net/dev", f"eth0: {rx} 1 0 0 0 0 0 0 {tx} 1 0 0 0 0 0 0\nlo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n")
        self.put(self.proc, "123/stat", stat())

    def test_cpu_ignores_guest_double_counting_and_handles_resets(self):
        counters = monitor.cpu_counters("cpu 100 0 30 70 0 0 0 0 40 0\n")
        self.assertEqual(counters["cpu"], (200, 70))
        self.assertEqual(monitor.cpu_delta((100, 50), (200, 70)), 80.0)
        self.assertIsNone(monitor.cpu_delta(None, (200, 70)))
        self.assertIsNone(monitor.cpu_delta((300, 90), (200, 70)))
        self.assertIsNone(monitor.cpu_delta((200, 70), (200, 70)))

    def test_first_sample_null_rates_and_second_sample_actual_deltas(self):
        self.fixture()
        with mock.patch.object(monitor.time, "monotonic", return_value=10.0):
            first = self.sampler.sample()
        self.assertIsNone(first["cpu"]["percent"])
        self.assertIsNone(first["network"]["rxBytesPerSecond"])
        self.assertIsNone(first["processes"]["items"][0]["cpuPercent"])
        self.fixture(cpu="cpu 180 0 70 950 0 0 0 0\ncpu0 180 0 70 950 0 0 0 0\n", rx=500, tx=800)
        self.put(self.proc, "123/stat", stat(ticks=20 + self.sampler.ticks_per_second))
        with mock.patch.object(monitor.time, "monotonic", return_value=12.0):
            second = self.sampler.sample()
        self.assertEqual(second["cpu"]["percent"], 50.0)
        self.assertEqual(second["cpu"]["cores"][0]["percent"], 50.0)
        self.assertEqual(second["network"]["rxBytesPerSecond"], 200.0)
        self.assertEqual(second["network"]["txBytesPerSecond"], 300.0)
        self.assertEqual(second["processes"]["items"][0]["cpuPercent"], 50.0)
        self.assertEqual(second["memory"]["percent"], 60.0)
        self.assertEqual(second["memory"]["usedBytes"], 60 * 1024)
        self.assertEqual(second["processes"]["items"][0]["rssPercent"],
                         round(100.0 * 2 * self.sampler.page_size / (100 * 1024), 2))
        self.assertIsNone(second["swap"]["percent"])
        self.assertEqual(second["uptimeSeconds"], 123.5)

    def test_missing_files_remain_unavailable_without_nan(self):
        result = self.sampler.sample()
        for key in ("cpu", "memory", "swap", "network", "temperatures", "gpu"):
            self.assertFalse(result[key]["available"], key)
        self.assertIsNone(result["uptimeSeconds"])
        json.dumps(result, allow_nan=False)

    def test_process_comm_parentheses_and_pid_reuse(self):
        self.assertEqual(monitor.process_stat(stat("worker (pool)", rss=3), 4096),
                         ("worker (pool)", 20, 5, 12288))
        self.assertIsNone(monitor.process_stat("bad data", 4096))
        self.fixture()
        with mock.patch.object(monitor.time, "monotonic", return_value=10.0):
            self.sampler.sample()
        self.put(self.proc, "123/stat", stat(ticks=1000, start=99))
        with mock.patch.object(monitor.time, "monotonic", return_value=12.0):
            result = self.sampler.sample()
        self.assertIsNone(result["processes"]["items"][0]["cpuPercent"])

    def test_process_count_and_output_are_bounded_and_do_not_read_cmdline(self):
        for pid in range(100, 125):
            self.put(self.proc, f"{pid}/stat", stat(rss=pid))
            self.put(self.proc, f"{pid}/cmdline", "SECRET ARGUMENTS")
            self.put(self.proc, f"{pid}/environ", "SECRET ENVIRONMENT")
        with mock.patch.object(monitor, "MAX_PROCESSES", 15):
            result = self.sampler.processes(None, 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["items"]), 15)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(set(result["items"][0]), {"pid", "name", "cpuPercent", "rssBytes", "rssPercent"})
        self.assertEqual([item["rssBytes"] for item in result["items"]],
                         sorted((item["rssBytes"] for item in result["items"]), reverse=True))

    def test_complete_scan_exposes_every_accessible_active_process_and_memory_share(self):
        for pid in range(100, 130):
            self.put(self.proc, f"{pid}/stat", stat(rss=pid))
        self.put(self.proc, "130/stat", stat(state="Z"))
        self.put(self.proc, "131/stat", stat(state="X"))
        (self.proc / "132").mkdir()
        with mock.patch.object(monitor.time, "monotonic", return_value=1.0):
            result = self.sampler.processes(None, 1, 1000 * self.sampler.page_size)
        self.assertFalse(result["truncated"])
        self.assertEqual(len(result["items"]), 30)
        self.assertEqual(result["omittedCount"], 3)
        self.assertEqual(result["limit"], 2048)
        self.assertEqual(result["items"][0]["pid"], 129)
        self.assertEqual(result["items"][0]["rssPercent"], 12.9)
        self.assertEqual({item["pid"] for item in result["items"]}, set(range(100, 130)))

    def test_process_memory_share_unavailable_without_total_memory(self):
        self.fixture()
        self.assertIsNone(self.sampler.processes(None, 1)["items"][0]["rssPercent"])

    def test_process_time_budget(self):
        self.fixture()
        with mock.patch.object(monitor.time, "monotonic", side_effect=[1.0, 2.0]):
            result = self.sampler.processes(None, 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["items"], [])

    def test_sensor_and_gpu_optional_counters(self):
        self.put(self.sysfs, "class/thermal/thermal_zone0/temp", "45000")
        self.put(self.sysfs, "class/thermal/thermal_zone0/type", "cpu\n")
        self.put(self.sysfs, "class/thermal/thermal_zone1/temp", "9999999")
        self.put(self.sysfs, "class/drm/card0/device/vendor", "0x1002\n")
        self.put(self.sysfs, "class/drm/card0/device/gpu_busy_percent", "29")
        self.put(self.sysfs, "class/drm/card0/device/mem_info_vram_total", "4096")
        sensors = self.sampler.temperatures()
        self.assertEqual(sensors["sensors"], [{"name": "cpu", "celsius": 45.0}])
        gpu = self.sampler.gpu()
        self.assertTrue(gpu["available"])
        self.assertEqual(gpu["devices"][0]["busyPercent"], 29)
        self.assertIsNone(gpu["devices"][0]["memoryUsedBytes"])

    def test_network_reset_new_interface_and_loopback(self):
        current = monitor.network_counters("eth0: 20 0 0 0 0 0 0 0 40 0 0 0 0 0 0 0\nlo: 99 0 0 0 0 0 0 0 99 0 0 0 0 0 0 0\n")
        self.assertNotIn("lo", current)
        result = monitor.network_metrics(current, {"eth0": (100, 100)}, 2.0)
        self.assertIsNone(result["rxBytesPerSecond"])
        self.assertIsNone(result["interfaces"][0]["txBytesPerSecond"])
        self.assertIsNone(monitor.network_metrics(current, {}, 2.0)["rxBytesPerSecond"])

    def test_filesystem_reserved_blocks_not_counted_as_used(self):
        fake = mock.Mock(f_blocks=100, f_bfree=30, f_bavail=20, f_frsize=1024)
        with mock.patch.object(monitor.os, "statvfs", return_value=fake):
            result = self.sampler.filesystem()
        self.assertEqual(result["usedBytes"], 70 * 1024)
        self.assertEqual(result["availableBytes"], 20 * 1024)
        self.assertEqual(result["percent"], 70.0)

    def test_cli_rejects_bad_intervals(self):
        with mock.patch.object(monitor.sys, "stderr"):
            for args in (["watch", "nan"], ["watch", "0.1"], ["watch", "61"], ["unknown"]):
                self.assertEqual(monitor.main(args), 2)

    def test_status_emits_one_valid_json_document(self):
        result = subprocess.run(["python3", str(SCRIPT), "status"], capture_output=True,
                                text=True, timeout=5, check=True)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["schemaVersion"], 1)
        self.assertIsNone(parsed["cpu"]["percent"])
        self.assertEqual(len(result.stdout.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
