import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

TextField {
    id: root
    implicitHeight: 32
    color: QuattroTheme.Theme.textStrong
    placeholderTextColor: QuattroTheme.Theme.textMuted
    selectionColor: QuattroTheme.Theme.hover
    selectedTextColor: QuattroTheme.Theme.textStrong
    font.pixelSize: 11
    background: Rectangle {
        color: QuattroTheme.Theme.surface
        border.width: 1
        border.color: root.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.border
        radius: QuattroTheme.Theme.cornerRadius
    }
}
