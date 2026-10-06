pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import "../../theme" as QuattroTheme

ComboBox {
    id: root
    implicitHeight: QuattroTheme.Theme.compactTarget
    font.family: QuattroTheme.Theme.fontFamily
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    opacity: enabled ? 1 : QuattroTheme.Theme.disabledOpacity
    palette.button: QuattroTheme.Theme.surface
    palette.buttonText: QuattroTheme.Theme.textStrong
    palette.base: QuattroTheme.Theme.surface
    palette.text: QuattroTheme.Theme.textStrong
    palette.highlight: QuattroTheme.Theme.hover
    palette.highlightedText: QuattroTheme.Theme.textStrong
    font.pixelSize: QuattroTheme.Theme.typeBody
    indicator: Text {
        x: root.width - width - 9
        height: root.height
        text: "󰅀"
        color: root.enabled ? QuattroTheme.Theme.textMuted : QuattroTheme.Theme.textDim
        font.family: QuattroTheme.Theme.iconFontFamily
        font.pixelSize: QuattroTheme.Theme.iconSmall
        width: 16
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    contentItem: Text {
        leftPadding: 8
        rightPadding: 26
        text: root.displayText
        color: root.enabled ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textDim
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        color: root.down ? QuattroTheme.Theme.pressed
            : root.hovered || root.popup.visible ? QuattroTheme.Theme.hover : QuattroTheme.Theme.surface
        border.width: root.activeFocus ? QuattroTheme.Theme.focusLine : QuattroTheme.Theme.isInstrument ? 1 : 0
        border.color: root.activeFocus ? QuattroTheme.Theme.textStrong
            : root.hovered ? QuattroTheme.Theme.borderStrong : QuattroTheme.Theme.border
        radius: QuattroTheme.Theme.cornerRadius
    }
    delegate: ItemDelegate {
        id: option
        required property int index
        required property var modelData
        width: root.popup.width - root.popup.leftPadding - root.popup.rightPadding
        height: 32
        hoverEnabled: true
        highlighted: root.highlightedIndex === option.index
        contentItem: Text {
            leftPadding: 8
            rightPadding: 8
            text: option.modelData
            color: option.enabled ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textDim
            font: root.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            color: option.highlighted || option.hovered ? QuattroTheme.Theme.hover : "transparent"
            border.width: option.activeFocus ? QuattroTheme.Theme.focusLine : 0
            border.color: QuattroTheme.Theme.textStrong
            radius: QuattroTheme.Theme.cornerRadius
        }
    }
    popup: Popup {
        y: root.height + QuattroTheme.Theme.spaceXs
        width: root.width
        padding: QuattroTheme.Theme.spaceXs
        implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, 200)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }
        background: Rectangle {
            color: QuattroTheme.Theme.surfaceRaised
            border.width: 1
            border.color: QuattroTheme.Theme.borderStrong
            radius: QuattroTheme.Theme.cornerRadius
        }
    }
}
