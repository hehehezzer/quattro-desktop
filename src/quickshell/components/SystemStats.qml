import Quickshell
import Quickshell.Io
import QtQuick

Scope {
    id: root

    property var snapshot: ({
        "schemaVersion": 1,
        "cpuPercent": 0,
        "ramPercent": 0,
        "ramUsedBytes": 0,
        "ramTotalBytes": 0,
        "updatedAt": 0,
        "available": false
    })

    Process {
        id: monitorProcess
        running: true
        command: [
            Quickshell.env("HOME") + "/.local/bin/quattro-system-stats",
            "watch",
            "2"
        ]

        stdout: SplitParser {
            onRead: data => {
                try {
                    const parsed = JSON.parse(data.trim())
                    if (parsed.schemaVersion !== 1)
                        return
                    parsed.available = true
                    root.snapshot = parsed
                } catch (error) {
                    // Keep the last known good snapshot through a malformed line.
                }
            }
        }

        onExited: restartTimer.restart()
    }

    Timer {
        id: restartTimer
        interval: 5000
        repeat: false
        onTriggered: monitorProcess.running = true
    }
}
