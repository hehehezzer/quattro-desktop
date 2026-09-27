import Quickshell
import Quickshell.Io
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../shared"
import "../../theme" as QuattroTheme

Item {
    id: root
    signal requestFocus
    property var adapters: []
    property var devices: []
    property var adapter: adapters.length ? adapters[adapterPicker.currentIndex >= 0 ? adapterPicker.currentIndex : 0] : null
    property bool available: false
    property bool busy: false
    property string pendingPath: ""
    property string action: ""
    property string error: ""
    property string message: ""
    property var prompt: null
    property string removePath: ""
    property string expandedPath: ""
    implicitWidth: 430
    implicitHeight: 500

    function send(data) {
        if (bridge.running)
            bridge.write(JSON.stringify(data) + "\n");
        else
            root.error = "Bluetooth bridge unavailable. Reconnecting…";
    }
    function refreshBluetooth() {
        send({
            action: "refresh"
        });
    }
    function resetTransientState() {
        removePath = "";
        expandedPath = "";
        if (adapter && adapter.scanning)
            send({
                action: "stop",
                path: adapter.path
            });
    }
    function handleEscape() {
        if (prompt && prompt.id) {
            send({
                action: "respond",
                id: prompt.id,
                accept: false
            });
            return true;
        }
        if (removePath) {
            removePath = "";
            return true;
        }
        return false;
    }
    IpcHandler {
        target: "bluetooth"
        function status(): string {
            return JSON.stringify({
                available: root.available,
                adapters: root.adapters,
                devices: root.devices,
                busy: root.busy,
                error: root.error,
                prompt: root.prompt
            });
        }
        function scan(): void {
            if (root.adapter)
                root.send({
                    action: "scan",
                    path: root.adapter.path
                });
        }
        function stopScan(): void {
            if (root.adapter)
                root.send({
                    action: "stop",
                    path: root.adapter.path
                });
        }
        function power(enabled: bool): void {
            if (root.adapter)
                root.send({
                    action: "power",
                    path: root.adapter.path,
                    value: enabled
                });
        }
    }
    Process {
        id: bridge
        running: true
        stdinEnabled: true
        command: ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_bluetooth.py"]
        stdout: SplitParser {
            onRead: data => {
                try {
                    const s = JSON.parse(data);
                    for (const key of ["adapters", "devices", "available", "busy", "pendingPath", "action", "error", "message", "prompt"])
                        if (s[key] !== undefined)
                            root[key] = s[key];
                } catch (e) {
                    root.error = "Invalid Bluetooth service response";
                }
            }
        }
        onExited: {
            root.available = false;
            root.adapters = [];
            root.devices = [];
            root.busy = false;
            root.prompt = null;
            root.error = "Bluetooth bridge stopped. Reconnecting…";
            retry.restart();
        }
    }
    Timer {
        id: retry
        interval: 5000
        onTriggered: bridge.running = true
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Rectangle {
                width: 7
                height: 7
                color: !root.available || !root.adapter ? QuattroTheme.Theme.textDim
                    : root.adapter.powered ? QuattroTheme.Theme.success
                    : QuattroTheme.Theme.textMuted
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    text: !root.available ? "Service unavailable" : !root.adapter ? "No adapter" : root.adapter.powered ? "Bluetooth on" : "Bluetooth off"
                    color: QuattroTheme.Theme.textStrong
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: 13
                    font.bold: true
                }
                Text {
                    text: root.adapter && root.adapter.powered
                        ? root.devices.filter(d => d.adapter === root.adapter.path && d.connected).length + " connected"
                        : "Discovery and connections are paused"
                    color: QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: 9
                }
            }
            DesktopButton {
                text: root.adapter && root.adapter.powered ? "Turn off" : "Turn on"
                prominent: !!root.adapter && !root.adapter.powered
                enabled: !!root.adapter && !root.busy
                onClicked: root.send({ action: "power", path: root.adapter.path, value: !root.adapter.powered })
            }
        }
        DesktopCombo {
            id: adapterPicker
            visible: root.adapters.length > 1
            Layout.fillWidth: true
            model: root.adapters
            textRole: "name"
        }
        Text {
            visible: root.adapters.length > 1 || !root.available || !root.adapter
            Layout.fillWidth: true
            text: !root.available ? "Bluetooth service unavailable" : !root.adapter ? "No Bluetooth adapter detected" : root.adapter.name + (root.adapter.powered ? " · On" : " · Off")
            color: QuattroTheme.Theme.textMuted
            wrapMode: Text.Wrap
            font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            visible: !!root.adapter && root.adapter.powered
            Text {
                text: root.adapter && root.adapter.scanning ? "DISCOVERING" : "DEVICES"
                color: root.adapter && root.adapter.scanning ? QuattroTheme.Theme.accent : QuattroTheme.Theme.textMuted
                font.family: QuattroTheme.Theme.fontFamily
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 0.8
                Layout.fillWidth: true
            }
            DesktopButton {
                text: root.adapter && root.adapter.scanning ? "Stop scan" : "Scan"
                enabled: !!root.adapter && root.adapter.powered && !root.busy
                onClicked: root.send({
                    action: root.adapter.scanning ? "stop" : "scan",
                    path: root.adapter.path
                })
            }
        }
        ListView {
            visible: !!root.adapter && root.adapter.powered
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: root.devices.filter(d => root.adapter && d.adapter === root.adapter.path)
            ScrollBar.vertical: ScrollBar {}
            delegate: ColumnLayout {
                id: deviceRow
                required property var modelData
                width: ListView.view.width
                spacing: 5
                RowLayout {
                    Layout.fillWidth: true
                    Rectangle {
                        Layout.preferredWidth: 3
                        Layout.preferredHeight: 30
                        color: deviceRow.modelData.connected ? QuattroTheme.Theme.success
                            : root.pendingPath === deviceRow.modelData.path ? QuattroTheme.Theme.accent
                            : "transparent"
                    }
                    Image {
                        source: Quickshell.iconPath(deviceRow.modelData.icon, "bluetooth")
                        sourceSize.width: 24
                        sourceSize.height: 24
                        Layout.preferredWidth: 24
                        Layout.preferredHeight: 24
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: deviceRow.modelData.name
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: QuattroTheme.Theme.textStrong
                            font.pixelSize: 12
                        }
                        Text {
                            Layout.fillWidth: true
                            text: root.pendingPath === deviceRow.modelData.path ? root.action + "…" : deviceRow.modelData.connected ? "Connected" : deviceRow.modelData.paired ? "Paired · Disconnected" : "Available to pair"
                            color: deviceRow.modelData.connected ? QuattroTheme.Theme.success : QuattroTheme.Theme.textMuted
                            font.pixelSize: 10
                            elide: Text.ElideRight
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    DesktopButton {
                        text: deviceRow.modelData.connected ? "Disconnect" : deviceRow.modelData.paired ? "Connect" : "Pair"
                        prominent: !deviceRow.modelData.connected
                        enabled: !root.busy && !!root.adapter && root.adapter.powered
                        onClicked: root.send({
                            action: deviceRow.modelData.connected ? "disconnect" : deviceRow.modelData.paired ? "connect" : "pair",
                            path: deviceRow.modelData.path
                        })
                    }
                    DesktopButton {
                        visible: deviceRow.modelData.paired
                        text: root.expandedPath === deviceRow.modelData.path ? "Less" : "More"
                        onClicked: root.expandedPath = root.expandedPath === deviceRow.modelData.path ? "" : deviceRow.modelData.path
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.expandedPath === deviceRow.modelData.path && deviceRow.modelData.paired
                    DesktopButton {
                        text: deviceRow.modelData.trusted ? "Untrust" : "Trust"
                        enabled: !root.busy
                        onClicked: root.send({
                            action: "trust",
                            path: deviceRow.modelData.path,
                            value: !deviceRow.modelData.trusted
                        })
                    }
                    DesktopButton {
                        destructive: true
                        text: root.removePath === deviceRow.modelData.path ? "Confirm remove" : "Remove"
                        enabled: !root.busy
                        onClicked: {
                            if (root.removePath === deviceRow.modelData.path) {
                                root.send({
                                    action: "remove",
                                    path: deviceRow.modelData.path
                                });
                                root.removePath = "";
                            } else
                                root.removePath = deviceRow.modelData.path;
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: QuattroTheme.Theme.border
                }
            }
            Text {
                anchors.centerIn: parent
                visible: parent.count === 0
                width: parent.width
                text: root.adapter && root.adapter.powered ? "No devices yet. Put your device in pairing mode, then Scan." : "Turn Bluetooth on to discover devices."
                wrapMode: Text.Wrap
                color: QuattroTheme.Theme.textMuted
                font.pixelSize: 12
            }
        }
        Text {
            visible: !!root.adapter && !root.adapter.powered
            Layout.fillWidth: true
            text: "Turn on Bluetooth to reconnect your devices."
            wrapMode: Text.Wrap
            color: QuattroTheme.Theme.textMuted
            font.family: QuattroTheme.Theme.fontFamily
            font.pixelSize: 11
        }
        ColumnLayout {
            visible: !!root.prompt
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: root.prompt ? root.prompt.name + " · " + root.prompt.message : ""
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: QuattroTheme.Theme.textStrong
            }
            DesktopField {
                id: pin
                Layout.fillWidth: true
                visible: root.prompt && (root.prompt.kind === "pin" || root.prompt.kind === "passkey")
                placeholderText: root.prompt && root.prompt.kind === "passkey" ? "Six-digit passkey" : "Device PIN"
                maximumLength: 16
            }
            RowLayout {
                visible: root.prompt && root.prompt.id > 0
                DesktopButton {
                    text: "Reject"
                    onClicked: root.send({
                        action: "respond",
                        id: root.prompt.id,
                        accept: false
                    })
                }
                DesktopButton {
                    text: "Confirm"
                    onClicked: {
                        root.send({
                            action: "respond",
                            id: root.prompt.id,
                            accept: true,
                            value: pin.text
                        });
                        pin.text = "";
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: root.error.length > 0
            text: root.error
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: root.error ? QuattroTheme.Theme.danger : QuattroTheme.Theme.textMuted
            font.pixelSize: 11
        }
    }
}
