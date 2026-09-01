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

    implicitHeight: 31

    radius: QuattroTheme.Theme.cornerRadius

    color:
        button.accent
        ? QuattroTheme.Theme.accent
        : buttonMouse.containsMouse
        ? QuattroTheme.Theme.border
        : QuattroTheme.Theme.border

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
            "JetBrainsMono Nerd Font"

        font.pixelSize: 10

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
