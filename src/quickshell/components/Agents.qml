import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Wayland
import QtQuick
import QtQuick.Layouts
import "../theme" as QuattroTheme

Scope {
    id: root

    property string agentCommand: Quickshell.env("HOME") + "/.local/bin/quattro-agent"
    property bool opened: false
    property string page: "home"
    property string selectedAgent: "auto"
    property string knowledgeMode: "retrieval"
    property string statusMessage: ""
    property var dashboard: ({"schemaVersion": 1, "agents": {}, "tasks": [], "sessions": [], "logicalSessions": [], "approvals": [], "project": {}, "retrieval": {}, "memory": {}})
    property var selectedTaskDetails: null
    property var selectedApproval: null
    property var knowledgeResults: []
    property var knowledgeMeta: ({})
    property bool paletteOpen: false
    property int paletteIndex: 0
    property bool confirmOpen: false
    property string approvalDecision: ""
    property string actionKind: ""
    property string actionOut: ""
    property string actionErr: ""
    property string searchOut: ""
    property string searchErr: ""
    property bool notificationBaselineReady: false
    property var knownTaskStates: ({})
    property var knownApprovals: ({})
    property var promptEditor: null
    property var knowledgeEditor: null
    property var sessionEditor: null
    property string promptDraft: ""
    property string knowledgeQuery: ""
    property string sessionQuery: ""

    readonly property var activeStates: ["queued", "validating", "awaiting_approval", "ready", "running", "waiting_on_children", "validating_result", "blocked"]
    readonly property var terminalStates: ["succeeded", "failed", "cancelled", "timed_out", "interrupted"]
    readonly property var commandItems: [
        {"id":"new-auto","label":"New AUTO Task","detail":"Use Quattro routing"},
        {"id":"new-codex","label":"New Codex Task","detail":"Queue with Codex"},
        {"id":"new-pi","label":"New Pi Task","detail":"Queue with Pi"},
        {"id":"resume","label":"Resume Session","detail":"Recover checkpointed work"},
        {"id":"knowledge","label":"Search Knowledge","detail":"Code and architecture evidence"},
        {"id":"memory","label":"Search Memory","detail":"Project-scoped memories"},
        {"id":"active","label":"View Active Task","detail":"Observe current execution"},
        {"id":"tasks","label":"View Recent Tasks","detail":"Durable task history"},
        {"id":"open","label":"Open Current Project","detail":"Use Quattro's Zed wrapper"},
        {"id":"diff","label":"Review Current Diff","detail":"Open changed files"},
        {"id":"system","label":"Retrieval Status","detail":"System diagnostics"},
        {"id":"reindex","label":"Reindex Knowledge","detail":"Explicit maintenance"},
        {"id":"benchmark","label":"Run Retrieval Benchmark","detail":"Explicit developer operation"}
    ]

    function array(value) { return Array.isArray(value) ? value : [] }
    function object(value) { return value && typeof value === "object" ? value : ({}) }
    function shortId(value) { const text = String(value || ""); return text.length > 14 ? text.slice(0, 12) + "…" : text }
    function human(value) { const text = String(value || "unknown").replace(/_/g, " "); return text.charAt(0).toUpperCase() + text.slice(1) }
    function age(value) {
        if (!value) return "—"
        const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
        if (seconds < 60) return seconds + "s"
        if (seconds < 3600) return Math.floor(seconds / 60) + "m"
        return Math.floor(seconds / 3600) + "h " + Math.floor((seconds % 3600) / 60) + "m"
    }
    function resetText(epochSeconds) {
        const value = Number(epochSeconds || 0)
        if (!value) return "Reset unavailable"
        const seconds = Math.max(0, Math.floor(value - Date.now() / 1000))
        if (seconds < 3600) return "Resets in " + Math.max(1, Math.ceil(seconds / 60)) + "m"
        if (seconds < 86400) return "Resets in " + Math.floor(seconds / 3600) + "h " + Math.floor((seconds % 3600) / 60) + "m"
        return "Resets in " + Math.floor(seconds / 86400) + "d " + Math.floor((seconds % 86400) / 3600) + "h"
    }
    function stateColor(value) {
        const state = String(value || "").toLowerCase()
        if (["ready", "succeeded", "passed", "healthy"].indexOf(state) >= 0) return QuattroTheme.Theme.success
        if (["failed", "cancelled", "timed_out", "unavailable", "declined"].indexOf(state) >= 0) return QuattroTheme.Theme.danger
        if (["awaiting_approval", "blocked", "authentication required", "stale"].indexOf(state) >= 0) return QuattroTheme.Theme.warning
        return QuattroTheme.Theme.accent
    }
    function activeTask() { return array(dashboard.tasks).find(task => activeStates.indexOf(task.state) >= 0) || null }
    function filteredSessions(items) {
        const query = sessionQuery.trim().toLowerCase()
        if (!query) return array(items)
        return array(items).filter(item => [
            item.title, item.projectName, item.repository, item.workingDirectory,
            item.sessionId, item.taskId, item.quattroSessionId,
            item.coordinationSessionId, item.agent, item.accountId
        ].map(value => String(value || "").toLowerCase()).join(" ").indexOf(query) >= 0)
    }
    function projectPath() {
        const value = object(dashboard.project).repository
        return typeof value === "string" && value.length > 0 ? value : ""
    }
    function requireProject() {
        if (projectPath()) return true
        statusMessage = "Authoritative project state is not available yet"
        return false
    }
    function focusedScreen() {
        for (let screen of Quickshell.screens) if (Hyprland.monitorFor(screen) === Hyprland.focusedMonitor) return screen
        return Quickshell.screens[0]
    }
    function agentState(name) {
        const record = object(object(dashboard.agents)[name])
        if (!record.available) return "Unavailable"
        if (name === "codex") {
            const account = array(dashboard.accounts).find(item => item.id === dashboard.activeAccount)
            if (account && !account.authenticated) return "Authentication required"
        }
        const busy = array(dashboard.sessions).some(item => item.agent === name)
            || array(dashboard.tasks).some(item => item.agent === name && activeStates.indexOf(item.state) >= 0)
        return busy ? "Busy" : "Ready"
    }
    function open(pageName) {
        page = pageName || "home"
        agentsWindow.screen = focusedScreen()
        opened = true
        refresh()
        refreshAccountState()
        refreshTitles()
        Qt.callLater(() => root.promptEditor ? root.promptEditor.forceActiveFocus() : keyScope.forceActiveFocus())
    }
    function close() { opened = false; paletteOpen = false; confirmOpen = false; page = "home"; statusMessage = "" }
    function go(target) { page = target; paletteOpen = false; confirmOpen = false; Qt.callLater(() => keyScope.forceActiveFocus()) }
    function refresh() {
        if (!stateProcess.running) { statusMessage = "Refreshing…"; stateProcess.running = true }
    }
    function refreshTitles() {
        if (!titleRefreshProcess.running)
            titleRefreshProcess.running = true
    }
    function refreshAccountState() {
        if (!accountStatusProcess.running)
            accountStatusProcess.running = true
    }
    function invoke(args, kind) {
        if (actionProcess.running) { statusMessage = "Another control action is still running"; return }
        actionKind = kind || "action"; actionOut = ""; actionErr = ""
        actionProcess.command = [agentCommand].concat(args)
        statusMessage = "Working…"
        actionProcess.running = true
    }
    function launch(args) { Quickshell.execDetached([agentCommand].concat(args)); close() }
    function submitPrompt() {
        const prompt = promptDraft.trim()
        if (!prompt) { statusMessage = "Describe the work for Quattro"; if (promptEditor) promptEditor.forceActiveFocus(); return }
        if (actionProcess.running) { statusMessage = "Another control action is still running"; return }
        if (!requireProject()) return
        const project = projectPath()
        invoke(["submit", "--agent", selectedAgent, "--directory", project, "--prompt", prompt], "submit")
    }
    function showTask(identifier) { if (identifier) invoke(["task", "show", String(identifier), "--json"], "task-show") }
    function showApproval(approval) { selectedApproval = approval; go("approval") }
    function resolveApproval(decision) { approvalDecision = decision; confirmOpen = true }
    function confirmApproval() {
        confirmOpen = false
        if (selectedApproval && selectedApproval.approvalId) invoke(["approval", approvalDecision, selectedApproval.approvalId, "--json"], "approval")
    }
    function searchKnowledge() {
        const query = knowledgeQuery.trim()
        if (!query) { statusMessage = "Enter a search query"; if (knowledgeEditor) knowledgeEditor.forceActiveFocus(); return }
        if (searchProcess.running) return
        if (!requireProject()) return
        const project = projectPath()
        searchOut = ""; searchErr = ""; knowledgeResults = []; knowledgeMeta = ({})
        searchProcess.command = knowledgeMode === "memory"
            ? [agentCommand, "memory", "ui-search", query, "--directory", project, "--limit", "12", "--json"]
            : [agentCommand, "retrieval", "ui-search", query, "--directory", project, "--limit", "12", "--budget", "3000"]
        statusMessage = "Searching…"; searchProcess.running = true
    }
    function startMaintenance(kind) {
        if (maintenanceProcess.running) { statusMessage = "Knowledge maintenance is already running"; return }
        if (!requireProject()) return
        maintenanceProcess.command = [agentCommand, "retrieval", kind, "--directory", projectPath()]
        statusMessage = kind === "reindex" ? "Reindexing knowledge…" : "Running retrieval benchmark…"
        maintenanceProcess.running = true
    }
    function dispatch(identifier) {
        paletteOpen = false
        if (identifier.indexOf("new-") === 0) { selectedAgent = identifier.replace("new-", ""); go("home"); Qt.callLater(() => { if (root.promptEditor) root.promptEditor.forceActiveFocus() }) }
        else if (identifier === "resume") go("sessions")
        else if (identifier === "knowledge" || identifier === "memory") { knowledgeMode = identifier === "memory" ? "memory" : "retrieval"; go("knowledge"); Qt.callLater(() => { if (root.knowledgeEditor) root.knowledgeEditor.forceActiveFocus() }) }
        else if (identifier === "active") { const task = activeTask(); task ? showTask(task.taskId || task.id) : statusMessage = "No active task" }
        else if (identifier === "tasks") go("tasks")
        else if (identifier === "open" && requireProject()) invoke(["open", projectPath()], "zed")
        else if (identifier === "diff" && requireProject()) invoke(["diff", "--directory", projectPath()], "zed")
        else if (identifier === "system") go("system")
        else if (identifier === "reindex" || identifier === "benchmark") startMaintenance(identifier)
    }
    function filteredCommands() {
        const query = paletteQuery.text.trim().toLowerCase()
        return commandItems.filter(item => !query || (item.label + " " + item.detail).toLowerCase().indexOf(query) >= 0)
    }
    function updateNotificationBaseline(next) {
        const states = ({}); const approvals = ({})
        for (const task of array(next.tasks)) {
            const id = task.taskId || task.id; states[id] = task.state
            if (notificationBaselineReady && knownTaskStates[id] && knownTaskStates[id] !== task.state && terminalStates.indexOf(task.state) >= 0)
                Quickshell.execDetached(["notify-send", "-u", task.state === "succeeded" ? "normal" : "critical", "Quattro task " + human(task.state), task.title || shortId(id)])
        }
        for (const approval of array(next.approvals)) {
            approvals[approval.approvalId] = true
            if (notificationBaselineReady && !knownApprovals[approval.approvalId])
                Quickshell.execDetached(["notify-send", "-u", "critical", "Quattro approval required", approval.confirmationSummary || approval.scope])
        }
        knownTaskStates = states; knownApprovals = approvals; notificationBaselineReady = true
    }

    IpcHandler {
        target: "agents"
        function open(): void { root.open("home") }
        function close(): void { root.close() }
        function toggle(): void { root.opened ? root.close() : root.open("home") }
        function newTask(): void { root.open("home") }
        function commandPalette(): void {
            root.open("home")
            root.paletteOpen = true
            root.paletteIndex = 0
            Qt.callLater(() => paletteQuery.forceActiveFocus())
        }
        function refresh(): void { root.refresh(); root.refreshTitles() }
    }

    Process {
        id: stateProcess
        command: [root.agentCommand, "ui-state"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(text)
                    if (parsed.schemaVersion === 1) { root.updateNotificationBaseline(parsed); root.dashboard = parsed; root.statusMessage = "Updated " + Qt.formatTime(new Date(), "HH:mm:ss") }
                } catch (error) { root.statusMessage = "Quattro state is unavailable" }
            }
        }
    }
    Process {
        id: titleRefreshProcess
        command: [root.agentCommand, "recent", "refresh"]
        onRunningChanged: {
            if (!running)
                root.refresh()
        }
    }
    Process {
        id: accountStatusProcess
        command: [root.agentCommand, "account", "list"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(text)
                    if (!parsed.active) return
                    const changed = parsed.active !== root.dashboard.activeAccount
                    const next = Object.assign({}, root.dashboard)
                    next.activeAccount = parsed.active
                    if (Array.isArray(parsed.accounts)) next.accounts = parsed.accounts
                    root.dashboard = next
                    if (changed) {
                        if (!panelUsageProcess.running) panelUsageProcess.running = true
                        root.refresh()
                    }
                } catch (error) {}
            }
        }
    }
    Process {
        id: panelUsageProcess
        command: [root.agentCommand, "usage", "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(text)
                    const next = Object.assign({}, root.dashboard)
                    next.usage = parsed
                    if (parsed.accountId) next.activeAccount = parsed.accountId
                    root.dashboard = next
                } catch (error) {}
            }
        }
    }
    Process {
        id: actionProcess
        stdout: StdioCollector { onStreamFinished: root.actionOut = text }
        stderr: StdioCollector { onStreamFinished: root.actionErr = text }
        onRunningChanged: {
            if (running || !root.actionKind) return
            if (root.actionErr.trim()) root.statusMessage = root.actionErr.trim().replace(/^quattro-agent:\s*/, "")
            else if (root.actionKind === "task-show") {
                try { root.selectedTaskDetails = JSON.parse(root.actionOut); root.go("task"); root.statusMessage = "Task loaded" }
                catch (error) { root.statusMessage = "Task details were invalid" }
            } else if (root.actionKind === "memory-show") {
                try { root.knowledgeMeta = JSON.parse(root.actionOut); root.statusMessage = "Memory loaded" }
                catch (error) { root.statusMessage = "Memory details were invalid" }
            } else {
                if (root.actionKind === "submit") {
                    try {
                        const submitted = JSON.parse(root.actionOut)
                        if (submitted.schemaVersion !== 1 || !submitted.taskId) throw new Error("invalid submit response")
                        root.promptDraft = ""
                        if (root.promptEditor) root.promptEditor.text = ""
                        root.statusMessage = "Task queued · " + root.shortId(submitted.taskId)
                    } catch (error) { root.statusMessage = "Quattro did not confirm task submission" }
                } else root.statusMessage = root.actionKind === "zed" ? "Sent to Zed" : "Action completed"
                if (root.actionKind === "approval") root.go("home")
            }
            root.actionKind = ""; root.refresh()
        }
    }
    Process {
        id: searchProcess
        stdout: StdioCollector { onStreamFinished: root.searchOut = text }
        stderr: StdioCollector { onStreamFinished: root.searchErr = text }
        onRunningChanged: {
            if (running) return
            if (root.searchErr.trim()) { root.statusMessage = root.searchErr.trim().replace(/^quattro-agent:\s*/, ""); return }
            try { const parsed = JSON.parse(root.searchOut); root.knowledgeResults = root.array(parsed.results); root.knowledgeMeta = parsed; root.statusMessage = root.knowledgeResults.length + " results" }
            catch (error) { root.statusMessage = "Knowledge results were invalid" }
        }
    }
    Process {
        id: maintenanceProcess
        stderr: StdioCollector { onStreamFinished: root.actionErr = text }
        onRunningChanged: { if (!running) { root.statusMessage = root.actionErr.trim() || "Knowledge operation completed"; root.refresh() } }
    }
    Timer { running: root.opened; repeat: true; interval: 15000; onTriggered: root.refresh() }
    Timer {
        running: root.opened
        repeat: true
        interval: 2000
        onTriggered: root.refreshAccountState()
    }

    PanelWindow {
        id: agentsWindow
        visible: root.opened
        anchors { top: true; bottom: true; left: true; right: true }
        aboveWindows: true; focusable: true; exclusionMode: ExclusionMode.Ignore
        WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        color: QuattroTheme.Theme.overlayLight
        MouseArea { anchors.fill: parent; onClicked: root.close() }
        Rectangle {
            anchors { top: parent.top; bottom: parent.bottom; right: parent.right; topMargin: 42; bottomMargin: 12; rightMargin: 12 }
            width: 760; color: QuattroTheme.Theme.background; border.width: 1; border.color: QuattroTheme.Theme.border
            MouseArea { anchors.fill: parent }
            FocusScope {
                id: keyScope
                anchors.fill: parent; focus: agentsWindow.visible
                Shortcut {
                    sequence: "Ctrl+K"
                    context: Qt.WindowShortcut
                    onActivated: {
                        root.paletteOpen = true
                        root.paletteIndex = 0
                        paletteQuery.text = ""
                        Qt.callLater(() => paletteQuery.forceActiveFocus())
                    }
                }
                Keys.onEscapePressed: {
                    if (root.paletteOpen) root.paletteOpen = false
                    else if (root.confirmOpen) root.confirmOpen = false
                    else if (root.page === "task" || root.page === "approval") root.go("home")
                    else root.close()
                }
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_K && (event.modifiers & Qt.ControlModifier)) { root.paletteOpen = true; root.paletteIndex = 0; paletteQuery.text = ""; Qt.callLater(() => paletteQuery.forceActiveFocus()); event.accepted = true }
                    else if (event.key === Qt.Key_Slash && root.page === "home" && root.promptEditor) { root.promptEditor.forceActiveFocus(); event.accepted = true }
                    else if (event.key === Qt.Key_F5) { root.refresh(); event.accepted = true }
                }
                RowLayout {
                    anchors.fill: parent; anchors.margins: 14; spacing: 12
                    Rectangle {
                        Layout.preferredWidth: 128; Layout.fillHeight: true
                        color: QuattroTheme.Theme.surface; border.width: 1; border.color: QuattroTheme.Theme.border
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 10; spacing: 7
                            Text { text: "QUATTRO"
                            color: QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 15
                            font.bold: true }
                            Text { text: "CONTROL CENTER"
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8 }
                            Rectangle { Layout.fillWidth: true
                            implicitHeight: 1
                            color: QuattroTheme.Theme.border }
                            NavButton { label: "󰋜  Home"
                            target: "home" }
                            NavButton { label: "󰒓  Tasks"
                            target: "tasks" }
                            NavButton { label: "󰔚  Sessions"
                            target: "sessions" }
                            NavButton { label: "󰈙  Knowledge"
                            target: "knowledge" }
                            NavButton { label: "󰒓  System"
                            target: "system" }
                            Item { Layout.fillHeight: true }
                            ActionButton { label: "Ctrl+K Commands"
                            Layout.fillWidth: true
                            onClicked: { root.paletteOpen = true
                            Qt.callLater(() => paletteQuery.forceActiveFocus()) } }
                            Text { text: "Esc close · F5 refresh"
                            color: QuattroTheme.Theme.textDim
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 7
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 9
                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: root.page === "task" ? "Task Detail" : root.page === "approval" ? "Approval" : root.human(root.page)
                            color: QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 18
                            font.bold: true
                            Layout.fillWidth: true }
                            Text { text: root.statusMessage
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            elide: Text.ElideLeft
                            Layout.maximumWidth: 250 }
                            ActionButton { label: "Refresh"
                            onClicked: { root.refresh(); root.refreshTitles() } }
                        }
                        Rectangle { Layout.fillWidth: true
                        implicitHeight: 1
                        color: QuattroTheme.Theme.border }
                        Loader {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            sourceComponent: root.page === "home" ? homePage : root.page === "tasks" ? tasksPage : root.page === "sessions" ? sessionsPage : root.page === "knowledge" ? knowledgePage : root.page === "system" ? systemPage : root.page === "task" ? taskPage : approvalPage
                        }
                    }
                }
                Rectangle {
                    visible: root.paletteOpen
                    anchors.fill: parent
                    color: QuattroTheme.Theme.overlay
                    z: 20
                    MouseArea { anchors.fill: parent
                    onClicked: root.paletteOpen = false }
                    Rectangle {
                        anchors { top: parent.top
                        horizontalCenter: parent.horizontalCenter
                        topMargin: 54 }
                        width: 500
                        height: 480
                        color: QuattroTheme.Theme.background
                        border.width: 1
                        border.color: QuattroTheme.Theme.borderStrong
                        MouseArea { anchors.fill: parent }
                        ColumnLayout {
                            id: paletteColumn
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8
                            Text { text: "QUATTRO COMMANDS"
                            color: QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 11
                            font.bold: true }
                            Field {
                                id: paletteQuery
                                placeholder: "Search actions…"
                                onTextChanged: root.paletteIndex = 0
                                Keys.onPressed: event => {
                                    const rows = root.filteredCommands()
                                    if (event.key === Qt.Key_Down && rows.length) { root.paletteIndex = Math.min(rows.length - 1, root.paletteIndex + 1)
                                    event.accepted = true }
                                    else if (event.key === Qt.Key_Up && rows.length) { root.paletteIndex = Math.max(0, root.paletteIndex - 1)
                                    event.accepted = true }
                                    else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && rows.length) { root.dispatch(rows[root.paletteIndex].id)
                                    event.accepted = true }
                                }
                            }
                            Flickable {
                                Layout.fillWidth: true
                                Layout.preferredHeight: Math.min(420, paletteRows.implicitHeight)
                                contentWidth: width
                                contentHeight: paletteRows.implicitHeight
                                clip: true
                                ColumnLayout {
                                    id: paletteRows
                                    width: parent.width
                                    Repeater {
                                        model: root.filteredCommands()
                                        delegate: ResultRow { required property var modelData
                                        required property int index
                                        title: (index === root.paletteIndex ? "› " : "") + modelData.label
                                        detail: modelData.detail
                                        onActivated: root.dispatch(modelData.id) }
                                    }
                                }
                            }
                        }
                    }
                }
                Rectangle {
                    visible: root.confirmOpen
                    anchors.fill: parent
                    color: QuattroTheme.Theme.overlay
                    z: 25
                    MouseArea { anchors.fill: parent
                    onClicked: {} }
                    Rectangle {
                        anchors.centerIn: parent
                        width: 430
                        implicitHeight: confirmColumn.implicitHeight + 28
                        color: QuattroTheme.Theme.background
                        border.width: 1
                        border.color: root.approvalDecision === "approve" ? QuattroTheme.Theme.warning : QuattroTheme.Theme.danger
                        ColumnLayout {
                            id: confirmColumn
                            anchors { left: parent.left
                            right: parent.right
                            top: parent.top
                            margins: 14 }
                            spacing: 10
                            Text { text: root.approvalDecision === "approve" ? "Confirm approval" : "Confirm rejection"
                            color: QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 14
                            font.bold: true }
                            Text { text: root.selectedApproval ? root.selectedApproval.confirmationSummary : ""
                            color: QuattroTheme.Theme.text
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true }
                            Text { text: "This resolves the durable Quattro approval. It does not bypass policy."
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true }
                            RowLayout { ActionButton { label: "Confirm"
                            accent: true
                            onClicked: root.confirmApproval() }
                            ActionButton { label: "Cancel"
                            onClicked: root.confirmOpen = false }
                            Item { Layout.fillWidth: true } }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: homePage
        Flickable {
            contentWidth: width
            contentHeight: homeColumn.implicitHeight
            clip: true
            ColumnLayout {
                id: homeColumn
                width: parent.width
                spacing: 10
                SectionLabel { text: "QUICK PROMPT" }
                Card {
                    implicitHeight: promptColumn.implicitHeight + 22
                    ColumnLayout {
                        id: promptColumn
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 8
                        RowLayout { ActionButton { label: "AUTO"
                        accent: root.selectedAgent === "auto"
                        onClicked: root.selectedAgent = "auto" }
                        ActionButton { label: "CODEX"
                        accent: root.selectedAgent === "codex"
                        onClicked: root.selectedAgent = "codex" }
                        ActionButton { label: "PI"
                        accent: root.selectedAgent === "pi"
                        onClicked: root.selectedAgent = "pi" }
                        Item { Layout.fillWidth: true }
                        Text { text: root.object(root.dashboard.project).name || "Current project"
                        color: QuattroTheme.Theme.textMuted
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 8 } }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 102
                            color: QuattroTheme.Theme.surfaceRaised
                            border.width: promptInput.activeFocus ? 1 : 0
                            border.color: QuattroTheme.Theme.accent
                            TextEdit {
                                id: promptInput
                                Component.onCompleted: root.promptEditor = promptInput
                                Component.onDestruction: { if (root.promptEditor === promptInput) root.promptEditor = null }
                                text: root.promptDraft
                                onTextChanged: { if (root.promptDraft !== text) root.promptDraft = text }
                                anchors.fill: parent
                                anchors.margins: 10
                                color: QuattroTheme.Theme.textStrong
                                selectionColor: QuattroTheme.Theme.accentMuted
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 11
                                wrapMode: TextEdit.Wrap
                                Keys.onPressed: event => { if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier)) { root.submitPrompt()
                                event.accepted = true } }
                            }
                            Text { visible: !promptInput.text.length
                            anchors { left: parent.left
                            top: parent.top
                            margins: 10 }
                            text: "Ask Quattro to implement, inspect, repair, or continue…\nEnter submits · Shift+Enter adds a line"
                            color: QuattroTheme.Theme.textDim
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 9 }
                        }
                        RowLayout { ActionButton { label: "Submit"
                        accent: true
                        enabled: !actionProcess.running
                        onClicked: root.submitPrompt() }
                        Text { text: "AUTO is resolved by Quattro."
                        color: QuattroTheme.Theme.textMuted
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 8 }
                        Item { Layout.fillWidth: true } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Card {
                        Layout.fillWidth: true
                        implicitHeight: agentColumn.implicitHeight + 22
                        ColumnLayout { id: agentColumn
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 7
                        SectionLabel { text: "AGENT STATUS" }
                        AgentRow { name: "Codex"
                        state: root.agentState("codex") }
                        AgentRow { name: "Pi"
                        state: root.agentState("pi") } }
                    }
                    Card {
                        Layout.fillWidth: true
                        implicitHeight: projectColumn.implicitHeight + 22
                        ColumnLayout {
                            id: projectColumn
                            anchors.fill: parent
                            anchors.margins: 11
                            spacing: 5
                            SectionLabel { text: "CURRENT PROJECT" }
                            Text { text: root.object(root.dashboard.project).name || "Unavailable"
                            color: QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 11
                            font.bold: true }
                            Text { text: (root.object(root.dashboard.project).branch || "detached") + " · " + root.shortId(root.object(root.dashboard.project).commitSha)
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8 }
                            Text { text: root.object(root.dashboard.project).dirty ? root.object(root.dashboard.project).changedFileCount + " changed files" : "Working tree clean"
                            color: root.object(root.dashboard.project).dirty ? QuattroTheme.Theme.warning : QuattroTheme.Theme.success
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8 }
                            RowLayout { ActionButton { label: "Open in Zed"
                            enabled: root.object(root.dashboard.project).zedAvailable === true
                            onClicked: root.invoke(["open", root.object(root.dashboard.project).repository], "zed") }
                            ActionButton { label: "Review Diff"
                            enabled: root.object(root.dashboard.project).dirty === true && root.object(root.dashboard.project).zedAvailable === true
                            onClicked: root.invoke(["diff", "--directory", root.object(root.dashboard.project).repository], "zed") } }
                        }
                    }
                }
                SectionLabel { text: "CODEX ACCOUNT & LIMITS" }
                Card {
                    implicitHeight: accountLimitsColumn.implicitHeight + 22
                    ColumnLayout {
                        id: accountLimitsColumn
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 7
                        RowLayout {
                            Layout.fillWidth: true
                            Repeater {
                                model: root.array(root.dashboard.accounts)
                                delegate: ActionButton {
                                    required property var modelData
                                    label: modelData.alias + (modelData.authenticated ? "" : " · auth required")
                                    accent: modelData.id === root.dashboard.activeAccount
                                    enabled: modelData.enabled && modelData.available && modelData.authenticated && !actionProcess.running
                                    onClicked: root.invoke(["account", "set", modelData.id], "account")
                                }
                            }
                            Item { Layout.fillWidth: true }
                            ActionButton {
                                label: actionProcess.running && root.actionKind === "usage" ? "Refreshing…" : "Refresh limits"
                                enabled: !actionProcess.running
                                onClicked: root.invoke(["usage", "refresh", "--all"], "usage")
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: (root.object(root.dashboard.usage).alias || root.dashboard.activeAccount || "Codex")
                                      + " · " + (root.object(root.dashboard.usage).plan || "plan unavailable")
                                color: QuattroTheme.Theme.textStrong
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 9
                                font.bold: true
                                Layout.fillWidth: true
                            }
                            Text {
                                text: root.object(root.dashboard.usage).stale ? "STALE" : "LIVE"
                                color: root.object(root.dashboard.usage).stale ? QuattroTheme.Theme.warning : QuattroTheme.Theme.success
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 7
                                font.bold: true
                            }
                        }
                        UsageMeter {
                            label: root.object(root.object(root.dashboard.usage).primary).label || "Primary"
                            window: root.object(root.dashboard.usage).primary || null
                            visible: !!window
                        }
                        UsageMeter {
                            label: root.object(root.object(root.dashboard.usage).secondary).label || "Secondary"
                            window: root.object(root.dashboard.usage).secondary || null
                            visible: !!window
                        }
                        Text {
                            visible: !root.object(root.dashboard.usage).primary && !root.object(root.dashboard.usage).secondary
                            text: root.object(root.dashboard.usage).loggedIn ? "Usage limits are not available for this account." : "Authentication required before limits can be read."
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }
                SectionLabel { text: "ACTIVE TASK" }
                TaskSummary { task: root.activeTask() }
                SectionLabel { text: "PENDING APPROVALS  ·  " + root.array(root.dashboard.approvals).length }
                Repeater { model: root.array(root.dashboard.approvals).slice(0, 3)
                delegate: ApprovalRow { required property var modelData
                approval: modelData } }
                EmptyState { visible: root.array(root.dashboard.approvals).length === 0
                title: "No pending approvals"
                detail: "Approval-bound actions will appear here." }
                SectionLabel { text: "RECENT TASKS" }
                Repeater { model: root.array(root.dashboard.tasks).slice(0, 5)
                delegate: TaskRow { required property var modelData
                task: modelData } }
                EmptyState { visible: root.array(root.dashboard.tasks).length === 0
                title: "No recent tasks"
                detail: "Start work from Quick Prompt." }
            }
        }
    }

    Component {
        id: tasksPage
        Flickable {
            contentWidth: width
            contentHeight: taskRows.implicitHeight
            clip: true
            ColumnLayout { id: taskRows
            width: parent.width
            spacing: 8
            Text { text: "Durable state and backend-provided capabilities."
            color: QuattroTheme.Theme.textMuted
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 8 }
            Repeater { model: root.array(root.dashboard.tasks)
            delegate: TaskRow { required property var modelData
            task: modelData } }
            EmptyState { visible: root.array(root.dashboard.tasks).length === 0
            title: "No durable tasks"
            detail: "Submit a prompt to create one." } }
        }
    }

    Component {
        id: sessionsPage
        Flickable {
            contentWidth: width
            contentHeight: sessionsColumn.implicitHeight
            clip: true
            ColumnLayout {
                id: sessionsColumn
                width: parent.width
                spacing: 8
                Field {
                    id: sessionSearch
                    Component.onCompleted: root.sessionEditor = sessionSearch
                    Component.onDestruction: { if (root.sessionEditor === sessionSearch) root.sessionEditor = null }
                    text: root.sessionQuery
                    onTextChanged: { if (root.sessionQuery !== text) root.sessionQuery = text }
                    placeholder: "Search title, project, q-session, task, agent…"
                    onAccepted: {}
                }
                SectionLabel { text: "LOGICAL SESSIONS" }
                Repeater {
                    model: root.filteredSessions(root.dashboard.logicalSessions)
                    delegate: Card {
                        required property var modelData
                        implicitHeight: logicalColumn.implicitHeight + 20
                        ColumnLayout {
                            id: logicalColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 4
                            RowLayout { Layout.fillWidth: true
                            Text { text: modelData.title || "Agent session"
                            color: QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 10
                            font.bold: true
                            Layout.fillWidth: true }
                            StatePill { state: modelData.recoveryState || modelData.sessionHealth || "unknown" } }
                            Text { text: modelData.repository || modelData.workingDirectory || "Unknown project"
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true }
                            Text { text: root.shortId(modelData.quattroSessionId) + " · Last active " + (modelData.updatedAt || "unknown") + " · " + (modelData.currentCheckpointId ? "checkpoint available" : "no checkpoint")
                            color: QuattroTheme.Theme.textDim
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8 }
                            RowLayout { ActionButton { label: "Resume"
                            enabled: !!modelData.currentCheckpointId
                            onClicked: root.launch(["resume", modelData.quattroSessionId]) }
                            ActionButton { label: "Open Project"
                            enabled: root.object(root.dashboard.project).zedAvailable === true
                            onClicked: root.invoke(["open", modelData.repository], "zed") }
                            Item { Layout.fillWidth: true } }
                        }
                    }
                }
                EmptyState { visible: root.filteredSessions(root.dashboard.logicalSessions).length === 0
                title: "No recoverable sessions"
                detail: root.sessionQuery.length ? "No logical session matches this search." : "Start a new Quattro task." }
                SectionLabel { text: "RUNNING  ·  " + root.filteredSessions(root.dashboard.sessions).length }
                Repeater {
                    model: root.filteredSessions(root.dashboard.sessions)
                    delegate: Card {
                        required property var modelData
                        implicitHeight: 58
                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 9
                            spacing: 8
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Text { text: modelData.title || ((modelData.agent || "agent").toUpperCase() + " · " + (modelData.projectName || "project"))
                                color: QuattroTheme.Theme.textStrong
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 9
                                font.bold: true
                                elide: Text.ElideRight
                                Layout.fillWidth: true }
                                Text { text: (modelData.agent || "agent").toUpperCase() + " · " + (modelData.projectName || "project") + " · PID " + (modelData.pid || "—")
                                color: QuattroTheme.Theme.textMuted
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 7
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true }
                                Text { text: modelData.coordinationSessionId || modelData.quattroSessionId || modelData.sessionId || ""
                                color: QuattroTheme.Theme.textDim
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 7
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true }
                            }
                            ActionButton { label: "Open"
                            onClicked: root.launch(["sessions", "open", modelData.coordinationSessionId || modelData.sessionId || modelData.taskId]) }
                            ActionButton { label: "Stop"
                            enabled: modelData.stoppable === true
                            onClicked: root.invoke(["sessions", "stop", modelData.coordinationSessionId || modelData.sessionId || modelData.taskId], "session-stop") }
                        }
                    }
                }
                EmptyState { visible: root.filteredSessions(root.dashboard.sessions).length === 0
                title: root.sessionQuery.length ? "No running session matches" : "No sessions are running"
                detail: root.sessionQuery.length ? "Try a title, project, q-session, task, or agent." : "Stopped sessions remain resumable from Logical Sessions." }
            }
        }
    }

    Component {
        id: knowledgePage
        ColumnLayout {
            spacing: 9
            RowLayout { ActionButton { label: "Retrieval"
            accent: root.knowledgeMode === "retrieval"
            onClicked: root.knowledgeMode = "retrieval" }
            ActionButton { label: "Memory"
            accent: root.knowledgeMode === "memory"
            onClicked: root.knowledgeMode = "memory" }
            Item { Layout.fillWidth: true } }
            RowLayout { Layout.fillWidth: true
            Field { id: knowledgeInput
            Component.onCompleted: root.knowledgeEditor = knowledgeInput
            Component.onDestruction: { if (root.knowledgeEditor === knowledgeInput) root.knowledgeEditor = null }
            text: root.knowledgeQuery
            onTextChanged: { if (root.knowledgeQuery !== text) root.knowledgeQuery = text }
            placeholder: root.knowledgeMode === "memory" ? "Search project memory…" : "Search code, symbols, architecture, decisions…"
            Layout.fillWidth: true
            onAccepted: root.searchKnowledge() }
            ActionButton { label: searchProcess.running ? "Searching…" : "Search"
            accent: true
            enabled: !searchProcess.running
            onClicked: root.searchKnowledge() } }
            Text { text: root.knowledgeMode === "memory" ? "Project-scoped memory evidence only." : "Authority-scoped retrieval
            hidden context and embeddings stay private."
            color: QuattroTheme.Theme.textMuted
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 8
            wrapMode: Text.Wrap
            Layout.fillWidth: true }
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: knowledgeRows.implicitHeight
                clip: true
                ColumnLayout {
                    id: knowledgeRows
                    width: parent.width
                    spacing: 7
                    Repeater {
                        model: root.knowledgeResults
                        delegate: ResultRow {
                            required property var modelData
                            title: modelData.title || modelData.symbol || modelData.source_type || modelData.sourceType || "Evidence"
                            detail: (modelData.path || modelData.repository || modelData.origin || "") + (modelData.startLine ? ":" + modelData.startLine : "")
                            body: modelData.content || modelData.snippet || ""
                            actionLabel: modelData.origin === "repository" ? "Open" : "Inspect"
                            onActivated: modelData.origin === "repository" && root.requireProject()
                                ? root.invoke(["retrieval", "open", modelData.id, "--directory", root.projectPath()], "zed")
                                : root.requireProject() ? root.invoke(["memory", "inspect", modelData.id, "--directory", root.projectPath(), "--json"], "memory-show") : undefined
                        }
                    }
                    EmptyState { visible: root.knowledgeResults.length === 0 && !searchProcess.running
                    title: "No matching knowledge found"
                    detail: "Try a filename, symbol, architecture concept, or decision." }
                    Card {
                        visible: root.knowledgeMode === "retrieval" && root.object(root.knowledgeMeta).trace !== undefined
                        implicitHeight: diagnosticsColumn.implicitHeight + 20
                        ColumnLayout {
                            id: diagnosticsColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 3
                            SectionLabel { text: "WHY THESE RESULTS" }
                            Text { text: "Route " + (root.object(root.knowledgeMeta.route).intent || "unknown") + " · semantic " + (root.object(root.knowledgeMeta.route).use_semantic ? "used" : "skipped") + " · graph " + (root.object(root.knowledgeMeta.route).use_graph ? "used" : "skipped")
                            color: QuattroTheme.Theme.text
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true }
                            Text { text: "Selected " + root.knowledgeResults.length + " · latency " + (root.object(root.knowledgeMeta.trace).latencyMs || root.object(root.knowledgeMeta.trace).latency_ms || "—") + " ms"
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8 }
                        }
                    }
                    Card {
                        visible: root.knowledgeMode === "memory" && !!root.object(root.knowledgeMeta).id
                        implicitHeight: memoryInspectColumn.implicitHeight + 20
                        ColumnLayout {
                            id: memoryInspectColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 4
                            SectionLabel { text: "MEMORY DETAIL" }
                            Text { text: root.object(root.knowledgeMeta).source_type || root.object(root.knowledgeMeta).sourceType || "Memory"
                            color: QuattroTheme.Theme.accent
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            font.bold: true }
                            Text { text: root.object(root.knowledgeMeta).content || "No displayable content."
                            color: QuattroTheme.Theme.text
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true }
                            Text { text: root.shortId(root.object(root.knowledgeMeta).id)
                            color: QuattroTheme.Theme.textDim
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 7 }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: systemPage
        Flickable {
            contentWidth: width
            contentHeight: systemColumn.implicitHeight
            clip: true
            ColumnLayout {
                id: systemColumn
                width: parent.width
                spacing: 9
                SectionLabel { text: "AGENTS" }
                Card { implicitHeight: 58
                RowLayout { anchors.fill: parent
                anchors.margins: 11
                AgentRow { name: "Codex"
                state: root.agentState("codex")
                Layout.fillWidth: true }
                AgentRow { name: "Pi"
                state: root.agentState("pi")
                Layout.fillWidth: true } } }
                SectionLabel { text: "RETRIEVAL" }
                Card {
                    implicitHeight: metrics.implicitHeight + 22
                    GridLayout {
                        id: metrics
                        anchors.fill: parent
                        anchors.margins: 11
                        columns: 2
                        columnSpacing: 20
                        rowSpacing: 5
                        Metric { label: "Embedding"
                        value: root.object(root.dashboard.retrieval).embeddingBackend || root.object(root.dashboard.retrieval).embedding_backend || "quattro-feature-hash-v1" }
                        Metric { label: "Documents"
                        value: String(root.object(root.dashboard.retrieval).documents || root.object(root.dashboard.retrieval).documentCount || 0) }
                        Metric { label: "Indexed files"
                        value: String(root.object(root.dashboard.retrieval).indexedFiles || root.object(root.dashboard.retrieval).files || "—") }
                        Metric { label: "Graph edges"
                        value: String(root.object(root.dashboard.retrieval).graphEdges || root.object(root.dashboard.retrieval).edges || "—") }
                        Metric { label: "Database"
                        value: String(root.object(root.dashboard.retrieval).databaseBytes || root.object(root.dashboard.retrieval).databaseSize || "—") }
                        Metric { label: "Cache hits"
                        value: String(root.object(root.dashboard.retrieval).cacheHits || root.object(root.dashboard.retrieval).cache_hits || "—") }
                    }
                }
                RowLayout { ActionButton { label: maintenanceProcess.running ? "Maintenance running…" : "Reindex Knowledge"
                enabled: !maintenanceProcess.running
                onClicked: root.startMaintenance("reindex") }
                ActionButton { label: "Run Retrieval Benchmark"
                enabled: !maintenanceProcess.running
                onClicked: root.startMaintenance("benchmark") }
                Item { Layout.fillWidth: true } }
                Text { text: "Maintenance never runs automatically. Production embedding remains quattro-feature-hash-v1."
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8
                wrapMode: Text.Wrap
                Layout.fillWidth: true }
                SectionLabel { text: "MEMORY" }
                Card { implicitHeight: 58
                RowLayout { anchors.fill: parent
                anchors.margins: 11
                StatePill { state: root.object(root.dashboard.memory).status === "ok" ? "Healthy" : root.object(root.dashboard.memory).status || "Unavailable" }
                Text { text: "Display-safe institutional and project memory projections only."
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8
                Layout.fillWidth: true } } }
                SectionLabel { text: "ZED" }
                Card { implicitHeight: 58
                RowLayout { anchors.fill: parent
                anchors.margins: 11
                StatePill { state: root.object(root.dashboard.project).zedAvailable ? "Ready" : "Unavailable" }
                Text { text: root.object(root.dashboard.project).zedAvailable ? "Quattro wrappers enforce project and file restrictions." : "Zed is not installed and will not be installed automatically."
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8
                Layout.fillWidth: true } } }
            }
        }
    }

    Component {
        id: taskPage
        Flickable {
            contentWidth: width
            contentHeight: taskDetail.implicitHeight
            clip: true
            ColumnLayout {
                id: taskDetail
                width: parent.width
                spacing: 9
                property var task: root.object(root.object(root.selectedTaskDetails).task)
                property var caps: root.object(task.capabilities)
                Card {
                    implicitHeight: summary.implicitHeight + 22
                    ColumnLayout {
                        id: summary
                        anchors.fill: parent
                        anchors.margins: 11
                        spacing: 5
                        RowLayout { Layout.fillWidth: true
                        Text { text: taskDetail.task.title || "Untitled task"
                        color: QuattroTheme.Theme.textStrong
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 13
                        font.bold: true
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true }
                        StatePill { state: taskDetail.task.state || "unknown" } }
                        Text { text: (taskDetail.task.agent || "agent") + " · " + (taskDetail.task.projectName || "project") + " · " + root.age(taskDetail.task.createdAt)
                        color: QuattroTheme.Theme.textMuted
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 8 }
                        Text { text: taskDetail.task.terminalSummary || "Current step: " + (taskDetail.task.phase || taskDetail.task.state || "unknown")
                        color: QuattroTheme.Theme.text
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true }
                        Text { text: "Validation " + (root.object(taskDetail.task.validation).status || taskDetail.task.validation || "Not Run") + " · session " + root.shortId(taskDetail.task.quattroSessionId)
                        color: QuattroTheme.Theme.accent
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 8 }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ActionButton { label: "Open Project"
                    enabled: taskDetail.caps.openProject && root.object(root.dashboard.project).zedAvailable
                    onClicked: root.invoke(["open", taskDetail.task.projectPath], "zed") }
                    ActionButton { label: "Changed Files"
                    enabled: taskDetail.caps.openChangedFiles && root.object(root.dashboard.project).zedAvailable
                    onClicked: root.invoke(["task", "open", taskDetail.task.taskId], "zed") }
                    ActionButton { label: "Checkpoint"
                    enabled: taskDetail.caps.checkpoint
                    onClicked: root.invoke(["checkpoint", taskDetail.task.quattroSessionId, "--task", taskDetail.task.taskId], "checkpoint") }
                    ActionButton { label: "Resume"
                    enabled: taskDetail.caps.resume
                    onClicked: root.launch(["resume", taskDetail.task.quattroSessionId]) }
                    ActionButton { label: "Retry"
                    enabled: taskDetail.caps.retry
                    onClicked: root.invoke(["task", "retry", taskDetail.task.taskId, "--json"], "retry") }
                    ActionButton { label: "Cancel"
                    enabled: taskDetail.caps.cancel
                    onClicked: root.invoke(["task", "cancel", taskDetail.task.taskId, "--json"], "cancel") }
                }
                SectionLabel { text: "WORKFLOW" }
                Card { visible: !!taskDetail.task.workflow
                implicitHeight: 54
                RowLayout { anchors.fill: parent
                anchors.margins: 11
                Text { text: taskDetail.task.workflow || "Single task"
                color: QuattroTheme.Theme.textStrong
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 9
                Layout.fillWidth: true }
                Text { text: root.object(taskDetail.task.children).completed + "/" + root.object(taskDetail.task.children).total + " stages"
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8 } } }
                Repeater { model: root.array(root.object(root.selectedTaskDetails).children)
                delegate: ResultRow { required property var modelData
                title: modelData.title || root.object(modelData.metadata).role || "Workflow stage"
                detail: (modelData.agent || "agent") + " · " + root.human(modelData.state)
                actionLabel: "View"
                onActivated: root.showTask(modelData.taskId || modelData.id) } }
                SectionLabel { text: "RECENT EVENTS" }
                Repeater { model: root.array(root.object(root.selectedTaskDetails).events).slice(-12).reverse()
                delegate: ResultRow { required property var modelData
                title: root.human(modelData.type)
                detail: modelData.createdAt || ""
                body: root.object(modelData.payload).summary || root.object(modelData.payload).code || ""
                actionLabel: "" } }
                EmptyState { visible: root.array(root.object(root.selectedTaskDetails).events).length === 0
                title: "No recent events"
                detail: "No display-safe events have been emitted." }
            }
        }
    }

    Component {
        id: approvalPage
        ColumnLayout {
            spacing: 10
            Card {
                implicitHeight: approvalDetail.implicitHeight + 24
                ColumnLayout { id: approvalDetail
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7
                Text { text: root.selectedApproval ? root.human(root.selectedApproval.scope) : "Approval"
                color: QuattroTheme.Theme.warning
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 14
                font.bold: true }
                Text { text: root.selectedApproval ? root.selectedApproval.confirmationSummary : "Approval details unavailable"
                color: QuattroTheme.Theme.textStrong
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 10
                wrapMode: Text.Wrap
                Layout.fillWidth: true }
                Text { text: root.selectedApproval ? "Task " + root.shortId(root.selectedApproval.taskId) + " · requested " + root.selectedApproval.requestedAt : ""
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8 } }
            }
            RowLayout { ActionButton { label: "Approve"
            accent: true
            enabled: root.selectedApproval && root.object(root.selectedApproval.capabilities).approve
            onClicked: root.resolveApproval("approve") }
            ActionButton { label: "Reject"
            enabled: root.selectedApproval && root.object(root.selectedApproval.capabilities).reject
            onClicked: root.resolveApproval("reject") }
            ActionButton { label: "View Task"
            onClicked: { if (root.selectedApproval) root.showTask(root.selectedApproval.taskId) } }
            Item { Layout.fillWidth: true } }
            Text { text: "Resolution goes through Quattro's durable approval lifecycle and cannot bypass policy."
            color: QuattroTheme.Theme.textMuted
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 8
            wrapMode: Text.Wrap
            Layout.fillWidth: true }
            Item { Layout.fillHeight: true }
        }
    }

    component SectionLabel: Text { color: QuattroTheme.Theme.textMuted
    font.family: "JetBrainsMono Nerd Font"
    font.pixelSize: 8
    font.bold: true
    Layout.fillWidth: true }
    component Card: Rectangle { Layout.fillWidth: true
    implicitHeight: 48
    color: QuattroTheme.Theme.surface
    border.width: 1
    border.color: QuattroTheme.Theme.border }
    component ActionButton: Rectangle {
        id: button
        required property string label
        property bool accent: false
        signal clicked()
        implicitWidth: Math.max(62, buttonText.implicitWidth + 18)
        implicitHeight: 28
        color: accent ? QuattroTheme.Theme.accent : buttonMouse.containsMouse ? QuattroTheme.Theme.hover : QuattroTheme.Theme.border
        opacity: enabled ? 1 : 0.35
        Text { id: buttonText
        anchors.centerIn: parent
        text: button.label
        color: button.accent ? QuattroTheme.Theme.background : QuattroTheme.Theme.text
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8
        font.bold: button.accent }
        MouseArea { id: buttonMouse
        anchors.fill: parent
        enabled: button.enabled
        hoverEnabled: true
        cursorShape: button.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: button.clicked() }
    }
    component NavButton: Rectangle {
        id: nav
        required property string label
        required property string target
        Layout.fillWidth: true
        implicitHeight: 34
        color: root.page === target ? QuattroTheme.Theme.accentMuted : navMouse.containsMouse ? QuattroTheme.Theme.hover : "transparent"
        Rectangle { visible: root.page === target
        anchors { left: parent.left
        top: parent.top
        bottom: parent.bottom }
        width: 2
        color: QuattroTheme.Theme.accent }
        Text { anchors { left: parent.left
        leftMargin: 9
        verticalCenter: parent.verticalCenter }
        text: nav.label
        color: root.page === target ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9
        font.bold: root.page === target }
        MouseArea { id: navMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.go(nav.target) }
    }
    component Field: Rectangle {
        id: field
        property alias text: input.text
        required property string placeholder
        signal accepted()
        Layout.fillWidth: true
        implicitHeight: 36
        color: QuattroTheme.Theme.surfaceRaised
        border.width: input.activeFocus ? 1 : 0
        border.color: QuattroTheme.Theme.accent
        TextInput { id: input
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        verticalAlignment: TextInput.AlignVCenter
        color: QuattroTheme.Theme.textStrong
        selectionColor: QuattroTheme.Theme.accentMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 10
        onAccepted: field.accepted() }
        Text { visible: !input.text.length
        anchors { left: parent.left
        leftMargin: 10
        verticalCenter: parent.verticalCenter }
        text: field.placeholder
        color: QuattroTheme.Theme.textDim
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9 }
        function forceActiveFocus() { input.forceActiveFocus() }
    }
    component StatePill: Rectangle {
        id: pill
        required property string state
        implicitWidth: pillText.implicitWidth + 14
        implicitHeight: 22
        color: root.stateColor(state)
        Text { id: pillText
        anchors.centerIn: parent
        text: root.human(pill.state)
        color: QuattroTheme.Theme.background
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 7
        font.bold: true }
    }
    component AgentRow: RowLayout {
        required property string name
        required property string state
        spacing: 7
        Rectangle { width: 7
        height: 7
        color: root.stateColor(parent.state) }
        Text { text: parent.name
        color: QuattroTheme.Theme.textStrong
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 10
        Layout.fillWidth: true }
        Text { text: parent.state
        color: root.stateColor(parent.state)
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8 }
    }
    component Metric: ColumnLayout {
        required property string label
        required property string value
        Layout.fillWidth: true
        spacing: 1
        Text { text: parent.label
        color: QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 7 }
        Text { text: parent.value
        color: QuattroTheme.Theme.textStrong
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9
        elide: Text.ElideRight
        Layout.fillWidth: true }
    }
    component UsageMeter: ColumnLayout {
        required property string label
        required property var window
        property real remaining: window ? Math.max(0, Math.min(100, 100 - Number(window.usedPercent || 0))) : 0
        Layout.fillWidth: true
        spacing: 3
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: parent.parent.label
                color: QuattroTheme.Theme.text
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8
                Layout.fillWidth: true
            }
            Text {
                text: Math.round(parent.parent.remaining) + "% remaining · " + root.resetText(parent.parent.window ? parent.parent.window.resetAt : 0)
                color: parent.parent.remaining <= 10 ? QuattroTheme.Theme.danger : parent.parent.remaining <= 30 ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 8
            }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 5
            color: QuattroTheme.Theme.border
            Rectangle {
                width: parent.width * parent.parent.remaining / 100
                height: parent.height
                color: parent.parent.remaining <= 10 ? QuattroTheme.Theme.danger : parent.parent.remaining <= 30 ? QuattroTheme.Theme.warning : QuattroTheme.Theme.accent
            }
        }
    }
    component EmptyState: Rectangle {
        id: empty
        required property string title
        required property string detail
        Layout.fillWidth: true
        implicitHeight: 64
        color: QuattroTheme.Theme.surface
        border.width: 1
        border.color: QuattroTheme.Theme.border
        Column { anchors.centerIn: parent
        spacing: 3
        Text { anchors.horizontalCenter: parent.horizontalCenter
        text: empty.title
        color: QuattroTheme.Theme.text
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9
        font.bold: true }
        Text { anchors.horizontalCenter: parent.horizontalCenter
        text: empty.detail
        color: QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8 } }
    }
    component ResultRow: Rectangle {
        id: result
        required property string title
        required property string detail
        property string body: ""
        property string actionLabel: "Open"
        signal activated()
        Layout.fillWidth: true
        implicitHeight: resultBody.visible ? 70 : 50
        color: resultMouse.containsMouse ? QuattroTheme.Theme.hover : QuattroTheme.Theme.surface
        border.width: 1
        border.color: QuattroTheme.Theme.border
        Column { anchors { left: parent.left
        right: actionText.left
        leftMargin: 10
        rightMargin: 8
        verticalCenter: parent.verticalCenter }
        spacing: 2
        Text { text: result.title
        color: QuattroTheme.Theme.textStrong
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9
        font.bold: true
        elide: Text.ElideRight
        width: parent.width }
        Text { text: result.detail
        color: QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 7
        elide: Text.ElideMiddle
        width: parent.width }
        Text { id: resultBody
        visible: result.body.length > 0
        text: result.body
        color: QuattroTheme.Theme.textDim
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 7
        elide: Text.ElideRight
        width: parent.width } }
        Text { id: actionText
        anchors { right: parent.right
        rightMargin: 10
        verticalCenter: parent.verticalCenter }
        text: result.actionLabel
        color: QuattroTheme.Theme.accent
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8 }
        MouseArea { id: resultMouse
        anchors.fill: parent
        enabled: result.actionLabel.length > 0
        hoverEnabled: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: result.activated() }
    }
    component TaskRow: Rectangle {
        id: taskRow
        required property var task
        Layout.fillWidth: true
        implicitHeight: 58
        color: taskMouse.containsMouse ? QuattroTheme.Theme.hover : QuattroTheme.Theme.surface
        border.width: 1
        border.color: QuattroTheme.Theme.border
        Column { anchors { left: parent.left
        right: taskState.left
        leftMargin: 10
        rightMargin: 8
        verticalCenter: parent.verticalCenter }
        spacing: 3
        Text { text: taskRow.task.title || "Task"
        color: QuattroTheme.Theme.textStrong
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9
        font.bold: true
        elide: Text.ElideRight
        width: parent.width }
        Text { text: (taskRow.task.agent || "agent") + " · " + (taskRow.task.projectName || "project") + " · " + root.age(taskRow.task.updatedAt || taskRow.task.createdAt)
        color: QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 7
        elide: Text.ElideRight
        width: parent.width } }
        StatePill { id: taskState
        anchors { right: parent.right
        rightMargin: 10
        verticalCenter: parent.verticalCenter }
        state: taskRow.task.state || "unknown" }
        MouseArea { id: taskMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.showTask(taskRow.task.taskId || taskRow.task.id) }
    }
    component ApprovalRow: Rectangle {
        id: approvalRow
        required property var approval
        Layout.fillWidth: true
        implicitHeight: 60
        color: QuattroTheme.Theme.surface
        border.width: 1
        border.color: QuattroTheme.Theme.warning
        Column { anchors { left: parent.left
        right: inspectText.left
        leftMargin: 10
        rightMargin: 8
        verticalCenter: parent.verticalCenter }
        spacing: 3
        Text { text: root.human(approvalRow.approval.scope)
        color: QuattroTheme.Theme.warning
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8
        font.bold: true }
        Text { text: approvalRow.approval.confirmationSummary
        color: QuattroTheme.Theme.textStrong
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8
        elide: Text.ElideRight
        width: parent.width } }
        Text { id: inspectText
        anchors { right: parent.right
        rightMargin: 10
        verticalCenter: parent.verticalCenter }
        text: "Inspect"
        color: QuattroTheme.Theme.accent
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8 }
        MouseArea { anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.showApproval(approvalRow.approval) }
    }
    component TaskSummary: Card {
        id: activeCard
        required property var task
        implicitHeight: task ? activeColumn.implicitHeight + 22 : 64
        ColumnLayout { id: activeColumn
        visible: !!activeCard.task
        anchors.fill: parent
        anchors.margins: 11
        spacing: 5
        RowLayout { Layout.fillWidth: true
        Text { text: activeCard.task ? activeCard.task.title : ""
        color: QuattroTheme.Theme.textStrong
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 11
        font.bold: true
        Layout.fillWidth: true }
        StatePill { state: activeCard.task ? activeCard.task.state : "idle" } }
        Text { text: activeCard.task ? (activeCard.task.agent || "agent") + " · " + (activeCard.task.projectName || "project") + " · " + root.age(activeCard.task.createdAt) : ""
        color: QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 8 }
        RowLayout { ActionButton { label: "View"
        onClicked: root.showTask(activeCard.task.taskId || activeCard.task.id) }
        ActionButton { label: "Open Code"
        enabled: root.object(root.dashboard.project).zedAvailable === true
        onClicked: root.invoke(["task", "open", activeCard.task.taskId || activeCard.task.id], "zed") }
        Item { Layout.fillWidth: true } } }
        Text { visible: !activeCard.task
        anchors.centerIn: parent
        text: "Quattro is idle. Start a task from Quick Prompt."
        color: QuattroTheme.Theme.textMuted
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 9 }
    }
}
