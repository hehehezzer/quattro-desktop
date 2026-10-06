import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

Button {
    id: root
    property bool destructive: false
    property bool prominent: false
    property bool quiet: false
    // Keep the installed icon face independent from ordinary control labels.
    readonly property bool iconOnly: /^[\uE000-\uF8FF\u{F0000}-\u{FFFFD}\u{100000}-\u{10FFFD}]$/u.test(text)
    readonly property font glyphFont: Qt.font({ family: QuattroTheme.Theme.iconFontFamily,
        pixelSize: root.font.pixelSize, weight: root.font.weight })
    implicitHeight: QuattroTheme.Theme.compactTarget
    implicitWidth: Math.max(QuattroTheme.Theme.compactTarget, contentItem.implicitWidth + 20)
    font.family: QuattroTheme.Theme.fontFamily
    font.pixelSize: QuattroTheme.Theme.typeBody
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : QuattroTheme.Theme.disabledOpacity
    Accessible.name: text
    Accessible.description: ToolTip.text
    contentItem: Text {
        text: root.text
        font: root.iconOnly ? root.glyphFont : root.font
        color: !root.enabled ? QuattroTheme.Theme.textDim
            : root.prominent ? QuattroTheme.Theme.background
            : root.destructive ? QuattroTheme.Theme.danger
            : QuattroTheme.Theme.textStrong
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        y: root.iconOnly ? QuattroTheme.Theme.iconOpticalOffsetY : 0
    }
    background: Rectangle {
        radius: QuattroTheme.Theme.cornerRadius
        color: root.prominent ? (QuattroTheme.Theme.isInstrument && (root.down || root.hovered)
            ? QuattroTheme.Theme.text : QuattroTheme.Theme.textStrong)
            : root.down ? QuattroTheme.Theme.pressed
            : root.hovered ? QuattroTheme.Theme.hover
            : root.quiet ? "transparent"
            : QuattroTheme.Theme.surfaceRaised
        border.width: root.activeFocus ? QuattroTheme.Theme.focusLine
            : QuattroTheme.Theme.isInstrument && !root.quiet ? 1
            : root.destructive || root.prominent ? 1 : 0
        border.color: root.activeFocus ? (QuattroTheme.Theme.isInstrument
            ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.accent)
            : root.destructive ? QuattroTheme.Theme.danger
            : QuattroTheme.Theme.isInstrument && root.hovered ? QuattroTheme.Theme.borderStrong : QuattroTheme.Theme.border

        Behavior on color {
            ColorAnimation { duration: QuattroTheme.Theme.motionFast }
        }
    }
    // Preserve existing callers' attached ToolTip.text as the content API.
    ToolTip.visible: false
    HoverTooltip {
        target: root
        text: root.ToolTip.text
        hoverActive: root.hovered
        focusActive: root.activeFocus
    }
}
