import Quickshell
import Quickshell.Io
import QtQuick
import QtQuick.Layouts
import "../../theme" as QuattroTheme

Item {
    id: root

    signal requestFocus()

    property bool bluetoothPowered: false
    property bool scanning: false
    property bool busy: false

    property string controllerName: ""
    property string controllerAddress: ""

    property string statusMessage: ""
    property bool statusIsError: false

    property var allDevices: []
    property var pairedDevices: []
    property var connectedDevices: []
    property var nearbyDevices: []

    property string pendingCommand: ""
    property string pendingAction: ""
    property string pendingMac: ""

    implicitWidth: 430
    implicitHeight: 500

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    function shellQuote(value) {
        return "'" + String(value).replace(/'/g, "'\\''") + "'"
    }

    function containsMac(list, mac) {
        for (let i = 0; i < list.length; i++) {
            if (list[i].mac === mac)
                return true
        }

        return false
    }

    function findDevice(list, mac) {
        for (let i = 0; i < list.length; i++) {
            if (list[i].mac === mac)
                return list[i]
        }

        return null
    }

    function deviceIsPaired(mac) {
        return containsMac(root.pairedDevices, mac)
    }

    function deviceIsConnected(mac) {
        return containsMac(root.connectedDevices, mac)
    }

    function parseDeviceLines(output) {
        let result = []

        let lines = String(output)
            .split("\n")

        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim()

            if (!line.startsWith("Device "))
                continue

            let parts = line.split(/\s+/)

            if (parts.length < 2)
                continue

            let mac = parts[1]

            let name = line
                .substring(("Device " + mac).length)
                .trim()

            if (name.length === 0)
                name = mac

            result.push({
                "mac": mac,
                "name": name
            })
        }

        return result
    }

    function rebuildNearbyDevices() {
        let result = []

        for (let i = 0; i < root.allDevices.length; i++) {
            let device = root.allDevices[i]

            if (!root.deviceIsPaired(device.mac))
                result.push(device)
        }

        root.nearbyDevices = result
    }

    function setStatus(message, error) {
        root.statusMessage = message
        root.statusIsError = error === true
    }

    function clearStatusLater() {
        statusClearTimer.restart()
    }

    // ------------------------------------------------------------------
    // Public API used by SystemPanels.qml
    // ------------------------------------------------------------------

    function refreshBluetooth() {
        controllerProcess.running = false
        pairedProcess.running = false
        connectedProcess.running = false
        devicesProcess.running = false

        controllerProcess.running = true
    }

    function scanBluetooth() {
        if (!root.bluetoothPowered) {
            root.setStatus("Bluetooth is turned off.", true)
            root.clearStatusLater()
            return
        }

        if (root.scanning || root.busy)
            return

        root.scanning = true
        root.setStatus("Scanning for nearby devices...", false)

        scanProcess.running = false
        scanProcess.running = true
    }

    function setBluetoothPower(enabled) {
        if (root.busy)
            return

        root.runAction(
            "bluetoothctl power " + (enabled ? "on" : "off"),
            enabled ? "power-on" : "power-off",
            ""
        )
    }

    function pairDevice(mac) {
        if (root.busy)
            return

        root.runAction(
            "bluetoothctl --timeout 25 pair " + root.shellQuote(mac),
            "pair",
            mac
        )
    }

    function connectDevice(mac) {
        if (root.busy)
            return

        root.runAction(
            "bluetoothctl --timeout 20 connect " + root.shellQuote(mac),
            "connect",
            mac
        )
    }

    function disconnectDevice(mac) {
        if (root.busy)
            return

        root.runAction(
            "bluetoothctl --timeout 15 disconnect " + root.shellQuote(mac),
            "disconnect",
            mac
        )
    }

    function forgetDevice(mac) {
        if (root.busy)
            return

        root.runAction(
            "bluetoothctl remove " + root.shellQuote(mac),
            "forget",
            mac
        )
    }

    function runAction(command, action, mac) {
        root.pendingCommand = command
        root.pendingAction = action
        root.pendingMac = mac

        root.busy = true
        root.statusIsError = false

        if (action === "pair")
            root.statusMessage = "Pairing device..."
        else if (action === "connect")
            root.statusMessage = "Connecting device..."
        else if (action === "disconnect")
            root.statusMessage = "Disconnecting device..."
        else if (action === "forget")
            root.statusMessage = "Removing device..."
        else if (action === "power-on")
            root.statusMessage = "Turning Bluetooth on..."
        else if (action === "power-off")
            root.statusMessage = "Turning Bluetooth off..."

        actionProcess.running = false
        actionProcess.running = true
    }

    function resetTransientState() {
        root.statusMessage = ""
        root.statusIsError = false

        if (root.scanning)
            scanProcess.running = false

        root.scanning = false
    }

    function handleEscape() {
        if (root.scanning) {
            scanProcess.running = false
            root.scanning = false
            root.statusMessage = ""
            return true
        }

        return false
    }

    // ------------------------------------------------------------------
    // Controller state
    // ------------------------------------------------------------------

    Process {
        id: controllerProcess

        command: [
            "sh",
            "-c",
            "bluetoothctl show"
        ]

        stdout: StdioCollector {
            id: controllerOutput
        }

        onExited: (exitCode, exitStatus) => {
            let output = controllerOutput.text

            let addressMatch =
                output.match(/Controller\s+([0-9A-Fa-f:]{17})/)

            let nameMatch =
                output.match(/Name:\s*(.+)/)

            let poweredMatch =
                output.match(/Powered:\s*(yes|no)/)

            root.controllerAddress =
                addressMatch
                ? addressMatch[1]
                : ""

            root.controllerName =
                nameMatch
                ? nameMatch[1].trim()
                : ""

            root.bluetoothPowered =
                poweredMatch
                ? poweredMatch[1] === "yes"
                : false

            pairedProcess.running = false
            pairedProcess.running = true
        }
    }

    // ------------------------------------------------------------------
    // Paired devices
    // ------------------------------------------------------------------

    Process {
        id: pairedProcess

        command: [
            "sh",
            "-c",
            "bluetoothctl devices Paired"
        ]

        stdout: StdioCollector {
            id: pairedOutput
        }

        onExited: (exitCode, exitStatus) => {
            root.pairedDevices =
                root.parseDeviceLines(
                    pairedOutput.text
                )

            connectedProcess.running = false
            connectedProcess.running = true
        }
    }

    // ------------------------------------------------------------------
    // Connected devices
    // ------------------------------------------------------------------

    Process {
        id: connectedProcess

        command: [
            "sh",
            "-c",
            "bluetoothctl devices Connected"
        ]

        stdout: StdioCollector {
            id: connectedOutput
        }

        onExited: (exitCode, exitStatus) => {
            root.connectedDevices =
                root.parseDeviceLines(
                    connectedOutput.text
                )

            devicesProcess.running = false
            devicesProcess.running = true
        }
    }

    // ------------------------------------------------------------------
    // All discovered devices
    // ------------------------------------------------------------------

    Process {
        id: devicesProcess

        command: [
            "sh",
            "-c",
            "bluetoothctl devices"
        ]

        stdout: StdioCollector {
            id: devicesOutput
        }

        onExited: (exitCode, exitStatus) => {
            root.allDevices =
                root.parseDeviceLines(
                    devicesOutput.text
                )

            root.rebuildNearbyDevices()
        }
    }

    // ------------------------------------------------------------------
    // Scan
    // ------------------------------------------------------------------

    Process {
        id: scanProcess

        command: [
            "sh",
            "-c",
            "bluetoothctl --timeout 12 scan on"
        ]

        stdout: StdioCollector {
            id: scanOutput
        }

        onExited: (exitCode, exitStatus) => {
            root.scanning = false

            if (exitCode === 0) {
                root.setStatus(
                    "Scan complete.",
                    false
                )
            } else {
                root.setStatus(
                    "Bluetooth scan failed.",
                    true
                )
            }

            root.refreshBluetooth()
            root.clearStatusLater()
        }
    }

    // ------------------------------------------------------------------
    // Generic action process
    // ------------------------------------------------------------------

    Process {
        id: actionProcess

        command: [
            "sh",
            "-c",
            root.pendingCommand
        ]

        stdout: StdioCollector {
            id: actionOutput
        }

        stderr: StdioCollector {
            id: actionErrorOutput
        }

        onExited: (exitCode, exitStatus) => {
            root.busy = false

            let output =
                (
                    actionOutput.text
                    + "\n"
                    + actionErrorOutput.text
                ).trim()

            if (exitCode === 0) {
                if (root.pendingAction === "pair") {
                    root.setStatus(
                        "Device paired.",
                        false
                    )
                } else if (root.pendingAction === "connect") {
                    root.setStatus(
                        "Device connected.",
                        false
                    )
                } else if (root.pendingAction === "disconnect") {
                    root.setStatus(
                        "Device disconnected.",
                        false
                    )
                } else if (root.pendingAction === "forget") {
                    root.setStatus(
                        "Device removed.",
                        false
                    )
                } else if (root.pendingAction === "power-on") {
                    root.setStatus(
                        "Bluetooth enabled.",
                        false
                    )
                } else if (root.pendingAction === "power-off") {
                    root.setStatus(
                        "Bluetooth disabled.",
                        false
                    )
                }
            } else {
                let message = "Bluetooth action failed."

                if (root.pendingAction === "pair")
                    message = "Pairing failed."
                else if (root.pendingAction === "connect")
                    message = "Connection failed."
                else if (root.pendingAction === "disconnect")
                    message = "Disconnect failed."
                else if (root.pendingAction === "forget")
                    message = "Could not remove device."

                if (output.length > 0)
                    message += " " + output

                root.setStatus(
                    message,
                    true
                )
            }

            root.pendingCommand = ""
            root.pendingAction = ""
            root.pendingMac = ""

            root.refreshBluetooth()
            root.clearStatusLater()
        }
    }

    Timer {
        id: statusClearTimer

        interval: 3500
        repeat: false

        onTriggered: {
            if (!root.busy && !root.scanning)
                root.statusMessage = ""
        }
    }

    // ------------------------------------------------------------------
    // UI
    // ------------------------------------------------------------------

    ColumnLayout {
        anchors {
            fill: parent
            margins: 18
        }

        spacing: 12

        // Header
        RowLayout {
            Layout.fillWidth: true

            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    text: "Bluetooth"

                    color: QuattroTheme.Theme.textStrong

                    font {
                        pixelSize: 18
                        weight: Font.DemiBold
                    }
                }

                Text {
                    visible:
                        root.controllerName.length > 0

                    text:
                        root.controllerName

                    color: QuattroTheme.Theme.textMuted

                    font.pixelSize: 12
                }
            }

            // Bluetooth switch
            Rectangle {
                id: bluetoothSwitch

                width: 46
                height: 24

                radius: height / 2

                color:
                    root.bluetoothPowered
                    ? QuattroTheme.Theme.textStrong
                    : QuattroTheme.Theme.border

                opacity:
                    root.busy
                    ? 0.5
                    : 1.0

                Rectangle {
                    width: 18
                    height: 18

                    radius: width / 2

                    anchors.verticalCenter:
                        parent.verticalCenter

                    x:
                        root.bluetoothPowered
                        ? parent.width - width - 3
                        : 3

                    color:
                        root.bluetoothPowered
                        ? QuattroTheme.Theme.background
                        : QuattroTheme.Theme.text

                    Behavior on x {
                        NumberAnimation {
                            duration: 130
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent

                    enabled:
                        !root.busy

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        root.setBluetoothPower(
                            !root.bluetoothPowered
                        )
                    }
                }
            }
        }

        Text {
            visible:
                root.controllerAddress.length > 0

            Layout.fillWidth: true

            text:
                root.controllerAddress

            color: QuattroTheme.Theme.textDim

            font {
                family: "monospace"
                pixelSize: 11
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1

            color: QuattroTheme.Theme.border
        }

        // --------------------------------------------------------------
        // Paired section
        // --------------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true

            Text {
                Layout.fillWidth: true

                text: "PAIRED DEVICES"

                color: QuattroTheme.Theme.textMuted

                font {
                    pixelSize: 11
                    weight: Font.DemiBold
                    letterSpacing: 1
                }
            }

            Text {
                visible:
                    root.connectedDevices.length > 0

                text:
                    root.connectedDevices.length
                    + " connected"

                color: QuattroTheme.Theme.textMuted

                font.pixelSize: 11
            }
        }

        Text {
            visible:
                root.pairedDevices.length === 0

            Layout.fillWidth: true

            text:
                root.bluetoothPowered
                ? "No paired devices"
                : "Bluetooth is off"

            color: QuattroTheme.Theme.textMuted

            font.pixelSize: 13
        }

        Repeater {
            model:
                root.pairedDevices

            delegate: Rectangle {
                required property var modelData

                Layout.fillWidth: true
                Layout.preferredHeight: 58

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    pairedMouse.containsMouse
                    ? QuattroTheme.Theme.surface
                    : "transparent"

                RowLayout {
                    anchors {
                        fill: parent
                        leftMargin: 8
                        rightMargin: 8
                    }

                    spacing: 10

                    Rectangle {
                        width: 34
                        height: 34

                        radius: QuattroTheme.Theme.cornerRadius

                        color: QuattroTheme.Theme.hover

                        Text {
                            anchors.centerIn: parent

                            text: "B"

                            color: QuattroTheme.Theme.text

                            font {
                                pixelSize: 13
                                weight: Font.Bold
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true

                        spacing: 2

                        Text {
                            Layout.fillWidth: true

                            text:
                                modelData.name

                            color: QuattroTheme.Theme.textStrong

                            elide:
                                Text.ElideRight

                            font.pixelSize: 13
                        }

                        Text {
                            Layout.fillWidth: true

                            text:
                                modelData.mac

                            color: QuattroTheme.Theme.textMuted

                            elide:
                                Text.ElideRight

                            font {
                                family: "monospace"
                                pixelSize: 10
                            }
                        }
                    }

                    Rectangle {
                        width:
                            pairedActionText.implicitWidth
                            + 22

                        height: 30

                        radius: QuattroTheme.Theme.cornerRadius

                        color: QuattroTheme.Theme.border

                        Text {
                            id: pairedActionText

                            anchors.centerIn: parent

                            text:
                                root.deviceIsConnected(
                                    modelData.mac
                                )
                                ? "Disconnect"
                                : "Connect"

                            color: QuattroTheme.Theme.text

                            font.pixelSize: 11
                        }

                        MouseArea {
                            anchors.fill: parent

                            enabled:
                                !root.busy

                            cursorShape:
                                Qt.PointingHandCursor

                            onClicked: {
                                if (
                                    root.deviceIsConnected(
                                        modelData.mac
                                    )
                                ) {
                                    root.disconnectDevice(
                                        modelData.mac
                                    )
                                } else {
                                    root.connectDevice(
                                        modelData.mac
                                    )
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: 56
                        height: 30

                        radius: QuattroTheme.Theme.cornerRadius

                        color: QuattroTheme.Theme.surfaceRaised

                        Text {
                            anchors.centerIn: parent

                            text: "Forget"

                            color: QuattroTheme.Theme.textMuted

                            font.pixelSize: 11
                        }

                        MouseArea {
                            anchors.fill: parent

                            enabled:
                                !root.busy

                            cursorShape:
                                Qt.PointingHandCursor

                            onClicked: {
                                root.forgetDevice(
                                    modelData.mac
                                )
                            }
                        }
                    }
                }

                MouseArea {
                    id: pairedMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    acceptedButtons:
                        Qt.NoButton
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1

            color: QuattroTheme.Theme.border
        }

        // --------------------------------------------------------------
        // Nearby header
        // --------------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true

            Text {
                Layout.fillWidth: true

                text: "NEARBY DEVICES"

                color: QuattroTheme.Theme.textMuted

                font {
                    pixelSize: 11
                    weight: Font.DemiBold
                    letterSpacing: 1
                }
            }

            Rectangle {
                width:
                    refreshText.implicitWidth
                    + 18

                height: 28

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    refreshMouse.containsMouse
                    ? QuattroTheme.Theme.border
                    : QuattroTheme.Theme.surfaceRaised

                opacity:
                    root.bluetoothPowered
                    && !root.scanning
                    && !root.busy
                    ? 1.0
                    : 0.45

                Text {
                    id: refreshText

                    anchors.centerIn: parent

                    text:
                        root.scanning
                        ? "Scanning..."
                        : "Refresh"

                    color: QuattroTheme.Theme.text

                    font.pixelSize: 11
                }

                MouseArea {
                    id: refreshMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    enabled:
                        root.bluetoothPowered
                        && !root.scanning
                        && !root.busy

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked:
                        root.scanBluetooth()
                }
            }
        }

        Text {
            visible:
                root.bluetoothPowered
                && root.nearbyDevices.length === 0
                && !root.scanning

            Layout.fillWidth: true

            text:
                "No nearby devices found"

            color: QuattroTheme.Theme.textMuted

            font.pixelSize: 13
        }

        Text {
            visible:
                root.scanning

            Layout.fillWidth: true

            text:
                "Looking for Bluetooth devices..."

            color: QuattroTheme.Theme.text

            font.pixelSize: 13
        }

        // --------------------------------------------------------------
        // Nearby device list
        // --------------------------------------------------------------

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true

            clip: true

            contentWidth: width
            contentHeight:
                nearbyColumn.implicitHeight

            boundsBehavior:
                Flickable.StopAtBounds

            ColumnLayout {
                id: nearbyColumn

                width: parent.width

                spacing: 3

                Repeater {
                    model:
                        root.nearbyDevices

                    delegate: Rectangle {
                        required property var modelData

                        Layout.fillWidth: true
                        Layout.preferredHeight: 58

                        radius: QuattroTheme.Theme.cornerRadius

                        color:
                            nearbyMouse.containsMouse
                            ? QuattroTheme.Theme.surface
                            : "transparent"

                        RowLayout {
                            anchors {
                                fill: parent
                                leftMargin: 8
                                rightMargin: 8
                            }

                            spacing: 10

                            Rectangle {
                                width: 34
                                height: 34

                                radius: QuattroTheme.Theme.cornerRadius

                                color: QuattroTheme.Theme.hover

                                Text {
                                    anchors.centerIn: parent

                                    text: "B"

                                    color: QuattroTheme.Theme.text

                                    font {
                                        pixelSize: 13
                                        weight: Font.Bold
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true

                                spacing: 2

                                Text {
                                    Layout.fillWidth: true

                                    text:
                                        modelData.name

                                    color: QuattroTheme.Theme.textStrong

                                    elide:
                                        Text.ElideRight

                                    font.pixelSize: 13
                                }

                                Text {
                                    Layout.fillWidth: true

                                    text:
                                        modelData.mac

                                    color: QuattroTheme.Theme.textMuted

                                    elide:
                                        Text.ElideRight

                                    font {
                                        family: "monospace"
                                        pixelSize: 10
                                    }
                                }
                            }

                            Rectangle {
                                width: 54
                                height: 30

                                radius: QuattroTheme.Theme.cornerRadius

                                color:
                                    pairMouse.containsMouse
                                    ? QuattroTheme.Theme.border
                                    : QuattroTheme.Theme.border

                                opacity:
                                    root.busy
                                    ? 0.45
                                    : 1.0

                                Text {
                                    anchors.centerIn: parent

                                    text: "Pair"

                                    color: QuattroTheme.Theme.text

                                    font.pixelSize: 11
                                }

                                MouseArea {
                                    id: pairMouse

                                    anchors.fill: parent

                                    hoverEnabled: true

                                    enabled:
                                        !root.busy

                                    cursorShape:
                                        Qt.PointingHandCursor

                                    onClicked: {
                                        root.pairDevice(
                                            modelData.mac
                                        )
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: nearbyMouse

                            anchors.fill: parent

                            hoverEnabled: true

                            acceptedButtons:
                                Qt.NoButton
                        }
                    }
                }
            }
        }

        // --------------------------------------------------------------
        // Status message
        // --------------------------------------------------------------

        Rectangle {
            visible:
                root.statusMessage.length > 0

            Layout.fillWidth: true

            Layout.preferredHeight:
                statusText.implicitHeight
                + 18

            radius: QuattroTheme.Theme.cornerRadius

            color:
                root.statusIsError
                ? QuattroTheme.Theme.border
                : QuattroTheme.Theme.surfaceRaised

            Text {
                id: statusText

                anchors {
                    fill: parent
                    margins: 9
                }

                text:
                    root.statusMessage

                color:
                    root.statusIsError
                    ? QuattroTheme.Theme.danger
                    : QuattroTheme.Theme.text

                wrapMode:
                    Text.Wrap

                font.pixelSize: 11
            }
        }
    }

    Component.onCompleted: {
        root.refreshBluetooth()
    }
}
