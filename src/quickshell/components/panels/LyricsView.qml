pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../shared"
import "../../services"
import "../../theme" as QuattroTheme

Item {
    id: root
    property bool autoFollow: true
    readonly property var player: DesktopMedia.player

    function returnToCurrent() {
        autoFollow = true;
        if (LyricsController.activeIndex >= 0) {
            lyricList.currentIndex = LyricsController.activeIndex;
            lyricList.positionViewAtIndex(LyricsController.activeIndex, ListView.Center);
        }
    }

    onVisibleChanged: if (visible)
        Qt.callLater(returnToCurrent)

    Connections {
        target: LyricsController
        function onTrackKeyChanged() {
            root.autoFollow = true;
            Qt.callLater(root.returnToCurrent);
        }
        function onActiveIndexChanged() {
            if (root.autoFollow && LyricsController.activeIndex >= 0)
                lyricList.currentIndex = LyricsController.activeIndex;
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: QuattroTheme.Theme.spaceSm

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Lyrics"
                color: QuattroTheme.Theme.textStrong
                font.family: QuattroTheme.Theme.fontFamily
                font.pixelSize: QuattroTheme.Theme.typeLabel
                font.bold: true
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: LyricsController.state === "synced" ? "SYNCED" : LyricsController.state === "plain" ? "PLAIN" : LyricsController.state === "loading" ? "LOOKING UP" : LyricsController.state === "instrumental" ? "INSTRUMENTAL" : LyricsController.source ? LyricsController.source.toUpperCase() : ""
                color: LyricsController.state === "synced" ? QuattroTheme.Theme.accent : QuattroTheme.Theme.textDim
                font.family: QuattroTheme.Theme.fontFamily
                font.pixelSize: QuattroTheme.Theme.typeMicro
                font.letterSpacing: 0.8
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150

            ListView {
                id: lyricList
                anchors.fill: parent
                visible: LyricsController.state === "synced"
                clip: true
                model: LyricsController.lines
                spacing: QuattroTheme.Theme.spaceXs
                boundsBehavior: Flickable.StopAtBounds
                reuseItems: true
                activeFocusOnTab: visible
                highlight: Item {}
                highlightRangeMode: ListView.ApplyRange
                preferredHighlightBegin: height * 0.42
                preferredHighlightEnd: height * 0.58
                highlightMoveDuration: QuattroTheme.Theme.transitionDuration
                Accessible.name: "Synchronized lyrics"
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                onMovementStarted: root.autoFollow = false
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Home) {
                        root.returnToCurrent();
                        event.accepted = true;
                    }
                }

                delegate: Item {
                    id: lyricRow
                    required property var modelData
                    required property int index
                    width: lyricList.width - 10
                    height: Math.max(34, lyricText.implicitHeight + QuattroTheme.Theme.spaceSm)
                    readonly property bool activeLine: index === LyricsController.activeIndex
                    Accessible.role: Accessible.Button
                    Accessible.name: lyricText.text
                    Accessible.description: root.player && root.player.canSeek ? "Seek Spotify to this lyric" : "Lyric line"

                    Rectangle {
                        anchors.fill: parent
                        radius: QuattroTheme.Theme.cornerRadius
                        color: lyricRow.activeLine ? QuattroTheme.Theme.accentMuted : lyricHover.hovered ? QuattroTheme.Theme.hover : "transparent"
                        opacity: lyricRow.activeLine ? 0.72 : 1
                        Behavior on color {
                            ColorAnimation {
                                duration: QuattroTheme.Theme.motionFast
                            }
                        }
                    }
                    Text {
                        id: lyricText
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: QuattroTheme.Theme.spaceSm
                        anchors.rightMargin: QuattroTheme.Theme.spaceSm
                        text: lyricRow.modelData.text
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        color: lyricRow.activeLine ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textMuted
                        font.family: QuattroTheme.Theme.fontFamily
                        font.pixelSize: lyricRow.activeLine ? QuattroTheme.Theme.typeLabel : QuattroTheme.Theme.typeBody
                        font.bold: lyricRow.activeLine
                        opacity: lyricRow.activeLine ? 1 : 0.72
                        Behavior on opacity {
                            NumberAnimation {
                                duration: QuattroTheme.Theme.transitionDuration
                            }
                        }
                        Behavior on color {
                            ColorAnimation {
                                duration: QuattroTheme.Theme.transitionDuration
                            }
                        }
                    }
                    HoverHandler {
                        id: lyricHover
                    }
                    TapHandler {
                        enabled: root.player && root.player.canSeek
                        onTapped: {
                            root.player.position = Number(lyricRow.modelData.timestampMs) / 1000;
                            root.returnToCurrent();
                        }
                    }
                }
            }

            ScrollView {
                anchors.fill: parent
                visible: LyricsController.state === "plain"
                clip: true
                TextArea {
                    text: LyricsController.plainText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    color: QuattroTheme.Theme.text
                    selectionColor: QuattroTheme.Theme.accentMuted
                    selectedTextColor: QuattroTheme.Theme.textStrong
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeBody
                    background: null
                    Accessible.name: "Plain lyrics"
                }
            }

            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - QuattroTheme.Theme.spaceXl, 320)
                spacing: QuattroTheme.Theme.spaceSm
                visible: LyricsController.state !== "synced" && LyricsController.state !== "plain"
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: LyricsController.state === "loading" ? "Finding lyrics…" : LyricsController.state === "instrumental" ? "Instrumental" : LyricsController.state === "idle" ? "Play a song to see lyrics" : LyricsController.state === "error" ? "Lyrics are unavailable right now" : "Lyrics unavailable"
                    color: LyricsController.state === "instrumental" ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.textMuted
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: LyricsController.state === "instrumental" ? QuattroTheme.Theme.typeLabel : QuattroTheme.Theme.typeBody
                    font.bold: LyricsController.state === "instrumental"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    visible: LyricsController.state === "error"
                    text: "Spotify controls remain available"
                    color: QuattroTheme.Theme.textDim
                    font.family: QuattroTheme.Theme.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeMeta
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }
            }

            DesktopButton {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                visible: LyricsController.state === "synced" && !root.autoFollow
                text: "󰑐  Current line"
                implicitHeight: 30
                Accessible.name: "Return to current lyric"
                onClicked: root.returnToCurrent()
            }
        }
    }
}
