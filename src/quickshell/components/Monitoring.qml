import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "../theme" as QuattroTheme
import "../services"
import "shared"

Scope {
    id: root
    property int tab: 0
    readonly property var data: metrics.snapshot
    readonly property bool narrow: panel.width <= 900
    readonly property real unit: Math.max(0.8, Math.min(1, panel.width / 1360))
    readonly property var sensors: data && data.temperatures.available ? data.temperatures.sensors : []
    readonly property var processes: data && data.processes.available ? data.processes.items : []
    property string processQuery: ""
    property int processOrder: 0
    readonly property var selectedProcesses: selectProcesses(processes, processQuery, processOrder)
    readonly property var gpus: data && data.gpu.available ? data.gpu.devices : []

    function open() {
        panel.screen = PopupManager.focusedScreen()
        panel.opened = true
        Qt.callLater(() => pauseButton.forceActiveFocus())
    }
    function close() { panel.opened = false }
    function toggle() { if (panel.opened) close(); else open() }
    function percent(value) { return value === null || value === undefined ? "—" : value.toFixed(1) + " %" }
    function bytes(value) {
        if (value === null || value === undefined) return "—"
        if (value >= 1099511627776) return (value / 1099511627776).toFixed(1) + " TiB"
        if (value >= 1073741824) return (value / 1073741824).toFixed(1) + " GiB"
        if (value >= 1048576) return (value / 1048576).toFixed(1) + " MiB"
        return (value / 1024).toFixed(1) + " KiB"
    }
    function rate(value) { return value === null || value === undefined ? "—" : bytes(value) + "/s" }
    function selectProcesses(items, query, order) {
        const needle = query.trim().toLowerCase()
        const rows = items.filter(p => !needle || p.name.toLowerCase().indexOf(needle) !== -1 || String(p.pid).indexOf(needle) !== -1)
        rows.sort((a, b) => {
            if (order === 1) return a.rssBytes - b.rssBytes || a.pid - b.pid
            if (order === 2) return a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.pid - b.pid
            if (order === 3) return a.pid - b.pid
            return b.rssBytes - a.rssBytes || a.pid - b.pid
        })
        return rows
    }
    function networkLimit(field) {
        let highest = 0
        const end = metrics.history.length ? metrics.history[metrics.history.length - 1].time : 0
        for (const point of metrics.history)
            if (point.time >= end - 120000 && point[field] !== null) highest = Math.max(highest, point[field])
        // A dynamic, explicitly labelled scale; no implied fixed bandwidth.
        return Math.max(1024, Math.pow(2, Math.ceil(Math.log(Math.max(1, highest * 1.2)) / Math.LN2)))
    }
    Connections {
        target: PopupManager
        function onRequested(name) { if (name === "monitoring") root.toggle() }
    }
    IpcHandler {
        target: "monitor"
        function toggle(): void { root.toggle() }
        function open(): void { root.open() }
        function processes(): string {
            root.tab = 1
            root.open()
            return JSON.stringify({open: panel.opened, tab: "Processes", state: metrics.state})
        }
        function close(): void { root.close() }
        function status(): string {
            return JSON.stringify({open: panel.opened, screen: panel.screen ? panel.screen.name : "", state: metrics.state,
                paused: metrics.paused, updatedAt: root.data ? root.data.updatedAt : null, samples: metrics.history.length})
        }
    }
    MonitorMetrics { id: metrics; active: panel.visible }

    component Label: Text {
        color: QuattroTheme.Theme.textStrong
        font.family: QuattroTheme.Theme.fontFamily
        font.pixelSize: 15 * root.unit
        textFormat: Text.PlainText
        elide: Text.ElideRight
    }
    component Heading: Label { font.pixelSize: 23 * root.unit; font.weight: Font.Medium }
    component Rule: Rectangle { color: QuattroTheme.Theme.border; implicitHeight: 1; Layout.fillWidth: true }
    component Action: Button {
        id: action
        hoverEnabled: true
        activeFocusOnTab: true
        implicitHeight: 40 * root.unit
        implicitWidth: contentItem.implicitWidth + 26 * root.unit
        padding: 8 * root.unit
        Accessible.name: text
        background: Rectangle {
            color: action.down ? QuattroTheme.Theme.pressed : action.hovered ? QuattroTheme.Theme.hover : "transparent"
            border.width: action.activeFocus ? 2 : 1
            border.color: action.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.borderStrong
        }
        contentItem: Label { text: action.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    }
    component Gauge: Rectangle {
        property var value: null
        implicitHeight: 24 * root.unit
        color: "transparent"
        border.width: 1
        border.color: QuattroTheme.Theme.borderStrong
        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 1 }
            width: parent.value === null ? 0 : (parent.width - 2) * Math.max(0, Math.min(100, parent.value)) / 100
            color: QuattroTheme.Theme.textStrong
        }
    }
    component ValueRow: Item {
        id: rowRoot
        property string label: ""
        property string value: "—"
        property string detail: ""
        property real valueWidth: 150 * root.unit
        implicitHeight: 34 * root.unit
        RowLayout {
            anchors.fill: parent
            spacing: 12 * root.unit
            Label { text: rowRoot.label; Layout.fillWidth: true }
            Label { text: rowRoot.value; Layout.preferredWidth: rowRoot.valueWidth; horizontalAlignment: Text.AlignRight }
            Label { visible: rowRoot.detail.length > 0; text: rowRoot.detail; Layout.preferredWidth: 66 * root.unit; horizontalAlignment: Text.AlignRight }
        }
        Rectangle { anchors { bottom: parent.bottom; left: parent.left; right: parent.right } height: 1; color: QuattroTheme.Theme.border }
    }
    component ThermalLedger: ColumnLayout {
        property bool expanded: false
        spacing: 0
        Heading { text: "THERMALS"; Layout.bottomMargin: 10 * root.unit }
        Rule {}
        Repeater {
            model: root.sensors.slice(0, parent.expanded ? 32 : 2)
            delegate: ValueRow {
                required property var modelData
                Layout.fillWidth: true
                label: modelData.name
                value: modelData.celsius.toFixed(1) + " °C"
            }
        }
        Label {
            visible: !root.sensors.length
            text: root.data ? "No temperature sensors available" : "Waiting for sensor readings…"
            color: QuattroTheme.Theme.textMuted
            Layout.topMargin: 12 * root.unit
        }
    }
    component ProcessRow: Item {
        required property var modelData
        required property int index
        implicitHeight: 34 * root.unit
        Rectangle { anchors.fill: parent; color: index % 2 ? QuattroTheme.Theme.surface : "transparent" }
        RowLayout {
            anchors.fill: parent
            anchors.rightMargin: 12 * root.unit
            spacing: (root.narrow ? 8 : 16) * root.unit
            Label { text: modelData.name; Layout.fillWidth: true }
            Label { text: String(modelData.pid); Layout.preferredWidth: (root.narrow ? 64 : 100) * root.unit; horizontalAlignment: Text.AlignRight }
            Label { visible: !root.narrow; text: root.percent(modelData.cpuPercent); Layout.preferredWidth: 136 * root.unit; horizontalAlignment: Text.AlignRight }
            Label { text: root.bytes(modelData.rssBytes); Layout.preferredWidth: (root.narrow ? 114 : 160) * root.unit; horizontalAlignment: Text.AlignRight }
            Label { text: modelData.rssPercent === null ? "—" : modelData.rssPercent.toFixed(2) + " %"; Layout.preferredWidth: 88 * root.unit; horizontalAlignment: Text.AlignRight }
        }
    }
    component ProcessLedger: ColumnLayout {
        id: ledger
        property bool expanded: false
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 10 * root.unit
            Heading { text: "PROCESSES"; Layout.fillWidth: true }
            Label { text: ledger.expanded ? root.selectedProcesses.length + " / " + root.processes.length + " processes" : "Highest RAM · read only"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 12 * root.unit }
        }
        RowLayout {
            visible: ledger.expanded
            Layout.fillWidth: true
            Layout.bottomMargin: 12 * root.unit
            spacing: 12 * root.unit
            DesktopField {
                objectName: "processSearch"
                Layout.fillWidth: true
                implicitHeight: 40 * root.unit
                placeholderText: "Search process name or PID"
                Accessible.name: "Search process name or PID"
                text: root.processQuery
                onTextEdited: root.processQuery = text
            }
            DesktopCombo {
                objectName: "processSort"
                implicitHeight: 40 * root.unit
                Layout.preferredWidth: 210 * root.unit
                model: ["RAM: highest first", "RAM: lowest first", "Name: A to Z", "PID: lowest first"]
                currentIndex: root.processOrder
                Accessible.name: "Sort processes"
                onActivated: root.processOrder = currentIndex
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 28 * root.unit
            Layout.rightMargin: 12 * root.unit
            spacing: (root.narrow ? 8 : 16) * root.unit
            Label { text: "NAME"; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true }
            Label { text: "PID"; color: QuattroTheme.Theme.textMuted; Layout.preferredWidth: (root.narrow ? 64 : 100) * root.unit; horizontalAlignment: Text.AlignRight }
            Label { visible: !root.narrow; text: "CPU / CORE"; color: QuattroTheme.Theme.textMuted; Layout.preferredWidth: 136 * root.unit; horizontalAlignment: Text.AlignRight }
            Label { text: "RAM (RSS)"; color: QuattroTheme.Theme.textMuted; Layout.preferredWidth: (root.narrow ? 114 : 160) * root.unit; horizontalAlignment: Text.AlignRight }
            Label { text: "% RAM"; color: QuattroTheme.Theme.textMuted; Layout.preferredWidth: 88 * root.unit; horizontalAlignment: Text.AlignRight }
        }
        Rule {}
        Repeater {
            model: ledger.expanded ? [] : root.processes.slice(0, 3)
            delegate: ProcessRow {
                Layout.fillWidth: true
            }
        }
        ListView {
            id: processList
            objectName: "processList"
            visible: ledger.expanded && root.selectedProcesses.length > 0
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(536 * root.unit, root.selectedProcesses.length * 34 * root.unit)
            model: ledger.expanded ? root.selectedProcesses : []
            clip: true
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            activeFocusOnTab: true
            Accessible.name: "Process resident memory list"
            delegate: ProcessRow { width: processList.width }
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle { implicitWidth: 6; color: parent.pressed ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.borderStrong }
            }
            Rectangle { anchors.fill: parent; color: "transparent"; border.width: processList.activeFocus ? 2 : 0; border.color: QuattroTheme.Theme.textStrong }
        }
        Label {
            visible: !root.processes.length || ledger.expanded && !root.selectedProcesses.length
            text: !root.data ? "Waiting for process readings…" : !root.data.processes.available ? "Process readings unavailable" : root.processes.length ? "No processes match. Try another name or PID." : "No accessible active processes in this sample."
            color: QuattroTheme.Theme.textMuted
            Layout.topMargin: 12 * root.unit
        }
        Label {
            visible: ledger.expanded || !!root.data && root.data.processes.truncated
            text: "RAM is resident memory (RSS); % RAM uses total physical memory. Shared pages count in each process, so RSS must not be summed as system used RAM."
                + (ledger.expanded ? " CPU uses one core as 100%." : "")
                + (root.data && root.data.processes.truncated ? " Partial scan: time or process limit reached; some processes are absent." : "")
                + (root.data && root.data.processes.omittedCount ? " " + root.data.processes.omittedCount + " exited, zombie or unreadable entries omitted." : "")
            color: QuattroTheme.Theme.textMuted
            font.pixelSize: 12 * root.unit
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            elide: Text.ElideNone
            Layout.topMargin: 10 * root.unit
        }
    }

    TemporaryPanel {
        id: panel
        panelName: "monitoring"
        onDismissed: root.close()
        color: "transparent"
        anchors { top: true; right: true }
        margins {
            top: Math.max(QuattroTheme.Theme.barHeight + 12, Math.min(96, (screen ? screen.height : 1080) * 0.089))
            right: Math.min(36, (screen ? screen.width : 1920) * 0.019)
        }
        implicitWidth: Math.min(1360, Math.max(1, (screen ? screen.width : 1920) - 48))
        implicitHeight: Math.min(956, Math.max(1, (screen ? screen.height : 1080) - margins.top - 28))

        Rectangle {
            anchors.fill: parent
            color: QuattroTheme.Theme.panelSurface
            border.width: 1
            border.color: QuattroTheme.Theme.panelBorder
            FocusScope {
                anchors.fill: parent
                focus: panel.visible
                Keys.onEscapePressed: root.close()
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 1
                    spacing: 0
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 86 * root.unit
                        Layout.minimumHeight: 86 * root.unit
                        Layout.maximumHeight: 86 * root.unit
                        Layout.leftMargin: 26 * root.unit
                        Layout.rightMargin: 26 * root.unit
                        spacing: 24 * root.unit
                        Label {
                            text: "MONITORING"
                            font.family: QuattroTheme.Theme.displayFontFamily
                            font.pixelSize: (root.narrow ? 46 : 82) * root.unit
                            font.variableAxes: ({ "ROND": 100, "wght": 600 })
                            font.weight: Font.DemiBold
                            Layout.fillWidth: root.narrow
                        }
                        Rectangle { visible: !root.narrow; color: QuattroTheme.Theme.borderStrong; implicitWidth: 1; implicitHeight: 38 * root.unit }
                        Label {
                            visible: !root.narrow
                            text: metrics.state + " · " + metrics.detail
                            color: metrics.state === "Stale" || metrics.state === "Unavailable" ? QuattroTheme.Theme.danger : QuattroTheme.Theme.textMuted
                            Layout.fillWidth: true
                        }
                        Action {
                            id: pauseButton
                            text: metrics.paused ? "Resume" : "Pause"
                            Accessible.name: metrics.paused ? "Resume live monitoring" : "Pause live monitoring"
                            onClicked: metrics.paused = !metrics.paused
                        }
                        Action { text: "Close  Esc"; Accessible.name: "Close monitoring, Escape"; onClicked: root.close() }
                    }
                    Rule {}
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 48 * root.unit
                        Layout.minimumHeight: 48 * root.unit
                        Layout.maximumHeight: 48 * root.unit
                        Layout.leftMargin: 10 * root.unit
                        spacing: 0
                        Repeater {
                            model: ["Overview", "Processes", "Thermals", "GPU"]
                            delegate: Button {
                                id: tabButton
                                required property string modelData
                                required property int index
                                Layout.fillHeight: true
                                implicitWidth: (root.narrow ? 112 : 134) * root.unit
                                activeFocusOnTab: true
                                hoverEnabled: true
                                Accessible.name: modelData + " monitoring tab"
                                Accessible.role: Accessible.PageTab
                                Accessible.selected: root.tab === index
                                onClicked: root.tab = index
                                background: Rectangle {
                                    color: tabButton.hovered ? QuattroTheme.Theme.hover : "transparent"
                                    border.width: tabButton.activeFocus ? 2 : 0
                                    border.color: QuattroTheme.Theme.textStrong
                                    Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 2; color: QuattroTheme.Theme.textStrong; visible: root.tab === tabButton.index }
                                }
                                contentItem: Label { text: tabButton.modelData; color: root.tab === tabButton.index ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }
                    Rule {}
                    ScrollView {
                        id: scroll
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        contentWidth: availableWidth
                        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                            contentItem: Rectangle { implicitWidth: 6; color: parent.pressed ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.borderStrong }
                        }
                        ColumnLayout {
                            width: scroll.availableWidth
                            spacing: 0
                            GridLayout {
                                visible: root.tab === 0
                                columns: root.narrow ? 1 : 3
                                rowSpacing: 0
                                columnSpacing: 0
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 900
                                    Layout.minimumHeight: 234 * root.unit
                                    Layout.leftMargin: 26 * root.unit
                                    Layout.rightMargin: 26 * root.unit
                                    Layout.topMargin: 18 * root.unit
                                    Layout.bottomMargin: 18 * root.unit
                                    spacing: 8 * root.unit
                                    Heading { text: "CPU" }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Label { text: root.data && root.data.cpu.available ? root.percent(root.data.cpu.percent) : "—"; font.pixelSize: 36 * root.unit; Layout.fillWidth: true }
                                        Label { text: "120 s"; color: QuattroTheme.Theme.textMuted }
                                    }
                                    MetricPlot { samples: metrics.history; field: "cpu"; maximum: 100; Layout.fillWidth: true; Layout.preferredHeight: 128 * root.unit }
                                    Label { visible: !!root.data && root.data.cpu.available && root.data.cpu.percent === null; text: "Collecting the next CPU interval…"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 12 * root.unit }
                                }
                                Rectangle { visible: !root.narrow; Layout.preferredWidth: 1; Layout.fillHeight: true; color: QuattroTheme.Theme.border }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 430
                                    Layout.alignment: Qt.AlignTop
                                    Layout.leftMargin: 26 * root.unit
                                    Layout.rightMargin: 26 * root.unit
                                    Layout.topMargin: 18 * root.unit
                                    Layout.bottomMargin: 18 * root.unit
                                    spacing: 12 * root.unit
                                    Heading { text: "MEMORY" }
                                    Label { text: root.data && root.data.memory.available ? root.bytes(root.data.memory.usedBytes) + " / " + root.bytes(root.data.memory.totalBytes) : "—"; font.pixelSize: 27 * root.unit; Layout.fillWidth: true }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Gauge { value: root.data && root.data.memory.available ? root.data.memory.percent : null; Layout.fillWidth: true }
                                        Label { text: root.data && root.data.memory.available ? root.percent(root.data.memory.percent) : "—" }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 0
                                        ValueRow { Layout.fillWidth: true; label: "Used"; value: root.data && root.data.memory.available ? root.bytes(root.data.memory.usedBytes) : "—" }
                                        ValueRow { Layout.fillWidth: true; label: "Available"; value: root.data && root.data.memory.available ? root.bytes(root.data.memory.availableBytes) : "—" }
                                        ValueRow { Layout.fillWidth: true; label: "Swap"; value: root.data && root.data.swap.available ? root.bytes(root.data.swap.usedBytes) : "—" }
                                    }
                                }
                            }
                            Rule { visible: root.tab === 0 }
                            GridLayout {
                                visible: root.tab === 0
                                columns: root.narrow ? 1 : 3
                                rowSpacing: 0
                                columnSpacing: 0
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.leftMargin: 26 * root.unit
                                    Layout.rightMargin: 26 * root.unit
                                    Layout.topMargin: 16 * root.unit
                                    Layout.bottomMargin: 16 * root.unit
                                    spacing: 10 * root.unit
                                    Heading { text: "STORAGE  /" }
                                    Rule {}
                                    ValueRow { Layout.fillWidth: true; label: "Used"; valueWidth: 280 * root.unit; value: root.data && root.data.filesystem.available ? root.bytes(root.data.filesystem.usedBytes) + " / " + root.bytes(root.data.filesystem.totalBytes) : "—"; detail: root.data && root.data.filesystem.available ? root.percent(root.data.filesystem.percent) : "—" }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Label { text: "Root filesystem"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 12 * root.unit }
                                        Gauge { value: root.data && root.data.filesystem.available ? root.data.filesystem.percent : null; Layout.fillWidth: true; implicitHeight: 15 * root.unit }
                                    }
                                    Label { text: "Read / write rates unavailable"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 12 * root.unit }
                                }
                                Rectangle { visible: !root.narrow; Layout.preferredWidth: 1; Layout.fillHeight: true; color: QuattroTheme.Theme.border }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                    Layout.leftMargin: 26 * root.unit
                                    Layout.rightMargin: 26 * root.unit
                                    Layout.topMargin: 16 * root.unit
                                    Layout.bottomMargin: 16 * root.unit
                                    spacing: 8 * root.unit
                                    Heading { text: "NETWORK" }
                                    Rule {}
                                    Repeater {
                                        model: [{label: "Receive", field: "rx", key: "rxBytesPerSecond"}, {label: "Transmit", field: "tx", key: "txBytesPerSecond"}]
                                        delegate: RowLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: 14 * root.unit
                                            Label { text: modelData.label; Layout.preferredWidth: 94 * root.unit }
                                            Label { text: root.data && root.data.network.available ? root.rate(root.data.network[modelData.key]) : "—"; Layout.preferredWidth: 140 * root.unit }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 1
                                                MetricPlot { Layout.fillWidth: true; Layout.preferredHeight: 32 * root.unit; showAxis: false; samples: metrics.history; field: modelData.field; maximum: root.networkLimit(modelData.field); strokeColor: modelData.field === "tx" ? QuattroTheme.Theme.danger : QuattroTheme.Theme.textStrong }
                                                Label { text: "0–" + root.rate(root.networkLimit(modelData.field)) + " · 120 s"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 10 * root.unit; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight }
                                            }
                                        }
                                    }
                                }
                            }
                            Rule { visible: root.tab === 0 }
                            ThermalLedger { visible: root.tab === 0 || root.tab === 2; expanded: root.tab === 2; Layout.fillWidth: true; Layout.leftMargin: 26 * root.unit; Layout.rightMargin: 26 * root.unit; Layout.topMargin: 14 * root.unit; Layout.bottomMargin: 14 * root.unit }
                            Rule { visible: root.tab === 0 }
                            ProcessLedger { visible: root.tab === 0 || root.tab === 1; expanded: root.tab === 1; Layout.fillWidth: true; Layout.leftMargin: 26 * root.unit; Layout.rightMargin: 26 * root.unit; Layout.topMargin: 16 * root.unit; Layout.bottomMargin: 16 * root.unit }
                            ColumnLayout {
                                visible: root.tab === 3
                                Layout.fillWidth: true
                                Layout.margins: 26 * root.unit
                                spacing: 14 * root.unit
                                Heading { text: "GPU" }
                                Label { text: "Counters depend on the graphics driver."; color: QuattroTheme.Theme.textMuted; Layout.fillWidth: true }
                                Repeater {
                                    model: root.gpus
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        spacing: 0
                                        Heading { text: modelData.name; Layout.topMargin: 16 * root.unit; Layout.bottomMargin: 12 * root.unit }
                                        Rule {}
                                        ValueRow { label: "Utilization"; value: root.percent(modelData.busyPercent); detail: modelData.busyPercent === null ? "—" : ""; Layout.fillWidth: true }
                                        ValueRow { label: "Video memory"; valueWidth: 280 * root.unit; value: root.bytes(modelData.memoryUsedBytes) + " / " + root.bytes(modelData.memoryTotalBytes); Layout.fillWidth: true }
                                        Label { visible: modelData.busyPercent === null || modelData.memoryUsedBytes === null; text: "—  Counter unavailable from this driver"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 12 * root.unit; Layout.topMargin: 12 * root.unit }
                                    }
                                }
                                Label { visible: !root.gpus.length; text: root.data ? "GPU counters unavailable" : "Waiting for GPU readings…"; color: QuattroTheme.Theme.textMuted; Layout.topMargin: 16 * root.unit }
                            }
                        }
                    }
                    Rule {}
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34 * root.unit
                        Layout.minimumHeight: 34 * root.unit
                        Layout.maximumHeight: 34 * root.unit
                        Layout.leftMargin: 26 * root.unit
                        Layout.rightMargin: 26 * root.unit
                        Label {
                            text: metrics.state + " · " + metrics.detail
                            color: metrics.state === "Stale" || metrics.state === "Unavailable" ? QuattroTheme.Theme.danger : QuattroTheme.Theme.textMuted
                            font.pixelSize: 11 * root.unit
                            Layout.fillWidth: true
                        }
                        Label { text: root.data ? "Updated " + new Date(root.data.updatedAt * 1000).toLocaleTimeString(Qt.locale(), "HH:mm:ss") : "No readings yet"; color: QuattroTheme.Theme.textMuted; font.pixelSize: 11 * root.unit }
                    }
                }
            }
        }
    }
}
