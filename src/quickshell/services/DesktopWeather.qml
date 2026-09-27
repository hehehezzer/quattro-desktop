pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

QtObject {
    id: root
    property var snapshot: ({
            available: false,
            configured: false
        })
    property bool loading: worker.running
    property string error: ""
    property string glyph: {
        const c = snapshot.code;
        if (c === 0)
            return snapshot.day ? "󰖙" : "󰖔";
        if (c <= 3)
            return "󰖐";
        if (c <= 48)
            return "󰖑";
        if (c >= 95)
            return "󰖓";
        if (c >= 71 && c <= 77 || c === 85 || c === 86)
            return "󰖘";
        return "󰖖";
    }
    property string label: snapshot.available ? glyph + " " + Number(snapshot.temperature).toFixed(1) + "°C" + (snapshot.stale ? " *" : "") : loading ? "Weather…" : "Weather —"
    function refresh(force, latitude, longitude) {
        if (worker.running)
            return;
        let args = ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_desktop_controls.py", "weather"];
        if (force)
            args.push("--refresh");
        if (latitude !== undefined)
            args.push("--location", String(latitude), String(longitude));
        worker.command = args;
        worker.running = true;
    }
    Component.onCompleted: refresh(false)
    property Process worker: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const s = JSON.parse(text);
                    root.error = s.error || "";
                    if (s.available !== undefined)
                        root.snapshot = s;
                } catch (e) {
                    root.error = "Weather helper unavailable";
                }
            }
        }
    }
    property Timer refreshTimer: Timer {
        running: true
        repeat: true
        interval: 1800000
        onTriggered: root.refresh(false)
    }
}
