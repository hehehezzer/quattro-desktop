import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import QtQuick
import QtQuick.Layouts
import "../theme" as QuattroTheme
import "../services"
import "shared"

Scope {
    id: root

    property string page: "main"
    property string agentCommand: Quickshell.env("QUATTRO_AGENT_COMMAND") || "quattro-agent"
    property string projectsOMPCommand: Quickshell.env("QUATTRO_PROJECTS_OMP_COMMAND") || "quattro-projects-omp"
    property string menuCommand: Quickshell.env("QUATTRO_MENU_COMMAND") || "quattro-menu"
    property string themeCommand: Quickshell.env("QUATTRO_THEME_COMMAND") || "quattro-theme"
    property string pointerCommand: Quickshell.env("QUATTRO_POINTER_COMMAND") || "quattro-pointer"
    property string sessionCommand: Quickshell.env("QUATTRO_SESSION_COMMAND") || "quattro-session"
    property var globalFileResults: []
    property string activeSearchQuery: ""
    property bool globalSearchRunning: false
    property var installPackages: [
        { "id": "code", "icon": "󰨞", "label": "Code - OSS", "detail": "Code editor" },
        { "id": "docker", "icon": "󰡨", "label": "Docker", "detail": "Containers and local services" },
        { "id": "gimp", "icon": "󰏘", "label": "GIMP", "detail": "Image editing" },
        { "id": "blender", "icon": "󰂫", "label": "Blender", "detail": "3D creation suite" },
        { "id": "obs", "icon": "󰑋", "label": "OBS Studio", "detail": "Recording and streaming" },
        { "id": "office", "icon": "󰈙", "label": "LibreOffice", "detail": "Documents and spreadsheets" },
        { "id": "steam", "icon": "󰓓", "label": "Steam", "detail": "PC games" }
    ]

    function setTheme(name) {
        if (!QuattroTheme.Theme.apply(name))
            return
        Quickshell.execDetached([root.themeCommand, "set", name])
    }

    Connections {
        target: PopupManager
        function onRequested(name) {
            if (name === "menu") menuWindow.visible ? root.close() : root.open("main");
        }
    }

    function openPanel(name) {
        Quickshell.execDetached(["qs", "ipc", "call", "panel", name])
        root.close()
    }

    function openMonitor() {
        root.close()
        PopupManager.request("monitoring")
    }

    function editConfig(target, title) {
        Quickshell.execDetached([
            "ghostty", "--gtk-single-instance=false", "--wait-after-command=true", "--class=com.quattro.setup",
            "--title=Setup · " + title, "-e",
            root.menuCommand, "edit", target
        ])
        root.close()
    }

    function installPackage(packageId, title) {
        Quickshell.execDetached([
            "ghostty", "--gtk-single-instance=false", "--wait-after-command=true", "--class=com.quattro.install",
            "--title=Install · " + title, "-e",
            root.menuCommand, "install", packageId
        ])
        root.close()
    }

    function setPointerSensitivity(preset) {
        Quickshell.execDetached([root.pointerCommand, "set", preset])
    }

    function scheduleGlobalSearch() {
        if (root.page !== "main" || search.text.trim() === "") {
            root.globalFileResults = []
            root.globalSearchRunning = false
            return
        }
        globalSearchTimer.restart()
    }

    function startGlobalSearch() {
        const query = search.text.trim()
        if (root.page !== "main" || query === "" || globalSearchProcess.running)
            return
        root.activeSearchQuery = query
        root.globalSearchRunning = true
        globalSearchProcess.command = [root.menuCommand, "search", query]
        globalSearchProcess.running = true
    }

    function matchScore(value, query) {
        const normalized = String(value).toLowerCase()
        if (normalized === query)
            return 0
        if (normalized.startsWith(query))
            return 1
        if (normalized.includes(query))
            return 2
        return 99
    }

    function globalResults() {
        const query = search.text.trim().toLowerCase()
        if (query === "")
            return []

        let results = []
        const destinations = [
            { "label": "Monitoring", "detail": "Live CPU, memory, network and sensors", "icon": "󰄧", "page": "monitoring" },
            { "label": "Apps", "detail": "Browse installed applications", "icon": "󰀻", "page": "apps" },
            { "label": "AI / Agents", "detail": "Agents and AI tasks", "icon": "󰚩", "page": "ai" },
            { "label": "Style", "detail": "Desktop themes", "icon": "󰏘", "page": "style" },
            { "label": "Setup", "detail": "Desktop configuration", "icon": "", "page": "setup" },
            { "label": "Install", "detail": "Official Arch packages", "icon": "󰏔", "page": "install" },
            { "label": "System", "detail": "Lock, suspend, restart, and power", "icon": "󰒓", "page": "system" },
            { "label": "Keybindings", "detail": "Keyboard shortcuts", "icon": "󰞋", "page": "keys" }
        ]

        for (const destination of destinations) {
            const score = Math.min(
                root.matchScore(destination.label, query),
                root.matchScore(destination.detail, query)
            )
            if (score < 99)
                results.push({
                    "type": "destination",
                    "label": destination.label,
                    "detail": destination.detail,
                    "icon": destination.icon,
                    "page": destination.page,
                    "score": score
                })
        }

        for (const app of DesktopEntries.applications.values) {
            const score = root.matchScore(app.name, query)
            if (score < 99)
                results.push({
                    "type": "app",
                    "label": app.name,
                    "detail": "Application",
                    "icon": "󰀻",
                    "application": app,
                    "score": score
                })
        }

        for (const item of root.globalFileResults) {
            results.push({
                "type": "path",
                "label": item.name,
                "detail": item.kind + " · " + item.displayPath,
                "icon": item.kind === "Directory" ? "󰉋"
                    : item.kind === "Image" ? "󰋩"
                    : item.kind === "Audio" ? "󰎆"
                    : item.kind === "Video" ? "󰕧" : "󰈙",
                "path": item.path,
                "score": root.matchScore(item.name, query) + 1
            })
        }

        results.sort((left, right) => {
            if (left.score !== right.score)
                return left.score - right.score
            return left.label.localeCompare(right.label)
        })
        return results.slice(0, 40)
    }

    function activateGlobalResult(result) {
        if (result.type === "destination") {
            if (result.page === "monitoring") { root.openMonitor(); return }
            root.page = result.page
            search.text = ""
            return
        }
        if (result.type === "app") {
            Quickshell.execDetached({
                command: result.application.command,
                workingDirectory: result.application.workingDirectory
            })
            root.close()
            return
        }
        if (result.type === "path") {
            Quickshell.execDetached(["xdg-open", result.path])
            root.close()
        }
    }

    function focusedScreen() {
        for (let screen of Quickshell.screens) {
            if (
                Hyprland.monitorFor(screen)
                === Hyprland.focusedMonitor
            )
                return screen
        }

        return Quickshell.screens[0]
    }

    function open(pageName) {
        page = pageName

        menuWindow.screen = focusedScreen()
        menuWindow.opened = true

        search.text = ""
        search.forceActiveFocus()
    }

    function close() {
        menuWindow.opened = false
        page = "main"
        search.text = ""
        globalFileResults = []
    }

    onPageChanged: {
        if (page !== "main") {
            globalSearchTimer.stop()
            globalFileResults = []
            globalSearchRunning = false
        }
    }

    Timer {
        id: globalSearchTimer
        interval: 180
        repeat: false
        onTriggered: root.startGlobalSearch()
    }

    Process {
        id: globalSearchProcess

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(text)
                    if (
                        parsed
                        && parsed.schemaVersion === 1
                        && parsed.query === root.activeSearchQuery
                        && search.text.trim() === root.activeSearchQuery
                    )
                        root.globalFileResults = parsed.results || []
                } catch (error) {
                    console.warn("Main Menu global search failed:", error)
                }
            }
        }

        onRunningChanged: {
            if (running)
                return
            root.globalSearchRunning = false
            if (
                root.page === "main"
                && search.text.trim() !== ""
                && search.text.trim() !== root.activeSearchQuery
            )
                globalSearchTimer.restart()
        }
    }


    IpcHandler {
        target: "menu"

        function toggle(): void {
            if (menuWindow.visible)
                root.close()
            else
                root.open("main")
        }

        function apps(): void {
            root.open("apps")
        }

        function system(): void {
            root.open("system")
        }

        function setup(): void {
            root.open("setup")
        }

        function install(): void {
            root.open("install")
        }

        function monitoring(): void { root.openMonitor() }

        function keybindings(): void {
            root.open("keys")
        }
    }


    TemporaryPanel {
        id: menuWindow
        panelName: "menu"
        onDismissed: root.close()
        implicitWidth: 520
        implicitHeight: root.page === "main" ? 500 : root.page === "style" ? 680 : 620
        color: "transparent"


        Rectangle {
            anchors.centerIn: parent

            width: 520

            height:
                root.page === "main"
                ? 500
                : root.page === "style" ? 680 : 620

            color: QuattroTheme.Theme.background

            border.width: 1
            border.color: QuattroTheme.Theme.border

            radius: QuattroTheme.Theme.cornerRadius


            MouseArea {
                anchors.fill: parent
            }


            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16

                spacing: 6


                // ============================
                // SEARCH
                // ============================

                Rectangle {
                    Layout.fillWidth: true

                    implicitHeight: 46

                    radius: QuattroTheme.Theme.cornerRadius

                    color: QuattroTheme.Theme.surfaceRaised


                    TextInput {
                        id: search

                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14

                        verticalAlignment:
                            TextInput.AlignVCenter

                        color: QuattroTheme.Theme.textStrong

                        font.family: QuattroTheme.Theme.fontFamily

                        font.pixelSize: 14

                        onTextChanged: root.scheduleGlobalSearch()


                        Text {
                            visible:
                                search.text.length === 0

                            anchors.verticalCenter:
                                parent.verticalCenter

                            text:
                                root.page === "keys"
                                ? "Search keybindings..."
                                : root.page === "install"
                                ? "Search official packages..."
                                : root.page === "apps"
                                ? "Search applications..."
                                : root.page === "main"
                                ? "Search apps, files, folders, images..."
                                : "Search..."

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"
                        }


                        Keys.onEscapePressed: root.close()
                    }
                }


                // ============================
                // MAIN MENU
                // ============================

                ColumnLayout {
                    visible: root.page === "main" && search.text.trim() === ""

                    Layout.fillWidth: true

                    MenuRow {
                        icon: "󰀻"
                        label: "Apps"
                        arrow: true

                        onClicked:
                            root.page = "apps"
                    }

                    MenuRow {
                        icon: "󰚩"
                        label: "AI / Agents"
                        arrow: true

                        onClicked:
                            root.page = "ai"
                    }

                    MenuRow {
                        icon: "󰔚"
                        label: "Monitoring"
                        onClicked: root.openMonitor()
                    }

                    MenuRow {
                        icon: "󰏘"
                        label: "Style"
                        arrow: true

                        onClicked:
                            root.page = "style"
                    }

                    MenuRow {
                        icon: ""
                        label: "Setup"
                        arrow: true

                        onClicked:
                            root.page = "setup"
                    }

                    MenuRow {
                        icon: "󰏔"
                        label: "Install"
                        arrow: true

                        onClicked:
                            root.page = "install"
                    }

                    MenuRow {
                        icon: "󰒓"
                        label: "System"
                        arrow: true

                        onClicked:
                            root.page = "system"
                    }

                    MenuRow {
                        icon: "󰞋"
                        label: "Keybindings"

                        onClicked:
                            root.page = "keys"
                    }
                }


                // ============================
                // GLOBAL SEARCH
                // ============================

                ListView {
                    visible: root.page === "main" && search.text.trim() !== ""

                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    model: ScriptModel {
                        values: root.globalResults()
                    }

                    delegate: Rectangle {
                        required property var modelData

                        width: ListView.view.width
                        height: 58
                        radius: QuattroTheme.Theme.cornerRadius
                        color: globalResultMouse.containsMouse
                            ? QuattroTheme.Theme.hover
                            : "transparent"

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 12

                            AppIcon {
                                visible: modelData.type === "app"
                                desktopEntry: modelData.application || null
                            }
                            Text {
                                visible: modelData.type !== "app"
                                text: modelData.icon
                                color: QuattroTheme.Theme.accent
                                font.family: QuattroTheme.Theme.iconFontFamily
                                font.pixelSize: 16
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: modelData.label
                                    color: QuattroTheme.Theme.textStrong
                                    font.family: QuattroTheme.Theme.fontFamily
                                    font.pixelSize: 13
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }

                                Text {
                                    text: modelData.detail
                                    color: QuattroTheme.Theme.textMuted
                                    font.family: QuattroTheme.Theme.fontFamily
                                    font.pixelSize: 10
                                    elide: Text.ElideMiddle
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        MouseArea {
                            id: globalResultMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.activateGlobalResult(parent.modelData)
                        }
                    }

                    footer: Text {
                        visible: root.globalSearchRunning
                        width: ListView.view ? ListView.view.width : 0
                        height: 38
                        text: "Searching files and folders…"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: QuattroTheme.Theme.textMuted
                        font.family: QuattroTheme.Theme.fontFamily
                        font.pixelSize: 10
                    }
                }


                // ============================
                // AI / AGENTS
                // ============================

                ColumnLayout {
                    visible: root.page === "ai"

                    Layout.fillWidth: true

                    MenuRow {
                        icon: "󰚩"
                        label: "Agents"

                        onClicked: {
                            Quickshell.execDetached(["qs", "ipc", "call", "agents", "open"])
                            root.close()
                        }
                    }

                    MenuRow {
                        icon: "󰆍"
                        label: "New AI Task"

                        onClicked: {
                            Quickshell.execDetached(["qs", "ipc", "call", "agents", "newTask"])
                            root.close()
                        }
                    }

                    MenuRow {
                        icon: "󰚩"
                        label: "Codex"

                        onClicked: {
                            Quickshell.execDetached([root.agentCommand, "launch", "codex"])
                            root.close()
                        }
                    }

                    MenuRow {
                        icon: "󰚩"
                        label: "OMP"

                        onClicked: {
                            Quickshell.execDetached([root.projectsOMPCommand, "--choose-project"])
                            root.close()
                        }
                    }

                    MenuRow {
                        icon: "󰭹"
                        label: "ChatGPT"

                        onClicked: {
                            Quickshell.execDetached([root.agentCommand, "chatgpt"])
                            root.close()
                        }
                    }

                    MenuRow {
                        icon: "󰠮"
                        label: "Memory Vault"

                        onClicked: {
                            Quickshell.execDetached([root.agentCommand, "memory", "open"])
                            root.close()
                        }
                    }
                }


                // ============================
                // STYLE / THEMES
                // ============================

                ColumnLayout {
                    visible: root.page === "style"

                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: QuattroTheme.Theme.availableThemes

                        delegate: Rectangle {
                            id: themeRow

                            required property var modelData

                            Layout.fillWidth: true
                            implicitHeight: 62
                            radius: QuattroTheme.Theme.cornerRadius
                            color: themeMouse.containsMouse
                                ? QuattroTheme.Theme.hover
                                : "transparent"
                            activeFocusOnTab: true
                            Accessible.role: Accessible.Button
                            Accessible.name: modelData.label
                            Keys.onReturnPressed: root.setTheme(modelData.id)
                            Keys.onSpacePressed: root.setTheme(modelData.id)
                            border.width: activeFocus ? 2 : QuattroTheme.Theme.current === modelData.id ? 1 : 0
                            border.color: QuattroTheme.Theme.accent

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: 12

                                Rectangle {
                                    implicitWidth: 22
                                    implicitHeight: 22
                                    radius: QuattroTheme.Theme.cornerRadius
                                    color: QuattroTheme.Theme.instrumentPalettes[modelData.id] ? QuattroTheme.Theme.instrumentPalettes[modelData.id].textStrong : modelData.id === "cyberpunk-2077" ? "#fcee09"
                                        : modelData.id === "terminal" ? "#88a98f"
                                        : modelData.id === "graphite" ? "#aeb5c0" : "#b9ae91"
                                    border.width: 5
                                    border.color: QuattroTheme.Theme.instrumentPalettes[modelData.id] ? QuattroTheme.Theme.instrumentPalettes[modelData.id].background : modelData.id === "cyberpunk-2077" ? "#00f0ff"
                                        : modelData.id === "terminal" ? "#0d1711"
                                        : modelData.id === "graphite" ? "#181a1d" : "#111317"
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Text {
                                        text: modelData.label
                                        color: QuattroTheme.Theme.textStrong
                                        font.family: QuattroTheme.Theme.fontFamily
                                        font.pixelSize: 14
                                    }

                                    Text {
                                        text: modelData.detail
                                        color: QuattroTheme.Theme.textMuted
                                        font.family: QuattroTheme.Theme.fontFamily
                                        font.pixelSize: 11
                                    }
                                }

                                Text {
                                    text: QuattroTheme.Theme.current === modelData.id ? "ACTIVE" : ""
                                    color: QuattroTheme.Theme.accent
                                    font.family: QuattroTheme.Theme.fontFamily
                                    font.pixelSize: 10
                                    font.bold: true
                                }
                            }

                            MouseArea {
                                id: themeMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.setTheme(themeRow.modelData.id)
                            }
                        }
                    }

                    Text {
                        text: "SUPER + SHIFT + CTRL + T  cycles themes"
                        color: QuattroTheme.Theme.textDim
                        font.family: QuattroTheme.Theme.fontFamily
                        font.pixelSize: 10
                        Layout.leftMargin: 10
                        Layout.topMargin: 10
                    }
                }


                // ============================
                // APPLICATIONS
                // ============================

                ListView {
                    visible: root.page === "apps"

                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    clip: true

                    model: ScriptModel {
                        values: {
                            let q =
                                search.text
                                .toLowerCase()

                            return DesktopEntries
                                .applications
                                .values
                                .filter(app =>
                                    q === "" ||
                                    app.name
                                    .toLowerCase()
                                    .includes(q)
                                )
                        }
                    }

                    delegate: Rectangle {
                        id: installedAppRow
                        required property var modelData
                        required property int index
                        onActiveFocusChanged: if (activeFocus)
                            ListView.view.positionViewAtIndex(index, ListView.Contain)
                        width: ListView.view.width
                        height: 42
                        activeFocusOnTab: true
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.name
                        Accessible.onPressAction: launch()
                        function launch() {
                            Quickshell.execDetached({
                                command: modelData.command,
                                workingDirectory: modelData.workingDirectory
                            })
                            root.close()
                        }
                        Keys.onReturnPressed: launch()
                        Keys.onEnterPressed: launch()
                        Keys.onSpacePressed: launch()
                        Keys.onEscapePressed: root.close()
                        border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
                        border.color: QuattroTheme.Theme.textStrong
                        color: appMouse.containsMouse ? QuattroTheme.Theme.hover : "transparent"
                        radius: QuattroTheme.Theme.cornerRadius
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 12
                            AppIcon { desktopEntry: installedAppRow.modelData }
                            Text {
                                Layout.fillWidth: true
                                text: installedAppRow.modelData.name
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: QuattroTheme.Theme.textStrong
                                font.family: QuattroTheme.Theme.fontFamily
                            }
                        }
                        MouseArea {
                            id: appMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                installedAppRow.forceActiveFocus(Qt.MouseFocusReason)
                                installedAppRow.launch()
                            }
                        }
                    }
                }


                // ============================
                // SETUP
                // ============================

                ColumnLayout {
                    visible: root.page === "setup"

                    Layout.fillWidth: true

                    MenuRow {
                        icon: "󰍹"
                        label: "Displays"
                        detail: "Layout, scale, and orientation"
                        onClicked: root.openPanel("display")
                    }

                    MenuRow {
                        icon: "󰕾"
                        label: "Audio"
                        detail: "Output, input, and volume"
                        onClicked: root.openPanel("audio")
                    }

                    MenuRow {
                        icon: "󰤨"
                        label: "Network"
                        detail: "Wi-Fi and wired connections"
                        onClicked: root.openPanel("network")
                    }

                    MenuRow {
                        icon: "󰂯"
                        label: "Bluetooth"
                        detail: "Discover and manage devices"
                        onClicked: root.openPanel("bluetooth")
                    }

                    MenuRow {
                        icon: "󰍽"
                        label: "Mouse Sensitivity"
                        detail: "Lower or restore pointer speed"
                        arrow: true
                        onClicked: root.page = "pointer"
                    }

                    MenuRow {
                        icon: "󰖲"
                        label: "Hyprland"
                        detail: "Edit compositor settings; reload on exit"
                        onClicked: root.editConfig("hyprland", "Hyprland")
                    }

                    MenuRow {
                        icon: "󰌌"
                        label: "Keybindings Config"
                        detail: "Edit shortcuts; reload on exit"
                        onClicked: root.editConfig("bindings", "Keybindings")
                    }

                    MenuRow {
                        icon: "󰚩"
                        label: "AI Preferences"
                        detail: "Edit display-safe agent configuration"
                        onClicked: root.editConfig("ai", "AI Preferences")
                    }

                    MenuRow {
                        icon: "󰉋"
                        label: "Quickshell Files"
                        detail: "Open the shell configuration folder"
                        onClicked: {
                            Quickshell.execDetached([
                                "xdg-open",
                                (Quickshell.env("XDG_CONFIG_HOME") ||
                                    (Quickshell.env("HOME") + "/.config")) + "/quickshell"
                            ])
                            root.close()
                        }
                    }
                }


                // ============================
                // POINTER
                // ============================

                ColumnLayout {
                    visible: root.page === "pointer"

                    Layout.fillWidth: true

                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 10
                        Layout.rightMargin: 10
                        Layout.bottomMargin: 8
                        text: "Software pointer sensitivity · applies immediately"
                        color: QuattroTheme.Theme.textMuted
                        font.family: QuattroTheme.Theme.fontFamily
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                    }

                    MenuRow {
                        icon: "󰾅"
                        label: "Very Low"
                        detail: "-0.80 · slowest"
                        onClicked: root.setPointerSensitivity("very-low")
                    }

                    MenuRow {
                        icon: "󰾅"
                        label: "Low"
                        detail: "-0.50 · recommended"
                        onClicked: root.setPointerSensitivity("low")
                    }

                    MenuRow {
                        icon: "󰾅"
                        label: "Reduced"
                        detail: "-0.25 · slightly slower"
                        onClicked: root.setPointerSensitivity("reduced")
                    }

                    MenuRow {
                        icon: "󰍽"
                        label: "Normal"
                        detail: "0.00 · Hyprland default"
                        onClicked: root.setPointerSensitivity("normal")
                    }

                    MenuRow {
                        icon: "󰁍"
                        label: "Back to Setup"
                        onClicked: root.page = "setup"
                    }
                }


                // ============================
                // INSTALL
                // ============================

                ColumnLayout {
                    visible: root.page === "install"

                    Layout.fillWidth: true

                    MenuRow {
                        icon: "󰞷"
                        label: "Package by Name"
                        detail: "Official repositories · terminal confirmation"
                        onClicked: root.installPackage("custom", "Package")
                    }

                    Repeater {
                        model: root.installPackages.filter(item => {
                            const query = search.text.toLowerCase()
                            return query === ""
                                || item.label.toLowerCase().includes(query)
                                || item.detail.toLowerCase().includes(query)
                        })

                        delegate: MenuRow {
                            required property var modelData

                            icon: modelData.icon
                            label: modelData.label
                            detail: modelData.detail + " · official repository"
                            onClicked: root.installPackage(modelData.id, modelData.label)
                        }
                    }
                }


                // ============================
                // SYSTEM
                // ============================

                ColumnLayout {
                    visible:
                        root.page === "system"

                    Layout.fillWidth: true

                    MenuRow {
                        icon: ""
                        label: "Lock"
                        detail: "Unlock with your account password · same password used by sudo"

                        onClicked: {
                            Quickshell.execDetached([root.sessionCommand, "lock"])

                            root.close()
                        }
                    }

                    MenuRow {
                        icon: "󰤄"
                        label: "Suspend"

                        onClicked:
                            Quickshell.execDetached([
                                "systemctl",
                                "suspend"
                            ])
                    }

                    MenuRow {
                        icon: "󰜉"
                        label: "Restart"

                        onClicked:
                            Quickshell.execDetached([
                                "systemctl",
                                "reboot"
                            ])
                    }

                    MenuRow {
                        icon: ""
                        label: "Shutdown"

                        onClicked:
                            Quickshell.execDetached([
                                "systemctl",
                                "poweroff"
                            ])
                    }

                    MenuRow {
                        icon: "󰍃"
                        label: "Logout"

                        onClicked:
                            Quickshell.execDetached([
                                "hyprctl",
                                "dispatch",
                                "exit"
                            ])
                    }
                }


                // ============================
                // KEYBINDINGS
                // ============================

                ColumnLayout {
                    visible:
                        root.page === "keys"

                    Layout.fillWidth: true

                    spacing: 9

                    KeyRow {
                        keys: "SUPER + SPACE"
                        action: "Quattro menu"
                    }

                    KeyRow {
                        keys: "SUPER + ALT + SPACE"
                        action: "Applications"
                    }

                    KeyRow {
                        keys: "SUPER + K"
                        action: "Keybindings"
                    }

                    KeyRow {
                        keys: "SUPER + ESC"
                        action: "System"
                    }

                    KeyRow {
                        keys: "SUPER + CTRL + M"
                        action: "Monitoring"
                    }

                    KeyRow {
                        keys: "SUPER + RETURN"
                        action: "Terminal"
                    }

                    KeyRow {
                        keys: "SUPER + SHIFT + CTRL + A"
                        action: "Agents panel"
                    }

                    KeyRow {
                        keys: "SUPER + SHIFT + CTRL + SPACE"
                        action: "New AI task"
                    }

                    KeyRow {
                        keys: "SUPER + CTRL + G"
                        action: "ChatGPT"
                    }

                    KeyRow {
                        keys: "SUPER + CTRL + X"
                        action: "Dictation"
                    }

                    KeyRow {
                        keys: "SUPER + SHIFT + CTRL + T"
                        action: "Cycle dark theme"
                    }

                    KeyRow {
                        keys: "SUPER + W"
                        action: "Close window"
                    }

                    KeyRow {
                        keys: "SUPER + T"
                        action: "Toggle floating"
                    }

                    KeyRow {
                        keys: "SUPER + J"
                        action: "Toggle split"
                    }

                    KeyRow {
                        keys: "SUPER + F"
                        action: "Fullscreen"
                    }

                    KeyRow {
                        keys: "SUPER + 1..0"
                        action: "Workspace"
                    }

                    KeyRow {
                        keys: "SUPER + SHIFT + 1..0"
                        action: "Move window"
                    }
                }
            }
        }
    }


    component MenuRow: Rectangle {
        id: row

        required property string icon
        required property string label

        property bool arrow: false
        property string detail: ""

        signal clicked()

        Layout.fillWidth: true
        implicitHeight: row.detail === "" ? 46 : 58

        radius: QuattroTheme.Theme.cornerRadius

        color: rowMouse.containsMouse
            ? QuattroTheme.Theme.hover
            : "transparent"


        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: row.label
        Accessible.description: row.detail
        Accessible.onPressAction: row.clicked()
        border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
        border.color: QuattroTheme.Theme.textStrong
        Keys.onReturnPressed: row.clicked()
        Keys.onEnterPressed: row.clicked()
        Keys.onSpacePressed: row.clicked()

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: row.arrow ? 32 : 12
            spacing: 12
            Text {
                text: row.icon
                color: QuattroTheme.Theme.text
                font.family: QuattroTheme.Theme.iconFontFamily
                font.pixelSize: 16
                Layout.preferredWidth: 20
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: row.label
                    color: QuattroTheme.Theme.textStrong
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: 14
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Text {
                    visible: row.detail !== ""
                    text: row.detail
                    color: QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: 11
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        Text {
            visible: row.arrow

            anchors {
                right: parent.right
                rightMargin: 12
                verticalCenter:
                    parent.verticalCenter
            }

            text: "›"

            color: QuattroTheme.Theme.textMuted
        }


        MouseArea {
            id: rowMouse

            anchors.fill: parent
            hoverEnabled: true

            cursorShape: Qt.PointingHandCursor
            onClicked: { row.forceActiveFocus(Qt.MouseFocusReason); row.clicked() }
        }
    }


    component KeyRow: RowLayout {
        required property string keys
        required property string action

        Layout.fillWidth: true

        Text {
            text: keys

            color: QuattroTheme.Theme.textStrong

            font.family:
                "JetBrainsMono Nerd Font"

            Layout.preferredWidth: 210
        }

        Text {
            text: action

            color: QuattroTheme.Theme.textMuted

            font.family:
                "JetBrainsMono Nerd Font"
        }
    }
}
