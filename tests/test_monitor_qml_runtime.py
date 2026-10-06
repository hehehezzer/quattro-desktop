"""Windowless checks of the real QML service and its subprocess lifecycle."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "src/quickshell/services"


def sample():
    memory = {"available": True, "totalBytes": 1000, "usedBytes": 400,
              "availableBytes": 600, "percent": 40}
    return {"schemaVersion": 1, "updatedAt": 1000,
            "cpu": {"available": True, "percent": None, "cores": []},
            "memory": memory, "swap": memory,
            "filesystem": dict(memory, mount="/"), "uptimeSeconds": 100,
            "network": {"available": True, "rxBytesPerSecond": None,
                        "txBytesPerSecond": None, "interfaces": []},
            "temperatures": {"available": False, "sensors": []},
            "gpu": {"available": False, "devices": []},
            "processes": {"available": True, "truncated": False, "omittedCount": 0,
                          "limit": 2048, "items": []}}


@unittest.skipUnless(shutil.which("qs"), "Quickshell is required")
class MonitorRuntimeTests(unittest.TestCase):
    def run_qml(self, body, worker_body, timeout=8, desktop=False):
        with tempfile.TemporaryDirectory(prefix="quattro-monitor-qml-") as directory:
            work = Path(directory)
            runtime = work / "runtime"
            runtime.mkdir(mode=0o700)
            worker = work / "worker"
            events = work / "events"
            worker.write_text("#!/usr/bin/env python3\nimport json, signal, time\n"
                              f"events = {str(events)!r}\n"
                              "def record(value):\n    with open(events, 'a') as f: f.write(value + '\\n')\n"
                              "record('start')\n" + worker_body)
            worker.chmod(0o755)
            qml = work / "shell.qml"
            # Follow the native shell's relative directory import, including its
            # actual qmldir exports, rather than resolving a file-URL shortcut.
            (work / "services").symlink_to(SERVICE, target_is_directory=True)
            if desktop:
                shutil.copytree(ROOT / "src/quickshell/components", work / "components")
                (work / "theme").symlink_to(ROOT / "src/quickshell/theme", target_is_directory=True)
                # The offscreen Qt platform has no layer-shell PanelWindow
                # backend. Load the real table with an inert window boundary;
                # the compositor placement is checked separately on desktop.
                (work / "components/shared/TemporaryPanel.qml").write_text(
                    "import QtQuick\nQtObject {\n"
                    " default property list<QtObject> content\n"
                    " property string panelName: ''\n property bool opened: false\n"
                    " property bool visible: opened\n property var screen: null\n"
                    " property color color: 'transparent'\n"
                    " property real width: implicitWidth\n property real implicitWidth: 0\n"
                    " property real implicitHeight: 0\n signal dismissed()\n"
                    " component DockAnchors: QtObject { property bool top: false; property bool right: false }\n"
                    " property DockAnchors anchors: DockAnchors {}\n"
                    " component DockMargins: QtObject { property real top: 0; property real right: 0 }\n"
                    " property DockMargins margins: DockMargins {}\n}\n")
            qml.write_text("import QtQuick\nimport Quickshell\n"
                           'import "services"\n'
                           + ('import "components" as Desktop\n' if desktop else "")
                           +
                           "Scope {\n id: test\n property bool passed: true\n"
                           " property int stage: 0\n property int frozen: 0\n property double frozenClock: 0\n"
                           " MonitorMetrics { id: metrics }\n"
                           " function check(value, name) { if (!value) { passed = false; console.log('CHECK_FAILED', name) } }\n"
                           f" property var fixture: ({json.dumps(sample())})\n" + body + "\n}\n")
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="basic",
                       QT_QUICK_CONTROLS_STYLE="Basic", XDG_RUNTIME_DIR=str(runtime),
                       XDG_CACHE_HOME=str(work / "cache"), XDG_CONFIG_HOME=str(work / "config"),
                       QUATTRO_MONITOR_COMMAND=str(worker), QS_NO_RELOAD_POPUP="1")
            env.pop("WAYLAND_DISPLAY", None)
            result = subprocess.run(["qs", "-p", str(qml), "--no-color"], env=env,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=timeout)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("MONITOR_TEST_PASS", result.stdout, result.stdout)
            self.assertNotIn("CHECK_FAILED", result.stdout, result.stdout)
            self.assertNotIn("TypeError", result.stdout, result.stdout)
            self.assertNotIn("ReferenceError", result.stdout, result.stdout)
            return events.read_text().splitlines() if events.exists() else []

    def test_process_table_loads_and_filters_sorts_without_mutating_snapshot(self):
        body = """
 Desktop.Monitoring { id: view }
 Timer { interval: 250; running: true; onTriggered: {
   const rows = [{pid: 41, name: 'zebra', rssBytes: 30}, {pid: 12, name: 'Alpha', rssBytes: 90}, {pid: 25, name: 'alpha helper', rssBytes: 10}, {pid: 13, name: 'Beta', rssBytes: 90}]
   const saved = JSON.stringify(rows)
   test.check(view.selectProcesses(rows, '', 0).map(p => p.pid).join(',') === '12,13,41,25', 'default highest RAM with stable PID ties')
   test.check(view.selectProcesses(rows, '', 1).map(p => p.pid).join(',') === '25,41,12,13', 'lowest RAM sort')
   test.check(view.selectProcesses(rows, '', 2).map(p => p.pid).join(',') === '12,25,13,41', 'case-insensitive name sort')
   test.check(view.selectProcesses(rows, '', 3).map(p => p.pid).join(',') === '12,13,25,41', 'PID sort')
   test.check(view.selectProcesses(rows, '  ALPHA  ', 0).map(p => p.pid).join(',') === '12,25', 'trimmed case-insensitive name search')
   test.check(view.selectProcesses(rows, '13', 0).map(p => p.pid).join(',') === '13', 'PID search')
   test.check(view.selectProcesses(rows, 'missing', 0).length === 0, 'empty search results')
   test.check(JSON.stringify(rows) === saved, 'snapshot order and values preserved')
   if (test.passed) console.log('MONITOR_TEST_PASS')
   Qt.quit()
 } }
