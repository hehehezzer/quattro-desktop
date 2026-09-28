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
    font.pixelSize: QuattroTheme.Theme.typeBody
    background: Rectangle {
        color: QuattroTheme.Theme.surface
        border.width: root.activeFocus ? QuattroTheme.Theme.focusLine : 0
        border.color: root.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.border
        radius: QuattroTheme.Theme.cornerRadius
    }
}
