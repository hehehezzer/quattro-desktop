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
EQ_RESTART_MARKER = CONFIG / "equalizer.restarting"


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


# Generic city fallback, never an inferred personal location (GeoNames 1701668).
DEFAULT_LOCATION = {"id": 1701668, "name": "Manila", "admin1": "Metro Manila",
                    "country": "Philippines", "country_code": "PH", "timezone": "Asia/Manila",
                    "latitude": 14.6042, "longitude": 120.9822}


def normalize_place(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid weather location")
    lat, lon = coordinates(value["latitude"], value["longitude"])
    result = {"latitude": lat, "longitude": lon}
    for key in ("name", "admin1", "admin2", "country", "country_code", "timezone"):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > 160 or any(ord(c) < 32 for c in text):
            raise ValueError("Invalid location metadata")
        result[key] = text.strip()
    if result["timezone"] and not re.fullmatch(r"[A-Za-z0-9_+./-]{1,80}", result["timezone"]):
        raise ValueError("Invalid location timezone")
    if isinstance(value.get("id"), int) and not isinstance(value["id"], bool):
        result["id"] = value["id"]
    parts = []
    for key in ("name", "admin2", "admin1", "country"):
        if result[key] and result[key] not in parts:
            parts.append(result[key])
    result["label"] = ", ".join(parts) or "Saved location"
    return result


def geocode(query):
    query = query.strip()
    if len(query) < 2:
        return {"query": query, "results": []}
    if len(query) > 100 or any(ord(c) < 32 for c in query):
        raise ValueError("Search must be 2–100 characters")
    params = urllib.parse.urlencode({"name": query, "count": 8, "language": "en", "format": "json"})
    request = urllib.request.Request("https://geocoding-api.open-meteo.com/v1/search?" + params,
                                     headers={"User-Agent": "QuattroDesktop/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read(65536))
        rows = data.get("results", [])
        if not isinstance(rows, list):
            raise ValueError("Invalid geocoding results")
        results = []
        for row in rows[:8]:
            place = normalize_place(row)
            if place["name"]:
                results.append(place)
        return {"query": query, "results": results}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"query": query, "results": [], "error": "Location search unavailable. Check your connection and retry."}


def save_place(value):
    place = normalize_place(value)
    if not place["name"]:
        raise ValueError("Select a named location")
    atomic(CONFIG / "weather.json", json.dumps(place, ensure_ascii=False))
    return place


def weather(force=False):
    saved = load(CONFIG / "weather.json", {})
    location = normalize_place(saved or DEFAULT_LOCATION)
    context = {"place": location, "defaultLocation": not bool(saved), "configured": True}
    cached = load(CACHE / "weather.json", {})
    lat, lon = location["latitude"], location["longitude"]
    timezone = location["timezone"] or "auto"
    if cached.get("location") != [lat, lon] or cached.get("timezone", "auto") != timezone:
        cached = {}
    if not force and 0 <= time.time() - cached.get("updated", 0) < 1800:
        return {**cached, **context, "cached": True}
    try:
        query = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
            "current": "temperature_2m,weather_code,is_day", "temperature_unit": "celsius", "timezone": timezone})
        request = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + query,
                                         headers={"User-Agent": "QuattroDesktop/1.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read(65536))["current"]
        temperature = float(data["temperature_2m"])
        if not math.isfinite(temperature) or not -100 <= temperature <= 70:
            raise ValueError("Invalid temperature")
        result = {"available": True, "configured": True, "temperature": temperature,
                  "code": int(data["weather_code"]), "day": bool(data["is_day"]),
                  "updated": time.time(), "location": [lat, lon], "timezone": timezone, "cached": False}
        atomic(CACHE / "weather.json", json.dumps(result))
        return {**result, **context}
    except (OSError, ValueError, KeyError, TypeError):
        return {**cached, **context, "available": bool(cached), "cached": bool(cached),
                "stale": True, "error": "Showing saved conditions. Refresh when online."
                if cached else "Weather is unavailable. Check your connection and refresh."}


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


def physical_sinks(sinks):
    """Return stable hardware sink names, excluding virtual/mixing sinks."""
    return [sink["name"] for sink in sinks
            if isinstance(sink.get("name"), str)
            and (sink["name"].startswith("alsa_output.")
                 or sink["name"].startswith("bluez_output."))]


def eq_graph_active(target=None):
    dump = json.loads(run(["pw-dump"], timeout=3))
    names = {node.get("info", {}).get("props", {}).get("node.name"): node
             for node in dump if node.get("type") == "PipeWire:Interface:Node"}
    capture = names.get(EQ_NAME)
    playback = names.get(EQ_NAME + "_output")
    if not capture or not playback:
        return False
    configured_target = playback.get("info", {}).get("props", {}).get("target.object")
    if target and configured_target != target:
        return False
    if configured_target:
        links = run(["pw-link", "-l"], timeout=3)
        relationship = re.compile(
            rf"(?m)^quattro_eq_output:output_[^\n]*\n\s*\|-> {re.escape(configured_target)}:playback_"
        )
        if not relationship.search(links):
            return False
    return True


def eq_move_streams(sinks, target, source_sink=None):
    source_index = next((sink.get("index") for sink in sinks
                         if sink.get("name") == source_sink), None)
    for stream in json.loads(run(["pactl", "-f", "json", "list", "sink-inputs"])):
        if source_sink is None or stream.get("sink") == source_index:
            if stream.get("properties", {}).get("node.name") != "quattro_eq_output":
                run(["pactl", "move-sink-input", str(stream["index"]), target])


def eq_recover(reason="DSP unavailable"):
    """Bypass a missing DSP graph to an available physical output."""
    state = load(CONFIG / "equalizer.json", {})
    sinks = json.loads(run(["pactl", "-f", "json", "list", "sinks"]))
    physical = physical_sinks(sinks)
    default = run(["pactl", "get-default-sink"]).strip()
    target = state.get("target") if state.get("target") in physical else None
    if target is None and default in physical:
        target = default
    if target is None and physical:
        target = physical[0]
    if target is None:
        raise RuntimeError("No physical audio output is available")
    if default != target:
        run(["pactl", "set-default-sink", target])
    # WirePlumber may already have evacuated streams to an arbitrary fallback
    # before ExecStopPost runs. Reunite them on the user's saved output.
    eq_move_streams(sinks, target)
    recovered = {**state, "enabled": False, "target": target, "degraded": True,
                 "error": reason[:160]}
    atomic(CONFIG / "equalizer.json", json.dumps(recovered))
    return {**recovered, "bands": BANDS, "presets": list(PRESETS), "active": False}


def eq_temporary_bypass(target):
    """Keep sound alive during a supervised DSP rebuild without disabling EQ."""
    sinks = json.loads(run(["pactl", "-f", "json", "list", "sinks"]))
    if target not in physical_sinks(sinks):
        raise RuntimeError("Saved physical output is unavailable")
    run(["pactl", "set-default-sink", target])
    eq_move_streams(sinks, target)


def eq_activate():
    """Fail startup unless the persisted target and DSP sink are both live."""
    state = load(CONFIG / "equalizer.json", {})
    target = state.get("target")
    sinks = []
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            sinks = json.loads(run(["pactl", "-f", "json", "list", "sinks"]))
            if target in physical_sinks(sinks) and eq_graph_active(target):
                break
        except (RuntimeError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(.1)
    else:
        eq_recover("DSP or saved output did not recover; EQ bypassed")
        raise RuntimeError("PipeWire equalizer or its saved output did not become available")
    run(["pactl", "set-default-sink", EQ_NAME])
    eq_move_streams(sinks, EQ_NAME)
    active = {**state, "enabled": True, "degraded": False}
    active.pop("error", None)
    atomic(CONFIG / "equalizer.json", json.dumps(active))
    return {**active, "bands": BANDS, "presets": list(PRESETS), "active": True}


def eq_status():
    state = load(CONFIG / "equalizer.json", {"gains": [0] * 10, "preset": "Flat", "enabled": False})
    active = eq_graph_active(state.get("target"))
    if state.get("enabled") and not active:
        try:
            return eq_recover("DSP graph unavailable; EQ bypassed")
        except RuntimeError:
            pass
    state.update({"bands": BANDS, "presets": list(PRESETS), "active": active})
    if state.get("enabled") and not active:
        state.update({"enabled": False, "degraded": True,
                      "error": "DSP unavailable; using physical output"})
    return state


def eq_should_start():
    state = load(CONFIG / "equalizer.json", {})
    if state.get("enabled") is not True:
        raise RuntimeError("Equalizer is bypassed")
    return {"enabled": True}


def eq_service_stopped(result):
    if result == "success":
        return {"recovering": True}
    return eq_recover("DSP stopped unexpectedly; EQ bypassed")


def eq_supervise():
    """Own and continuously validate the DSP process and its physical link."""
    state = load(CONFIG / "equalizer.json", {})
    if state.get("enabled") is not True:
        return {"enabled": False}
    child = subprocess.Popen(["/usr/bin/pipewire", "-c", str(CONFIG / "equalizer.conf")])
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
        child.terminate()

    prior = {signal.SIGTERM: signal.signal(signal.SIGTERM, stop),
             signal.SIGINT: signal.signal(signal.SIGINT, stop)}
    try:
        eq_activate()
        missing_since = None
        while not stopping and child.poll() is None:
            if not eq_graph_active(state.get("target")):
                try:
                    run(["pactl", "info"], timeout=2)
                except RuntimeError:
                    # The core graph is restarting. Preserve enabled state so
                    # systemd can retry once Pulse/WirePlumber return.
                    raise RuntimeError("Core audio graph is restarting")
                missing_since = missing_since or time.monotonic()
                if time.monotonic() - missing_since >= 5:
                    eq_temporary_bypass(state.get("target"))
                    child.terminate()
                    raise RuntimeError("DSP graph disconnected; rebuilding")
            else:
                missing_since = None
            time.sleep(1)
        if stopping:
            if EQ_RESTART_MARKER.exists():
                return {"restarting": True}
            eq_recover("DSP service stopped; EQ bypassed")
            return {"enabled": False, "degraded": True}
        try:
            eq_temporary_bypass(state.get("target"))
        except RuntimeError:
            pass
        raise RuntimeError("Equalizer process exited unexpectedly")
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        for signum, handler in prior.items():
            signal.signal(signum, handler)


def eq_apply(gains, preset="Custom", enabled=True, target=None):
    gains = gains_valid(gains)
    old = load(CONFIG / "equalizer.json", {})
    sinks = json.loads(run(["pactl", "-f", "json", "list", "sinks"]))
    physical = physical_sinks(sinks)
    default = run(["pactl", "get-default-sink"]).strip()
    target = target or (default if default != EQ_NAME else old.get("target"))
    if enabled and target not in physical:
        raise ValueError("Select an available physical output before enabling EQ")
    if not enabled:
        if default == EQ_NAME and old.get("target") in physical:
            run(["pactl", "set-default-sink", old["target"]])
        if old.get("target") in physical:
            eq_move_streams(sinks, old["target"], EQ_NAME)
        run(["systemctl", "--user", "disable", "--now", "quattro-equalizer.service"])
    else:
        try:
            atomic(CONFIG / "equalizer.conf", eq_config(gains, target))
            atomic(CONFIG / "equalizer.json", json.dumps({"gains": gains, "preset": preset,
                "enabled": True, "target": target, "headroom": sum(max(0, g) for g in gains)}))
            nodes = eq_nodes()
            if not eq_graph_active(target) or target != old.get("target"):
                run(["systemctl", "--user", "enable", "quattro-equalizer.service"])
                atomic(EQ_RESTART_MARKER, "reconfigure\n")
                try:
                    run(["systemctl", "--user", "restart", "quattro-equalizer.service"])
                finally:
                    EQ_RESTART_MARKER.unlink(missing_ok=True)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    nodes = eq_nodes()
                    if nodes and eq_graph_active(target):
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError("PipeWire equalizer did not become available")
            # Live updates use SPA Props; the DSP graph is not restarted while dragging.
            params = ["pre:Gain 1", 10 ** (-sum(max(0, g) for g in gains) / 20)]
            for i, gain in enumerate(gains):
                params += [f"eq{i}:Gain", gain]
            run(["pw-cli", "set-param", str(nodes[0]["id"]), "Props", spa({"params": params})])
            if default != EQ_NAME:
                run(["pactl", "set-default-sink", EQ_NAME])
                eq_move_streams(sinks, EQ_NAME)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError):
            eq_recover("EQ activation failed; using physical output")
            raise
    state = {"gains": gains, "preset": preset, "enabled": enabled, "target": target or old.get("target", ""),
             "headroom": sum(max(0, g) for g in gains), "degraded": False}
    atomic(CONFIG / "equalizer.json", json.dumps(state))
    return {**state, "bands": BANDS, "presets": list(PRESETS), "active": enabled}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("weather")
    w.add_argument("--refresh", action="store_true")
    w.add_argument("--location", nargs=2, type=float, help="Legacy scripting interface; use the desktop location picker")
    w.add_argument("--place", help="Selected geocoder location as JSON")
    search = sub.add_parser("geocode")
    search.add_argument("query")
    sub.add_parser("applications")
    app = sub.add_parser("application")
    app.add_argument("action", choices=["open", "close", "terminate", "force"])
    app.add_argument("address")
    app.add_argument("pid", type=int)
    app.add_argument("start")
    eq = sub.add_parser("eq")
    eq.add_argument("action", choices=["status", "preset", "custom", "disable", "output",
                                      "activate", "recover", "should-start", "service-stopped",
                                      "supervise"])
    eq.add_argument("values", nargs="*")
    args = parser.parse_args()
    lock = None
    try:
        if args.command == "eq" and args.action not in {
                "status", "activate", "recover", "should-start", "service-stopped", "supervise"}:
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
            if args.place:
                if len(args.place) > 4096:
                    raise ValueError("Location payload too large")
                save_place(json.loads(args.place))
            result = weather(args.refresh or bool(args.location) or bool(args.place))
        elif args.command == "geocode":
            result = geocode(args.query)
        elif args.command == "applications":
            result = applications()
        elif args.command == "application":
            result = application_action(args.action, args.address, args.pid, args.start)
        elif args.action == "status":
            result = eq_status()
        elif args.action == "activate":
            result = eq_activate()
        elif args.action == "recover":
            result = eq_recover("DSP stopped; EQ bypassed")
        elif args.action == "should-start":
            result = eq_should_start()
        elif args.action == "service-stopped":
            result = eq_service_stopped(" ".join(args.values))
        elif args.action == "supervise":
            result = eq_supervise()
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
