import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell.Services.Notifications
import "../../theme" as QuattroTheme
import "../../services"

Rectangle {
    id: root
    required property var notice
    readonly property var clock: notice ? NotificationHistory.current(notice.id) : null
    readonly property bool defaultActionAvailable: !!notice && notice.actions.some(a => a.identifier === "default")
    function activateDefault() {
        if (notice && defaultActionAvailable) NotificationHistory.invoke(notice.id, "default")
    }
    activeFocusOnTab: defaultActionAvailable
    Accessible.role: defaultActionAvailable ? Accessible.Button : Accessible.Grouping
    Accessible.name: notice ? notice.summary + " " + notice.body : "Notification"
    Accessible.onPressAction: activateDefault()
    Keys.onReturnPressed: activateDefault()
    Keys.onSpacePressed: activateDefault()
    Keys.onEscapePressed: if (notice) NotificationHistory.dismiss(notice.id)
    implicitHeight: content.implicitHeight + 24
    onVisibleChanged: if (!visible && clock) clock.pause(false)
    Component.onDestruction: if (clock) clock.pause(false)
    color: QuattroTheme.Theme.panelSurface
    radius: QuattroTheme.Theme.panelRadius
    border.width: activeFocus ? QuattroTheme.Theme.focusLine : 1
    border.color: activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.panelBorder
    MouseArea {
        anchors.fill: parent
        cursorShape: root.defaultActionAvailable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.activateDefault()
    }
    HoverHandler { onHoveredChanged: if (root.clock) root.clock.pause(hovered) }
    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 8
        Text {
            Layout.fillWidth: true
            text: root.notice ? root.notice.appName + (root.notice.urgency === NotificationUrgency.Critical ? " · Critical" : "") : ""
            textFormat: Text.PlainText
            font.family: QuattroTheme.Theme.fontFamily
            color: QuattroTheme.Theme.textMuted
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            text: root.notice ? root.notice.summary : ""
            textFormat: Text.PlainText
            font.family: QuattroTheme.Theme.fontFamily
            font.bold: true
            color: QuattroTheme.Theme.textStrong
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            visible: text.length > 0
            text: root.notice ? root.notice.body : ""
            textFormat: Text.PlainText
            font.family: QuattroTheme.Theme.fontFamily
            color: QuattroTheme.Theme.text
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            text: !root.clock ? "" : root.clock.persistent ? "Until dismissed"
                : Math.ceil(root.clock.remaining / 1000) + " s" + (root.clock.paused ? " · Paused" : "")
            textFormat: Text.PlainText
            font.family: QuattroTheme.Theme.fontFamily
            color: QuattroTheme.Theme.textMuted
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 2
            visible: root.clock && !root.clock.persistent
            color: QuattroTheme.Theme.border
            Rectangle {
                height: parent.height
                width: root.clock && root.clock.duration > 0 ? parent.width * root.clock.remaining / root.clock.duration : 0
                color: QuattroTheme.Theme.textStrong
            }
        }
        Flow {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: root.notice ? root.notice.actions : []
                delegate: DesktopButton {
                    required property var modelData
                    text: modelData.text || (modelData.identifier === "default" ? "Open" : modelData.identifier)
                    onClicked: if (root.notice) NotificationHistory.invoke(root.notice.id, modelData.identifier)
                }
            }
            DesktopButton { text: "Dismiss"; onClicked: if (root.notice) NotificationHistory.dismiss(root.notice.id) }
        }
    }
}
