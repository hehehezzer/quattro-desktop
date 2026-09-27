pragma Singleton
import Quickshell
import Quickshell.Io
import Quickshell.Services.Mpris
import QtQuick
import QtQml.Models

QtObject {
    id: root
    property var activity: ({})
    property string preferred: ""
    property var players: Mpris.players.values
    property var player: {
        const list = players.slice();
        list.sort((a, b) => Number(b.isPlaying) - Number(a.isPlaying) || (activity[b.dbusName] || 0) - (activity[a.dbusName] || 0) || Number(b.dbusName === preferred) - Number(a.dbusName === preferred));
        return list.length ? list[0] : null;
    }
    property real position: 0
    function touch(p) {
        if (!p.isPlaying)
            return;
        const next = Object.assign({}, activity);
        next[p.dbusName] = Date.now();
        activity = next;
    }
    function updatePosition() {
        position = player && player.positionSupported ? Math.max(0, player.position) : 0;
    }
    onPlayerChanged: updatePosition()
    property Instantiator watchers: Instantiator {
        model: Mpris.players
        delegate: QtObject {
            required property var modelData
            Component.onCompleted: root.touch(modelData)
            property Connections connection: Connections {
                target: modelData
                function onIsPlayingChanged() {
                    root.touch(modelData);
                    root.updatePosition();
                }
                function onTrackChanged() {
                    root.touch(modelData);
                    root.updatePosition();
                }
                function onPositionChanged() {
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
                players: root.players.map(item => item.identity)
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
        interval: 1000
        running: !!root.player && root.player.isPlaying && root.player.positionSupported
        repeat: true
        onTriggered: root.updatePosition()
    }
}
