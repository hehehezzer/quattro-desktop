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

    color:
        button.accent
        ? QuattroTheme.Theme.accent
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
            button.clicked()
        }
    }
}
