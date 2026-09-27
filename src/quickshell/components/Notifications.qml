import Quickshell
import Quickshell.Services.Notifications
import QtQuick
import QtQuick.Controls
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

        implicitWidth: Math.min(360, (screen ? screen.width : 1920) - 24)

        implicitHeight: Math.min(notificationColumn.implicitHeight,
            (screen ? screen.height : 1080) - 54)

        exclusionMode:
            ExclusionMode.Ignore

        color: "transparent"

        Flickable {
            id: notificationViewport
            anchors.fill: parent
            contentWidth: width
            contentHeight: notificationColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            ScrollBar.vertical: ScrollBar {
                policy: notificationViewport.interactive ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
            }

            ColumnLayout {
                id: notificationColumn

                width: notificationViewport.width

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

                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.summary + (modelData.body ? ". " + modelData.body : "")
                    Keys.onReturnPressed: notificationCard.activate()
                    Keys.onSpacePressed: notificationCard.activate()
                    Keys.onEscapePressed: modelData.dismiss()

                    function activate() {
                        const actions = modelData.actions || []
                        const defaultAction = actions.find(action => action.identifier === "default")
                        if (defaultAction)
                            defaultAction.invoke()
                        modelData.dismiss()
                    }

                    radius: QuattroTheme.Theme.cornerRadius

                    color: QuattroTheme.Theme.background

                    border.width: activeFocus ? 2 : 1
                    border.color: activeFocus ? QuattroTheme.Theme.accent : QuattroTheme.Theme.border

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

                            textFormat: Text.PlainText
                            maximumLineCount: 2
                            elide: Text.ElideRight

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

                            maximumLineCount: 5
                            elide: Text.ElideRight

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

                        onClicked: notificationCard.activate()
                    }
                }
            }
        }
    }
}
}
