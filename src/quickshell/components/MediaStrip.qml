import Quickshell
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "shared"
import "../services"
import "../theme" as QuattroTheme

Rectangle {
    id: root
    signal openRequested()
    readonly property var player: DesktopMedia.player
    readonly property bool hasTrack: !!player && !!player.trackTitle
    implicitWidth: 360
    implicitHeight: 32
    visible: !!player
    color: QuattroTheme.Theme.surface
    border.width: 1
    border.color: QuattroTheme.Theme.border

    function duration(seconds) {
        const n = Math.max(0, Math.floor(seconds || 0))
        return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0")
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 3
        spacing: 5
        Item {
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            Rectangle {
                anchors.fill: parent
                color: QuattroTheme.Theme.surfaceRaised
                Text {
                    anchors.centerIn: parent
                    text: "󰓇"
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: 15
                    color: QuattroTheme.Theme.accent
                }
            }
            Image {
                anchors.fill: parent
                source: DesktopMedia.artwork
                sourceSize.width: 48
                sourceSize.height: 48
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                visible: status === Image.Ready
            }
            TapHandler { onTapped: root.openRequested() }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            spacing: 0
            Text {
                Layout.fillWidth: true
                text: root.hasTrack ? root.player.trackTitle : "Spotify"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: QuattroTheme.Theme.textStrong
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 10
                font.bold: true
            }
            Text {
                Layout.fillWidth: true
                visible: root.width >= 200
                text: root.hasTrack ? (root.player.trackArtist || (root.player.isPlaying ? "Playing" : "Paused")) : "No active track"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 9
            }
            TapHandler { onTapped: root.openRequested() }
        }
        Text {
            visible: root.width >= 325 && root.hasTrack && root.player.lengthSupported && root.player.positionSupported
            text: root.duration(DesktopMedia.position) + " / " + root.duration(root.player ? root.player.length : 0)
            color: QuattroTheme.Theme.textMuted
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 9
        }
        DesktopButton {
            text: "󰒮"
            visible: root.width >= 240
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: "Spotify previous track"
            ToolTip.text: Accessible.name
            enabled: root.hasTrack && root.player.canControl && root.player.canGoPrevious
            onClicked: root.player.previous()
        }
        DesktopButton {
            text: root.player && root.player.isPlaying ? "󰏤" : "󰐊"
            visible: root.width >= 240
            implicitWidth: 30
            implicitHeight: 28
            prominent: true
            Accessible.name: root.player && root.player.isPlaying ? "Pause Spotify" : "Play Spotify"
            ToolTip.text: Accessible.name
            enabled: root.hasTrack && root.player.canControl && root.player.canTogglePlaying
            onClicked: root.player.togglePlaying()
        }
        DesktopButton {
            text: "󰒭"
            visible: root.width >= 240
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: "Spotify next track"
            ToolTip.text: Accessible.name
            enabled: root.hasTrack && root.player.canControl && root.player.canGoNext
            onClicked: root.player.next()
        }
    }
    Rectangle {
        anchors.bottom: parent.bottom
        height: 2
        width: root.hasTrack && root.player.lengthSupported && root.player.length > 0
            ? parent.width * Math.min(1, DesktopMedia.position / root.player.length) : 0
        color: QuattroTheme.Theme.accent
    }
    HoverHandler { id: hover }
    ToolTip.visible: hover.hovered
    ToolTip.delay: 900
    ToolTip.text: root.hasTrack
        ? "Spotify · " + root.player.trackTitle + "\n" + root.player.trackArtist
        : "Spotify · no active track"
}
