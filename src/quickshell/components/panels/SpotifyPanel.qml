import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../shared"
import "../../services"
import "../../theme" as QuattroTheme

Item {
    id: root
    readonly property var player: DesktopMedia.player
    readonly property bool hasTrack: !!player && !!player.trackTitle
    readonly property bool hasProgress: hasTrack && player.lengthSupported && player.positionSupported && player.length > 0

    function duration(seconds) {
        const n = Math.max(0, Math.floor(seconds || 0));
        return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0");
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: QuattroTheme.Theme.spaceMd

        RowLayout {
            Layout.fillWidth: true
            spacing: QuattroTheme.Theme.spaceLg
            Item {
                Layout.preferredWidth: Math.min(92, Math.max(72, root.width * 0.24))
                Layout.preferredHeight: width
                Rectangle {
                    anchors.fill: parent
                    color: QuattroTheme.Theme.surfaceRaised
                    Text {
                        anchors.centerIn: parent
                        text: "󰓇"
                        color: QuattroTheme.Theme.accent
                        font.family: QuattroTheme.Theme.iconFontFamily
                        font.pixelSize: 34
                    }
                }
                Image {
                    anchors.fill: parent
                    source: DesktopMedia.artwork
                    sourceSize.width: 240
                    sourceSize.height: 240
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    visible: status === Image.Ready
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: QuattroTheme.Theme.spaceXs
                Text {
                    Layout.fillWidth: true
                    text: root.hasTrack ? root.player.trackTitle : root.player ? "Ready to play" : "Spotify is closed"
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    color: QuattroTheme.Theme.textStrong
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeTitle
                    font.bold: true
                }
                Text {
                    Layout.fillWidth: true
                    text: root.hasTrack ? (root.player.trackArtist || "Artist unavailable") : root.player ? "Choose a track in Spotify" : "Open Spotify to see your music here"
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    color: QuattroTheme.Theme.text
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeBody
                }
                Text {
                    visible: root.hasTrack && !!root.player.trackAlbum
                    Layout.fillWidth: true
                    text: root.hasTrack ? root.player.trackAlbum : ""
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeMeta
                }
                Text {
                    text: root.player ? root.hasTrack ? root.player.isPlaying ? "PLAYING" : "PAUSED" : "IDLE" : "UNAVAILABLE"
                    color: root.player && root.player.isPlaying ? QuattroTheme.Theme.success : QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeMicro
                    font.letterSpacing: 1
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: QuattroTheme.Theme.spaceXs
            Slider {
                id: progress
                Layout.fillWidth: true
                Layout.preferredHeight: 24
                from: 0
                to: root.hasProgress ? root.player.length : 1
                value: root.hasProgress ? Math.min(root.player.length, DesktopMedia.position) : 0
                enabled: root.hasProgress && root.player.canSeek
                Accessible.name: "Spotify playback position"
                onMoved: if (root.player && root.player.canSeek)
                    root.player.position = value
                background: Rectangle {
                    x: progress.leftPadding
                    y: progress.topPadding + progress.availableHeight / 2 - height / 2
                    width: progress.availableWidth
                    height: 4
                    color: QuattroTheme.Theme.border
                    Rectangle {
                        width: parent.width * progress.visualPosition
                        height: parent.height
                        color: QuattroTheme.Theme.accent
                    }
                }
                handle: Rectangle {
                    x: progress.leftPadding + progress.visualPosition * (progress.availableWidth - width)
                    y: progress.topPadding + progress.availableHeight / 2 - height / 2
                    width: 10
                    height: 10
                    color: progress.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.accent
                    visible: progress.hovered || progress.pressed || progress.activeFocus
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: root.hasProgress ? root.duration(DesktopMedia.position) : "—:—"
                    color: QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeMeta
                }
                Item {
                    Layout.fillWidth: true
                }
                Text {
                    text: root.hasProgress ? root.duration(root.player.length) : "—:—"
                    color: QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeMeta
                }
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: QuattroTheme.Theme.spaceXs
            DesktopButton {
                text: "󰒮"
                quiet: true
                implicitWidth: 44
                implicitHeight: 40
                Accessible.name: "Spotify previous track"
                ToolTip.text: Accessible.name
                enabled: root.hasTrack && root.player.canControl && root.player.canGoPrevious
                onClicked: root.player.previous()
            }
            DesktopButton {
                text: root.player && root.player.isPlaying ? "󰏤" : "󰐊"
                implicitWidth: 48
                implicitHeight: 44
                prominent: true
                Accessible.name: root.player && root.player.isPlaying ? "Pause Spotify" : "Play Spotify"
                ToolTip.text: Accessible.name
                enabled: root.hasTrack && root.player.canControl && root.player.canTogglePlaying
                onClicked: root.player.togglePlaying()
            }
            DesktopButton {
                text: "󰒭"
                quiet: true
                implicitWidth: 44
                implicitHeight: 40
                Accessible.name: "Spotify next track"
                ToolTip.text: Accessible.name
                enabled: root.hasTrack && root.player.canControl && root.player.canGoNext
                onClicked: root.player.next()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 1
            color: QuattroTheme.Theme.border
        }

        LyricsView {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}