"""
        events = self.run_qml(body, "raise SystemExit(0)\n", desktop=True)
        self.assertEqual(events, [])

    def test_visibility_pause_validation_history_and_stale_retention(self):
        worker = ("def stop(*args):\n    record('stop')\n    raise SystemExit(0)\n"
                  "signal.signal(signal.SIGTERM, stop)\n"
                  f"print(json.dumps({sample()!r}), flush=True)\n"
                  "while True: time.sleep(0.05)\n")
        body = """
 Timer {
   interval: 250; running: true; repeat: true
   onTriggered: {
     test.stage++
     if (test.stage === 1) {
       test.check(!metrics.workerRunning && metrics.state === 'Hidden', 'hidden at startup')
       metrics.active = true
     } else if (test.stage === 2) {
       test.check(metrics.workerRunning && metrics.snapshot !== null, 'worker started and parsed')
       test.check(metrics.snapshot.cpu.percent === null && metrics.history[0].rx === null, 'missing first rates stay missing')
       metrics.paused = true; test.frozen = metrics.history.length
     } else if (test.stage === 3) {
       test.check(!metrics.workerRunning && metrics.state === 'Paused', 'pause stops worker')
       test.check(metrics.history.length === test.frozen, 'pause freezes history')
       metrics.active = false; metrics.paused = false
     } else if (test.stage === 4) {
       test.check(!metrics.workerRunning, 'hidden resume does not sample')
       metrics.active = true
     } else if (test.stage === 5) {
       test.check(metrics.workerRunning, 'visible resume starts worker')
       metrics.receivedAt = Date.now() - 10000; metrics.clock = Date.now()
       test.check(metrics.state === 'Stale' && metrics.snapshot !== null, 'stale retains last good data')
       const saved = JSON.stringify(metrics.snapshot)
       test.check(!metrics.consume('{broken') && JSON.stringify(metrics.snapshot) === saved, 'malformed line retains data')
       const invalid = JSON.parse(JSON.stringify(test.fixture)); invalid.updatedAt = 1002; invalid.cpu.percent = 101
       test.check(!metrics.consume(JSON.stringify(invalid)), 'invalid range rejected')
       invalid.cpu.percent = 20; invalid.temperatures.sensors = [{name: 'sensor', celsius: null}]
       test.check(!metrics.consume(JSON.stringify(invalid)), 'invalid sensor rejected')
       for (let i = 1; i <= 75; i++) {
         const s = JSON.parse(JSON.stringify(test.fixture)); s.updatedAt += i * 2; s.cpu.percent = i
         s.network.rxBytesPerSecond = i * 1024; s.network.txBytesPerSecond = 0
         test.check(metrics.consume(JSON.stringify(s)), 'valid history sample ' + i)
       }
       test.check(metrics.history.length === 60 && metrics.history[0].time === 1032000, 'history bounded to latest 60')
       const clock = metrics.receivedAt
       test.check(!metrics.consume(JSON.stringify(metrics.snapshot)) && metrics.receivedAt === clock, 'duplicate does not refresh freshness')
       const hole = JSON.parse(JSON.stringify(metrics.snapshot)); hole.updatedAt += 10; hole.cpu.percent = null
       test.check(metrics.consume(JSON.stringify(hole)) && metrics.history[59].cpu === null, 'timestamp hole preserved')
       test.check(metrics.history[59].time - metrics.history[58].time === 10000, 'gap remains actual elapsed time')
       test.check(metrics.state === 'Live', 'fresh valid data recovers state')
       const many = JSON.parse(JSON.stringify(metrics.snapshot)); many.updatedAt += 2
       many.processes.items = Array.from({length: 200}, (_, i) => ({pid: i + 1, name: 'worker', cpuPercent: null, rssBytes: 2048, rssPercent: 0.25}))
       test.check(metrics.consume(JSON.stringify(many)) && metrics.snapshot.processes.items.length === 200, 'all process rows accepted beyond old top twelve')
       const oversized = JSON.parse(JSON.stringify(many)); oversized.updatedAt += 2
       oversized.processes.items = Array.from({length: 2049}, (_, i) => ({pid: i + 1, name: 'worker', cpuPercent: null, rssBytes: 2048, rssPercent: 0.25}))
       test.check(!metrics.consume(JSON.stringify(oversized)), 'process payload cap enforced')
       const wrongShare = JSON.parse(JSON.stringify(many)); wrongShare.updatedAt += 2; wrongShare.processes.items[0].rssPercent = 101
       test.check(!metrics.consume(JSON.stringify(wrongShare)), 'invalid RAM share rejected')
       metrics.active = false; test.frozenClock = metrics.clock; test.frozen = metrics.history.length
     } else if (test.stage === 6) {
       test.check(!metrics.workerRunning && metrics.history.length === test.frozen, 'hide stops worker and samples')
       test.check(metrics.clock === test.frozenClock, 'hidden freshness timer stopped')
       if (test.passed) console.log('MONITOR_TEST_PASS')
       Qt.quit()
     }
   }
 }
"""
        events = self.run_qml(body, worker)
        self.assertEqual(events, ["start", "stop", "start", "stop"])

    def test_exit_retries_after_bounded_delay_and_hide_cancels_retry(self):
        body = """
 Component.onCompleted: metrics.active = true
 Timer {
   interval: 200; running: true
   onTriggered: test.check(metrics.state === 'Unavailable' && !metrics.workerRunning, 'exit enters recoverable unavailable state')
 }
 Timer { interval: 5300; running: true; onTriggered: metrics.active = false }
 Timer {
   interval: 5800; running: true
   onTriggered: {
     test.check(!metrics.workerRunning && metrics.state === 'Hidden', 'hide cancels scheduled retry')
     if (test.passed) console.log('MONITOR_TEST_PASS')
     Qt.quit()
   }
 }
"""
        events = self.run_qml(body, "raise SystemExit(1)\n")
        self.assertEqual(events, ["start", "start"])


if __name__ == "__main__":
    unittest.main()
