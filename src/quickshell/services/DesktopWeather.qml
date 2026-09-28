pragma Singleton
import Quickshell
import Quickshell.Io
import QtQuick

QtObject {
    id: root
    property var snapshot: ({
            available: false,
            configured: false
        })
    property bool loading: worker.running || pendingRefresh
    property string error: ""
    readonly property string helper: Quickshell.env("HOME") + "/.local/bin/quattro_desktop_controls.py"
    property int revision: 0
    property bool pendingRefresh: false
    property bool pendingForce: false
    property var pendingPlace: null
    property string searchQuery: ""
    property var searchResults: []
    property string searchError: ""
    property int searchRevision: 0
    property bool searchPending: false
    property bool searching: searchQuery.trim().length >= 2 && (debounce.running || searchPending || searchWorker.running)
    readonly property string placeLabel: snapshot.place ? snapshot.place.label : "Choose a location"
    readonly property string condition: {
        const c = snapshot.code;
        if (!snapshot.available)
            return "";
        if (c === 0)
            return "Clear sky";
        if (c === 1)
            return "Mainly clear";
        if (c === 2)
            return "Partly cloudy";
        if (c === 3)
            return "Overcast";
        if (c <= 48)
            return "Fog";
        if (c >= 95)
            return "Thunderstorms";
        if (c >= 71 && c <= 77 || c === 85 || c === 86)
            return "Snow";
        if (c <= 57)
            return "Drizzle";
        return "Rain";
    }
    readonly property string glyph: {
        const c = snapshot.code;
        if (c === 0)
            return snapshot.day ? "󰖙" : "󰖔";
        if (c <= 3)
            return "󰖐";
        if (c <= 48)
            return "󰖑";
        if (c >= 95)
            return "󰖓";
        if (c >= 71 && c <= 77 || c === 85 || c === 86)
            return "󰖘";
        return "󰖖";
    }
    readonly property string label: snapshot.available ? glyph + " " + Number(snapshot.temperature).toFixed(1) + "°C" : loading ? "Weather…" : "Weather —"
    function refresh(force) {
        pendingRefresh = true;
        pendingForce = pendingForce || !!force;
        startWeather();
    }
    function selectPlace(place) {
        revision++;
        pendingPlace = place;
        pendingRefresh = true;
        pendingForce = true;
        // Never show the previous city's temperature beneath the new name.
        snapshot = {
            available: false,
            configured: true,
            place: place
        };
        error = "";
        searchQuery = "";
        if (worker.running)
            worker.signal(15);
        else
            startWeather();
    }
    function startWeather() {
        if (worker.running || !pendingRefresh)
            return;
        let args = ["python3", helper, "weather"];
        if (pendingForce)
            args.push("--refresh");
        if (pendingPlace)
            args.push("--place", JSON.stringify(pendingPlace));
        pendingRefresh = false;
        pendingForce = false;
        pendingPlace = null;
        worker.requestRevision = revision;
        worker.command = args;
        worker.running = true;
    }
    onSearchQueryChanged: {
        searchRevision++;
        searchResults = [];
        searchError = "";
        searchPending = searchQuery.trim().length >= 2;
        debounce.stop();
        if (searchWorker.running)
            searchWorker.signal(15);
        if (searchPending)
            debounce.restart();
    }
    function startSearch() {
        if (!searchPending || searchWorker.running || debounce.running)
            return;
        searchPending = false;
        searchWorker.requestRevision = searchRevision;
        searchWorker.command = ["python3", helper, "geocode", searchQuery.trim()];
        searchWorker.running = true;
    }
    Component.onCompleted: refresh(false)
    property Process worker: Process {
        property int requestRevision: -1
        stdout: StdioCollector {
            onStreamFinished: {
                if (worker.requestRevision !== root.revision)
                    return;
                try {
                    const s = JSON.parse(text);
                    root.error = s.error || "";
                    if (s.available !== undefined)
                        root.snapshot = s;
                } catch (e) {
                    root.error = "Weather helper unavailable. Try refreshing.";
                }
            }
        }
        onExited: Qt.callLater(root.startWeather)
    }
    property Timer debounce: Timer {
        interval: 325
        onTriggered: root.startSearch()
    }
    property Process searchWorker: Process {
        property int requestRevision: -1
        stdout: StdioCollector {
            onStreamFinished: {
                if (searchWorker.requestRevision !== root.searchRevision)
                    return;
                try {
                    const s = JSON.parse(text);
                    root.searchResults = s.results || [];
                    root.searchError = s.error || "";
                } catch (e) {
                    root.searchError = "Location search unavailable. Try again.";
                }
            }
        }
        onExited: Qt.callLater(root.startSearch)
    }
    property Timer refreshTimer: Timer {
        running: true
        repeat: true
        interval: 1800000
        onTriggered: root.refresh(false)
    }
}
