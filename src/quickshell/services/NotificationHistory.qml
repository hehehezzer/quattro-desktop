pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications

Scope {
    id: root
    // Private local archive: at most 100 entries retained for 24 hours.
    // Only plain notice fields are stored; native actions are never serialized.
    readonly property int retentionMs: 86400000
    readonly property int capacity: 100
    property bool storageReady: false
    property bool storageAvailable: false
    property string storageError: ""
    property bool editedWhileLoading: false
    property var carriedIds: ({})
    property string pendingPayload: "[]"
    property var entries: []
    onEntriesChanged: scheduleSave()
    function scheduleSave() {
        if (storageReady && storageAvailable && !saveDelay.running) saveDelay.start()
    }
    function save() {
        if (archiveWrite.running) { saveDelay.restart(); return; }
        pendingPayload = JSON.stringify(entries)
        archiveWrite.running = true
    }
    Component.onCompleted: archiveRead.running = true
    Process {
        id: archiveRead
        command: ["python3", Quickshell.env("HOME") + "/.local/bin/quattro-notification-store", "read"]
        clearEnvironment: true
        environment: ({HOME: Quickshell.env("HOME"), XDG_STATE_HOME: Quickshell.env("XDG_STATE_HOME"), PATH: "/usr/bin:/bin"})
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text)
                    if (!Array.isArray(result.entries)) throw new Error("unavailable")
                    if (!root.editedWhileLoading) {
                        // Reload-carried native notices already have a current live record.
                        const saved = result.entries.filter(e => !root.carriedIds[e.nativeId]
                            && !root.entries.some(current => current.key === e.key))
                        root.entries = root.entries.concat(saved).sort((a,b) => b.time-a.time)
                        if (root.opened) root.markSeen()
                        root.prune()
                    }
                    root.storageAvailable = true
                } catch (_) {
                    root.storageError = "Local history storage unavailable; this session is retained"
                }
                root.storageReady = true
                root.scheduleSave()
            }
        }
        onExited: {
            if (!root.storageReady) {
                root.storageReady = true
                root.storageError = "Local history storage unavailable; this session is retained"
            }
        }
    }
    Process {
        id: archiveWrite
        stdinEnabled: true
        command: ["python3", Quickshell.env("HOME") + "/.local/bin/quattro-notification-store", "write"]
        clearEnvironment: true
        environment: ({HOME: Quickshell.env("HOME"), XDG_STATE_HOME: Quickshell.env("XDG_STATE_HOME"), PATH: "/usr/bin:/bin"})
        onStarted: write(root.pendingPayload + "\n")
        onExited: (code, status) => {
            if (code !== 0) root.storageError = "Local history storage unavailable; this session is retained"
            else root.storageError = ""
        }
    }
    Timer { id: saveDelay; interval: 200; onTriggered: root.save() }
    Timer {
        interval: 3000; running: archiveRead.running || archiveWrite.running
        onTriggered: {
            archiveRead.running = false; archiveWrite.running = false
            root.storageReady = true
            root.storageError = "Local history storage unavailable; this session is retained"
        }
    }
    property var active: ({})
    property int unseenCount: 0
    property bool opened: false
    signal openRequested()
    signal toggleRequested()
    property int serial: 0
    function open() { openRequested() }
    function toggle() { toggleRequested() }
    function seen() { unseenCount = 0 }
    function prune() {
        const cutoff = Date.now() - retentionMs
        entries = entries.filter(e => e.time >= cutoff).slice(0, capacity)
        unseenCount = entries.filter(e => !e.seen).length
    }
    function clear() { editedWhileLoading = true; entries = []; unseenCount = 0; scheduleSave() }
    function remove(key) {
        editedWhileLoading = true
        entries = entries.filter(e => e.key !== key)
        unseenCount = entries.filter(e => !e.seen).length
    }
    function markSeen() {
        entries = entries.map(e => Object.assign({}, e, {seen: true}))
        seen()
    }
    function receive(notification) {
        notification.tracked = true
        const id = String(notification.id)
        if (notification.lastGeneration) {
            const carried = Object.assign({}, carriedIds); carried[id] = true; carriedIds = carried
        }
        let clock = active[id]
        if (!clock) {
            clock = lifetime.createObject(root, {notice: notification})
            const next = Object.assign({}, active); next[id] = clock; active = next
        }
        clock.reset()
        // Replacements update one history record rather than inventing a new notice.
        const previous = entries.find(e => e.nativeId === id && e.key === clock.key)
        if (!previous) clock.key = String(++serial) + "-" + Date.now()
        // A transient sender explicitly asks not to retain the notice in a history area.
        if (!notification.transient) {
        entries = [{key: clock.key, nativeId: id, app: String(notification.appName).slice(0, 256),
            summary: String(notification.summary).slice(0, 2048), body: String(notification.body).slice(0, 8192),
            time: Date.now(), urgency: notification.urgency, seen: opened}].concat(entries.filter(e => e.key !== clock.key))
        }
        prune()
    }
    function release(id, clock) {
        if (active[id] !== clock) return
        const next = Object.assign({}, active); delete next[id]; active = next
        clock.notice = null
        clock.destroy()
    }
    function current(id) { return active[String(id)] || null }
    function dismiss(id) { const c = current(id); if (c && c.notice) c.notice.dismiss() }
    function invoke(id, identifier) {
        const c = current(id)
        if (!c || !c.notice) return
        const action = c.notice.actions.find(a => a.identifier === identifier)
        // invoke() owns native resident/dismiss behavior. Do not dismiss again.
        if (action) action.invoke()
    }
    Timer { interval: 60000; running: true; repeat: true; onTriggered: root.prune() }
    Component {
        id: lifetime
        QtObject {
            id: clock
            property var notice: null
            property string key: ""
            property real duration: 0
            property real remaining: 0
            property real deadline: 0
            property bool paused: false
            property bool persistent: duration === 0
            property bool updatePending: false
            function updated() {
                if (updatePending) return
                updatePending = true
                const id = notice ? String(notice.id) : ""
                Qt.callLater(() => {
                    const current = root.current(id)
                    if (current !== clock) return
                    current.updatePending = false
                    if (current.notice) root.receive(current.notice)
                })
            }
            function reset() {
                duration = notice.urgency === NotificationUrgency.Critical || notice.expireTimeout === 0
                    ? 0 : notice.expireTimeout < 0 ? 5000 : notice.expireTimeout
                remaining = duration
                deadline = Date.now() + remaining
            }
            function pause(value) {
                if (paused === value) return
                if (value && !persistent) remaining = Math.max(0, deadline - Date.now())
                paused = value
                if (!value) deadline = Date.now() + remaining
            }
            property Timer tick: Timer {
                interval: 40; repeat: true; running: clock.notice !== null && !clock.persistent && !clock.paused
                onTriggered: {
                    clock.remaining = Math.max(0, clock.deadline - Date.now())
                    if (clock.remaining === 0 && clock.notice) clock.notice.expire()
                }
            }
            property Connections events: Connections {
                target: clock.notice
                function onSummaryChanged() { clock.updated() }
                function onBodyChanged() { clock.updated() }
                function onAppNameChanged() { clock.updated() }
                function onUrgencyChanged() { clock.updated() }
                function onExpireTimeoutChanged() { clock.updated() }
                function onActionsChanged() { clock.updated() }
                function onClosed(reason) {
                    if (clock.notice) root.release(String(clock.notice.id), clock)
                }
            }
        }
    }
    IpcHandler {
        target: "notifications"
        function open(): void { root.open() }
        function toggle(): void { root.toggle() }
        function status(): string { return JSON.stringify({open: root.opened, unseen: root.unseenCount,
            saved: root.entries.length, active: Object.keys(root.active).length, retentionHours: 24, capacity: 100, storage: root.storageAvailable && !root.storageError ? "local" : "session", storageReady: root.storageReady}) }
    }
}
