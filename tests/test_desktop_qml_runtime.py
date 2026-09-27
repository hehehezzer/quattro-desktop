"""Hermetic weather race tests in a bounded, windowless Quickshell test engine."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(sys.platform == "linux" and shutil.which("qs"), "Requires Linux Quickshell")
class WeatherQmlRuntimeTests(unittest.TestCase):
    def test_debounce_cancellation_stale_results_and_selection(self):
        with tempfile.TemporaryDirectory(prefix="quattro-weather-test-") as directory:
            root = Path(directory)
            service = Path(__file__).parents[1] / "src/quickshell/services/DesktopWeather.qml"
            shutil.copyfile(service, root / "DesktopWeather.qml")
            (root / "qmldir").write_text("singleton DesktopWeather 1.0 DesktopWeather.qml\n")
            helper = root / ".local/bin/quattro_desktop_controls.py"
            helper.parent.mkdir(parents=True)
            helper.write_text('''import json, signal, sys, time
from pathlib import Path
root = Path.home()
args = sys.argv[1:]
if args[0] == "geocode":
    query = args[1]
    with (root / "requests").open("a") as log: log.write(query + "\\n")
    if query == "slow":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(.7)
    print(json.dumps({"query": query, "results": [] if query in ["empty", "offline"] else [{"name": query, "label": query, "latitude": 1, "longitude": 2}], **({"error": "Network unavailable"} if query == "offline" else {})}), flush=True)
else:
    path = root / "selection"
    if "--place" in args: path.write_text(args[args.index("--place") + 1])
    place = json.loads(path.read_text()) if path.exists() else {"name": "Manila", "label": "Manila"}
    print(json.dumps({"available": True, "configured": True, "place": place, "temperature": 25, "code": 2, "day": True}), flush=True)
''')
            (root / "shell.qml").write_text('''import Quickshell
import Quickshell.Io
import QtQuick
import "."
ShellRoot {
    IpcHandler {
        target: "weatherTest"
        function query(value: string): void { DesktopWeather.searchQuery = value; }
        function choose(): void { DesktopWeather.selectPlace(DesktopWeather.searchResults[0]); }
        function state(): string { return JSON.stringify({query: DesktopWeather.searchQuery, results: DesktopWeather.searchResults, error: DesktopWeather.searchError, searching: DesktopWeather.searching, snapshot: DesktopWeather.snapshot}); }
    }
}
''')
            env = {**os.environ, "HOME": str(root), "QT_QPA_PLATFORM": "offscreen", "XDG_CONFIG_HOME": str(root / "config")}
            with (root / "engine.log").open("w+") as log:
                engine = subprocess.Popen(["qs", "--no-color", "-p", str(root)], env=env, stdout=log, stderr=log)
                try:
                    def call(method, *args):
                        return subprocess.run(["qs", "-p", str(root), "ipc", "call", "weatherTest", method, *args], env=env, text=True, capture_output=True, timeout=3)

                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        if call("state").returncode == 0:
                            break
                        if engine.poll() is not None:
                            log.seek(0)
                            self.fail("Windowless engine failed: " + log.read()[-3000:])
                        time.sleep(.05)
                    else:
                        self.fail("Windowless engine did not start")

                    def state():
                        result = call("state")
                        self.assertEqual(result.returncode, 0, result.stderr)
                        return json.loads(result.stdout)

                    def settled():
                        deadline = time.monotonic() + 4
                        while time.monotonic() < deadline:
                            value = state()
                            if not value["searching"]:
                                return value
                            time.sleep(.04)
                        self.fail("Search failed to settle")

                    for query in ["T", "To", "Tok", "Tokyo"]:
                        self.assertEqual(call("query", query).returncode, 0)
                    self.assertEqual(settled()["results"][0]["name"], "Tokyo")
                    self.assertEqual((root / "requests").read_text().splitlines(), ["Tokyo"])
                    call("query", "slow")
                    time.sleep(.45)
                    call("query", "London")
                    # A cancelled worker deliberately ignores SIGTERM and returns
                    # late: neither its data nor its error may replace the new query.
                    self.assertEqual(state()["results"], [])
                    value = settled()
                    self.assertEqual(value["results"][0]["name"], "London")
                    call("choose")
                    time.sleep(.3)
                    self.assertEqual(state()["snapshot"]["place"]["name"], "London")
                    self.assertEqual(json.loads((root / "selection").read_text())["longitude"], 2)
                    call("query", "empty")
                    value = settled()
                    self.assertEqual(value["results"], [])
                    self.assertEqual(value["error"], "")
                    call("query", "offline")
                    self.assertTrue(settled()["error"])
                    call("query", "slow")
                    time.sleep(.45)
                    call("query", "")
                    time.sleep(.8)
                    self.assertEqual(state()["results"], [])
                    self.assertEqual(state()["error"], "")
                finally:
                    engine.terminate()
                    try:
                        engine.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        engine.kill()
                        engine.wait(timeout=3)
