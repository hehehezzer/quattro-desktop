import Quickshell
import Quickshell.Wayland
import QtQuick
import "../theme" as QuattroTheme

PanelWindow {
    id: root

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    color: QuattroTheme.Theme.background
    exclusionMode: ExclusionMode.Ignore

    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    WlrLayershell.namespace: "quattro-theme-background"

    // Optional user-provided artwork. The public distribution intentionally
    // ships no wallpapers; a theme-color background remains available on a
    // clean machine. Set QUATTRO_WALLPAPER_DIR to opt into local artwork.
    property string wallpaperDirectory: Quickshell.env("QUATTRO_WALLPAPER_DIR") || ""

    Rectangle {
        anchors.fill: parent
        color: QuattroTheme.Theme.background
    }

    Image {
        id: wallpaper

        anchors.fill: parent
        source: root.wallpaperDirectory === "" ? ""
            : "file://" + root.wallpaperDirectory + "/"
                + QuattroTheme.Theme.current + ".png"
        fillMode: Image.PreserveAspectCrop
        horizontalAlignment: Image.AlignHCenter
        verticalAlignment: Image.AlignVCenter
        asynchronous: true
        cache: true
        smooth: true
        mipmap: true

        opacity: status === Image.Ready ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 280
                easing.type: Easing.OutCubic
            }
        }
    }
}
