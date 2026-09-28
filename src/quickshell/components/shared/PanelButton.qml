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
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 1
        height: buttonMouse.containsMouse ? 18 : 8
        color: QuattroTheme.Theme.accent
        opacity: buttonMouse.containsMouse ? 1 : 0

        Behavior on height { NumberAnimation { duration: QuattroTheme.Theme.motionFast } }
        Behavior on opacity { NumberAnimation { duration: QuattroTheme.Theme.motionFast } }
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
