import QtQuick
import QtQuick.Layouts
import "../../theme" as QuattroTheme

Rectangle {
    id: button

    required property string label

    signal clicked()

    Layout.fillWidth: true
    implicitHeight: 42

    radius: QuattroTheme.Theme.cornerRadius

    color:
        buttonMouse.containsMouse
        ? QuattroTheme.Theme.border
        : QuattroTheme.Theme.surface

    Text {
        anchors {
            left: parent.left
            right: parent.right

            leftMargin: 12
            rightMargin: 12

            verticalCenter:
                parent.verticalCenter
        }

        text:
            button.label

        color: QuattroTheme.Theme.textStrong

        font.family:
            "JetBrainsMono Nerd Font"

        font.pixelSize: 12

        wrapMode:
            Text.Wrap
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
