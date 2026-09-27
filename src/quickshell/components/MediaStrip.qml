import Quickshell
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "shared"
import "../services"
import "../theme" as QuattroTheme

Rectangle {
    id: root
    property var player: DesktopMedia.player
    implicitWidth: 310
    implicitHeight: 28
    visible: !!player
    radius: QuattroTheme.Theme.cornerRadius
    color: QuattroTheme.Theme.surface
    function duration(seconds) {
        const n = Math.max(0, Math.floor(seconds || 0));
        return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0");
    }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 5
        anchors.rightMargin: 3
        spacing: 3
        Image {
            Layout.preferredWidth: 18
            Layout.preferredHeight: 18
            source: root.player ? Quickshell.iconPath(root.player.desktopEntry, "audio-x-generic") : ""
            sourceSize.width: 18
            sourceSize.height: 18
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Text {
                Layout.fillWidth: true
                text: root.player ? root.player.trackTitle || root.player.identity : ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: QuattroTheme.Theme.textStrong
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 10
            }
            Text {
                Layout.fillWidth: true
                text: root.player ? root.player.trackArtist : ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: QuattroTheme.Theme.textMuted
                font.pixelSize: 9
            }
        }
        Text {
            visible: root.width >= 310 && root.player && root.player.lengthSupported && root.player.positionSupported
            text: root.duration(DesktopMedia.position) + "/" + root.duration(root.player ? root.player.length : 0)
            color: QuattroTheme.Theme.textMuted
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 9
        }
        DesktopButton {
            text: "󰒮"
            implicitWidth: 26
            implicitHeight: 24
            Accessible.name: "Previous track"
            ToolTip.text: "Previous track"
            enabled: !!root.player && root.player.canControl && root.player.canGoPrevious
            onClicked: root.player.previous()
        }
        DesktopButton {
            text: root.player && root.player.isPlaying ? "󰏤" : "󰐊"
            implicitWidth: 26
            implicitHeight: 24
            Accessible.name: root.player && root.player.isPlaying ? "Pause" : "Play"
            ToolTip.text: Accessible.name
            enabled: !!root.player && root.player.canControl && root.player.canTogglePlaying
            onClicked: root.player.togglePlaying()
        }
        DesktopButton {
            text: "󰒭"
            implicitWidth: 26
            implicitHeight: 24
            Accessible.name: "Next track"
            ToolTip.text: "Next track"
            enabled: !!root.player && root.player.canControl && root.player.canGoNext
            onClicked: root.player.next()
        }
    }
    Rectangle {
        anchors.bottom: parent.bottom
        height: 1
        width: root.player && root.player.lengthSupported && root.player.length > 0 ? parent.width * Math.min(1, DesktopMedia.position / root.player.length) : 0
        color: QuattroTheme.Theme.textStrong
    }
    HoverHandler {
        id: hover
    }
    ToolTip.visible: hover.hovered
    ToolTip.delay: 900
    ToolTip.text: root.player ? root.player.identity + " · " + root.player.trackTitle + "\n" + root.player.trackArtist : ""
}
