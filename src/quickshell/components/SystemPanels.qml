import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Services.Pipewire
import QtQuick
import QtQuick.Layouts
import "../theme" as QuattroTheme

import "panels"

Scope {
    id: root

    property string page: ""
    property string nightLightCommand: Quickshell.env("HOME") + "/.local/bin/quattro-night-light"
    property string sessionCommand: Quickshell.env("HOME") + "/.local/bin/quattro-session"
    property string nightLightPreset: "off"
    property bool nightLightBusy: false
    property string nightLightMessage: ""
    property var nightLightOptions: [
        { "id": "off", "label": "Off", "temperature": 6500 },
        { "id": "soft", "label": "Soft", "temperature": 5000 },
        { "id": "warm", "label": "Warm", "temperature": 4200 },
        { "id": "deep", "label": "Deep", "temperature": 3400 }
    ]

    function consumeNightLight(text) {
        try {
            const parsed = JSON.parse(text.trim())
            if (parsed.schemaVersion !== 1)
                return
            root.nightLightPreset = parsed.preset
            root.nightLightMessage = parsed.active
                ? parsed.label + " · " + parsed.temperature + " K"
                : "Neutral output · filter off"
        } catch (error) {
            root.nightLightMessage = "Night-light status unavailable"
        }
    }

    function setNightLight(preset) {
        if (root.nightLightBusy || !root.nightLightOptions.some(option => option.id === preset))
            return
        root.nightLightBusy = true
        nightLightSetProcess.command = [root.nightLightCommand, "set", preset]
        nightLightSetProcess.running = true
    }

    Component.onCompleted: nightLightApplyProcess.running = true

    Process {
        id: nightLightApplyProcess
        command: [root.nightLightCommand, "apply"]
        stdout: StdioCollector {
            onStreamFinished: root.consumeNightLight(text)
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0)
                root.nightLightMessage = "Night-light apply failed"
        }
    }

    Process {
        id: nightLightSetProcess
        stdout: StdioCollector {
            onStreamFinished: root.consumeNightLight(text)
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0)
                root.nightLightMessage = "Night-light change failed"
            nightLightCooldown.restart()
        }
    }

    Timer {
        id: nightLightCooldown
        interval: 900
        repeat: false
        onTriggered: root.nightLightBusy = false
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

    function openPage(name) {
        root.closeClock()

        root.page = name

        popupHost.screen = focusedScreen()
        popupHost.visible = true

        if (name === "network")
            networkPanel.refreshNetwork()

        if (name === "bluetooth")
            bluetoothPanel.refreshBluetooth()

        Qt.callLater(() => {
            keyScope.forceActiveFocus()
        })
    }

    function close() {
        popupHost.visible = false
        root.page = ""

        networkPanel.resetTransientState()
        bluetoothPanel.resetTransientState()
    }

    // ========================================================
    // CLOCK
    // ========================================================

    function openClock() {
        root.close()

        // Always start from today/current month.
        clockPanel.resetToToday()

        clockHost.screen = focusedScreen()
        clockHost.visible = true

        Qt.callLater(() => {
            clockKeyScope.forceActiveFocus()
        })
    }

    function closeClock() {
        // Reset first so any scroll/month navigation state is discarded.
        clockPanel.resetToToday()

        clockHost.visible = false
    }

    function toggleClock() {
        if (clockHost.visible)
            root.closeClock()
        else
            root.openClock()
    }

    // ========================================================
    // IPC
    // ========================================================

    IpcHandler {
        target: "panel"

        function audio(): void {
            root.openPage("audio")
        }

        function bluetooth(): void {
            root.openPage("bluetooth")
        }

        function network(): void {
            root.openPage("network")
        }

        function display(): void {
            root.openPage("display")
        }

        function power(): void {
            root.openPage("power")
        }

        function clock(): void {
            root.toggleClock()
        }

        function close(): void {
            root.close()
            root.closeClock()
        }
    }

    // ========================================================
    // RIGHT-SIDE SYSTEM PANEL HOST
    // ========================================================

    PanelWindow {
        id: popupHost

        visible: false
        color: "transparent"

        anchors {
            top: true
            right: true
        }

        margins {
            top: 32
            right: 8
        }

        implicitWidth: 1
        implicitHeight: 1

        exclusionMode:
            ExclusionMode.Ignore

        PopupWindow {
            id: popup

            visible:
                popupHost.visible

            color: "transparent"

            anchor.window:
                popupHost

            anchor.rect.x:
                root.page === "bluetooth"
                ? -560
                : root.page === "network"
                ? -529
                : root.page === "audio"
                ? -498
                : root.page === "display"
                ? -467
                : -436

            anchor.rect.y: 6

            width: 430

            height:
                root.page === "network"
                ? 620
                : 520

            grabFocus: true

            onVisibleChanged: {
                if (!visible && popupHost.visible)
                    root.close()
            }

            FocusScope {
                id: keyScope

                anchors.fill: parent

                focus:
                    popup.visible

                Keys.onEscapePressed: {
                    if (
                        root.page === "network"
                        && networkPanel.handleEscape()
                    ) {
                        keyScope.forceActiveFocus()
                        return
                    }

                    if (
                        root.page === "bluetooth"
                        && bluetoothPanel.handleEscape()
                    ) {
                        keyScope.forceActiveFocus()
                        return
                    }

                    root.close()
                }
            }

            Rectangle {
                anchors.fill: parent

                radius: QuattroTheme.Theme.cornerRadius

                color: QuattroTheme.Theme.background

                border.width: 1
                border.color: QuattroTheme.Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16

                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text:
                                root.page === "audio"
                                ? "Audio"
                                : root.page === "bluetooth"
                                ? "Bluetooth"
                                : root.page === "network"
                                ? "Network"
                                : root.page === "display"
                                ? "Display"
                                : root.page === "power"
                                ? "Power"
                                : ""

                            color: QuattroTheme.Theme.textStrong

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 17
                            font.bold: true

                            Layout.fillWidth: true
                        }

                        Text {
                            text: "Esc"

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 10
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1

                        color: QuattroTheme.Theme.border
                    }

                    AudioPanel {
                        id: audioPanel

                        visible:
                            root.page === "audio"

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        onRequestFocus: {
                            keyScope.forceActiveFocus()
                        }
                    }

                    BluetoothPanel {
                        id: bluetoothPanel

                        visible:
                            root.page === "bluetooth"

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        onRequestFocus: {
                            keyScope.forceActiveFocus()
                        }
                    }

                    NetworkPanel {
                        id: networkPanel

                        visible:
                            root.page === "network"

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        onRequestFocus: {
                            keyScope.forceActiveFocus()
                        }
                    }

                    ColumnLayout {
                        visible:
                            root.page === "display"

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        spacing: 10

                        Text {
                            text:
                                "󰍹  Native output"

                            color: QuattroTheme.Theme.text

                            font.family:
                                "JetBrainsMono Nerd Font"
                        }

                        Text {
                            text:
                                "DP-2 and HDMI-A-1 · 1920×1080 · scale 1.0"

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            Layout.fillWidth: true

                            wrapMode:
                                Text.Wrap
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 1
                            color: QuattroTheme.Theme.border
                        }

                        RowLayout {
                            Layout.fillWidth: true

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: "󰖔  Night light"
                                    color: QuattroTheme.Theme.textStrong
                                    font.family: "JetBrainsMono Nerd Font"
                                    font.pixelSize: 13
                                    font.bold: true
                                }

                                Text {
                                    text: root.nightLightMessage || "Loading output state…"
                                    color: root.nightLightPreset === "off"
                                        ? QuattroTheme.Theme.textMuted
                                        : QuattroTheme.Theme.accent
                                    font.family: "JetBrainsMono Nerd Font"
                                    font.pixelSize: 10
                                }
                            }

                            Text {
                                text: root.nightLightBusy ? "SETTLING" : "OUTPUT FILTER"
                                color: root.nightLightBusy
                                    ? QuattroTheme.Theme.warning
                                    : QuattroTheme.Theme.textDim
                                font.family: "JetBrainsMono Nerd Font"
                                font.pixelSize: 9
                                font.letterSpacing: 1
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Repeater {
                                model: root.nightLightOptions

                                delegate: Rectangle {
                                    id: nightLightButton
                                    required property var modelData
                                    Layout.fillWidth: true
                                    implicitHeight: 54
                                    color: root.nightLightPreset === modelData.id
                                        ? QuattroTheme.Theme.accentMuted
                                        : nightLightMouse.containsMouse
                                        ? QuattroTheme.Theme.hover
                                        : QuattroTheme.Theme.surface
                                    border.width: 1
                                    border.color: root.nightLightPreset === modelData.id
                                        ? QuattroTheme.Theme.accent
                                        : QuattroTheme.Theme.border

                                    Column {
                                        anchors.centerIn: parent
                                        spacing: 2

                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: nightLightButton.modelData.label
                                            color: root.nightLightPreset === nightLightButton.modelData.id
                                                ? QuattroTheme.Theme.textStrong
                                                : QuattroTheme.Theme.text
                                            font.family: "JetBrainsMono Nerd Font"
                                            font.pixelSize: 10
                                            font.bold: true
                                        }

                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: nightLightButton.modelData.temperature + " K"
                                            color: QuattroTheme.Theme.textMuted
                                            font.family: "JetBrainsMono Nerd Font"
                                            font.pixelSize: 8
                                        }
                                    }

                                    MouseArea {
                                        id: nightLightMouse
                                        anchors.fill: parent
                                        enabled: !root.nightLightBusy
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.setNightLight(nightLightButton.modelData.id)
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            implicitHeight: 70
                            color: QuattroTheme.Theme.surface
                            border.width: 1
                            border.color: QuattroTheme.Theme.border

                            Column {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 4

                                Text {
                                    text: "SHARP OUTPUT"
                                    color: QuattroTheme.Theme.accent
                                    font.family: "JetBrainsMono Nerd Font"
                                    font.pixelSize: 9
                                    font.letterSpacing: 1
                                    font.bold: true
                                }

                                Text {
                                    width: parent.width
                                    text: "Compositor blur is disabled. Night light is applied after capture, so screenshots remain neutral even while the display is warm."
                                    color: QuattroTheme.Theme.textMuted
                                    font.family: "JetBrainsMono Nerd Font"
                                    font.pixelSize: 9
                                    wrapMode: Text.Wrap
                                }
                            }
                        }

                        Item {
                            Layout.fillHeight: true
                        }
                    }

                    ColumnLayout {
                        visible:
                            root.page === "power"

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        spacing: 7

                        Text {
                            Layout.fillWidth: true
                            text: "Unlock with your account password · the same password used by sudo"
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 9
                            wrapMode: Text.Wrap
                            Layout.bottomMargin: 3
                        }

                        PanelButton {
                            label:
                                "  Lock"

                            onClicked: {
                                Quickshell.execDetached([root.sessionCommand, "lock"])

                                root.close()
                            }
                        }

                        PanelButton {
                            label:
                                "󰤄  Suspend"

                            onClicked: {
                                Quickshell.execDetached([
                                    "systemctl",
                                    "suspend"
                                ])

                                root.close()
                            }
                        }

                        PanelButton {
                            label:
                                "󰜉  Restart"

                            onClicked: {
                                Quickshell.execDetached([
                                    "systemctl",
                                    "reboot"
                                ])
                            }
                        }

                        PanelButton {
                            label:
                                "  Shutdown"

                            onClicked: {
                                Quickshell.execDetached([
                                    "systemctl",
                                    "poweroff"
                                ])
                            }
                        }

                        PanelButton {
                            label:
                                "󰍃  Logout"

                            onClicked: {
                                Quickshell.execDetached([
                                    "hyprctl",
                                    "dispatch",
                                    "exit"
                                ])
                            }
                        }

                        Item {
                            Layout.fillHeight: true
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: 1

                        color: QuattroTheme.Theme.border
                    }

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text:
                                "Esc  Close"

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 9
                        }

                        Item {
                            Layout.fillWidth: true
                        }

                        Text {
                            text:
                                root.page === "audio"
                                ? "Super+Ctrl+A"
                                : root.page === "bluetooth"
                                ? "Super+Ctrl+B"
                                : root.page === "network"
                                ? "Super+Ctrl+W"
                                : root.page === "display"
                                ? "Super+Ctrl+D"
                                : root.page === "power"
                                ? "Super+Ctrl+P"
                                : ""

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 9
                        }
                    }
                }
            }
        }
    }

    // ========================================================
    // CLOCK / CALENDAR POPUP
    // ========================================================

    PanelWindow {
        id: clockHost

        visible: false
        color: "transparent"

        anchors {
            top: true
            left: true
            right: true
        }

        margins {
            top: 32
        }

        implicitHeight: 1

        exclusionMode:
            ExclusionMode.Ignore

        onVisibleChanged: {
            // This catches all close paths at the host level too.
            if (!visible) {
                clockPanel.resetToToday()
            }
        }

        PopupWindow {
            id: clockPopup

            visible:
                clockHost.visible

            color: "transparent"

            anchor.window:
                clockHost

            anchor.rect.x:
                Math.round(
                    (
                        clockHost.width
                        - clockPopup.width
                    )
                    / 2
                )

            anchor.rect.y: 6

            width: 430
            height: 560

            grabFocus: true

            onVisibleChanged: {
                if (!visible) {
                    clockPanel.resetToToday()

                    if (clockHost.visible) {
                        clockHost.visible = false
                    }
                }
            }

            FocusScope {
                id: clockKeyScope

                anchors.fill: parent

                focus:
                    clockPopup.visible

                Keys.onEscapePressed: {
                    root.closeClock()
                }
            }

            Rectangle {
                anchors.fill: parent

                radius: QuattroTheme.Theme.cornerRadius

                color: QuattroTheme.Theme.background

                border.width: 1
                border.color: QuattroTheme.Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16

                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text: "Calendar"

                            color: QuattroTheme.Theme.textStrong

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 17
                            font.bold: true

                            Layout.fillWidth: true
                        }

                        Text {
                            text: "Esc"

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 10
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true

                        implicitHeight: 1

                        color: QuattroTheme.Theme.border
                    }

                    ClockPanel {
                        id: clockPanel

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        onRequestFocus: {
                            clockKeyScope.forceActiveFocus()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true

                        implicitHeight: 1

                        color: QuattroTheme.Theme.border
                    }

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            text:
                                "Esc  Close"

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 9
                        }

                        Item {
                            Layout.fillWidth: true
                        }

                        Text {
                            text:
                                "Super+Ctrl+Alt+D"

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 9
                        }
                    }
                }
            }
        }
    }

    component PanelButton: Rectangle {
        id: button

        required property string label

        signal clicked()

        Layout.fillWidth: true
        implicitHeight: 42

        radius: QuattroTheme.Theme.cornerRadius

        color:
            buttonMouse.containsMouse
            ? QuattroTheme.Theme.border
            : QuattroTheme.Theme.surface

        Text {
            anchors {
                left: parent.left
                right: parent.right

                leftMargin: 12
                rightMargin: 12

                verticalCenter:
                    parent.verticalCenter
            }

            text:
                button.label

            color: QuattroTheme.Theme.textStrong

            font.family:
                "JetBrainsMono Nerd Font"

            font.pixelSize: 12

            wrapMode:
                Text.Wrap
        }

        MouseArea {
            id: buttonMouse

            anchors.fill: parent

            hoverEnabled: true

            cursorShape:
                Qt.PointingHandCursor

            onClicked: {
                button.clicked()
            }
        }
    }
}
