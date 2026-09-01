pragma Singleton

import QtQuick

QtObject {
    id: root

    property string current: "lofi-noir"

    readonly property var availableThemes: [
        { "id": "lofi-noir", "label": "Lo-Fi Noir", "detail": "Warm ink, tape-grey type" },
        { "id": "graphite", "label": "Graphite", "detail": "Neutral studio charcoal" },
        { "id": "terminal", "label": "Terminal", "detail": "Muted phosphor green" },
        { "id": "cyberpunk-2077", "label": "Cyberpunk 2077", "detail": "Night City cyan and warning yellow" },
        { "id": "avengers-doomsday", "label": "Avengers: Doomsday", "detail": "Doom green, gunmetal, and eclipse crimson" }
    ]

    readonly property int cornerRadius: 0
    readonly property int transitionDuration: 150

    property color background: current === "avengers-doomsday" ? "#080b09"
        : current === "cyberpunk-2077" ? "#080b12"
        : current === "graphite" ? "#111214"
        : current === "terminal" ? "#09100c" : "#0b0c0e"
    property color surface: current === "avengers-doomsday" ? "#101512"
        : current === "cyberpunk-2077" ? "#0d121c"
        : current === "graphite" ? "#181a1d"
        : current === "terminal" ? "#0d1711" : "#111317"
    property color surfaceRaised: current === "avengers-doomsday" ? "#18211b"
        : current === "cyberpunk-2077" ? "#121a27"
        : current === "graphite" ? "#202329"
        : current === "terminal" ? "#132019" : "#171a1f"
    property color hover: current === "avengers-doomsday" ? "#233027"
        : current === "cyberpunk-2077" ? "#172334"
        : current === "graphite" ? "#292d33"
        : current === "terminal" ? "#1a2a20" : "#1e2228"
    property color border: current === "avengers-doomsday" ? "#33443a"
        : current === "cyberpunk-2077" ? "#25354a"
        : current === "graphite" ? "#30343a"
        : current === "terminal" ? "#26372c" : "#272b31"
    property color borderStrong: current === "avengers-doomsday" ? "#647568"
        : current === "cyberpunk-2077" ? "#3e5977"
        : current === "graphite" ? "#444a53"
        : current === "terminal" ? "#385040" : "#383e47"

    property color textStrong: current === "avengers-doomsday" ? "#f2eee4"
        : current === "cyberpunk-2077" ? "#f4f6e8"
        : current === "graphite" ? "#f0f1f2"
        : current === "terminal" ? "#d9e5dc" : "#e4e0d5"
    property color text: current === "avengers-doomsday" ? "#d5d7d2"
        : current === "cyberpunk-2077" ? "#d3dae6"
        : current === "graphite" ? "#d7d9dc"
        : current === "terminal" ? "#bfcfc3" : "#c8c5bc"
    property color textMuted: current === "avengers-doomsday" ? "#8b968e"
        : current === "cyberpunk-2077" ? "#7f91a8"
        : current === "graphite" ? "#90959d"
        : current === "terminal" ? "#7f9485" : "#888b8f"
    property color textDim: current === "avengers-doomsday" ? "#5e6962"
        : current === "cyberpunk-2077" ? "#52647a"
        : current === "graphite" ? "#666b73"
        : current === "terminal" ? "#586b5e" : "#5d6167"

    property color accent: current === "avengers-doomsday" ? "#8fb99a"
        : current === "cyberpunk-2077" ? "#fcee09"
        : current === "graphite" ? "#aeb5c0"
        : current === "terminal" ? "#88a98f" : "#b9ae91"
    property color accentMuted: current === "avengers-doomsday" ? "#354b3b"
        : current === "cyberpunk-2077" ? "#655f0a"
        : current === "graphite" ? "#4e5662"
        : current === "terminal" ? "#314b38" : "#514b3e"
    property color success: current === "avengers-doomsday" ? "#72b894"
        : current === "cyberpunk-2077" ? "#00f0ff"
        : current === "terminal" ? "#89ad91" : "#91a48b"
    property color warning: current === "avengers-doomsday" ? "#c9a75a"
        : current === "cyberpunk-2077" ? "#fcee09" : "#c2a66d"
    property color danger: current === "avengers-doomsday" ? "#c94a52"
        : current === "cyberpunk-2077" ? "#ff2a6d" : "#b87878"
    readonly property color overlay: "#b3000000"
    readonly property color overlayLight: "#73000000"

    Behavior on background { ColorAnimation { duration: root.transitionDuration } }
    Behavior on surface { ColorAnimation { duration: root.transitionDuration } }
    Behavior on surfaceRaised { ColorAnimation { duration: root.transitionDuration } }
    Behavior on hover { ColorAnimation { duration: root.transitionDuration } }
    Behavior on border { ColorAnimation { duration: root.transitionDuration } }
    Behavior on borderStrong { ColorAnimation { duration: root.transitionDuration } }
    Behavior on textStrong { ColorAnimation { duration: root.transitionDuration } }
    Behavior on text { ColorAnimation { duration: root.transitionDuration } }
    Behavior on textMuted { ColorAnimation { duration: root.transitionDuration } }
    Behavior on textDim { ColorAnimation { duration: root.transitionDuration } }
    Behavior on accent { ColorAnimation { duration: root.transitionDuration } }
    Behavior on accentMuted { ColorAnimation { duration: root.transitionDuration } }
    Behavior on success { ColorAnimation { duration: root.transitionDuration } }

    function isValid(name) {
        return name === "lofi-noir" || name === "graphite"
            || name === "terminal" || name === "cyberpunk-2077"
            || name === "avengers-doomsday"
    }

    function apply(name) {
        if (!isValid(name))
            return false
        current = name
        return true
    }

    function next() {
        const names = ["lofi-noir", "graphite", "terminal", "cyberpunk-2077", "avengers-doomsday"]
        const index = names.indexOf(current)
        current = names[(index + 1) % names.length]
        return current
    }
}
