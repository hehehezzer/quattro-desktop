import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

TextField {
    id: root
    implicitHeight: QuattroTheme.Theme.compactTarget
    color: QuattroTheme.Theme.textStrong
    placeholderTextColor: QuattroTheme.Theme.textMuted
    selectionColor: QuattroTheme.Theme.hover
    selectedTextColor: QuattroTheme.Theme.textStrong
    font.family: QuattroTheme.Theme.fontFamily
    font.pixelSize: QuattroTheme.Theme.typeBody
    leftPadding: QuattroTheme.Theme.spaceSm
    rightPadding: QuattroTheme.Theme.spaceSm
    hoverEnabled: true
    opacity: enabled ? 1 : QuattroTheme.Theme.disabledOpacity
    background: Rectangle {
        color: QuattroTheme.Theme.surface
        border.width: root.activeFocus ? QuattroTheme.Theme.focusLine : QuattroTheme.Theme.isInstrument ? 1 : 0
        border.color: root.activeFocus ? QuattroTheme.Theme.textStrong
            : root.hovered ? QuattroTheme.Theme.borderStrong : QuattroTheme.Theme.border
        radius: QuattroTheme.Theme.cornerRadius
    }
}
