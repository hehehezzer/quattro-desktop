import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root
    property bool active: false
    property bool paused: false
    readonly property bool collecting: active && !paused
    property string command: Quickshell.env("QUATTRO_MONITOR_COMMAND") || Quickshell.env("HOME") + "/.local/bin/quattro-monitor"
    property var snapshot: null
    property var history: []
    property double receivedAt: 0
    property double clock: Date.now()
    property string problem: ""
    readonly property bool workerRunning: worker.running
    readonly property bool stale: snapshot !== null && clock - receivedAt > 6500
    readonly property string state: !active ? "Hidden" : paused ? "Paused" : stale ? "Stale" : problem ? "Unavailable" : snapshot ? "Live" : "Loading"
    readonly property string detail: paused ? "Sampling paused" : stale ? "Last valid readings retained · retrying" : problem ? problem : snapshot ? "Updates every 2 s" : "Waiting for host readings…"

    function finite(value, min, max, nullable) {
        if (nullable && value === null) return true
        return typeof value === "number" && isFinite(value) && value >= min && value <= max
    }
    function named(value) { return typeof value === "string" && value.length <= 128 && !/[\x00-\x1f\x7f]/.test(value) }
    function metric(value) {
        return value && typeof value.available === "boolean"
            && finite(value.totalBytes, 0, Number.MAX_SAFE_INTEGER, true)
            && finite(value.usedBytes, 0, Number.MAX_SAFE_INTEGER, true)
            && finite(value.availableBytes, 0, Number.MAX_SAFE_INTEGER, true)
            && finite(value.percent, 0, 100, true)
            && (value.totalBytes === null || value.usedBytes === null || value.usedBytes <= value.totalBytes)
    }
    function valid(s) {
        return s && s.schemaVersion === 1 && finite(s.updatedAt, 1, Number.MAX_SAFE_INTEGER / 1000, false)
            && s.cpu && typeof s.cpu.available === "boolean" && finite(s.cpu.percent, 0, 100, true)
            && Array.isArray(s.cpu.cores) && s.cpu.cores.length <= 512
            && s.cpu.cores.every(c => named(c.id) && finite(c.percent, 0, 100, true))
            && metric(s.memory) && metric(s.swap) && metric(s.filesystem) && s.filesystem.mount === "/"
            && finite(s.uptimeSeconds, 0, Number.MAX_SAFE_INTEGER, true)
            && s.network && typeof s.network.available === "boolean"
            && finite(s.network.rxBytesPerSecond, 0, Number.MAX_SAFE_INTEGER, true)
            && finite(s.network.txBytesPerSecond, 0, Number.MAX_SAFE_INTEGER, true)
            && Array.isArray(s.network.interfaces) && s.network.interfaces.length <= 32
            && s.network.interfaces.every(n => named(n.name) && finite(n.rxBytesPerSecond, 0, Number.MAX_SAFE_INTEGER, true) && finite(n.txBytesPerSecond, 0, Number.MAX_SAFE_INTEGER, true))
            && s.temperatures && typeof s.temperatures.available === "boolean"
            && Array.isArray(s.temperatures.sensors) && s.temperatures.sensors.length <= 32
            && s.temperatures.sensors.every(t => named(t.name) && finite(t.celsius, -40, 200, false))
            && s.gpu && typeof s.gpu.available === "boolean" && Array.isArray(s.gpu.devices) && s.gpu.devices.length <= 32
            && s.gpu.devices.every(g => named(g.name) && finite(g.busyPercent, 0, 100, true) && finite(g.memoryUsedBytes, 0, Number.MAX_SAFE_INTEGER, true) && finite(g.memoryTotalBytes, 1, Number.MAX_SAFE_INTEGER, true))
            && s.processes && typeof s.processes.available === "boolean" && typeof s.processes.truncated === "boolean"
            && finite(s.processes.omittedCount, 0, 4096, false)
            && s.processes.limit === 2048
            && Array.isArray(s.processes.items) && s.processes.items.length <= 2048
            && s.processes.items.every(p => named(p.name) && finite(p.pid, 1, 2147483647, false) && Math.floor(p.pid) === p.pid && finite(p.cpuPercent, 0, 51200, true) && finite(p.rssBytes, 0, Number.MAX_SAFE_INTEGER, false) && finite(p.rssPercent, 0, 100, true))
    }
    function consume(line) {
        if (!collecting) return false
        try {
            if (line.length > 1048576) throw new Error("oversize")
            const s = JSON.parse(line)
            if (!valid(s)) throw new Error("schema")
            const time = s.updatedAt * 1000
            if (snapshot && time <= snapshot.updatedAt * 1000) return false
            snapshot = s
            receivedAt = Date.now()
            clock = receivedAt
            problem = ""
            if (!history.length || time > history[history.length - 1].time) {
                history = history.concat([{time: time, cpu: s.cpu.available ? s.cpu.percent : null,
                    rx: s.network.available ? s.network.rxBytesPerSecond : null,
                    tx: s.network.available ? s.network.txBytesPerSecond : null}]).slice(-60)
            }
            return true
        } catch (error) {
            problem = "Readings unavailable · waiting for a valid update"
            return false
        }
    }
    function reconcile() {
        retry.stop()
        if (collecting) {
            clock = Date.now()
            problem = ""
            worker.running = true
        } else {
            worker.running = false
        }
    }
    onCollectingChanged: reconcile()
    Component.onCompleted: reconcile()
    Component.onDestruction: worker.running = false

    Process {
        id: worker
        command: [root.command, "watch", "2"]
        stdout: SplitParser { onRead: data => root.consume(data.trim()) }
        // Worker diagnostics may contain local paths; never echo them into UI/logs.
        stderr: SplitParser { onRead: data => {} }
        onRunningChanged: {
            if (!running && root.collecting) {
                root.problem = "Host readings unavailable · retrying"
                retry.restart()
            }
        }
        onExited: {
            if (root.collecting) {
                root.problem = "Host readings unavailable · retrying"
                retry.restart()
            }
        }
    }
    Timer {
        id: retry
        interval: 5000
        onTriggered: if (root.collecting) worker.running = true
    }
    Timer {
        interval: 1000
        repeat: true
        running: root.collecting
        onTriggered: root.clock = Date.now()
    }
}
