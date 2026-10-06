import QtQuick
import QtQuick.Layouts
import "../../theme" as QuattroTheme

Rectangle {
    id: button

    required property string label

    signal clicked()

    Layout.fillWidth: true
    implicitHeight: QuattroTheme.Theme.primaryTarget

    radius: QuattroTheme.Theme.cornerRadius
    activeFocusOnTab: true
    opacity: enabled ? 1 : QuattroTheme.Theme.disabledOpacity
    border.width: activeFocus ? QuattroTheme.Theme.focusLine : QuattroTheme.Theme.isInstrument ? 1 : 0
    border.color: activeFocus ? QuattroTheme.Theme.textStrong
        : buttonMouse.containsMouse ? QuattroTheme.Theme.borderStrong : QuattroTheme.Theme.border
    Accessible.role: Accessible.Button
    Accessible.name: label
    Accessible.onPressAction: button.clicked()
    Keys.onReturnPressed: button.clicked()
    Keys.onEnterPressed: button.clicked()
    Keys.onSpacePressed: button.clicked()

    color:
        buttonMouse.pressed
        ? QuattroTheme.Theme.pressed
        : buttonMouse.containsMouse
        ? QuattroTheme.Theme.hover
        : QuattroTheme.Theme.surface

    Text {
        anchors {
            left: parent.left
            right: parent.right

            leftMargin: QuattroTheme.Theme.spaceMd
            rightMargin: QuattroTheme.Theme.spaceMd

            verticalCenter:
                parent.verticalCenter
        }

        text:
            button.label

        color: QuattroTheme.Theme.textStrong

        font.family:
            QuattroTheme.Theme.fontFamily

        font.pixelSize: QuattroTheme.Theme.typeLabel

        wrapMode:
            Text.Wrap
    }

    Rectangle {
        visible: !QuattroTheme.Theme.isInstrument
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 1
        height: buttonMouse.containsMouse ? 18 : 8
        color: QuattroTheme.Theme.accent
        opacity: buttonMouse.containsMouse ? 1 : 0

    }

    MouseArea {
        id: buttonMouse

        anchors.fill: parent

        hoverEnabled: true

        cursorShape:
            Qt.PointingHandCursor

        onClicked: {
            button.forceActiveFocus(Qt.MouseFocusReason)
            button.clicked()
        }
    }
}
