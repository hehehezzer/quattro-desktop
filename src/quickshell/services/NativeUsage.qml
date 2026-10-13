pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

QtObject {
    id: root
    property var snapshot: ({"schemaVersion": 1, "status": "unavailable", "stale": true})
    readonly property bool loading: worker.running

    function refresh() {
        if (!worker.running)
            worker.running = true
    }
    function failed() {
        snapshot = Object.assign({}, snapshot, {
            stale: true,
            status: snapshot.primary ? "stale" : "unavailable",
            message: "Native usage helper unavailable. Showing saved limits."
        })
    }

    Component.onCompleted: refresh()
    property Process worker: Process {
        command: ["/usr/bin/python3", Quickshell.env("HOME") + "/.local/bin/quattro_native_usage.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const value = JSON.parse(text)
                    if (value.schemaVersion !== 1)
                        throw new Error("Invalid usage snapshot")
                    root.snapshot = value
                } catch (error) {
                    root.failed()
                }
            }
        }
        onExited: function(code, status) {
            if (code !== 0)
                root.failed()
        }
    }
    property Timer refreshTimer: Timer {
        running: true
        repeat: true
        interval: 120000
        onTriggered: root.refresh()
    }
    property IpcHandler ipc: IpcHandler {
        target: "usage"
        function status(): string { return JSON.stringify(root.snapshot) }
        function refresh(): void { root.refresh() }
    }
}
