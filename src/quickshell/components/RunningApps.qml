import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Wayland
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "shared"
import "../services"
import "../theme" as QuattroTheme

DesktopButton {
    id: root
    required property var barWindow
    text: "󰍹"
    implicitWidth: 26
    implicitHeight: 26
    Accessible.name: "Running applications"
    ToolTip.text: "Running applications · right-click a window for process controls"
    property bool opened: false
    property var apps: []
    property var selected: null
    property bool confirmKill: false
    property bool needsForce: false
    property string message: ""
    property string lastAction: ""
    function refresh() {
        if (!listProcess.running)
            listProcess.running = true;
    }
    function act(action) {
        if (!selected || actionProcess.running)
            return;
        lastAction = action;
        actionProcess.command = ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_desktop_controls.py", "application", action, selected.address, String(selected.pid), selected.start];
        actionProcess.running = true;
    }
    onOpenedChanged: {
        if (!opened) {
            contextMenu.close();
            selected = null;
            confirmKill = false;
            needsForce = false;
        }
    }
    onClicked: {
        PopupManager.revision++;
        opened = !opened;
        selected = null;
        confirmKill = false;
        needsForce = false;
        message = "";
        if (opened)
            refresh();
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (root.opened && ["openwindow", "closewindow", "windowtitle", "windowtitlev2"].indexOf(event.name) >= 0)
                refreshDelay.restart();
        }
    }
    Timer {
        id: refreshDelay
        interval: 100
        onTriggered: root.refresh()
    }
    Process {
        id: listProcess
        command: ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_desktop_controls.py", "applications"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const s = JSON.parse(text);
                    root.apps = s.applications || [];
                    if (s.error)
                        root.message = s.error;
                    if (root.selected && !root.apps.some(a => a.address === root.selected.address && a.start === root.selected.start)) {
                        contextMenu.close();
                        root.selected = null;
                        root.confirmKill = false;
                        root.needsForce = false;
                    }
                } catch (e) {
                    root.message = "Application list unavailable";
                }
            }
        }
    }
    Process {
        id: actionProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const s = JSON.parse(text);
                    root.message = s.error || s.message || "Window action requested";
                    root.needsForce = !!s.needsForce;
                    root.confirmKill = false;
                } catch (e) {
                    root.message = "Application action failed";
                }
            }
        }
        onExited: {
            contextMenu.close();
            refreshDelay.restart();
            if (root.lastAction === "open")
                root.opened = false;
        }
    }
    component MenuAction: MenuItem {
        id: entry
        implicitHeight: 32
        implicitWidth: 220
        leftPadding: 10
        rightPadding: 10
        contentItem: Text {
            text: entry.text
            color: entry.enabled ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textDim
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 12
        }
        background: Rectangle {
            color: entry.highlighted ? QuattroTheme.Theme.hover : QuattroTheme.Theme.surface
        }
    }
    IpcHandler {
        target: "applications-" + root.barWindow.screen.name
        function status(): string {
            return JSON.stringify({
                opened: root.opened,
                menuOpen: contextMenu.visible,
                selectedPid: root.selected ? root.selected.pid : 0,
                confirming: root.confirmKill,
                needsForce: root.needsForce
            });
        }
        function open(): void {
            root.opened = true;
            root.refresh();
        }
        function close(): void {
            root.opened = false;
        }
    }
    TemporaryPanel {
        id: popup
        panelName: "applications"
        onDismissed: root.opened = false
        opened: root.opened
        screen: root.barWindow.screen
        anchors {
            top: true
            right: true
        }
        margins {
            top: 38
            right: 8
        }
        exclusionMode: ExclusionMode.Ignore
        implicitWidth: 410
        implicitHeight: 430
        color: QuattroTheme.Theme.background
        onVisibleChanged: if (!visible)
            root.opened = false
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 8
            RowLayout {
                Text {
                    text: "Running applications"
                    color: QuattroTheme.Theme.textStrong
                    font.pixelSize: 16
                    Layout.fillWidth: true
                }
                DesktopButton {
                    text: "Close"
                    onClicked: root.opened = false
                }
            }
            Text {
                text: "Right-click a window for process controls"
                color: QuattroTheme.Theme.textMuted
                font.pixelSize: 11
            }
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: root.apps
                clip: true
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    id: appRow
                    required property var modelData
                    width: ListView.view.width
                    height: 48
                    activeFocusOnTab: true
                    Accessible.role: Accessible.ListItem
                    Accessible.name: modelData.app + " " + modelData.title
                    Keys.onReturnPressed: {
                        root.selected = modelData;
                        root.act("open");
                    }
                    Keys.onMenuPressed: {
                        root.selected = modelData;
                        root.confirmKill = false;
                        root.needsForce = false;
                        contextMenu.close();
                        contextMenu.popup(appRow, 8, appRow.height);
                    }
                    border.width: activeFocus ? 1 : 0
                    border.color: QuattroTheme.Theme.textStrong
                    color: root.selected && root.selected.address === modelData.address ? QuattroTheme.Theme.hover : mouse.containsMouse ? QuattroTheme.Theme.surface : "transparent"
                    Text {
                        anchors.fill: parent
                        anchors.margins: 8
                        text: modelData.app + " · PID " + modelData.pid + "\n" + modelData.title
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: QuattroTheme.Theme.text
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: mouse
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: event => {
                            root.selected = modelData;
                            root.confirmKill = false;
                            root.needsForce = false;
                            root.message = "";
                            if (event.button === Qt.LeftButton)
                                root.act("open");
                            else {
                                contextMenu.close();
                                contextMenu.popup(appRow, event.x, event.y);
                            }
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: root.confirmKill || root.needsForce || root.message.length > 0
                text: root.confirmKill ? "Terminate PID " + root.selected.pid + "? All windows in this process may close; unsaved work may be lost." : root.message
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: QuattroTheme.Theme.warning
                font.pixelSize: 11
            }
            RowLayout {
                visible: root.confirmKill || root.needsForce
                DesktopButton {
                    text: "Cancel"
                    onClicked: {
                        root.confirmKill = false;
                        root.needsForce = false;
                    }
                }
                DesktopButton {
                    text: root.needsForce ? "Force kill" : "Terminate"
                    destructive: true
                    enabled: !actionProcess.running && !!root.selected && !root.selected.protected
                    onClicked: root.act(root.needsForce ? "force" : "terminate")
                }
            }
        }
        Menu {
            id: contextMenu
            popupType: Popup.Item
            width: 230
            palette.window: QuattroTheme.Theme.surface
            palette.text: QuattroTheme.Theme.textStrong
            palette.windowText: QuattroTheme.Theme.textStrong
            palette.highlight: QuattroTheme.Theme.hover
            palette.highlightedText: QuattroTheme.Theme.textStrong
            background: Rectangle {
                color: QuattroTheme.Theme.surface
                border.width: 1
                border.color: QuattroTheme.Theme.border
            }
            MenuAction {
                text: "Open"
                onTriggered: root.act("open")
            }
            MenuAction {
                text: "Close window"
                enabled: !!root.selected && !root.selected.protected
                onTriggered: root.act("close")
            }
            MenuSeparator {}
            MenuAction {
                text: root.selected && root.selected.protected ? "Protected desktop process" : "Kill Process…"
                enabled: !!root.selected && !root.selected.protected
                onTriggered: root.confirmKill = true
            }
        }
    }
}
