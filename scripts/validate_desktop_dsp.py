#!/usr/bin/env python3
"""Opt-in live DSP proof using an isolated null sink; never changes default output.

Requires an active PipeWire/Pulse session, paplay and parecord. The test emits
only into a temporary null sink and removes its graph, sink and files on exit.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import quattro_desktop_controls as desktop  # noqa: E402


def record_rms():
    process = subprocess.Popen(
        ["parecord", "--device=quattro_validation.monitor", "--raw", "--format=s16le",
         "--rate=48000", "--channels=2", "--latency-msec=50"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        process.communicate(timeout=1.2)
        raise RuntimeError("Recorder exited before capture completed")
    except subprocess.TimeoutExpired:
        process.terminate()
        data, errors = process.communicate(timeout=3)
    if len(data) < 8192:
        raise RuntimeError("Insufficient audio captured: " + errors.decode(errors="replace")[:200])
    # Ignore startup/transient samples.
    data = data[-(len(data) // 8) * 4:]
    values = struct.unpack("<" + "h" * (len(data) // 2), data)
    return math.sqrt(sum(value * value for value in values) / len(values))


def main():
    desktop.EQ_NAME = "quattro_validation_eq"
    original_default = desktop.run(["pactl", "get-default-sink"]).strip()
    module = desktop.run(["pactl", "load-module", "module-null-sink", "sink_name=quattro_validation"]).strip()
    graph = player = None
    try:
        with tempfile.TemporaryDirectory(prefix="quattro-dsp-") as directory:
            root = Path(directory)
            config = root / "filter.conf"
            config.write_text(desktop.eq_config([0] * 10, "quattro_validation"))
            with wave.open(str(root / "tone.wav"), "wb") as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                block = b"".join(struct.pack("<hh", *([int(1000 * math.sin(2 * math.pi * 125 * i / 48000))] * 2))
                                 for i in range(48000))
                stream.writeframes(block * 15)
            graph = subprocess.Popen(["pipewire", "-c", str(config)], stdout=subprocess.DEVNULL)
            nodes = []
            for _ in range(30):
                nodes = desktop.eq_nodes()
                if nodes:
                    break
                time.sleep(.1)
            if not nodes:
                raise RuntimeError("Test graph did not appear")
            node = str(nodes[0]["id"])
            player = subprocess.Popen(["paplay", "--device=" + desktop.EQ_NAME, str(root / "tone.wav")])
            time.sleep(.4)
            flat = record_rms()
            desktop.run(["pw-cli", "set-param", node, "Props", desktop.spa({"params": ["eq2:Gain", 6.0]})])
            time.sleep(.2)
            boosted = record_rms()
            props = desktop.run(["pw-cli", "enum-params", node, "Props"])
            if not re.search(r'String "eq2:Gain"\s+Float 6\.000000', props):
                raise RuntimeError("Live SPA gain was not acknowledged")
            desktop.run(["pw-cli", "set-param", node, "Props", desktop.spa({"params": ["eq2:Gain", 0.0]})])
            time.sleep(.2)
            reset = record_rms()
            if flat <= 0 or not 1.90 < boosted / flat < 2.10 or not .95 < reset / flat < 1.05:
                raise RuntimeError(f"Unexpected response: flat={flat}, boosted={boosted}, reset={reset}")
            if desktop.run(["pactl", "get-default-sink"]).strip() != original_default:
                raise RuntimeError("Default output changed unexpectedly")
            print(json.dumps({"status": "PASSED", "frequencyHz": 125,
                              "flatRms": round(flat, 2), "boost6dBRms": round(boosted, 2),
                              "resetRms": round(reset, 2), "defaultOutputPreserved": True}))
    finally:
        for process in (player, graph):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        desktop.run(["pactl", "unload-module", module])


if __name__ == "__main__":
    main()
