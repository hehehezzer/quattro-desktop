import Quickshell
import Quickshell.Services.Notifications
import QtQuick
import QtQuick.Layouts
import "../theme" as QuattroTheme

Scope {
    NotificationServer {
        id: notificationServer

        bodySupported: true
        actionsSupported: true

        onNotification: notification => {
            notification.tracked = true
        }
    }

    PanelWindow {
        anchors {
            top: true
            right: true
        }

        margins {
            top: 42
            right: 12
        }

        implicitWidth: 360

        implicitHeight:
            notificationColumn.implicitHeight

        exclusionMode:
            ExclusionMode.Ignore

        color: "transparent"

        ColumnLayout {
            id: notificationColumn

            width: parent.width

            spacing: 8

            Repeater {
                model:
                    notificationServer
                    .trackedNotifications

                delegate: Rectangle {
                    id: notificationCard

                    required property var modelData

                    Layout.fillWidth: true

                    implicitHeight:
                        content.implicitHeight + 24

                    radius: QuattroTheme.Theme.cornerRadius

                    color: QuattroTheme.Theme.background

                    border.width: 1
                    border.color: QuattroTheme.Theme.border

                    property bool hovered:
                        notificationMouse.containsMouse

                    Timer {
                        id: dismissTimer

                        interval: 5000
                        repeat: false

                        running:
                            notificationCard.visible
                            && !notificationCard.hovered

                        onTriggered: {
                            notificationCard
                                .modelData
                                .dismiss()
                        }
                    }

                    onHoveredChanged: {
                        if (hovered) {
                            dismissTimer.stop()
                        } else {
                            dismissTimer.restart()
                        }
                    }

                    ColumnLayout {
                        id: content

                        anchors {
                            left: parent.left
                            right: parent.right
                            top: parent.top

                            margins: 12
                        }

                        spacing: 6

                        Text {
                            text:
                                modelData.summary

                            color: QuattroTheme.Theme.textStrong

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.bold: true

                            Layout.fillWidth: true

                            wrapMode:
                                Text.Wrap
                        }

                        Text {
                            visible:
                                modelData.body !== ""

                            text:
                                modelData.body

                            textFormat:
                                Text.PlainText

                            color: QuattroTheme.Theme.text

                            font.family:
                                "JetBrainsMono Nerd Font"

                            Layout.fillWidth: true

                            wrapMode:
                                Text.Wrap
                        }
                    }

                    MouseArea {
                        id: notificationMouse

                        anchors.fill: parent

                        hoverEnabled: true

                        cursorShape:
                            Qt.PointingHandCursor

                        onClicked: {
                            // Discord and most notification senders expose their
                            // message target as the D-Bus default action.
                            // Invoke it before dismissing so a click opens the
                            // exact message/channel instead of only clearing UI.
                            const actions = modelData.actions || []
                            const defaultAction = actions.find(action => action.identifier === "default")
                            if (defaultAction)
                                defaultAction.invoke()
                            modelData.dismiss()
                        }
                    }
                }
            }
        }
    }
}
