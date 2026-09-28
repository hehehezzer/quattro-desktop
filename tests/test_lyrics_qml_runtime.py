"""Windowless runtime checks for lyrics invalidation and position synchronization."""
from __future__ import annotations

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
class LyricsQmlRuntimeTests(unittest.TestCase):
    def test_stale_track_response_states_and_active_line_selection(self):
        with tempfile.TemporaryDirectory(prefix="quattro-lyrics-qml-") as directory:
            root = Path(directory)
            source = Path(__file__).parents[1] / "src/quickshell/services/LyricsController.qml"
            shutil.copyfile(source, root / "LyricsController.qml")
            (root / "DesktopMedia.qml").write_text('''pragma Singleton
import QtQuick
QtObject {
    id: root
    property real position: 0
    property QtObject player: QtObject {
        property string trackTitle: ""
        property string trackArtist: "Test Artist"
        property string trackAlbum: "Test Album"
        property real length: 120
        property bool lengthSupported: true
    }
    function setTrack(value) { player.trackTitle = value; position = 0 }
    function clearTrack() { player.trackTitle = ""; position = 0 }
}
''', encoding="utf-8")
            (root / "qmldir").write_text(
                "singleton DesktopMedia 1.0 DesktopMedia.qml\n"
                "singleton LyricsController 1.0 LyricsController.qml\n",
                encoding="utf-8",
            )
            helper = root / ".local/bin/quattro-lyrics"
            helper.parent.mkdir(parents=True)
            helper.write_text('''#!/usr/bin/env python3
import json, signal, sys, time
args = sys.argv[1:]
title = args[args.index("--title") + 1]
if title == "Slow":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(.7)
if title == "Malformed":
    print("{bad", flush=True)
    raise SystemExit
state = {"Plain": "plain", "Instrumental": "instrumental", "Missing": "unavailable"}.get(title, "synced")
print(json.dumps({"schemaVersion": 1, "trackKey": "fake", "state": state,
    "instrumental": state == "instrumental", "source": "LRCLIB",
    "plainText": "Plain body" if state == "plain" else None,
    "lines": [{"timestampMs": 500, "text": title + " one"}, {"timestampMs": 2000, "text": title + " two"}] if state == "synced" else []}), flush=True)
''', encoding="utf-8")
            helper.chmod(0o755)
            (root / "shell.qml").write_text('''import Quickshell
import Quickshell.Io
import QtQuick
import "."
ShellRoot {
    IpcHandler {
        target: "lyricsTest"
        function track(value: string): void { DesktopMedia.setTrack(value) }
        function clear(): void { DesktopMedia.clearTrack() }
        function position(value: real): void { DesktopMedia.position = value }
        function state(): string { return JSON.stringify({state: LyricsController.state,
            lines: LyricsController.lines, plainText: LyricsController.plainText,
            activeIndex: LyricsController.activeIndex, key: LyricsController.trackKey}) }
    }
}
''', encoding="utf-8")
            env = {**os.environ, "HOME": str(root), "QT_QPA_PLATFORM": "offscreen",
                   "XDG_CONFIG_HOME": str(root / "config")}
            with (root / "engine.log").open("w+") as log:
                engine = subprocess.Popen(["qs", "--no-color", "-p", str(root)], env=env,
                                          stdout=log, stderr=log)
                try:
                    def call(method, *args):
                        return subprocess.run(["qs", "-p", str(root), "ipc", "call", "lyricsTest", method, *args],
                                              env=env, text=True, capture_output=True, timeout=3)

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

                    def wait_for(expected, timeout=4):
                        deadline = time.monotonic() + timeout
                        snapshots = []
                        while time.monotonic() < deadline:
                            value = state()
                            snapshots.append(value)
                            if value["state"] == expected:
                                return value, snapshots
                            time.sleep(.04)
                        self.fail(f"Lyrics state did not become {expected}: {snapshots[-3:]}")

                    self.assertEqual(call("track", "Slow").returncode, 0)
                    time.sleep(.35)
                    self.assertEqual(call("track", "Fast").returncode, 0)
                    value, snapshots = wait_for("synced")
                    self.assertEqual(value["lines"][0]["text"], "Fast one")
                    self.assertFalse(any(item["lines"] and item["lines"][0]["text"] == "Slow one" for item in snapshots))

                    call("position", "0.2")
                    self.assertEqual(state()["activeIndex"], -1)
                    call("position", "0.5")
                    self.assertEqual(state()["activeIndex"], 0)
                    call("position", "2.5")
                    self.assertEqual(state()["activeIndex"], 1)
                    call("position", "1.0")
                    self.assertEqual(state()["activeIndex"], 0)

                    for title, expected in [("Plain", "plain"), ("Instrumental", "instrumental"),
                                            ("Missing", "unavailable"), ("Malformed", "error")]:
                        call("track", title)
                        value, _ = wait_for(expected)
                        if expected == "plain":
                            self.assertEqual(value["plainText"], "Plain body")

                    call("clear")
                    value, _ = wait_for("idle")
                    self.assertEqual(value["lines"], [])
                    call("track", "Fast")
                    value, _ = wait_for("synced")
                    self.assertEqual(value["lines"][0]["text"], "Fast one")
                finally:
                    engine.terminate()
                    try:
                        engine.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        engine.kill()
                        engine.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
