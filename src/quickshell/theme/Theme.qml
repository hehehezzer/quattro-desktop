pragma Singleton

import QtQuick

QtObject {
    id: root

    property string current: "lofi-noir"

    readonly property var availableThemes: [
        { "id": "lofi-noir", "label": "Lo-Fi Noir", "detail": "Warm drafting room · ink and vellum" },
        { "id": "graphite", "label": "Graphite", "detail": "Mineral studio · cool architectural grid" },
        { "id": "terminal", "label": "Terminal", "detail": "Quiet phosphor · measured scan field" },
        { "id": "cyberpunk-2077", "label": "Cyberpunk 2077", "detail": "Night transit · sodium and cyan wayfinding" },
        { "id": "avengers-doomsday", "label": "Avengers: Doomsday", "detail": "Eclipse chamber · gunmetal and verdigris" },
        { "id": "instrument", "label": "Instrument", "detail": "Matte black · neutral state and red attention" },
        { "id": "instrument-paper", "label": "Instrument Paper", "detail": "Warm paper · ink and red attention" },
        { "id": "instrument-ember", "label": "Instrument Ember", "detail": "Warm charcoal · bone and muted red" }
    ]

    readonly property bool isInstrument: current === "instrument"
        || current === "instrument-paper" || current === "instrument-ember"
    // The approved instrument sheet uses flat fields and neutral rules. Red is
    // reserved for attention; ordinary active and healthy states stay neutral.
    readonly property var instrumentPalettes: ({
        "instrument": {
            "background": "#101112", "barSurface": "#101112", "panelSurface": "#101112",
            "surface": "#1b1c1c", "surfaceRaised": "#252625", "hover": "#2c2d2b", "pressed": "#353634",
            "border": "#494a47", "borderStrong": "#73746e", "panelBorder": "#73746e",
            "textStrong": "#ecece7", "text": "#d8d8d2", "textMuted": "#c0c0b8", "textDim": "#b3b3ad",
            "accent": "#ecece7", "accentMuted": "#353634", "success": "#c0c0b8",
            "attention": "#d24b3e", "attentionInk": "#ed8577", "attentionSurface": "#3a201e", "onAttention": "#080909"
        },
        "instrument-paper": {
            "background": "#f0efe8", "barSurface": "#f0efe8", "panelSurface": "#f0efe8",
            "surface": "#e8e7df", "surfaceRaised": "#e1e0d8", "hover": "#dcdbd3", "pressed": "#d7d6cf",
            "border": "#b3b2a9", "borderStrong": "#77786e", "panelBorder": "#77786e",
            "textStrong": "#20211f", "text": "#343530", "textMuted": "#494a43", "textDim": "#56574f",
            "accent": "#20211f", "accentMuted": "#d7d6cf", "success": "#494a43",
            "attention": "#a53a30", "attentionInk": "#96332a", "attentionSurface": "#e8d3ca", "onAttention": "#f0efe8"
        },
        "instrument-ember": {
            "background": "#191514", "barSurface": "#191514", "panelSurface": "#191514",
            "surface": "#241f1d", "surfaceRaised": "#2d2724", "hover": "#342d2a", "pressed": "#3b3230",
            "border": "#51443e", "borderStrong": "#837167", "panelBorder": "#837167",
            "textStrong": "#ebe5db", "text": "#d8cfc3", "textMuted": "#c4b8ab", "textDim": "#bbb0a6",
            "accent": "#ebe5db", "accentMuted": "#3b3230", "success": "#c4b8ab",
            "attention": "#bd6556", "attentionInk": "#ee9b8b", "attentionSurface": "#432922", "onAttention": "#12100f"
        }
    })
    // QML may reevaluate dependent bindings in either order during a switch.
    // Keep a complete palette available while isInstrument catches up.
    readonly property var instrumentPalette: instrumentPalettes[current] || instrumentPalettes["instrument"]
    readonly property color attention: isInstrument ? instrumentPalette.attention : danger
    readonly property color attentionInk: isInstrument ? instrumentPalette.attentionInk : danger
    readonly property color attentionSurface: isInstrument ? instrumentPalette.attentionSurface : surfaceRaised
    readonly property color onAttention: isInstrument ? instrumentPalette.onAttention : textStrong

    // Shared geometry and rhythm.
    readonly property int space2xs: 2
    readonly property int spaceXs: 4
    readonly property int spaceSm: 8
    readonly property int spaceMd: 12
    readonly property int spaceLg: 16
    readonly property int spaceXl: 24
    readonly property int space2xl: 32
    readonly property int cornerRadius: isInstrument ? 0 : 3
    readonly property int panelRadius: isInstrument ? 0 : 7
    readonly property int compactTarget: 32
    readonly property int primaryTarget: 44
    readonly property int barHeight: 40
    readonly property int barControlHeight: 30
    readonly property int panelWidth: 430
    readonly property int panelInset: 16
    readonly property int structuralLine: 1
    readonly property int focusLine: 2

    // Typography and normalized glyph metrics.
    readonly property string fontFamily: "JetBrainsMono Nerd Font"
    // User-provided NDOT47 is licensed independently of Nothing's Ndot-Regular.
    // Only the navbar opts into this role; operational panels retain their face.
    readonly property string navbarFontFamily: navbarDisplayFace.status === FontLoader.Ready
        ? navbarDisplayFace.name : fontFamily
    readonly property FontLoader navbarDisplayFace: FontLoader {
        source: Qt.resolvedUrl("../assets/fonts/ndot47/ndot-47-inspired-by-nothing.otf")
    }

    readonly property string displayFontFamily: instrumentDisplayFace.status === FontLoader.Ready
        ? instrumentDisplayFace.name : fontFamily
    readonly property FontLoader instrumentDisplayFace: FontLoader {
        source: Qt.resolvedUrl("../assets/fonts/Doto.ttf")
    }
    // Glyphs retain their installed asset family even if the text role changes.
    readonly property string iconFontFamily: "JetBrainsMono Nerd Font"
    readonly property int typeMicro: isInstrument ? 10 : 9
    readonly property int typeMeta: 10
    readonly property int typeBody: 11
    readonly property int typeLabel: 12
    readonly property int typeTitle: 16
    readonly property int typeValue: 20
    readonly property int iconSmall: 14
    readonly property int iconMedium: 16
    readonly property int iconLarge: 20
    // Nerd Font glyph boxes sit optically low when mathematically centered.
    readonly property real iconOpticalOffsetY: -0.5

    // Short state-driven motion only.
    readonly property int motionFast: 90
    readonly property int transitionDuration: 150
    readonly property int motionAtmosphere: 260
    readonly property real disabledOpacity: 0.46
    readonly property real inactiveOpacity: 0.68

    // Themes carry a material and background composition, not only colors.
    readonly property string motif: isInstrument ? "none" : current === "lofi-noir" ? "contour"
        : current === "graphite" ? "draft"
        : current === "terminal" ? "scan"
        : current === "cyberpunk-2077" ? "transit" : "eclipse"
    readonly property int motifStep: current === "terminal" ? 28
        : current === "cyberpunk-2077" ? 64 : 48
    readonly property real motifOpacity: isInstrument ? 0 : current === "lofi-noir" ? 0.16
        : current === "graphite" ? 0.18
        : current === "terminal" ? 0.13
        : current === "cyberpunk-2077" ? 0.14 : 0.17

    property color canvasTop: isInstrument ? instrumentPalette.background : current === "avengers-doomsday" ? "#101612"
        : current === "cyberpunk-2077" ? "#101724"
        : current === "graphite" ? "#20242a"
        : current === "terminal" ? "#101a14" : "#211f1c"
    property color canvasBottom: isInstrument ? instrumentPalette.background : current === "avengers-doomsday" ? "#080b09"
        : current === "cyberpunk-2077" ? "#090d14"
        : current === "graphite" ? "#101215"
        : current === "terminal" ? "#080d0a" : "#0d0e10"
    property color canvasLine: isInstrument ? instrumentPalette.border : current === "avengers-doomsday" ? "#7a9a82"
        : current === "cyberpunk-2077" ? "#6ba6ba"
        : current === "graphite" ? "#93a0ad"
        : current === "terminal" ? "#79a385" : "#b8a98a"
    property color ambientPrimary: isInstrument ? instrumentPalette.background : current === "avengers-doomsday" ? "#355742"
        : current === "cyberpunk-2077" ? "#214f62"
        : current === "graphite" ? "#47515e"
        : current === "terminal" ? "#244b31" : "#5a4937"
    property color ambientSecondary: isInstrument ? instrumentPalette.background : current === "avengers-doomsday" ? "#552c30"
        : current === "cyberpunk-2077" ? "#6a5d1f"
        : current === "graphite" ? "#2d3640"
        : current === "terminal" ? "#193423" : "#32394a"

    property color background: isInstrument ? instrumentPalette.background : current === "avengers-doomsday" ? "#0c100d"
        : current === "cyberpunk-2077" ? "#0b111a"
        : current === "graphite" ? "#15181c"
        : current === "terminal" ? "#0b120e" : "#111214"
    property color barSurface: isInstrument ? instrumentPalette.barSurface : current === "avengers-doomsday" ? "#F00D120F"
        : current === "cyberpunk-2077" ? "#F00B111B"
        : current === "graphite" ? "#F015181C"
        : current === "terminal" ? "#F00B130E" : "#F0121315"
    property color panelSurface: isInstrument ? instrumentPalette.panelSurface : current === "avengers-doomsday" ? "#FA101612"
        : current === "cyberpunk-2077" ? "#FA0E1621"
        : current === "graphite" ? "#FA1A1E23"
        : current === "terminal" ? "#FA0D1711" : "#FA161719"
    property color surface: isInstrument ? instrumentPalette.surface : current === "avengers-doomsday" ? "#151d18"
        : current === "cyberpunk-2077" ? "#121b28"
        : current === "graphite" ? "#22262c"
        : current === "terminal" ? "#142019" : "#1d1e20"
    property color surfaceRaised: isInstrument ? instrumentPalette.surfaceRaised : current === "avengers-doomsday" ? "#1c2920"
        : current === "cyberpunk-2077" ? "#192639"
        : current === "graphite" ? "#2a3038"
        : current === "terminal" ? "#1b2b21" : "#272629"
    property color hover: isInstrument ? instrumentPalette.hover : current === "avengers-doomsday" ? "#26362b"
        : current === "cyberpunk-2077" ? "#203149"
        : current === "graphite" ? "#343b44"
        : current === "terminal" ? "#23372a" : "#333136"
    property color pressed: isInstrument ? instrumentPalette.pressed : current === "avengers-doomsday" ? "#304437"
        : current === "cyberpunk-2077" ? "#2a3f5d"
        : current === "graphite" ? "#3f4853"
        : current === "terminal" ? "#2b4434" : "#403c40"
    property color border: isInstrument ? instrumentPalette.border : current === "avengers-doomsday" ? "#34453a"
        : current === "cyberpunk-2077" ? "#2a3d54"
        : current === "graphite" ? "#3a414a"
        : current === "terminal" ? "#2b3d31" : "#37373a"
    property color borderStrong: isInstrument ? instrumentPalette.borderStrong : current === "avengers-doomsday" ? "#66786b"
        : current === "cyberpunk-2077" ? "#496783"
        : current === "graphite" ? "#59636f"
        : current === "terminal" ? "#46604e" : "#57575d"
    property color panelBorder: isInstrument ? instrumentPalette.panelBorder : current === "lofi-noir" ? "#655d50" : borderStrong

    property color textStrong: isInstrument ? instrumentPalette.textStrong : current === "avengers-doomsday" ? "#f2eee4"
        : current === "cyberpunk-2077" ? "#f4f5ed"
        : current === "graphite" ? "#f2f3f4"
        : current === "terminal" ? "#deeadf" : "#eee9df"
    property color text: isInstrument ? instrumentPalette.text : current === "avengers-doomsday" ? "#d5d7d2"
        : current === "cyberpunk-2077" ? "#d6dde7"
        : current === "graphite" ? "#d9dce0"
        : current === "terminal" ? "#c5d6c9" : "#d3cec4"
    property color textMuted: isInstrument ? instrumentPalette.textMuted : current === "avengers-doomsday" ? "#adb9b0"
        : current === "cyberpunk-2077" ? "#a9bbcf"
        : current === "graphite" ? "#b4bac2"
        : current === "terminal" ? "#a6baa9" : "#aaaeb3"
    property color textDim: isInstrument ? instrumentPalette.textDim : current === "avengers-doomsday" ? "#94a198"
        : current === "cyberpunk-2077" ? "#8799af"
        : current === "graphite" ? "#a1a8b0"
        : current === "terminal" ? "#8fa793" : "#9ba0a5"

    property color accent: isInstrument ? instrumentPalette.accent : current === "avengers-doomsday" ? "#9bc8a7"
        : current === "cyberpunk-2077" ? "#eadf59"
        : current === "graphite" ? "#c1c9d4"
        : current === "terminal" ? "#93bb9c" : "#c7b894"
    property color accentMuted: isInstrument ? instrumentPalette.accentMuted : current === "avengers-doomsday" ? "#354d3c"
        : current === "cyberpunk-2077" ? "#59551c"
        : current === "graphite" ? "#515b67"
        : current === "terminal" ? "#344f3b" : "#554d3e"
    property color success: isInstrument ? instrumentPalette.success : current === "avengers-doomsday" ? "#7ec39c"
        : current === "cyberpunk-2077" ? "#6bc3ca"
        : current === "terminal" ? "#8fba99" : "#9cb094"
    property color warning: isInstrument ? instrumentPalette.attentionInk : current === "avengers-doomsday" ? "#d0ad62"
        : current === "cyberpunk-2077" ? "#eadf59" : "#c9ac70"
    property color danger: isInstrument ? instrumentPalette.attentionInk : current === "avengers-doomsday" ? "#d05b62"
        : current === "cyberpunk-2077" ? "#d85f83" : "#c17d7d"
    readonly property color overlay: "#B8000000"
    readonly property color overlayLight: "#73000000"

    Behavior on canvasTop { ColorAnimation { duration: root.motionAtmosphere } }
    Behavior on canvasBottom { ColorAnimation { duration: root.motionAtmosphere } }
    Behavior on canvasLine { ColorAnimation { duration: root.motionAtmosphere } }
    Behavior on ambientPrimary { ColorAnimation { duration: root.motionAtmosphere } }
    Behavior on ambientSecondary { ColorAnimation { duration: root.motionAtmosphere } }
    Behavior on background { ColorAnimation { duration: root.transitionDuration } }
    Behavior on barSurface { ColorAnimation { duration: root.transitionDuration } }
    Behavior on panelSurface { ColorAnimation { duration: root.transitionDuration } }
    Behavior on surface { ColorAnimation { duration: root.transitionDuration } }
    Behavior on surfaceRaised { ColorAnimation { duration: root.transitionDuration } }
    Behavior on hover { ColorAnimation { duration: root.transitionDuration } }
    Behavior on pressed { ColorAnimation { duration: root.motionFast } }
    Behavior on border { ColorAnimation { duration: root.transitionDuration } }
    Behavior on borderStrong { ColorAnimation { duration: root.transitionDuration } }
    Behavior on panelBorder { ColorAnimation { duration: root.transitionDuration } }
    Behavior on textStrong { ColorAnimation { duration: root.transitionDuration } }
    Behavior on text { ColorAnimation { duration: root.transitionDuration } }
    Behavior on textMuted { ColorAnimation { duration: root.transitionDuration } }
    Behavior on textDim { ColorAnimation { duration: root.transitionDuration } }
    Behavior on accent { ColorAnimation { duration: root.transitionDuration } }
    Behavior on accentMuted { ColorAnimation { duration: root.transitionDuration } }
    Behavior on success { ColorAnimation { duration: root.transitionDuration } }

    function isValid(name) {
        return availableThemes.some(theme => theme.id === name)
    }

    function apply(name) {
        if (!isValid(name))
            return false
        current = name
        return true
    }

    function next() {
        const names = availableThemes.map(theme => theme.id)
        const index = names.indexOf(current)
        current = names[(index + 1) % names.length]
        return current
    }
}
