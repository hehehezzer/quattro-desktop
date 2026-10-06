import Quickshell
import Quickshell.Services.SystemTray
import QtQuick
import QtQuick.Controls
import "../theme" as QuattroTheme

// Native application tray actions remain available inside the application panel.
Flow {
    id: root
    required property var hostWindow
    spacing: QuattroTheme.Theme.spaceSm
    visible: SystemTray.items.values.length > 0
        Repeater {
            model: SystemTray.items

            delegate: Rectangle {
                id: trayEntry

                required property var modelData

                implicitWidth: QuattroTheme.Theme.compactTarget
                implicitHeight: QuattroTheme.Theme.barControlHeight

                radius: QuattroTheme.Theme.cornerRadius
                activeFocusOnTab: true
                border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
                border.color: QuattroTheme.Theme.textStrong
                Accessible.role: Accessible.Button
                Accessible.name: modelData.title || "Tray application"
                Accessible.onPressAction: modelData.onlyMenu && modelData.hasMenu ? trayMouse.openMenu() : modelData.activate()
                Keys.onReturnPressed: modelData.onlyMenu && modelData.hasMenu ? trayMouse.openMenu() : modelData.activate()
                Keys.onEnterPressed: modelData.onlyMenu && modelData.hasMenu ? trayMouse.openMenu() : modelData.activate()
                Keys.onSpacePressed: modelData.onlyMenu && modelData.hasMenu ? trayMouse.openMenu() : modelData.activate()
                Keys.onMenuPressed: trayMouse.openMenu()

                color:
                    trayMouse.containsMouse
                    ? QuattroTheme.Theme.hover
                    : "transparent"

                Image {
                    anchors.centerIn: parent

                    width: QuattroTheme.Theme.iconMedium
                    height: QuattroTheme.Theme.iconMedium

                    source: trayEntry.modelData.icon

                    sourceSize.width: QuattroTheme.Theme.iconMedium
                    sourceSize.height: QuattroTheme.Theme.iconMedium

                    fillMode: Image.PreserveAspectFit

                    smooth: true
                }

                MouseArea {
                    id: trayMouse

                    anchors.fill: parent

                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor

                    acceptedButtons:
                        Qt.LeftButton
                        | Qt.MiddleButton
                        | Qt.RightButton

                    function openMenu() {
                        const item = trayEntry.modelData

                        if (!item.hasMenu)
                            return

                        const pos = trayEntry.mapToItem(
                            root.hostWindow.contentItem,
                            0,
                            trayEntry.height
                        )

                        item.display(
                            root.hostWindow,
                            pos.x,
                            pos.y
                        )
                    }

                    onClicked: mouse => {
                        trayEntry.forceActiveFocus(Qt.MouseFocusReason)
                        const item = trayEntry.modelData

                        if (mouse.button === Qt.LeftButton) {
                            if (
                                item.onlyMenu
                                && item.hasMenu
                            ) {
                                openMenu()
                            } else {
                                item.activate()
                            }

                            return
                        }

                        if (mouse.button === Qt.MiddleButton) {
                            item.secondaryActivate()
                            return
                        }

                        if (mouse.button === Qt.RightButton) {
                            openMenu()
                        }
                    }

                    onWheel: wheel => {
                        trayEntry.modelData.scroll(
                            wheel.angleDelta.y,
                            false
                        )
                    }
                }
            }
        }

}
