pragma Singleton
import Quickshell
import Quickshell.Io
import Quickshell.Services.Mpris
import QtQuick
import QtQml.Models

QtObject {
    id: root
    property var players: Mpris.players.values
    property string artwork: ""
    readonly property string artworkUrl: player && player.trackArtUrl ? String(player.trackArtUrl) : ""
    onArtworkUrlChanged: {
        artwork = ""
        if (artworkUrl && !artWorker.running)
            startArtwork()
    }
    function startArtwork() {
        if (!artworkUrl || artWorker.running)
            return
        artWorker.requestUrl = artworkUrl
        artWorker.command = ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_spotify_art.py", artworkUrl]
        artWorker.running = true
    }
    Component.onCompleted: startArtwork()
    property Process artWorker: Process {
        property string requestUrl: ""
        stdout: StdioCollector {
            onStreamFinished: {
                if (artWorker.requestUrl === root.artworkUrl)
                    root.artwork = text.trim()
            }
        }
        onExited: {
            if (artWorker.requestUrl !== root.artworkUrl)
                Qt.callLater(root.startArtwork)
        }
    }
    // Only Spotify's own MPRIS endpoint may drive the visible control or IPC.
    function isSpotify(p) {
        if (!p) return false;
        const name = String(p.dbusName || "").toLowerCase();
        return name === "org.mpris.mediaplayer2.spotify"
            || name.startsWith("org.mpris.mediaplayer2.spotify.instance");
    }
    property var player: {
        const list = players.filter(isSpotify);
        list.sort((a, b) => Number(b.isPlaying) - Number(a.isPlaying) || Number(!!b.trackTitle) - Number(!!a.trackTitle));
        return list.length ? list[0] : null;
    }
    property real position: 0
    function updatePosition() {
        position = player && player.positionSupported ? Math.max(0, player.position) : 0;
    }
    onPlayerChanged: updatePosition()
    property Instantiator watchers: Instantiator {
        model: Mpris.players
        delegate: QtObject {
            required property var modelData
            property Connections connection: Connections {
                target: modelData
                function onIsPlayingChanged() {
                    root.updatePosition();
                }
                function onPostTrackChanged() {
                    root.updatePosition();
                }
                function onPositionChanged() {
                    root.updatePosition();
                }
                function onPositionSupportedChanged() {
                    root.updatePosition();
                }
                function onRateChanged() {
                    root.updatePosition();
                }
            }
        }
    }
    property IpcHandler ipc: IpcHandler {
        target: "media"
        function status(): string {
            const p = root.player;
            return JSON.stringify(p ? {
                player: p.identity,
                title: p.trackTitle,
                artist: p.trackArtist,
                playing: p.isPlaying,
                position: root.position,
                length: p.length,
                players: root.players.filter(root.isSpotify).map(item => item.identity)
            } : {
                players: []
            });
        }
        function playPause(): void {
            if (root.player && root.player.canControl && root.player.canTogglePlaying)
                root.player.togglePlaying();
        }
        function next(): void {
            if (root.player && root.player.canControl && root.player.canGoNext)
                root.player.next();
        }
        function previous(): void {
            if (root.player && root.player.canControl && root.player.canGoPrevious)
                root.player.previous();
        }
    }
    property Timer progressTimer: Timer {
        // MprisPlayer.position already supplies the advancing playback clock.
        // Sampling it locally avoids up to a second of late lyric highlighting;
        // do not add an independent clock or a global lyric offset.
        interval: 50
        running: !!root.player && root.player.isPlaying && root.player.positionSupported
        repeat: true
        onTriggered: root.updatePosition()
    }
}
