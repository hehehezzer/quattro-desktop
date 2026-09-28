pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

QtObject {
    id: root
    readonly property var player: DesktopMedia.player
    readonly property string title: player && player.trackTitle ? String(player.trackTitle) : ""
    readonly property string artist: player && player.trackArtist ? String(player.trackArtist) : ""
    readonly property string album: player && player.trackAlbum ? String(player.trackAlbum) : ""
    readonly property real duration: player && player.lengthSupported ? Number(player.length) : 0
    readonly property string trackKey: title && artist ? [title, artist, Math.round(duration)].join("\u241f") : ""

    property string state: trackKey ? "loading" : "idle"
    property var lines: []
    property string plainText: ""
    property bool instrumental: false
    property string source: ""
    property bool cached: false
    property string message: ""
    property int revision: 0
    property int requestRevision: -1
    property string requestTrackKey: ""
    property bool outputHandled: false
    readonly property int activeIndex: activeLineAt(DesktopMedia.position)

    function activeLineAt(positionSeconds) {
        let low = 0;
        let high = lines.length - 1;
        let result = -1;
        const positionMs = Math.max(0, Number(positionSeconds) || 0) * 1000;
        while (low <= high) {
            const middle = Math.floor((low + high) / 2);
            if (Number(lines[middle].timestampMs) <= positionMs) {
                result = middle;
                low = middle + 1;
            } else {
                high = middle - 1;
            }
        }
        return result;
    }

    function resetForTrack() {
        revision++;
        lines = [];
        plainText = "";
        instrumental = false;
        source = "";
        cached = false;
        message = "";
        state = trackKey ? "loading" : "idle";
        lookupDebounce.stop();
        requestTimeout.stop();
        if (lookupWorker.running)
            lookupWorker.running = false;
        if (trackKey)
            lookupDebounce.restart();
    }

    function startLookup() {
        if (!trackKey || lookupWorker.running)
            return;
        requestRevision = revision;
        requestTrackKey = trackKey;
        outputHandled = false;
        const command = [Quickshell.env("HOME") + "/.local/bin/quattro-lyrics", "lookup", "--title", title, "--artist", artist];
        if (album)
            command.push("--album", album);
        if (duration > 0)
            command.push("--duration", String(duration));
        lookupWorker.command = command;
        lookupWorker.running = true;
        requestTimeout.restart();
    }

    function applyResult(text, requestRevision, requestTrackKey) {
        if (requestRevision !== revision || requestTrackKey !== trackKey)
            return;
        let result;
        try {
            result = JSON.parse(text.trim());
        } catch (error) {
            state = "error";
            message = "Lyrics are unavailable right now";
            return;
        }
        if (result.schemaVersion !== 1 || result.trackKey === undefined) {
            state = "error";
            message = "Lyrics are unavailable right now";
            return;
        }
        state = ["synced", "plain", "instrumental", "unavailable", "error"].indexOf(result.state) >= 0 ? result.state : "error";
        lines = Array.isArray(result.lines) ? result.lines : [];
        plainText = typeof result.plainText === "string" ? result.plainText : "";
        instrumental = !!result.instrumental;
        source = typeof result.source === "string" ? result.source : "";
        cached = !!result.cached;
        message = typeof result.message === "string" ? result.message : "";
    }

    onTrackKeyChanged: resetForTrack()
    Component.onCompleted: resetForTrack()

    property IpcHandler ipc: IpcHandler {
        target: "lyrics"
        function status(): string {
            return JSON.stringify({
                state: root.state,
                title: root.title,
                artist: root.artist,
                activeIndex: root.activeIndex,
                lineCount: root.lines.length,
                cached: root.cached,
                source: root.source
            });
        }
    }

    property Timer lookupDebounce: Timer {
        interval: 220
        repeat: false
        onTriggered: root.startLookup()
    }

    property Timer requestTimeout: Timer {
        interval: 18000
        repeat: false
        onTriggered: {
            if (!root.lookupWorker.running)
                return;
            const currentRequest = root.requestRevision === root.revision && root.requestTrackKey === root.trackKey;
            root.lookupWorker.running = false;
            if (currentRequest) {
                root.state = "error";
                root.message = "Lyrics request timed out";
            }
        }
    }

    property Process lookupWorker: Process {
        stdout: StdioCollector {
            onStreamFinished: {
                root.outputHandled = text.trim().length > 0;
                if (root.outputHandled)
                    root.applyResult(text, root.requestRevision, root.requestTrackKey);
            }
        }
        onExited: {
            root.requestTimeout.stop();
            const currentRequest = root.requestRevision === root.revision && root.requestTrackKey === root.trackKey;
            if (currentRequest && !root.outputHandled && root.state === "loading") {
                root.state = "error";
                root.message = "Lyrics are unavailable right now";
            }
            if (root.trackKey && root.state === "loading" && root.requestRevision !== root.revision)
                Qt.callLater(root.startLookup);
        }
    }
}
