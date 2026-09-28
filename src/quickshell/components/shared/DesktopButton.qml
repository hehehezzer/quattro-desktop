import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

Button {
    id: root
    property bool destructive: false
    property bool prominent: false
    property bool quiet: false
    implicitHeight: QuattroTheme.Theme.compactTarget
    implicitWidth: Math.max(QuattroTheme.Theme.compactTarget, contentItem.implicitWidth + 20)
    font.family: QuattroTheme.Theme.fontFamily
    font.pixelSize: QuattroTheme.Theme.typeBody
    hoverEnabled: true
    opacity: enabled ? 1 : QuattroTheme.Theme.disabledOpacity
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
        y: QuattroTheme.Theme.iconOpticalOffsetY
    }
    background: Rectangle {
        radius: QuattroTheme.Theme.cornerRadius
        color: root.prominent ? QuattroTheme.Theme.textStrong
            : root.down ? QuattroTheme.Theme.pressed
            : root.hovered ? QuattroTheme.Theme.hover
            : root.quiet ? "transparent"
            : QuattroTheme.Theme.surfaceRaised
        border.width: root.activeFocus ? QuattroTheme.Theme.focusLine
            : root.destructive || root.prominent ? 1 : 0
        border.color: root.activeFocus ? QuattroTheme.Theme.accent
            : root.destructive ? QuattroTheme.Theme.danger
            : QuattroTheme.Theme.border

        Behavior on color {
            ColorAnimation { duration: QuattroTheme.Theme.motionFast }
        }
    }
    ToolTip.visible: hovered && ToolTip.text.length > 0
    ToolTip.delay: 700
}
