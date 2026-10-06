import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Notifications
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as QuattroTheme
import "../services"
import "shared"

Scope {
    id: root
    function open() {
        history.screen = PopupManager.focusedScreen()
        history.opened = true
        NotificationHistory.markSeen()
        Qt.callLater(() => closeButton.forceActiveFocus())
    }
    function toggle() { if (history.opened) history.opened = false; else open() }
    NotificationServer {
        id: server
        bodySupported: true
        actionsSupported: true
        keepOnReload: true
        onNotification: notification => NotificationHistory.receive(notification)
    }
    Connections {
        target: NotificationHistory
        function onOpenRequested() { root.open() }
        function onToggleRequested() { root.toggle() }
    }
    Connections {
        target: PopupManager
        function onRequested(name) { if (name === "notifications") root.toggle() }
    }
    PanelWindow {
        focusable: true
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
        WlrLayershell.namespace: "quattro-toasts"
        screen: PopupManager.focusedScreen()
        visible: server.trackedNotifications.values.length > 0 && !history.opened
        anchors { top: true; right: true }
        margins { top: QuattroTheme.Theme.barHeight + 8; right: 12 }
        implicitWidth: Math.min(360, (screen ? screen.width : 1920) - 24)
        implicitHeight: Math.min(toasts.implicitHeight, (screen ? screen.height : 1080) - 64)
        exclusionMode: ExclusionMode.Ignore
        color: "transparent"
        Flickable {
            anchors.fill: parent
            contentWidth: width; contentHeight: toasts.implicitHeight
            clip: true
            ColumnLayout {
                id: toasts
                width: parent.width
                spacing: 8
                Repeater {
                    model: server.trackedNotifications
                    delegate: NotificationToast { required property var modelData; notice: modelData; Layout.fillWidth: true }
                }
            }
            ScrollBar.vertical: ScrollBar {}
        }
    }
    TemporaryPanel {
        id: history
        panelName: "notifications"
        onDismissed: opened = false
        onOpenedChanged: { NotificationHistory.opened = opened; if (opened) NotificationHistory.markSeen() }
        anchors { top: true; right: true }
        margins { top: QuattroTheme.Theme.barHeight + 8; right: 12 }
        implicitWidth: Math.min(QuattroTheme.Theme.panelWidth, (screen ? screen.width : 1920) - 24)
        implicitHeight: Math.min(720, (screen ? screen.height : 1080) - 64)
        color: QuattroTheme.Theme.panelSurface
        Rectangle { anchors.fill: parent; color: "transparent"; border.color: QuattroTheme.Theme.panelBorder }
        ColumnLayout {
            anchors { fill: parent; margins: 16 }
            spacing: 12
            Text { text: "Notifications"; color: QuattroTheme.Theme.textStrong; font.family: QuattroTheme.Theme.fontFamily; font.pixelSize: 20 }
            Text {
                Layout.fillWidth: true
                text: (NotificationHistory.storageAvailable && !NotificationHistory.storageError
                    ? "Saved locally" : "This session") + " · up to 100 notices · 24 hours"
                wrapMode: Text.Wrap
                color: QuattroTheme.Theme.textMuted; font.family: QuattroTheme.Theme.fontFamily
            }
            Text {
                visible: NotificationHistory.storageError.length > 0
                text: NotificationHistory.storageError
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: QuattroTheme.Theme.warning
                font.family: QuattroTheme.Theme.fontFamily
            }
            RowLayout {
                DesktopButton { text: "Clear history"; enabled: NotificationHistory.entries.length > 0; onClicked: NotificationHistory.clear() }
                Item { Layout.fillWidth: true }
                DesktopButton { id: closeButton; text: "Close"; onClicked: history.opened = false }
            }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; spacing: 12
                model: NotificationHistory.entries
                ScrollBar.vertical: ScrollBar {}
                delegate: ColumnLayout {
                    id: row
                    required property var modelData
                    width: ListView.view.width
                    readonly property var clock: NotificationHistory.current(modelData.nativeId)
                    readonly property var notice: clock && clock.key === modelData.key ? clock.notice : null
                    Text {
                        Layout.fillWidth: true
                        text: row.modelData.app + (row.modelData.urgency === NotificationUrgency.Critical ? " · Critical" : "") + " · " + new Date(row.modelData.time).toLocaleTimeString()
                        textFormat: Text.PlainText; wrapMode: Text.Wrap
                        color: QuattroTheme.Theme.textMuted; font.family: QuattroTheme.Theme.fontFamily
                    }
                    NotificationToast { visible: row.notice !== null; notice: row.notice; Layout.fillWidth: true }
                    Text {
                        visible: row.notice === null
                        Layout.fillWidth: true
                        text: row.modelData.summary + (row.modelData.body ? "\n" + row.modelData.body : "")
                        textFormat: Text.PlainText; wrapMode: Text.Wrap
                        color: QuattroTheme.Theme.text; font.family: QuattroTheme.Theme.fontFamily
                    }
                    DesktopButton { text: "Remove from history"; onClicked: NotificationHistory.remove(row.modelData.key) }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: QuattroTheme.Theme.border }
                }
                Text {
                    anchors.centerIn: parent
                    width: parent.width
                    visible: NotificationHistory.entries.length === 0
                    text: "New notifications will appear here.\nEarlier discarded notices cannot be recovered."
                    horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                    color: QuattroTheme.Theme.textMuted; font.family: QuattroTheme.Theme.fontFamily
                }
            }
        }
    }
}
