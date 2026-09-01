import Quickshell
import Quickshell.Io
import QtQuick
import QtQuick.Layouts
import "../../theme" as QuattroTheme

import "../shared"

ColumnLayout {
    id: root

    signal requestFocus()

    property var wifiNetworks: []
    property string ethernetStatus: "Checking..."
    property string wifiStatus: "Checking..."
    property bool wifiEnabled: true

    property bool passwordPrompt: false
    property bool showPassword: false
    property string passwordMode: "connect"
    property string pendingSsid: ""
    property string pendingSecurity: ""
    property string wifiPassword: ""

    property bool qrVisible: false
    property string qrSsid: ""
    property string qrPath: ""

    function resetTransientState() {
        root.passwordPrompt = false
        root.showPassword = false
        root.passwordMode = "connect"
        root.pendingSsid = ""
        root.pendingSecurity = ""
        root.wifiPassword = ""

        root.qrVisible = false
        root.qrSsid = ""
        root.qrPath = ""
    }

    function handleEscape() {
        if (root.qrVisible) {
            root.qrVisible = false
            root.qrPath = ""
            return true
        }

        if (root.passwordPrompt) {
            root.passwordPrompt = false
            root.showPassword = false
            root.wifiPassword = ""
            return true
        }

        return false
    }

    function refreshNetwork() {
        networkStatusProcess.running = false
        wifiScanProcess.running = false
        wifiRadioProcess.running = false

        networkStatusProcess.running = true
        wifiScanProcess.running = true
        wifiRadioProcess.running = true
    }

    function wifiQrEscape(value) {
        return value
            .replace(/\\/g, "\\\\")
            .replace(/;/g, "\\;")
            .replace(/,/g, "\\,")
            .replace(/:/g, "\\:")
            .replace(/"/g, "\\\"")
    }

    function generateWifiQr(ssid, password, security) {
        root.qrSsid = ssid

        const secure =
            security !== "" &&
            !security.toLowerCase().includes("open")

        let payload = ""

        if (secure) {
            payload =
                "WIFI:T:WPA;S:" +
                wifiQrEscape(ssid) +
                ";P:" +
                wifiQrEscape(password) +
                ";;"
        } else {
            payload =
                "WIFI:T:nopass;S:" +
                wifiQrEscape(ssid) +
                ";;"
        }

        root.qrPath =
            "/tmp/quattro-wifi-" +
            Date.now() +
            ".png"

        qrProcess.command = [
            "qrencode",
            "-o",
            root.qrPath,
            "-s",
            "8",
            "-m",
            "2",
            payload
        ]

        qrProcess.running = false
        qrProcess.running = true
    }

    function showPasswordPrompt(ssid, security, mode) {
        root.pendingSsid = ssid
        root.pendingSecurity = security
        root.passwordMode = mode
        root.wifiPassword = ""
        root.showPassword = false
        root.passwordPrompt = true

        Qt.callLater(() => {
            passwordInput.forceActiveFocus()
        })
    }

    function submitPassword() {
        if (root.wifiPassword.length === 0)
            return

        if (root.passwordMode === "qr") {
            root.generateWifiQr(
                root.pendingSsid,
                root.wifiPassword,
                root.pendingSecurity
            )

            root.passwordPrompt = false
            root.showPassword = false
            root.wifiPassword = ""
            return
        }

        wifiConnectProcess.ssid =
            root.pendingSsid

        wifiConnectProcess.password =
            root.wifiPassword

        wifiConnectProcess.running = false
        wifiConnectProcess.running = true
    }

    Process {
        id: networkStatusProcess

        command: [
            "nmcli",
            "-t",
            "-f",
            "DEVICE,TYPE,STATE,CONNECTION",
            "device"
        ]

        stdout: StdioCollector {
            onStreamFinished: {
                const lines = text.trim().split("\n")

                root.ethernetStatus = "Disconnected"
                root.wifiStatus = "Disconnected"

                for (let line of lines) {
                    if (line.trim() === "")
                        continue

                    const parts = line.split(":")

                    if (parts.length < 3)
                        continue

                    const type = parts[1]
                    const state = parts[2]

                    if (type === "ethernet") {
                        root.ethernetStatus =
                            state === "connected"
                            ? "Connected"
                            : state
                    }

                    if (type === "wifi") {
                        root.wifiStatus =
                            state === "connected"
                            ? "Connected"
                            : state
                    }
                }
            }
        }
    }

    Process {
        id: wifiRadioProcess

        command: [
            "nmcli",
            "radio",
            "wifi"
        ]

        stdout: StdioCollector {
            onStreamFinished: {
                root.wifiEnabled =
                    text.trim() === "enabled"
            }
        }
    }

    Process {
        id: wifiScanProcess

        command: [
            "nmcli",
            "-t",
            "-f",
            "IN-USE,SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "--rescan",
            "yes"
        ]

        stdout: StdioCollector {
            onStreamFinished: {
                const result = []
                const seen = {}

                const lines = text.trim().split("\n")

                for (let line of lines) {
                    if (line.trim() === "")
                        continue

                    const parts = line.split(":")

                    if (parts.length < 4)
                        continue

                    const active =
                        parts[0].trim() === "*"

                    const ssid =
                        parts[1].trim()

                    const signal =
                        parseInt(parts[2]) || 0

                    const security =
                        parts
                            .slice(3)
                            .join(":")
                            .trim()

                    if (ssid === "")
                        continue

                    if (seen[ssid])
                        continue

                    seen[ssid] = true

                    result.push({
                        active: active,
                        ssid: ssid,
                        signal: signal,
                        security: security
                    })
                }

                result.sort(
                    (a, b) =>
                        b.signal - a.signal
                )

                root.wifiNetworks = result
            }
        }
    }

    Process {
        id: wifiToggleProcess

        property bool desiredState: true

        command: [
            "nmcli",
            "radio",
            "wifi",
            desiredState ? "on" : "off"
        ]

        onRunningChanged: {
            if (!running)
                refreshDelay.restart()
        }
    }

    Process {
        id: wifiConnectProcess

        property string ssid: ""
        property string password: ""

        command:
            password.length > 0
            ? [
                "nmcli",
                "device",
                "wifi",
                "connect",
                ssid,
                "password",
                password
            ]
            : [
                "nmcli",
                "device",
                "wifi",
                "connect",
                ssid
            ]

        onRunningChanged: {
            if (!running) {
                root.wifiPassword = ""
                root.showPassword = false
                root.passwordPrompt = false
                refreshDelay.restart()
            }
        }
    }

    Process {
        id: wifiDisconnectProcess

        command: [
            "nmcli",
            "device",
            "disconnect",
            "wlp9s0"
        ]

        onRunningChanged: {
            if (!running)
                refreshDelay.restart()
        }
    }

    Process {
        id: qrProcess

        onRunningChanged: {
            if (!running && root.qrPath !== "")
                root.qrVisible = true
        }
    }

    Timer {
        id: refreshDelay

        interval: 1200
        repeat: false

        onTriggered: {
            root.refreshNetwork()
        }
    }

    spacing: 9

    ColumnLayout {
        visible:
            root.qrVisible

        Layout.fillWidth: true
        Layout.fillHeight: true

        spacing: 10

        Item {
            Layout.fillHeight: true
        }

        Rectangle {
            Layout.alignment:
                Qt.AlignHCenter

            Layout.preferredWidth: 300
            Layout.preferredHeight: 300

            radius: QuattroTheme.Theme.cornerRadius

            color: QuattroTheme.Theme.textStrong

            Image {
                anchors.fill: parent
                anchors.margins: 14

                source:
                    root.qrPath !== ""
                    ? "file://" + root.qrPath
                    : ""

                fillMode:
                    Image.PreserveAspectFit

                cache: false
            }
        }

        Text {
            text:
                "Scan to join " +
                root.qrSsid

            color: QuattroTheme.Theme.textStrong

            font.family:
                "JetBrainsMono Nerd Font"

            font.pixelSize: 13
            font.bold: true

            Layout.fillWidth: true

            horizontalAlignment:
                Text.AlignHCenter

            wrapMode:
                Text.Wrap
        }

        PanelButton {
            label: "Back"

            onClicked: {
                root.qrVisible = false
                root.qrPath = ""

                root.requestFocus()
            }
        }

        Item {
            Layout.fillHeight: true
        }
    }

    ColumnLayout {
        visible:
            !root.qrVisible

        Layout.fillWidth: true
        Layout.fillHeight: true

        spacing: 9

        RowLayout {
            Layout.fillWidth: true

            Text {
                text:
                    "󰈀  Ethernet"

                color: QuattroTheme.Theme.text

                font.family:
                    "JetBrainsMono Nerd Font"

                Layout.fillWidth: true
            }

            Text {
                text:
                    root.ethernetStatus

                color:
                    root.ethernetStatus ===
                    "Connected"
                    ? QuattroTheme.Theme.success
                    : QuattroTheme.Theme.textMuted

                font.family:
                    "JetBrainsMono Nerd Font"

                font.pixelSize: 11
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Text {
                text:
                    "󰖩  Wi-Fi"

                color: QuattroTheme.Theme.text

                font.family:
                    "JetBrainsMono Nerd Font"

                Layout.fillWidth: true
            }

            Text {
                text:
                    root.wifiEnabled
                    ? root.wifiStatus
                    : "Off"

                color:
                    root.wifiStatus ===
                    "Connected"
                    ? QuattroTheme.Theme.success
                    : QuattroTheme.Theme.textMuted

                font.family:
                    "JetBrainsMono Nerd Font"

                font.pixelSize: 10
            }

            Rectangle {
                implicitWidth: 44
                implicitHeight: 24

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    root.wifiEnabled
                    ? QuattroTheme.Theme.accent
                    : QuattroTheme.Theme.border

                Rectangle {
                    width: 18
                    height: 18

                    radius: QuattroTheme.Theme.cornerRadius

                    anchors.verticalCenter:
                        parent.verticalCenter

                    x:
                        root.wifiEnabled
                        ? parent.width - width - 3
                        : 3

                    color: QuattroTheme.Theme.textStrong

                    Behavior on x {
                        NumberAnimation {
                            duration: 120
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent

                    hoverEnabled: true

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        wifiToggleProcess.desiredState =
                            !root.wifiEnabled

                        root.wifiEnabled =
                            !root.wifiEnabled

                        wifiToggleProcess.running =
                            false

                        wifiToggleProcess.running =
                            true
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1

            color: QuattroTheme.Theme.border
        }

        Rectangle {
            visible:
                root.passwordPrompt

            Layout.fillWidth: true

            implicitHeight:
                passwordColumn.implicitHeight + 24

            radius: QuattroTheme.Theme.cornerRadius

            color: QuattroTheme.Theme.surface

            border.width: 1
            border.color: QuattroTheme.Theme.border

            ColumnLayout {
                id: passwordColumn

                anchors {
                    left: parent.left
                    right: parent.right
                    top: parent.top
                    margins: 12
                }

                spacing: 8

                Text {
                    text:
                        root.passwordMode === "qr"
                        ? "Share " + root.pendingSsid
                        : "Connect to " + root.pendingSsid

                    color: QuattroTheme.Theme.textStrong

                    font.family:
                        "JetBrainsMono Nerd Font"

                    font.pixelSize: 12
                    font.bold: true

                    Layout.fillWidth: true

                    wrapMode:
                        Text.Wrap
                }

                Text {
                    text:
                        root.passwordMode === "qr"
                        ? "Enter the Wi-Fi password to create a QR code."
                        : "Enter the Wi-Fi password."

                    color: QuattroTheme.Theme.textMuted

                    font.family:
                        "JetBrainsMono Nerd Font"

                    font.pixelSize: 10

                    Layout.fillWidth: true

                    wrapMode:
                        Text.Wrap
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 42

                    radius: QuattroTheme.Theme.cornerRadius
                    color: QuattroTheme.Theme.background

                    border.width:
                        passwordInput.activeFocus
                        ? 1
                        : 0

                    border.color:
                        QuattroTheme.Theme.accent

                    TextInput {
                        id: passwordInput

                        anchors {
                            left: parent.left
                            right: showPasswordButton.left
                            top: parent.top
                            bottom: parent.bottom

                            leftMargin: 12
                            rightMargin: 8
                        }

                        verticalAlignment:
                            TextInput.AlignVCenter

                        text:
                            root.wifiPassword

                        color:
                            root.showPassword
                            ? QuattroTheme.Theme.textStrong
                            : "transparent"

                        selectionColor:
                            QuattroTheme.Theme.accent

                        selectedTextColor:
                            root.showPassword
                            ? QuattroTheme.Theme.background
                            : "transparent"

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 12

                        echoMode:
                            TextInput.Normal

                        clip: true

                        onTextChanged: {
                            root.wifiPassword =
                                text
                        }

                        Keys.onReturnPressed: {
                            root.submitPassword()
                        }

                        Keys.onEscapePressed: {
                            root.passwordPrompt =
                                false

                            root.showPassword =
                                false

                            root.wifiPassword =
                                ""

                            root.requestFocus()
                        }
                    }

                    Item {
                        visible:
                            !root.showPassword

                        anchors {
                            left: parent.left
                            right: showPasswordButton.left
                            top: parent.top
                            bottom: parent.bottom

                            leftMargin: 12
                            rightMargin: 8
                        }

                        clip: true

                        Text {
                            anchors {
                                left: parent.left
                                verticalCenter:
                                    parent.verticalCenter
                            }

                            text: {
                                let result = ""

                                for (let i = 0;
                                     i < root.wifiPassword.length;
                                     i++) {
                                    if (i > 0)
                                        result += "\u200A"

                                    result += "•"
                                }

                                return result
                            }

                            color: QuattroTheme.Theme.textStrong

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 13
                        }

                        MouseArea {
                            anchors.fill: parent

                            onClicked: {
                                passwordInput.forceActiveFocus()
                            }
                        }
                    }

                    Rectangle {
                        id: showPasswordButton

                        implicitWidth: 52
                        height: 34

                        anchors {
                            right: parent.right
                            rightMargin: 4

                            verticalCenter:
                                parent.verticalCenter
                        }

                        radius: QuattroTheme.Theme.cornerRadius

                        color:
                            showPasswordMouse.containsMouse
                            ? QuattroTheme.Theme.border
                            : "transparent"

                        Text {
                            anchors.centerIn: parent

                            text:
                                root.showPassword
                                ? "Hide"
                                : "Show"

                            color:
                                showPasswordMouse.containsMouse
                                ? QuattroTheme.Theme.textStrong
                                : QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 9
                        }

                        MouseArea {
                            id: showPasswordMouse

                            anchors.fill: parent

                            hoverEnabled: true

                            cursorShape:
                                Qt.PointingHandCursor

                            onClicked: {
                                root.showPassword =
                                    !root.showPassword

                                passwordInput.forceActiveFocus()
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true

                    Item {
                        Layout.fillWidth: true
                    }

                    SmallButton {
                        label: "Cancel"

                        onClicked: {
                            root.passwordPrompt = false
                            root.showPassword = false
                            root.wifiPassword = ""

                            root.requestFocus()
                        }
                    }

                    SmallButton {
                        label:
                            root.passwordMode === "qr"
                            ? "Create QR"
                            : "Connect"

                        accent: true

                        onClicked: {
                            root.submitPassword()
                        }
                    }
                }
            }
        }

        RowLayout {
            visible:
                !root.passwordPrompt

            Layout.fillWidth: true

            Text {
                text:
                    "Nearby networks"

                color: QuattroTheme.Theme.text

                font.family:
                    "JetBrainsMono Nerd Font"

                font.pixelSize: 11

                Layout.fillWidth: true
            }

            Text {
                text: "󰑐  Refresh"

                color:
                    refreshMouse.containsMouse
                    ? QuattroTheme.Theme.textStrong
                    : QuattroTheme.Theme.textMuted

                font.family:
                    "JetBrainsMono Nerd Font"

                font.pixelSize: 10

                MouseArea {
                    id: refreshMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        root.refreshNetwork()
                    }
                }
            }
        }

        ListView {
            id: wifiList

            visible:
                !root.passwordPrompt

            Layout.fillWidth: true
            Layout.fillHeight: true

            clip: true
            spacing: 3

            model:
                root.wifiNetworks

            delegate: Rectangle {
                id: wifiRow

                required property var modelData

                width:
                    wifiList.width

                height: 52

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    wifiMainMouse.containsMouse
                    ? QuattroTheme.Theme.hover
                    : "transparent"

                MouseArea {
                    id: wifiMainMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        const network =
                            wifiRow.modelData

                        if (network.active) {
                            wifiDisconnectProcess.running =
                                false

                            wifiDisconnectProcess.running =
                                true

                            return
                        }

                        const isOpen =
                            network.security === "" ||
                            network.security
                                .toLowerCase()
                                .includes("open")

                        if (isOpen) {
                            wifiConnectProcess.ssid =
                                network.ssid

                            wifiConnectProcess.password =
                                ""

                            wifiConnectProcess.running =
                                false

                            wifiConnectProcess.running =
                                true

                            return
                        }

                        root.showPasswordPrompt(
                            network.ssid,
                            network.security,
                            "connect"
                        )
                    }
                }

                RowLayout {
                    anchors.fill: parent

                    anchors.leftMargin: 10
                    anchors.rightMargin: 8

                    spacing: 9

                    Text {
                        text:
                            modelData.signal >= 75
                            ? "󰤨"
                            : modelData.signal >= 50
                            ? "󰤥"
                            : modelData.signal >= 25
                            ? "󰤢"
                            : "󰤟"

                        color: QuattroTheme.Theme.text

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 16
                    }

                    ColumnLayout {
                        Layout.fillWidth: true

                        spacing: 0

                        Text {
                            text:
                                modelData.ssid

                            color: QuattroTheme.Theme.textStrong

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 12

                            Layout.fillWidth: true

                            elide:
                                Text.ElideRight
                        }

                        Text {
                            text:
                                modelData.security === ""
                                ? "Open network"
                                : modelData.security

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 9

                            Layout.fillWidth: true

                            elide:
                                Text.ElideRight
                        }
                    }

                    Text {
                        visible:
                            modelData.active

                        text:
                            "Connected"

                        color: QuattroTheme.Theme.success

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 9
                    }

                    Text {
                        text:
                            modelData.signal + "%"

                        color: QuattroTheme.Theme.textMuted

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 9
                    }

                    Rectangle {
                        implicitWidth: 30
                        implicitHeight: 28

                        radius: QuattroTheme.Theme.cornerRadius

                        color:
                            qrButtonMouse.containsMouse
                            ? QuattroTheme.Theme.border
                            : "transparent"

                        Text {
                            anchors.centerIn:
                                parent

                            text: "󰐲"

                            color: QuattroTheme.Theme.text

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 14
                        }

                        MouseArea {
                            id: qrButtonMouse

                            anchors.fill: parent

                            hoverEnabled: true

                            cursorShape:
                                Qt.PointingHandCursor

                            onClicked: {
                                const network =
                                    wifiRow.modelData

                                const isOpen =
                                    network.security === "" ||
                                    network.security
                                        .toLowerCase()
                                        .includes("open")

                                if (isOpen) {
                                    root.generateWifiQr(
                                        network.ssid,
                                        "",
                                        network.security
                                    )

                                    return
                                }

                                root.showPasswordPrompt(
                                    network.ssid,
                                    network.security,
                                    "qr"
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
