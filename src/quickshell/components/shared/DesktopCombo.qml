import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

ComboBox {
    id: root
    implicitHeight: 32
    palette.button: QuattroTheme.Theme.surface
    palette.buttonText: QuattroTheme.Theme.textStrong
    palette.base: QuattroTheme.Theme.surface
    palette.text: QuattroTheme.Theme.textStrong
    palette.highlight: QuattroTheme.Theme.hover
    palette.highlightedText: QuattroTheme.Theme.textStrong
    font.pixelSize: 11
    contentItem: Text {
        leftPadding: 8
        rightPadding: 24
        text: root.displayText
        color: QuattroTheme.Theme.textStrong
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        color: QuattroTheme.Theme.surface
        border.width: 1
        border.color: root.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.border
        radius: QuattroTheme.Theme.cornerRadius
    }
}
