import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

Button {
    id: root
    implicitHeight: 30
    implicitWidth: Math.max(30, contentItem.implicitWidth + 18)
    font.family: "JetBrainsMono Nerd Font"
    font.pixelSize: 11
    hoverEnabled: true
    Accessible.name: text
    contentItem: Text {
        text: root.text
        font: root.font
        color: root.enabled ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textDim
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: QuattroTheme.Theme.cornerRadius
        color: root.down || root.hovered ? QuattroTheme.Theme.hover : QuattroTheme.Theme.surfaceRaised
        border.width: 1
        border.color: root.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.border
    }
    ToolTip.visible: hovered && ToolTip.text.length > 0
    ToolTip.delay: 700
}
