"""Bounded desktop operations. No credentials, shell evaluation or name-based killing."""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "quattro"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "quattro"
BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
PRESETS = {
    "Flat": [0] * 10,
    "Bass Boost": [4, 4, 3, 1, 0, 0, 0, 0, 0, 0],
    "More Bass": [6, 6, 4, 2, 0, 0, 0, 0, 0, 0],
    "Treble Boost": [0, 0, 0, 0, 0, 0, 1, 2, 3, 3],
    "More Treble": [0, 0, 0, 0, 0, 0, 2, 3, 5, 5],
    "Vocal Clarity": [-2, -2, -1, 0, 1, 3, 3, 1, 0, -1],
    "Music": [2, 2, 1, 0, -1, 0, 1, 2, 2, 1],
    "Gaming": [1, 1, 0, -1, -1, 1, 3, 3, 1, 0],
    "Movie": [4, 3, 2, 0, -1, 1, 2, 1, 1, 0],
}
EQ_NAME = "quattro_eq"


def run(argv, timeout=8):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "System operation failed").strip()[:400])
    return result.stdout


def load(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".desktop-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def weather(force=False):
    location = load(CONFIG / "weather.json", {})
    cached = load(CACHE / "weather.json", {})
    if not location:
        return {"available": False, "error": "Set your weather location in Calendar", "configured": False}
    lat, lon = coordinates(location["latitude"], location["longitude"])
    if cached.get("location") != [lat, lon]:
        cached = {}
    if not force and time.time() - cached.get("updated", 0) < 1800:
        return {**cached, "cached": True, "configured": True}
    try:
        query = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
            "current": "temperature_2m,weather_code,is_day", "temperature_unit": "celsius"})
        request = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + query,
                                         headers={"User-Agent": "QuattroDesktop/1.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read(65536))["current"]
        temperature = float(data["temperature_2m"])
        if not math.isfinite(temperature) or not -100 <= temperature <= 70:
            raise ValueError("Invalid temperature")
        result = {"available": True, "configured": True, "temperature": temperature,
                  "code": int(data["weather_code"]), "day": bool(data["is_day"]),
                  "updated": time.time(), "location": [lat, lon], "cached": False}
        atomic(CACHE / "weather.json", json.dumps(result))
        return result
    except (OSError, ValueError, KeyError) as error:
        return {**cached, "available": bool(cached), "configured": True, "cached": bool(cached),
                "stale": True, "error": "Weather unavailable; retry later (" + type(error).__name__ + ")"}


def coordinates(latitude, longitude):
    lat, lon = float(latitude), float(longitude)
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude must be −90…90; longitude −180…180")
    return lat, lon


def clients():
    return json.loads(run(["hyprctl", "-j", "clients"]))


def process_identity(pid):
    path = Path("/proc") / str(pid)
    if pid <= 1 or path.stat().st_uid != os.getuid():
        raise ValueError("Not a user-owned application")
    # comm may contain spaces and parentheses. Fields after its final ')' are stable.
    fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
    executable = (path / "exe").resolve(strict=True).name
    return str(fields[19]), executable


def protected(pid, executable):
    names = {"quickshell", "qs", "Hyprland", "hyprland", "systemd", "init", "dbus-daemon",
             "dbus-broker", "pipewire", "pipewire-pulse", "wireplumber", "bluetoothd",
             "hyprlock", "hyprsunset", "polkitd", "xdg-desktop-portal", "sshd"}
    if executable in names or executable.startswith("xdg-desktop-portal-"):
        return True
    current = os.getpid()
    while current > 1:
        if current == pid:
            return True
        try:
            current = int((Path("/proc") / str(current) / "stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return False


def applications():
    result = []
    for client in clients():
        pid = int(client.get("pid", 0))
        try:
            start, exe = process_identity(pid)
        except (OSError, ValueError):
            continue
        result.append({"address": client["address"], "pid": pid, "start": start,
                       "title": client.get("title", "")[:160], "app": client.get("class", "")[:80],
                       "protected": protected(pid, exe)})
    return {"applications": result}


def application_action(action, address, pid, start):
    if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
        raise ValueError("Invalid window identity")
    if not any(c.get("address") == address and c.get("pid") == pid for c in clients()):
        raise ValueError("Window has exited or changed identity")
    # Pin the kernel process before checking identity, avoiding PID reuse during signalling.
    fd = os.pidfd_open(pid)
    try:
        actual, exe = process_identity(pid)
        if actual != start or protected(pid, exe):
            raise ValueError("Protected process or stale application identity")
        if action in {"open", "close"}:
            # Lua Hyprland uses typed dispatchers, not legacy focuswindow text.
            # Only the strictly validated hexadecimal address enters this fixed expression.
            selector = json.dumps("address:" + address)
            expression = ("hl.dsp.focus({window=" + selector + "})" if action == "open"
                          else "hl.dsp.window.close(" + selector + ")")
            run(["hyprctl", "eval", "hl.dispatch(" + expression + ")"])
            return {"ok": True}
        if action not in {"terminate", "force"}:
            raise ValueError("Unknown application action")
        signal.pidfd_send_signal(fd, signal.SIGKILL if action == "force" else signal.SIGTERM)
        exited = bool(select.select([fd], [], [], 2)[0])
        return {"ok": exited, "needsForce": not exited, "message": "Process exited" if exited else "Still running. Force kill may lose unsaved work."}
    finally:
        os.close(fd)


def gains_valid(values):
    gains = [float(value) for value in values]
    if len(gains) != 10 or any(not math.isfinite(v) or abs(v) > 12 for v in gains):
        raise ValueError("EQ requires ten finite gains between −12 and +12 dB")
    return gains


def spa(value):
    """PipeWire configuration uses SPA-JSON (no JSON array commas)."""
    if isinstance(value, dict):
        return "{ " + " ".join(json.dumps(k) + " = " + spa(v) for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[ " + " ".join(spa(v) for v in value) + " ]"
    return json.dumps(value)


def eq_config(gains, target):
    gains = gains_valid(gains)
    # Sum of positive peak gains is a conservative upper bound on the cascade.
    headroom = sum(max(0, gain) for gain in gains)
    nodes = [{"type": "builtin", "name": "pre", "label": "mixer", "control": {"Gain 1": 10 ** (-headroom / 20)}}]
    nodes += [{"type": "builtin", "name": f"eq{i}", "label": "bq_peaking",
               "control": {"Freq": frequency, "Q": 1.414, "Gain": gains[i]}} for i, frequency in enumerate(BANDS)]
    links = [{"output": "pre:Out", "input": "eq0:In"}]
    links += [{"output": f"eq{i}:Out", "input": f"eq{i+1}:In"} for i in range(9)]
    module = {"name": "libpipewire-module-filter-chain", "args": {
        "node.description": "Quattro Equalizer", "media.name": "Quattro Equalizer",
        "filter.graph": {"nodes": nodes, "links": links, "inputs": ["pre:In 1"], "outputs": ["eq9:Out"]},
        "audio.channels": 2, "audio.position": ["FL", "FR"],
        "capture.props": {"node.name": EQ_NAME, "media.class": "Audio/Sink"},
        "playback.props": {"node.name": EQ_NAME + "_output", "node.passive": True,
                           "target.object": target, "node.dont-fallback": True}}}
    return "context.modules = " + spa([{"name": "libpipewire-module-rt", "flags": ["ifexists", "nofail"]},
        {"name": "libpipewire-module-protocol-native"}, {"name": "libpipewire-module-client-node"},
        {"name": "libpipewire-module-adapter"}, module])


def eq_nodes():
    return [node for node in json.loads(run(["pw-dump"], timeout=3)) if node.get("type") == "PipeWire:Interface:Node"
            and node.get("info", {}).get("props", {}).get("node.name") == EQ_NAME]


def eq_status():
    state = load(CONFIG / "equalizer.json", {"gains": [0] * 10, "preset": "Flat", "enabled": False})
    state.update({"bands": BANDS, "presets": list(PRESETS), "active": bool(eq_nodes())})
    return state


def eq_apply(gains, preset="Custom", enabled=True, target=None):
    gains = gains_valid(gains)
    old = load(CONFIG / "equalizer.json", {})
    sinks = json.loads(run(["pactl", "-f", "json", "list", "sinks"]))
    physical = [s["name"] for s in sinks if s["name"] != EQ_NAME]
    default = run(["pactl", "get-default-sink"]).strip()
    target = target or (default if default != EQ_NAME else old.get("target"))
    if enabled and target not in physical:
        raise ValueError("Select an available physical output before enabling EQ")
    if not enabled:
        if default == EQ_NAME and old.get("target") in physical:
            run(["pactl", "set-default-sink", old["target"]])
        if old.get("target") in physical:
            eq_sink = next((s["index"] for s in sinks if s["name"] == EQ_NAME), None)
            for stream in json.loads(run(["pactl", "-f", "json", "list", "sink-inputs"])):
                if stream.get("sink") == eq_sink:
                    run(["pactl", "move-sink-input", str(stream["index"]), old["target"]])
        run(["systemctl", "--user", "disable", "--now", "quattro-equalizer.service"])
    else:
        atomic(CONFIG / "equalizer.conf", eq_config(gains, target))
        nodes = eq_nodes()
        if not nodes or target != old.get("target"):
            run(["systemctl", "--user", "enable", "quattro-equalizer.service"])
            run(["systemctl", "--user", "restart", "quattro-equalizer.service"])
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                nodes = eq_nodes()
                if nodes:
                    break
                time.sleep(.1)
            if not nodes:
                raise RuntimeError("PipeWire equalizer did not become available")
        # Live updates use SPA Props; the DSP graph is not restarted while dragging.
        params = ["pre:Gain 1", 10 ** (-sum(max(0, g) for g in gains) / 20)]
        for i, gain in enumerate(gains):
            params += [f"eq{i}:Gain", gain]
        run(["pw-cli", "set-param", str(nodes[0]["id"]), "Props", spa({"params": params})])
        if default != EQ_NAME:
            run(["pactl", "set-default-sink", EQ_NAME])
            for stream in json.loads(run(["pactl", "-f", "json", "list", "sink-inputs"])):
                if stream.get("properties", {}).get("node.name") != "quattro_eq_output":
                    run(["pactl", "move-sink-input", str(stream["index"]), EQ_NAME])
    state = {"gains": gains, "preset": preset, "enabled": enabled, "target": target or old.get("target", ""),
             "headroom": sum(max(0, g) for g in gains)}
    atomic(CONFIG / "equalizer.json", json.dumps(state))
    return {**state, "bands": BANDS, "presets": list(PRESETS), "active": enabled}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("weather")
    w.add_argument("--refresh", action="store_true")
    w.add_argument("--location", nargs=2, type=float)
    sub.add_parser("applications")
    app = sub.add_parser("application")
    app.add_argument("action", choices=["open", "close", "terminate", "force"])
    app.add_argument("address")
    app.add_argument("pid", type=int)
    app.add_argument("start")
    eq = sub.add_parser("eq")
    eq.add_argument("action", choices=["status", "preset", "custom", "disable", "output"])
    eq.add_argument("values", nargs="*")
    args = parser.parse_args()
    lock = None
    try:
        if args.command == "eq" and args.action != "status":
            CONFIG.mkdir(parents=True, exist_ok=True)
            lock = (CONFIG / "equalizer.lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another equalizer operation is running") from None
        if args.command == "weather":
            if args.location:
                lat, lon = coordinates(*args.location)
                atomic(CONFIG / "weather.json", json.dumps({"latitude": lat, "longitude": lon}))
            result = weather(args.refresh or bool(args.location))
        elif args.command == "applications":
            result = applications()
        elif args.command == "application":
            result = application_action(args.action, args.address, args.pid, args.start)
        elif args.action == "status":
            result = eq_status()
        else:
            state = eq_status()
            if args.action == "preset":
                name = " ".join(args.values)
                if name not in PRESETS:
                    raise ValueError("Unknown preset")
                result = eq_apply(PRESETS[name], name)
            elif args.action == "custom":
                result = eq_apply(args.values)
            elif args.action == "output":
                result = eq_apply(state["gains"], state["preset"], target=" ".join(args.values))
            else:
                result = eq_apply(state["gains"], state["preset"], enabled=False)
        print(json.dumps(result), flush=True)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error)[:400]}), flush=True)
        return 1
    finally:
        if lock is not None:
            lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
