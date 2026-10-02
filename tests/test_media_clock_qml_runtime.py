"""Exercise the real Quickshell MPRIS clock on an isolated D-Bus session."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import select
import subprocess
import sys
import tempfile
import time
import unittest


FAKE_PLAYER = '''
import time
from gi.repository import Gio, GLib
iface = "org.mpris.MediaPlayer2.Player"
path = "/org/mpris/MediaPlayer2"
xml = """<node><interface name="org.mpris.MediaPlayer2">
<property name="Identity" type="s" access="read"/>
<property name="DesktopEntry" type="s" access="read"/>
</interface><interface name="org.mpris.MediaPlayer2.Player">
<method name="Play"/><method name="Pause"/><method name="Next"/>
<method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
<property name="PlaybackStatus" type="s" access="read"/>
<property name="Rate" type="d" access="readwrite"/>
<property name="Metadata" type="a{sv}" access="read"/>
<property name="Position" type="x" access="read"/>
<property name="CanControl" type="b" access="read"/>
<property name="CanSeek" type="b" access="read"/>
<property name="CanPlay" type="b" access="read"/>
<property name="CanPause" type="b" access="read"/>
<signal name="Seeked"><arg type="x"/></signal>
</interface></node>"""
playing, anchor, epoch, rate, track = False, 0.0, time.monotonic(), 1.0, 1
def position():
    return anchor + (time.monotonic() - epoch) * rate if playing else anchor
def value(name):
    if name == "Identity": return GLib.Variant("s", "Spotify fixture")
    if name == "DesktopEntry": return GLib.Variant("s", "spotify")
    if name == "PlaybackStatus": return GLib.Variant("s", "Playing" if playing else "Paused")
    if name == "Rate": return GLib.Variant("d", rate)
    if name == "Position": return GLib.Variant("x", int(position() * 1e6))
    if name.startswith("Can"): return GLib.Variant("b", True)
    if name == "Metadata": return GLib.Variant("a{sv}", {
        "mpris:trackid": GLib.Variant("o", "/track/" + str(track)),
        "mpris:length": GLib.Variant("x", 180000000),
        "xesam:title": GLib.Variant("s", "Fixture " + str(track)),
        "xesam:artist": GLib.Variant("as", ["Fixture artist"])})
def changed(*names):
    bus.emit_signal(None, path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                    GLib.Variant("(sa{sv}as)", (iface, {n:value(n) for n in names}, [])))
def call(connection, sender, object_path, interface, method, params, invocation):
    global playing, anchor, epoch, track
    anchor, epoch = position(), time.monotonic()
    if method in ("Play", "Pause"):
        playing = method == "Play"
        changed("PlaybackStatus", "Position")
    elif method == "SetPosition":
        anchor = params.unpack()[1] / 1e6
        bus.emit_signal(None, path, iface, "Seeked", GLib.Variant("(x)", (int(anchor * 1e6),)))
    elif method == "Next":
        track += 1
        anchor = 0.0
        changed("Metadata", "Position")
    invocation.return_value(None)
def set_property(connection, sender, object_path, interface, name, variant):
    global anchor, epoch, rate
    if name != "Rate": return False
    anchor, epoch = position(), time.monotonic()
    rate = variant.unpack()
    changed("Rate", "Position")
    return True
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
for interface in Gio.DBusNodeInfo.new_for_xml(xml).interfaces:
    bus.register_object(path, interface, call,
                        lambda c,s,p,i,n: value(n), set_property)
Gio.bus_own_name_on_connection(bus, "org.mpris.MediaPlayer2.spotify", Gio.BusNameOwnerFlags.NONE, None, None)
GLib.MainLoop().run()
'''


@unittest.skipUnless(sys.platform == "linux" and shutil.which("qs")
                     and shutil.which("dbus-daemon") and shutil.which("busctl")
                     and importlib.util.find_spec("gi"), "Requires Quickshell, D-Bus and PyGObject")
class MediaClockRuntimeTests(unittest.TestCase):
    def test_clock_sampling_pause_resume_seek_rate_and_track_changes(self):
        with tempfile.TemporaryDirectory(prefix="quattro-clock-test-") as directory:
            root = Path(directory)
            source = Path(__file__).parents[1] / "src/quickshell/services/DesktopMedia.qml"
            shutil.copyfile(source, root / "DesktopMedia.qml")
            (root / "qmldir").write_text("singleton DesktopMedia 1.0 DesktopMedia.qml\n")
            (root / "shell.qml").write_text('''import Quickshell
import Quickshell.Io
import QtQuick
import "."
ShellRoot {
    IpcHandler {
        target: "clockTest"
        function state(): string { return JSON.stringify({position: DesktopMedia.position,
            raw: DesktopMedia.player ? DesktopMedia.player.position : -1,
            playing: DesktopMedia.player ? DesktopMedia.player.isPlaying : false,
            title: DesktopMedia.player ? DesktopMedia.player.trackTitle : ""}) }
    }
}
''')
            (root / "fake.py").write_text(FAKE_PLAYER)
            env = {**os.environ, "HOME": str(root), "QT_QPA_PLATFORM": "offscreen",
                   "XDG_CONFIG_HOME": str(root / "config"), "XDG_RUNTIME_DIR": str(root)}
            processes = []
            with (root / "engine.log").open("w+") as log:
                try:
                    bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                                           stdout=subprocess.PIPE, stderr=log, text=True, env=env)
                    processes.append(bus)
                    self.assertTrue(select.select([bus.stdout], [], [], 3)[0], "Private bus did not start")
                    env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
                    self.assertTrue(env["DBUS_SESSION_BUS_ADDRESS"], "Private bus address missing")
                    fake = subprocess.Popen([sys.executable, str(root / "fake.py")], env=env, stdout=log, stderr=log)
                    processes.append(fake)
                    engine = subprocess.Popen(["qs", "--no-color", "-p", str(root)], env=env, stdout=log, stderr=log)
                    processes.append(engine)

                    def run(*args):
                        return subprocess.run(args, env=env, text=True, capture_output=True, timeout=3)

                    def state():
                        try:
                            result = run("qs", "-p", str(root), "ipc", "call", "clockTest", "state")
                        except subprocess.TimeoutExpired:
                            log.seek(0)
                            self.fail("Clock IPC timed out: " + log.read()[-2500:])
                        return json.loads(result.stdout) if result.returncode == 0 else {}

                    def wait_for(predicate, timeout=5):
                        end = time.monotonic() + timeout
                        while time.monotonic() < end:
                            snapshot = state()
                            if predicate(snapshot):
                                return snapshot
                            time.sleep(.025)
                        log.seek(0)
                        self.fail(f"Clock condition failed: {snapshot}; {log.read()[-2500:]}")

                    def call(method, *args):
                        result = run("busctl", "--user", "call", "org.mpris.MediaPlayer2.spotify",
                                     "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method, *args)
                        self.assertEqual(result.returncode, 0, result.stderr)

                    wait_for(lambda s: s.get("title") == "Fixture 1")
                    call("Play")
                    wait_for(lambda s: s.get("position", 0) > .15)
                    lags = []
                    for _ in range(14):
                        snapshot = state()
                        lags.append(snapshot["raw"] - snapshot["position"])
                        time.sleep(.037)
                    # Fails for the former 1000 ms sampler, tolerant of loaded CI.
                    self.assertLess(max(lags), .25, lags)
                    call("Pause")
                    paused = wait_for(lambda s: not s.get("playing", True))["position"]
                    time.sleep(.2)
                    self.assertAlmostEqual(state()["position"], paused, places=3)
                    call("SetPosition", "ox", "/track/1", "50000000")
                    wait_for(lambda s: abs(s.get("position", 0) - 50) < .01, timeout=1)
                    call("SetPosition", "ox", "/track/1", "2000000")
                    wait_for(lambda s: abs(s.get("position", 0) - 2) < .01, timeout=1)
                    call("Play")
                    wait_for(lambda s: s.get("position", 0) > 2.1)
                    call("Pause")
                    wait_for(lambda s: not s.get("playing", True))
                    # A reported buffering pause holds position, then resumes cleanly.
                    held = state()["position"]
                    time.sleep(.2)
                    self.assertEqual(state()["position"], held)
                    call("Next")
                    wait_for(lambda s: s.get("title") == "Fixture 2" and s.get("position", -1) < .01)
                    result = run("busctl", "--user", "set-property", "org.mpris.MediaPlayer2.spotify",
                                 "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Rate", "d", "2")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    call("Play")
                    wait_for(lambda s: s.get("position", 0) > .1)
                    before = state()["position"]
                    time.sleep(.3)
                    delta = state()["position"] - before
                    self.assertGreater(delta, .45)
                    self.assertLess(delta, .9)
                finally:
                    for process in reversed(processes):
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
                    if processes and processes[0].stdout:
                        processes[0].stdout.close()
