import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

Button {
    id: root
    property bool destructive: false
    property bool prominent: false
    implicitHeight: QuattroTheme.Theme.compactTarget
    implicitWidth: Math.max(QuattroTheme.Theme.compactTarget, contentItem.implicitWidth + 20)
    font.family: QuattroTheme.Theme.fontFamily
    font.pixelSize: 11
    hoverEnabled: true
    Accessible.name: text
    contentItem: Text {
        text: root.text
        font: root.font
        color: !root.enabled ? QuattroTheme.Theme.textDim
            : root.prominent ? QuattroTheme.Theme.background
            : root.destructive ? QuattroTheme.Theme.danger
            : QuattroTheme.Theme.textStrong
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: QuattroTheme.Theme.cornerRadius
        color: root.prominent ? QuattroTheme.Theme.textStrong
            : root.down || root.hovered ? QuattroTheme.Theme.hover
            : QuattroTheme.Theme.surfaceRaised
        border.width: root.activeFocus ? 2 : 1
        border.color: root.activeFocus ? QuattroTheme.Theme.accent
            : root.destructive ? QuattroTheme.Theme.danger
            : QuattroTheme.Theme.border
    }
    ToolTip.visible: hovered && ToolTip.text.length > 0
    ToolTip.delay: 700
}
