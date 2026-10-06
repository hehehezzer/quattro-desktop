import "../../theme" as QuattroTheme
import QtQuick

Rectangle {
    id: button

    required property string label

    property bool accent: false

    signal clicked()

    implicitWidth:
        Math.max(
            78,
            buttonText.implicitWidth + 22
        )

    implicitHeight: QuattroTheme.Theme.compactTarget

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
        button.accent
        ? (QuattroTheme.Theme.isInstrument && (buttonMouse.pressed || buttonMouse.containsMouse)
            ? QuattroTheme.Theme.text : QuattroTheme.Theme.accent)
        : buttonMouse.pressed
        ? QuattroTheme.Theme.pressed
        : buttonMouse.containsMouse
        ? QuattroTheme.Theme.hover
        : QuattroTheme.Theme.surfaceRaised

    Text {
        id: buttonText

        anchors.centerIn: parent

        text:
            button.label

        color:
            button.accent
            ? QuattroTheme.Theme.background
            : QuattroTheme.Theme.text

        font.family:
            QuattroTheme.Theme.fontFamily

        font.pixelSize: QuattroTheme.Theme.typeMeta

        font.bold:
            button.accent
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
