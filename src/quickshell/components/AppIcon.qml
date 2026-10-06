import QtQuick
import Quickshell
import "../theme" as QuattroTheme

// Desktop metadata is the only source of app branding; missing icons stay generic.
Item {
    id: root
    property var desktopEntry: null
    property string iconName: desktopEntry ? desktopEntry.icon : ""
    readonly property string resolvedSource: iconName ? Quickshell.iconPath(iconName, true) : ""
    implicitWidth: 24
    implicitHeight: 24
    Image {
        id: artwork
        anchors.fill: parent
        source: root.resolvedSource
        sourceSize.width: root.width
        sourceSize.height: root.height
        fillMode: Image.PreserveAspectFit
        visible: source.toString() !== "" && status === Image.Ready
    }
    Text {
        anchors.centerIn: parent
        visible: !artwork.visible
        text: "󰀻"
        color: QuattroTheme.Theme.textMuted
        font.family: QuattroTheme.Theme.iconFontFamily
        font.pixelSize: 20
    }
}
