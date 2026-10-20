pragma ComponentBehavior: Bound
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as QuattroTheme
import "../services"
import "shared"

// Operate: a project-scoped Intelligence workspace in the existing Instrument
// Sheet world. Search leads; three independent quota ledgers replace account
// switching. Real semantic availability controls Hybrid/Lexical state. No agent
// execution, approvals or automatic indexing. Fixed chrome, scrollable evidence.
Scope {
    id: root
    property bool opened: false
    property string page: "knowledge"
    property string mode: "knowledge"
    property string project: ""
    property string queryDraft: ""
    property var dashboard: ({status: "loading", projects: []})
    property var results: []
    property var searchMeta: ({})
    property string searchState: "idle"
    property string searchMessage: ""
    property string requestedProject: ""
    property string requestedMode: ""
    property string requestedQuery: ""
    property var queryEditor: null
    property double clock: Date.now()
    readonly property string helper: Quickshell.env("HOME") + "/.local/bin/quattro_intelligence_panel.py"
    readonly property var projects: array(dashboard.projects)
    readonly property var currentProject: projects.find(item => item.id === project) || ({})
    readonly property var accounts: NativeUsage.snapshot.primary ? [NativeUsage.snapshot] : []
    readonly property bool compact: intelligenceWindow.width < 580
    readonly property var retrievalInfo: mode !== "memory" && searchState === "ready" ? searchMeta : dashboard

    function array(value) { return Array.isArray(value) ? value : [] }
    function focusedScreen() {
        for (const screen of Quickshell.screens)
            if (Hyprland.monitorFor(screen) === Hyprland.focusedMonitor) return screen
        return Quickshell.screens[0]
    }
    function open(target) {
        page = target || "knowledge"
        intelligenceWindow.screen = focusedScreen()
        opened = true
        refresh()
        Qt.callLater(() => queryEditor ? queryEditor.forceActiveFocus() : keyScope.forceActiveFocus())
    }
    function close() { opened = false }
    function refresh() {
        if (!stateProcess.running) stateProcess.running = true
        NativeUsage.refresh()
    }
    function clearSearch() {
        results = []; searchMeta = ({}); searchState = "idle"; searchMessage = ""
    }
    onProjectChanged: clearSearch()
    onModeChanged: clearSearch()
    onQueryDraftChanged: clearSearch()
    function search() {
        if (searchProcess.running || !project || !queryDraft.trim()) return
        requestedProject = project; requestedMode = mode; requestedQuery = queryDraft.trim()
        results = []; searchMeta = ({}); searchState = "loading"; searchMessage = ""
        searchProcess.command = ["/usr/bin/python3", helper, "search", "--project", project,
                                 "--mode", mode, "--query=" + requestedQuery]
        searchProcess.running = true
    }
    function age(timestamp) {
        const seconds = Math.max(0, Math.floor((clock - new Date(timestamp).getTime()) / 1000))
        if (!Number.isFinite(seconds)) return "Update time unavailable"
        if (seconds < 60) return "Updated just now"
        if (seconds < 3600) return "Updated " + Math.floor(seconds / 60) + "m ago"
        if (seconds < 86400) return "Updated " + Math.floor(seconds / 3600) + "h ago"
        return "Updated " + Math.floor(seconds / 86400) + "d ago"
    }
    function resetText(epoch) {
        if (!epoch) return "Reset unavailable"
        const seconds = Math.floor(Number(epoch) - clock / 1000)
        if (seconds <= 0) return "Reset passed · refresh needed"
        if (seconds < 3600) return "Resets in " + Math.ceil(seconds / 60) + "m"
        if (seconds < 86400) return "Resets in " + Math.floor(seconds / 3600) + "h " + Math.floor(seconds % 3600 / 60) + "m"
        return "Resets in " + Math.floor(seconds / 86400) + "d " + Math.floor(seconds % 86400 / 3600) + "h"
    }
    function windowName(window) {
        if (!window) return ""
        const minutes = Number(window.windowMinutes)
        return minutes === 300 ? "5 hours" : minutes === 10080 ? "Week"
            : minutes === 1440 ? "Day" : minutes >= 60 ? minutes / 60 + " hours" : minutes + " minutes"
    }
    function quotaState(account) {
        const expired = [account.primary, account.secondary].some(window => window && window.resetAt && window.resetAt * 1000 <= clock)
        const old = account.fetchedAt && clock - account.fetchedAt > 900000
        return account.status === "live" && (expired || old) ? "stale" : account.status || "unavailable"
    }
    function tightest(account) {
        const windows = [account.primary, account.secondary].filter(window => !!window)
        return windows.sort((a, b) => b.usedPercent - a.usedPercent)[0] || null
    }
    function remaining(window) { return window ? Math.round(100 - window.usedPercent) : 0 }
    function readingColor(window) {
        return remaining(window) <= 10 ? QuattroTheme.Theme.danger
            : remaining(window) <= 30 ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textStrong
    }

    Connections {
        target: PopupManager
        function onRequested(name) { if (name === "agents") root.opened ? root.close() : root.open("knowledge") }
    }
    IpcHandler {
        target: "agents"
        function open(): void { root.open("knowledge") }
        function close(): void { root.close() }
        function toggle(): void { root.opened ? root.close() : root.open("knowledge") }
        function search(): void { root.open("knowledge") }
        function usage(): void { root.open("usage") }
        function system(): void { root.open("status") }
        function refresh(): void { root.refresh() }
        function query(text: string): void { root.queryDraft = text; root.search() }
        function mode(value: string): void { if (["knowledge", "context", "memory"].indexOf(value) >= 0) root.mode = value }
        function status(): string {
            return JSON.stringify({opened: root.opened, page: root.page, project: root.project,
                mode: root.mode, state: root.dashboard.status, searchState: root.searchState,
                results: root.results.length, semanticAvailable: root.dashboard.semanticAvailable})
        }
    }
    Process {
        id: stateProcess
        command: ["/usr/bin/python3", root.helper, "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const next = JSON.parse(text)
                    if (next.schemaVersion !== 1) throw new Error("Invalid state")
                    root.dashboard = next
                    if (!root.projects.some(item => item.id === root.project))
                        root.project = root.projects.length ? root.projects[0].id : ""
                } catch (error) {
                    root.dashboard = ({status: "unavailable", projects: [], message: "Intelligence helper unavailable. Check the core runtime."})
                    root.project = ""
                }
            }
        }
        onExited: function(code, status) {
            if (code !== 0) {
                root.dashboard = ({status: "unavailable", projects: [], message: "Intelligence helper unavailable. Check the core runtime."})
                root.project = ""
            }
        }
    }
    Process {
        id: searchProcess
        stdout: StdioCollector {
            onStreamFinished: {
                if (root.requestedProject !== root.project || root.requestedMode !== root.mode || root.requestedQuery !== root.queryDraft.trim()) return
                try {
                    const next = JSON.parse(text)
                    if (next.schemaVersion !== 1) throw new Error("Invalid results")
                    root.searchMeta = next
                    root.results = root.array(next.results)
                    root.searchState = next.status === "ready" ? "ready" : "error"
                    root.searchMessage = next.message || ""
                } catch (error) {
                    root.searchState = "error"; root.searchMessage = "Search unavailable. Check Intelligence and retry."
                }
            }
        }
        onExited: function(code, status) {
            if (code !== 0 && root.requestedProject === root.project && root.requestedMode === root.mode) {
                root.searchState = "error"; root.searchMessage = "Search unavailable. Check Intelligence and retry."
            }
        }
    }
    Timer { running: root.opened; repeat: true; interval: 60000; onTriggered: { if (!stateProcess.running) stateProcess.running = true } }
    Timer { running: root.opened; repeat: true; interval: 2000; onTriggered: root.clock = Date.now() }

    TemporaryPanel {
        id: intelligenceWindow
        panelName: "agents"
        opened: root.opened
        onDismissed: root.close()
        anchors { top: true; bottom: true; right: true }
        margins { top: QuattroTheme.Theme.barHeight + 12; bottom: 12; right: 12 }
        implicitWidth: Math.min(760, (screen ? screen.width : 784) - 24)
        color: "transparent"
        Rectangle {
            anchors.fill: parent
            color: QuattroTheme.Theme.background
            border.width: 1
            border.color: QuattroTheme.Theme.panelBorder
            MouseArea { anchors.fill: parent }
            FocusScope {
                id: keyScope
                anchors.fill: parent
                focus: intelligenceWindow.visible
                Shortcut { sequence: "Escape"; context: Qt.WindowShortcut; onActivated: root.close() }
                Shortcut { sequence: "F5"; context: Qt.WindowShortcut; onActivated: root.refresh() }
                Shortcut {
                    sequence: "Ctrl+K"; context: Qt.WindowShortcut
                    onActivated: { root.page = "knowledge"; Qt.callLater(() => root.queryEditor ? root.queryEditor.forceActiveFocus() : undefined) }
                }
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: QuattroTheme.Theme.spaceXl
                    spacing: QuattroTheme.Theme.spaceLg
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4
                            Label { text: "Intelligence"; font.pixelSize: 26; font.weight: Font.Medium; color: QuattroTheme.Theme.textStrong }
                            Label { text: "Knowledge, context & persistent memory"; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                        }
                        DesktopButton { text: "Close"; quiet: true; onClicked: root.close() }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Repeater {
                            model: [{id: "knowledge", title: "Knowledge"}, {id: "usage", title: "Usage limits"}, {id: "status", title: "Status"}]
                            delegate: DesktopButton {
                                required property var modelData
                                text: modelData.title
                                prominent: root.page === modelData.id
                                quiet: root.page !== modelData.id
                                Layout.fillWidth: true
                                onClicked: root.page = modelData.id
                            }
                        }
                    }
                    Rule {}
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: root.page === "usage" ? usagePage : root.page === "status" ? statusPage : knowledgePage
                    }
                    Rule {}
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: root.dashboard.status === "ready" ? "Local Intelligence · " + root.dashboard.retrievalMode : stateProcess.running ? "Loading Intelligence…" : "Intelligence unavailable"; color: root.dashboard.status === "ready" ? QuattroTheme.Theme.textMuted : QuattroTheme.Theme.warning; Layout.fillWidth: true; elide: Text.ElideRight }
                        Label { text: "Ctrl+K search · F5 refresh"; visible: !root.compact; color: QuattroTheme.Theme.textMuted }
                    }
                }
            }
        }
    }

    Component {
        id: knowledgePage
        Flickable {
            contentWidth: width
            contentHeight: knowledgeContent.implicitHeight
            clip: true
            ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
            id: knowledgeContent
            width: parent.width
            spacing: QuattroTheme.Theme.spaceLg
            GridLayout {
                Layout.fillWidth: true
                columns: root.compact ? 1 : 3
                uniformCellWidths: true
                columnSpacing: 16
                rowSpacing: 8
                Repeater {
                    model: root.accounts
                    delegate: ColumnLayout {
                        required property var modelData
                        property var window: root.tightest(modelData)
                        Layout.fillWidth: true
                        spacing: 4
                        Label { text: parent.modelData.alias; color: QuattroTheme.Theme.textMuted }
                        Label { text: parent.window ? root.remaining(parent.window) + "% remaining" : "Unavailable"; font.pixelSize: QuattroTheme.Theme.typeTitle; color: parent.window ? root.readingColor(parent.window) : QuattroTheme.Theme.textMuted }
                        Label { text: (parent.window ? root.windowName(parent.window) + " · " : "") + (root.quotaState(parent.modelData) === "live" ? "Live" : root.quotaState(parent.modelData) === "stale" ? "Saved" : "Check omp /usage"); color: QuattroTheme.Theme.textMuted; font.pixelSize: QuattroTheme.Theme.typeMeta }
                    }
                }
            }
            Rule {}
            GridLayout {
                Layout.fillWidth: true
                columns: root.compact ? 1 : 2
                columnSpacing: 12
                rowSpacing: 12
                DesktopCombo {
                    Layout.fillWidth: true
                    model: root.projects.map(item => item.id)
                    currentIndex: Math.max(0, root.projects.findIndex(item => item.id === root.project))
                    enabled: root.projects.length > 0 && !searchProcess.running
                    displayText: root.project ? "Project: " + root.project : "No configured project"
                    Accessible.name: "Intelligence project"
                    onActivated: root.project = root.projects[currentIndex].id
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Repeater {
                        model: [{id: "knowledge", title: "Evidence"}, {id: "context", title: "Context"}, {id: "memory", title: "Memory"}]
                        delegate: DesktopButton {
                            required property var modelData
                            text: modelData.title
                            prominent: root.mode === modelData.id
                            quiet: root.mode !== modelData.id
                            Layout.fillWidth: true
                            onClicked: root.mode = modelData.id
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.columnSpan: root.compact ? 1 : 2
                    spacing: 12
                    DesktopField {
                        id: queryInput
                        Layout.fillWidth: true
                        Layout.preferredHeight: QuattroTheme.Theme.primaryTarget
                        text: root.queryDraft
                        placeholderText: root.mode === "memory" ? "Recall project memory…" : "Search code, concepts, decisions…"
                        Accessible.name: "Search Intelligence"
                        maximumLength: 4096
                        onTextChanged: { if (root.queryDraft !== text) root.queryDraft = text }
                        onAccepted: root.search()
                        Component.onCompleted: root.queryEditor = queryInput
                        Component.onDestruction: { if (root.queryEditor === queryInput) root.queryEditor = null }
                    }
                    DesktopButton {
                        text: searchProcess.running ? "Searching…" : "Search"
                        prominent: true
                        Layout.preferredWidth: 116
                        Layout.preferredHeight: QuattroTheme.Theme.primaryTarget
                        enabled: !searchProcess.running && !!root.project && !!root.queryDraft.trim()
                        onClicked: root.search()
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: root.dashboard.status !== "ready" ? root.dashboard.message || "Loading the local core…"
                    : root.retrievalInfo.semanticAvailable ? "Hybrid RAG · lexical + semantic retrieval"
                    : "Lexical RAG · semantic retrieval unavailable for this search"
                color: root.dashboard.status === "unavailable" ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
            }
            Label {
                visible: root.mode === "context" && root.searchState === "ready"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Cited context · " + (root.searchMeta.budget ? root.searchMeta.budget.estimated_used || 0 : 0)
                    + " / 3000 bytes · " + (root.searchMeta.conflicts || 0) + " conflicts · " + (root.searchMeta.outdated || 0) + " outdated"
                color: QuattroTheme.Theme.textMuted
            }
                ColumnLayout {
                    id: evidenceRows
                    Layout.fillWidth: true
                    spacing: 16
                    Label {
                        Layout.fillWidth: true
                        visible: root.results.length === 0
                        wrapMode: Text.Wrap
                        text: root.searchState === "loading" ? "Searching registered project sources…"
                            : root.searchState === "error" ? root.searchMessage
                            : root.searchState === "ready" ? "No matching evidence. Try a filename, symbol or a more specific query."
                            : root.mode === "context" ? "Build a cited context from project evidence and prior memory within a 3000-byte budget."
                            : root.mode === "memory" ? "Recall explicitly saved project memories. Verification stays attached to each record."
                            : "Search registered project knowledge. Results include source paths and citations; nothing here launches an agent."
                        color: root.searchState === "error" ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
                    }
                    Repeater {
                        model: root.results
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 8
                            Label { text: parent.modelData.title; font.pixelSize: QuattroTheme.Theme.typeLabel; font.bold: true; color: QuattroTheme.Theme.textStrong; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                text: parent.modelData.path ? parent.modelData.source + " · " + parent.modelData.path
                                    + (parent.modelData.line ? ":" + parent.modelData.line + (parent.modelData.endLine ? "–" + parent.modelData.endLine : "") : "")
                                    + " · " + parent.modelData.provenance
                                    : "Memory · " + (parent.modelData.verification || "Unverified")
                                color: QuattroTheme.Theme.textMuted
                                font.pixelSize: QuattroTheme.Theme.typeMeta
                            }
                            TextEdit {
                                Layout.fillWidth: true
                                Layout.preferredHeight: contentHeight
                                text: parent.modelData.content
                                readOnly: true
                                selectByMouse: true
                                wrapMode: TextEdit.Wrap
                                textFormat: TextEdit.PlainText
                                color: QuattroTheme.Theme.text
                                selectionColor: QuattroTheme.Theme.hover
                                selectedTextColor: QuattroTheme.Theme.textStrong
                                font.family: QuattroTheme.Theme.fontFamily
                                font.pixelSize: QuattroTheme.Theme.typeBody
                                Accessible.name: "Evidence content"
                            }
                            Label { visible: parent.modelData.commit.length > 0; text: "Commit " + parent.modelData.commit.slice(0, 12); color: QuattroTheme.Theme.textMuted; font.pixelSize: QuattroTheme.Theme.typeMeta }
                            Label { visible: parent.modelData.references.length > 0; text: parent.modelData.references.join(" · "); Layout.fillWidth: true; wrapMode: Text.Wrap; color: QuattroTheme.Theme.textMuted; font.pixelSize: QuattroTheme.Theme.typeMeta }
                            Rule {}
                        }
                    }
                }
        }
        }
    }

    Component {
        id: usagePage
        Flickable {
            contentWidth: width
            contentHeight: usageRows.implicitHeight
            clip: true
            ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: usageRows
                width: parent.width
                spacing: QuattroTheme.Theme.spaceXl
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "OpenAI Codex · omp"; font.pixelSize: QuattroTheme.Theme.typeTitle; color: QuattroTheme.Theme.textStrong; Layout.fillWidth: true }
                    DesktopButton { text: NativeUsage.loading ? "Refreshing…" : "Refresh"; enabled: !NativeUsage.loading; onClicked: NativeUsage.refresh() }
                }
                Label { text: "Read-only limits. Your active login stays unchanged."; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Repeater {
                    model: root.accounts
                    delegate: ColumnLayout {
                        id: accountRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: accountRow.modelData.alias; font.pixelSize: QuattroTheme.Theme.typeTitle; color: QuattroTheme.Theme.textStrong }
                            Label { text: accountRow.modelData.plan || "Plan unavailable"; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true }
                            Label { text: root.quotaState(accountRow.modelData) === "live" ? "Live" : root.quotaState(accountRow.modelData) === "stale" ? "Saved" : "Unavailable"; color: root.quotaState(accountRow.modelData) === "live" ? QuattroTheme.Theme.textMuted : QuattroTheme.Theme.warning }
                        }
                        Repeater {
                            model: [accountRow.modelData.primary, accountRow.modelData.secondary].filter(window => !!window)
                            delegate: UsageMeter { required property var modelData; window: modelData }
                        }
                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            text: accountRow.modelData.primary ? root.age(accountRow.modelData.lastSuccessfulRefresh)
                                + (root.quotaState(accountRow.modelData) === "stale" ? " · saved limits, refresh in omp /usage" : "")
                                : "No quota reported. Check omp /usage and /login " + accountRow.modelData.provider + "."
                            color: QuattroTheme.Theme.textMuted
                            font.pixelSize: QuattroTheme.Theme.typeMeta
                        }
                        Rule {}
                    }
                }
                Label { visible: root.accounts.length === 0; text: NativeUsage.loading ? "Loading native account limits…" : "Native usage unavailable. Refresh or check omp /usage."; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true; wrapMode: Text.Wrap }
            }
        }
    }

    Component {
        id: statusPage
        Flickable {
            contentWidth: width
            contentHeight: statusRows.implicitHeight
            clip: true
            ScrollBar.vertical: ScrollBar {}
            ColumnLayout {
                id: statusRows
                width: parent.width
                spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Local core"; font.pixelSize: QuattroTheme.Theme.typeTitle; color: QuattroTheme.Theme.textStrong; Layout.fillWidth: true }
                    DesktopButton { text: stateProcess.running ? "Refreshing…" : "Refresh"; enabled: !stateProcess.running; onClicked: root.refresh() }
                }
                Label { visible: root.dashboard.status !== "ready"; text: root.dashboard.message || "Loading local Intelligence…"; Layout.fillWidth: true; wrapMode: Text.Wrap; color: QuattroTheme.Theme.warning }
                Metric { label: "Retrieval"; value: root.dashboard.retrievalMode || "Unavailable" }
                Metric { label: "Semantic backend"; value: root.dashboard.embeddingBackend || "Unavailable" }
                Metric { label: "Knowledge storage"; value: root.dashboard.database || "Unavailable" }
                Metric { label: "Memory storage"; value: root.dashboard.memoryDatabase || "Unavailable" }
                Rule {}
                Repeater {
                    model: root.projects
                    delegate: ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 12
                        Label { text: parent.modelData.id; font.pixelSize: QuattroTheme.Theme.typeTitle; color: QuattroTheme.Theme.textStrong }
                        Metric { label: "Indexed files"; value: String(parent.modelData.files === null ? "—" : parent.modelData.files) }
                        Metric { label: "Documents"; value: String(parent.modelData.documents === null ? "—" : parent.modelData.documents) }
                        Metric { label: "Saved memories"; value: String(parent.modelData.memories === null ? "—" : parent.modelData.memories) }
                        Repeater {
                            model: parent.modelData.sources
                            delegate: Label { required property var modelData; text: modelData.id + " · " + root.age(modelData.indexedAt); Layout.fillWidth: true; wrapMode: Text.Wrap; color: QuattroTheme.Theme.textMuted }
                        }
                        Rule {}
                    }
                }
                Label { text: "Only registered project sources are searched. Indexing and memory writes remain explicit core operations; this panel does not execute or route agents."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: QuattroTheme.Theme.textMuted }
            }
        }
    }

    component Label: Text {
        textFormat: Text.PlainText
        font.family: QuattroTheme.Theme.fontFamily
        font.pixelSize: QuattroTheme.Theme.typeBody
    }
    component Rule: Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: QuattroTheme.Theme.border
    }
    component Metric: RowLayout {
        id: metric
        required property string label
        required property string value
        Layout.fillWidth: true
        Label { text: metric.label; Layout.fillWidth: true; color: QuattroTheme.Theme.textMuted }
        Label { text: metric.value; color: QuattroTheme.Theme.textStrong }
    }
    component UsageMeter: ColumnLayout {
        id: meter
        required property var window
        Layout.fillWidth: true
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Label { text: root.windowName(meter.window); Layout.fillWidth: true; color: QuattroTheme.Theme.text }
            Label { text: root.remaining(meter.window) + "% remaining"; font.pixelSize: QuattroTheme.Theme.typeTitle; color: root.readingColor(meter.window) }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 6
            color: QuattroTheme.Theme.border
            Rectangle { height: parent.height; width: parent.width * Math.max(0, Math.min(100, root.remaining(meter.window))) / 100; color: root.readingColor(meter.window) }
        }
        Label { text: root.resetText(meter.window.resetAt); font.pixelSize: QuattroTheme.Theme.typeMeta; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true; wrapMode: Text.Wrap }
    }
}
