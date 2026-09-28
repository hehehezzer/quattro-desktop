import Quickshell
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../services"
import "../theme" as QuattroTheme

Item {
    id: root

    signal openRequested()

    readonly property var player: DesktopMedia.player
    readonly property bool hasTrack: !!player && !!player.trackTitle
    readonly property bool controlsVisible: !!player && width >= 286
    implicitWidth: 360
    implicitHeight: QuattroTheme.Theme.barControlHeight

    Rectangle {
        anchors.fill: parent
        radius: QuattroTheme.Theme.cornerRadius
        color: stripHover.hovered ? QuattroTheme.Theme.hover : "transparent"

        Behavior on color {
            ColorAnimation { duration: QuattroTheme.Theme.motionFast }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: QuattroTheme.Theme.spaceSm

        Item {
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28

            Rectangle {
                anchors.fill: parent
                radius: QuattroTheme.Theme.cornerRadius
                color: root.player ? QuattroTheme.Theme.surfaceRaised : "transparent"

                Text {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
                    text: "󰓇"
                    font.family: QuattroTheme.Theme.iconFontFamily
                    font.pixelSize: QuattroTheme.Theme.iconMedium
                    color: root.player ? QuattroTheme.Theme.accent : QuattroTheme.Theme.textMuted
                }
            }

            Image {
                anchors.fill: parent
                source: DesktopMedia.artwork
                sourceSize.width: 56
                sourceSize.height: 56
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
                font.family: QuattroTheme.Theme.fontFamily
                font.pixelSize: QuattroTheme.Theme.typeMeta
                font.bold: true
            }

            Text {
                Layout.fillWidth: true
                visible: root.width >= 150
                text: root.hasTrack
                    ? (root.player.trackArtist || (root.player.isPlaying ? "Playing" : "Paused"))
                    : root.player ? "Ready" : "Closed"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: root.player && root.player.isPlaying
                    ? QuattroTheme.Theme.success
                    : QuattroTheme.Theme.textMuted
                font.family: QuattroTheme.Theme.fontFamily
                font.pixelSize: QuattroTheme.Theme.typeMicro
            }

            TapHandler { onTapped: root.openRequested() }
        }

        RowLayout {
            visible: root.controlsVisible
            spacing: 0

            TransportButton {
                glyph: "󰒮"
                accessibleName: "Spotify previous track"
                enabled: root.hasTrack && root.player.canControl && root.player.canGoPrevious
                onActivated: root.player.previous()
            }

            TransportButton {
                glyph: root.player && root.player.isPlaying ? "󰏤" : "󰐊"
                accessibleName: root.player && root.player.isPlaying ? "Pause Spotify" : "Play Spotify"
                primary: true
                enabled: root.hasTrack && root.player.canControl && root.player.canTogglePlaying
                onActivated: root.player.togglePlaying()
            }

            TransportButton {
                glyph: "󰒭"
                accessibleName: "Spotify next track"
                enabled: root.hasTrack && root.player.canControl && root.player.canGoNext
                onActivated: root.player.next()
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 36
        anchors.right: parent.right
        anchors.rightMargin: root.controlsVisible ? 92 : 0
        anchors.bottom: parent.bottom
        height: 1
        color: QuattroTheme.Theme.border
        opacity: root.hasTrack ? 1 : 0

        Rectangle {
            height: parent.height
            width: root.hasTrack && root.player.lengthSupported && root.player.length > 0
                ? parent.width * Math.min(1, DesktopMedia.position / root.player.length) : 0
            color: QuattroTheme.Theme.accent

            Behavior on width {
                NumberAnimation { duration: QuattroTheme.Theme.motionFast }
            }
        }
    }

    HoverHandler { id: stripHover }

    ToolTip.visible: stripHover.hovered
    ToolTip.delay: 900
    ToolTip.text: root.hasTrack
        ? "Spotify · " + root.player.trackTitle + "\n" + root.player.trackArtist
        : root.player ? "Spotify · ready" : "Spotify · closed"

    component TransportButton: Item {
        id: transport
        required property string glyph
        required property string accessibleName
        property bool primary: false
        signal activated()

        Layout.preferredWidth: primary ? 30 : 28
        Layout.preferredHeight: 28
        opacity: enabled ? 1 : QuattroTheme.Theme.disabledOpacity
        Accessible.role: Accessible.Button
        Accessible.name: accessibleName

        Rectangle {
            anchors.fill: parent
            radius: QuattroTheme.Theme.cornerRadius
            color: transportTap.pressed ? QuattroTheme.Theme.pressed
                : transportHover.hovered ? QuattroTheme.Theme.hover
                : transport.primary ? QuattroTheme.Theme.accentMuted
                : "transparent"
        }

        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
            width: parent.width
            height: parent.height
            text: transport.glyph
            color: transport.primary ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.text
            font.family: QuattroTheme.Theme.iconFontFamily
            font.pixelSize: transport.primary
                ? QuattroTheme.Theme.iconMedium : QuattroTheme.Theme.iconSmall
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        HoverHandler { id: transportHover }
        TapHandler {
            id: transportTap
            enabled: transport.enabled
            onTapped: transport.activated()
        }
        ToolTip.visible: transportHover.hovered
        ToolTip.delay: 700
        ToolTip.text: transport.accessibleName
    }
}
