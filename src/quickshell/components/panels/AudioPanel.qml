import Quickshell
import Quickshell.Services.Pipewire
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme" as QuattroTheme

Item {
    id: root

    signal requestFocus()

    property var sink: Pipewire.defaultAudioSink
    property var source: Pipewire.defaultAudioSource

    property bool outputExpanded: false
    property bool inputExpanded: false

    property real sinkVolume:
        sink && sink.audio
            ? sink.audio.volume
            : 0.0

    property bool sinkMuted:
        sink && sink.audio
            ? sink.audio.muted
            : false

    property real sourceVolume:
        source && source.audio
            ? source.audio.volume
            : 0.0

    property bool sourceMuted:
        source && source.audio
            ? source.audio.muted
            : false

    implicitWidth: 420
    implicitHeight: 520

    // ============================================================
    // PIPEWIRE TRACKING
    // ============================================================

    PwObjectTracker {
        objects: [
            root.sink,
            root.source
        ]
    }

    // ============================================================
    // PUBLIC FUNCTIONS
    // ============================================================

    function refreshAudio() {
        // PipeWire updates live.
    }

    function resetTransientState() {
        outputExpanded = false
        inputExpanded = false
    }

    function handleEscape() {
        if (outputExpanded) {
            outputExpanded = false
            return true
        }

        if (inputExpanded) {
            inputExpanded = false
            return true
        }

        return false
    }

    // ============================================================
    // HELPERS
    // ============================================================

    function clamp(value, minValue, maxValue) {
        return Math.max(
            minValue,
            Math.min(maxValue, value)
        )
    }

    function volumePercent(value) {
        return Math.round(
            clamp(value, 0.0, 1.0) * 100
        )
    }

    function setSinkVolume(value) {
        if (!root.sink || !root.sink.audio)
            return

        root.sink.audio.volume =
            clamp(value, 0.0, 1.0)

        if (
            root.sink.audio.muted
            && value > 0.0
        ) {
            root.sink.audio.muted = false
        }
    }

    function setSourceVolume(value) {
        if (!root.source || !root.source.audio)
            return

        root.source.audio.volume =
            clamp(value, 0.0, 1.0)

        if (
            root.source.audio.muted
            && value > 0.0
        ) {
            root.source.audio.muted = false
        }
    }

    function sinkIcon() {
        if (!root.sink)
            return "󰖁"

        if (root.sinkMuted)
            return "󰖁"

        if (root.sinkVolume <= 0.0)
            return "󰕿"

        if (root.sinkVolume < 0.34)
            return "󰕿"

        if (root.sinkVolume < 0.67)
            return "󰖀"

        return "󰕾"
    }

    function sourceIcon() {
        if (!root.source)
            return "󰍭"

        if (root.sourceMuted)
            return "󰍭"

        return "󰍬"
    }

    function displayName(node) {
        if (!node)
            return "No device"

        if (
            node.description
            && node.description.length > 0
        ) {
            return node.description
        }

        if (
            node.nickname
            && node.nickname.length > 0
        ) {
            return node.nickname
        }

        if (
            node.name
            && node.name.length > 0
        ) {
            return node.name
        }

        return "Unknown device"
    }

    function shortDeviceName(node) {
        if (!node)
            return "No device"

        if (
            node.nickname
            && node.nickname.length > 0
        ) {
            return node.nickname
        }

        if (
            node.description
            && node.description.length > 0
        ) {
            return node.description
        }

        return node.name
    }

    function isHardwareOutput(node) {
        return (
            node
            && node.audio !== null
            && !node.isStream
            && node.isSink
        )
    }

    function isHardwareInput(node) {
        return (
            node
            && node.audio !== null
            && !node.isStream
            && !node.isSink
        )
    }

    // On Quickshell 0.3.1 here, playback application streams
    // report as isStream=true and isSink=true.
    function isPlaybackStream(node) {
        return (
            node
            && node.isStream
            && node.isSink
        )
    }

    function streamName(node) {
        if (!node)
            return "Application"

        if (
            node.properties
            && node.properties["application.name"]
        ) {
            return node.properties["application.name"]
        }

        if (
            node.description
            && node.description.length > 0
        ) {
            return node.description
        }

        if (
            node.nickname
            && node.nickname.length > 0
        ) {
            return node.nickname
        }

        if (
            node.name
            && node.name.length > 0
        ) {
            return node.name
        }

        return "Application"
    }

    function streamDescription(node) {
        if (!node)
            return ""

        if (
            node.properties
            && node.properties["media.name"]
        ) {
            return node.properties["media.name"]
        }

        if (
            node.properties
            && node.properties["media.title"]
        ) {
            return node.properties["media.title"]
        }

        return "Application audio"
    }

    // ============================================================
    // SCROLLABLE CONTENT
    // ============================================================

    Flickable {
        id: audioScroll

        anchors.fill: parent

        clip: true

        contentWidth: width
        contentHeight: contentColumn.implicitHeight

        boundsBehavior:
            Flickable.StopAtBounds

        interactive:
            contentHeight > height

        flickableDirection:
            Flickable.VerticalFlick

        ScrollBar.vertical: ScrollBar {
            id: audioScrollBar

            policy:
                audioScroll.contentHeight > audioScroll.height
                    ? ScrollBar.AsNeeded
                    : ScrollBar.AlwaysOff
        }

        ColumnLayout {
            id: contentColumn

            width:
                Math.max(
                    0,
                    audioScroll.width
                    - (
                        audioScrollBar.visible
                            ? 8
                            : 0
                    )
                )

            spacing: 0

            // ====================================================
            // HEADER
            // ====================================================

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 18
                Layout.rightMargin: 18
                Layout.topMargin: 16
                Layout.bottomMargin: 14

                spacing: 10

                Text {
                    text: "Audio"

                    color: QuattroTheme.Theme.text

                    font.family:
                        "JetBrainsMono Nerd Font"

                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    text:
                        Pipewire.ready
                            ? "PipeWire"
                            : "Connecting…"

                    color: QuattroTheme.Theme.textMuted

                    font.family:
                        "JetBrainsMono Nerd Font"

                    font.pixelSize: 10
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 14
                Layout.rightMargin: 14

                height: 1
                color: QuattroTheme.Theme.border
            }

            // ====================================================
            // OUTPUT
            // ====================================================

            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 18
                Layout.rightMargin: 18
                Layout.topMargin: 16

                spacing: 10

                Text {
                    text: "OUTPUT"

                    color: QuattroTheme.Theme.textMuted

                    font.family:
                        "JetBrainsMono Nerd Font"

                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                RowLayout {
                    Layout.fillWidth: true

                    spacing: 12

                    Rectangle {
                        width: 38
                        height: 38

                        radius: QuattroTheme.Theme.cornerRadius

                        color:
                            outputMuteMouse.containsMouse
                                ? QuattroTheme.Theme.hover
                                : QuattroTheme.Theme.surfaceRaised

                        border.width: 1

                        border.color:
                            root.sinkMuted
                                ? QuattroTheme.Theme.textDim
                                : QuattroTheme.Theme.border

                        Text {
                            anchors.centerIn: parent

                            text:
                                root.sinkIcon()

                            color:
                                root.sink
                                    ? (
                                        root.sinkMuted
                                            ? QuattroTheme.Theme.textMuted
                                            : QuattroTheme.Theme.text
                                    )
                                    : QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 18
                        }

                        MouseArea {
                            id: outputMuteMouse

                            anchors.fill: parent

                            enabled:
                                root.sink !== null
                                && root.sink.audio !== null

                            hoverEnabled: true

                            cursorShape:
                                enabled
                                    ? Qt.PointingHandCursor
                                    : Qt.ArrowCursor

                            onClicked: {
                                root.sink.audio.muted =
                                    !root.sink.audio.muted
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        height: 38

                        Rectangle {
                            id: outputTrack

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter

                            height: 6
                            radius: QuattroTheme.Theme.cornerRadius

                            color: QuattroTheme.Theme.border

                            Rectangle {
                                width:
                                    parent.width
                                    * root.clamp(
                                        root.sinkVolume,
                                        0.0,
                                        1.0
                                    )

                                height: parent.height
                                radius: parent.radius

                                color:
                                    root.sinkMuted
                                        ? QuattroTheme.Theme.textDim
                                        : QuattroTheme.Theme.text
                            }

                            Rectangle {
                                x:
                                    root.clamp(
                                        root.sinkVolume,
                                        0.0,
                                        1.0
                                    )
                                    * (
                                        outputTrack.width
                                        - width
                                    )

                                anchors.verticalCenter:
                                    parent.verticalCenter

                                width: 14
                                height: 14

                                radius: QuattroTheme.Theme.cornerRadius

                                color:
                                    outputSliderMouse.pressed
                                        ? QuattroTheme.Theme.textStrong
                                        : QuattroTheme.Theme.text

                                border.width: 1
                                border.color: QuattroTheme.Theme.textDim
                            }
                        }

                        MouseArea {
                            id: outputSliderMouse

                            anchors.fill: parent

                            enabled:
                                root.sink !== null
                                && root.sink.audio !== null

                            hoverEnabled: true

                            cursorShape:
                                enabled
                                    ? Qt.PointingHandCursor
                                    : Qt.ArrowCursor

                            function updateVolume(mouseX) {
                                var value =
                                    root.clamp(
                                        mouseX / width,
                                        0.0,
                                        1.0
                                    )

                                root.setSinkVolume(value)
                            }

                            onPressed: function(mouse) {
                                updateVolume(mouse.x)
                            }

                            onPositionChanged: function(mouse) {
                                if (pressed)
                                    updateVolume(mouse.x)
                            }
                        }
                    }

                    Text {
                        Layout.preferredWidth: 42

                        horizontalAlignment:
                            Text.AlignRight

                        text:
                            root.sink
                                ? (
                                    root.volumePercent(
                                        root.sinkVolume
                                    )
                                    + "%"
                                )
                                : "--"

                        color: QuattroTheme.Theme.text

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 12
                    }
                }

                // =================================================
                // CURRENT OUTPUT DEVICE
                // =================================================

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 54
                    radius: QuattroTheme.Theme.cornerRadius

                    color:
                        outputDeviceMouse.containsMouse
                            ? QuattroTheme.Theme.hover
                            : QuattroTheme.Theme.surface

                    border.width: 1

                    border.color:
                        root.outputExpanded
                            ? QuattroTheme.Theme.borderStrong
                            : QuattroTheme.Theme.border

                    RowLayout {
                        anchors.fill: parent

                        anchors.leftMargin: 12
                        anchors.rightMargin: 12

                        spacing: 10

                        Text {
                            text: "󰓃"

                            color: QuattroTheme.Theme.text

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 17
                        }

                        ColumnLayout {
                            Layout.fillWidth: true

                            spacing: 2

                            Text {
                                Layout.fillWidth: true

                                text:
                                    root.displayName(
                                        root.sink
                                    )

                                color: QuattroTheme.Theme.text

                                elide:
                                    Text.ElideRight

                                font.family:
                                    "JetBrainsMono Nerd Font"

                                font.pixelSize: 11
                            }

                            Text {
                                Layout.fillWidth: true

                                text:
                                    root.sink
                                        ? "Current output"
                                        : "No output available"

                                color: QuattroTheme.Theme.textMuted

                                elide:
                                    Text.ElideRight

                                font.family:
                                    "JetBrainsMono Nerd Font"

                                font.pixelSize: 9
                            }
                        }

                        Text {
                            text:
                                root.outputExpanded
                                    ? "󰅃"
                                    : "󰅀"

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 13
                        }
                    }

                    MouseArea {
                        id: outputDeviceMouse

                        anchors.fill: parent

                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor

                        onClicked: {
                            root.outputExpanded =
                                !root.outputExpanded

                            root.inputExpanded = false
                        }
                    }
                }

                // =================================================
                // OUTPUT DEVICE LIST
                // =================================================

                ColumnLayout {
                    visible:
                        root.outputExpanded

                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model:
                            Pipewire.nodes

                        delegate: Rectangle {
                            id: outputDeviceRow

                            required property var modelData

                            property bool validDevice:
                                root.isHardwareOutput(
                                    modelData
                                )

                            visible:
                                validDevice

                            Layout.fillWidth: true

                            implicitHeight:
                                validDevice
                                    ? 48
                                    : 0

                            radius: QuattroTheme.Theme.cornerRadius

                            color:
                                outputRowMouse.containsMouse
                                    ? QuattroTheme.Theme.hover
                                    : QuattroTheme.Theme.surface

                            border.width: 1

                            border.color:
                                root.sink === modelData
                                    ? QuattroTheme.Theme.textDim
                                    : QuattroTheme.Theme.border

                            RowLayout {
                                anchors.fill: parent

                                anchors.leftMargin: 12
                                anchors.rightMargin: 12

                                spacing: 10

                                Text {
                                    text:
                                        root.sink ===
                                        outputDeviceRow.modelData
                                            ? "󰄬"
                                            : "󰓃"

                                    color:
                                        root.sink ===
                                        outputDeviceRow.modelData
                                            ? QuattroTheme.Theme.text
                                            : QuattroTheme.Theme.textMuted

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 15
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true

                                    spacing: 1

                                    Text {
                                        Layout.fillWidth: true

                                        text:
                                            root.shortDeviceName(
                                                outputDeviceRow.modelData
                                            )

                                        color: QuattroTheme.Theme.text

                                        elide:
                                            Text.ElideRight

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 10
                                    }

                                    Text {
                                        Layout.fillWidth: true

                                        text:
                                            root.displayName(
                                                outputDeviceRow.modelData
                                            )

                                        color: QuattroTheme.Theme.textMuted

                                        elide:
                                            Text.ElideRight

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 8
                                    }
                                }

                                Text {
                                    visible:
                                        root.sink ===
                                        outputDeviceRow.modelData

                                    text: "Default"

                                    color: QuattroTheme.Theme.textMuted

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 8
                                }
                            }

                            MouseArea {
                                id: outputRowMouse

                                anchors.fill: parent

                                enabled:
                                    outputDeviceRow.validDevice

                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor

                                onClicked: {
                                    Pipewire.preferredDefaultAudioSink =
                                        outputDeviceRow.modelData

                                    root.outputExpanded = false
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 14
                Layout.rightMargin: 14
                Layout.topMargin: 17

                height: 1
                color: QuattroTheme.Theme.border
            }

            // ====================================================
            // MICROPHONE
            // ====================================================

            ColumnLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 18
                Layout.rightMargin: 18
                Layout.topMargin: 16

                spacing: 10

                Text {
                    text: "MICROPHONE"

                    color: QuattroTheme.Theme.textMuted

                    font.family:
                        "JetBrainsMono Nerd Font"

                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    Rectangle {
                        width: 38
                        height: 38

                        radius: QuattroTheme.Theme.cornerRadius

                        color:
                            inputMuteMouse.containsMouse
                                ? QuattroTheme.Theme.hover
                                : QuattroTheme.Theme.surfaceRaised

                        border.width: 1

                        border.color:
                            root.sourceMuted
                                ? QuattroTheme.Theme.textDim
                                : QuattroTheme.Theme.border

                        Text {
                            anchors.centerIn: parent

                            text:
                                root.sourceIcon()

                            color:
                                root.source
                                    ? (
                                        root.sourceMuted
                                            ? QuattroTheme.Theme.textMuted
                                            : QuattroTheme.Theme.text
                                    )
                                    : QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 18
                        }

                        MouseArea {
                            id: inputMuteMouse

                            anchors.fill: parent

                            enabled:
                                root.source !== null
                                && root.source.audio !== null

                            hoverEnabled: true

                            cursorShape:
                                enabled
                                    ? Qt.PointingHandCursor
                                    : Qt.ArrowCursor

                            onClicked: {
                                root.source.audio.muted =
                                    !root.source.audio.muted
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        height: 38

                        Rectangle {
                            id: inputTrack

                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter

                            height: 6
                            radius: QuattroTheme.Theme.cornerRadius

                            color: QuattroTheme.Theme.border

                            Rectangle {
                                width:
                                    parent.width
                                    * root.clamp(
                                        root.sourceVolume,
                                        0.0,
                                        1.0
                                    )

                                height: parent.height
                                radius: parent.radius

                                color:
                                    root.sourceMuted
                                        ? QuattroTheme.Theme.textDim
                                        : QuattroTheme.Theme.text
                            }

                            Rectangle {
                                x:
                                    root.clamp(
                                        root.sourceVolume,
                                        0.0,
                                        1.0
                                    )
                                    * (
                                        inputTrack.width
                                        - width
                                    )

                                anchors.verticalCenter:
                                    parent.verticalCenter

                                width: 14
                                height: 14

                                radius: QuattroTheme.Theme.cornerRadius

                                color:
                                    inputSliderMouse.pressed
                                        ? QuattroTheme.Theme.textStrong
                                        : QuattroTheme.Theme.text

                                border.width: 1
                                border.color: QuattroTheme.Theme.textDim
                            }
                        }

                        MouseArea {
                            id: inputSliderMouse

                            anchors.fill: parent

                            enabled:
                                root.source !== null
                                && root.source.audio !== null

                            hoverEnabled: true

                            cursorShape:
                                enabled
                                    ? Qt.PointingHandCursor
                                    : Qt.ArrowCursor

                            function updateVolume(mouseX) {
                                var value =
                                    root.clamp(
                                        mouseX / width,
                                        0.0,
                                        1.0
                                    )

                                root.setSourceVolume(value)
                            }

                            onPressed: function(mouse) {
                                updateVolume(mouse.x)
                            }

                            onPositionChanged: function(mouse) {
                                if (pressed)
                                    updateVolume(mouse.x)
                            }
                        }
                    }

                    Text {
                        Layout.preferredWidth: 42

                        horizontalAlignment:
                            Text.AlignRight

                        text:
                            root.source
                                ? (
                                    root.volumePercent(
                                        root.sourceVolume
                                    )
                                    + "%"
                                )
                                : "--"

                        color: QuattroTheme.Theme.text

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 12
                    }
                }

                // =================================================
                // CURRENT INPUT DEVICE
                // =================================================

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 54
                    radius: QuattroTheme.Theme.cornerRadius

                    color:
                        inputDeviceMouse.containsMouse
                            ? QuattroTheme.Theme.hover
                            : QuattroTheme.Theme.surface

                    border.width: 1

                    border.color:
                        root.inputExpanded
                            ? QuattroTheme.Theme.borderStrong
                            : QuattroTheme.Theme.border

                    RowLayout {
                        anchors.fill: parent

                        anchors.leftMargin: 12
                        anchors.rightMargin: 12

                        spacing: 10

                        Text {
                            text: "󰍬"

                            color: QuattroTheme.Theme.text

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 17
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                Layout.fillWidth: true

                                text:
                                    root.displayName(
                                        root.source
                                    )

                                color: QuattroTheme.Theme.text

                                elide:
                                    Text.ElideRight

                                font.family:
                                    "JetBrainsMono Nerd Font"

                                font.pixelSize: 11
                            }

                            Text {
                                Layout.fillWidth: true

                                text:
                                    root.source
                                        ? "Current input"
                                        : "No microphone available"

                                color: QuattroTheme.Theme.textMuted

                                elide:
                                    Text.ElideRight

                                font.family:
                                    "JetBrainsMono Nerd Font"

                                font.pixelSize: 9
                            }
                        }

                        Text {
                            text:
                                root.inputExpanded
                                    ? "󰅃"
                                    : "󰅀"

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 13
                        }
                    }

                    MouseArea {
                        id: inputDeviceMouse

                        anchors.fill: parent

                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor

                        onClicked: {
                            root.inputExpanded =
                                !root.inputExpanded

                            root.outputExpanded = false
                        }
                    }
                }

                // =================================================
                // INPUT DEVICE LIST
                // =================================================

                ColumnLayout {
                    visible:
                        root.inputExpanded

                    Layout.fillWidth: true
                    spacing: 6

                    Repeater {
                        model:
                            Pipewire.nodes

                        delegate: Rectangle {
                            id: inputDeviceRow

                            required property var modelData

                            property bool validDevice:
                                root.isHardwareInput(
                                    modelData
                                )

                            visible:
                                validDevice

                            Layout.fillWidth: true

                            implicitHeight:
                                validDevice
                                    ? 48
                                    : 0

                            radius: QuattroTheme.Theme.cornerRadius

                            color:
                                inputRowMouse.containsMouse
                                    ? QuattroTheme.Theme.hover
                                    : QuattroTheme.Theme.surface

                            border.width: 1

                            border.color:
                                root.source === modelData
                                    ? QuattroTheme.Theme.textDim
                                    : QuattroTheme.Theme.border

                            RowLayout {
                                anchors.fill: parent

                                anchors.leftMargin: 12
                                anchors.rightMargin: 12

                                spacing: 10

                                Text {
                                    text:
                                        root.source ===
                                        inputDeviceRow.modelData
                                            ? "󰄬"
                                            : "󰍬"

                                    color:
                                        root.source ===
                                        inputDeviceRow.modelData
                                            ? QuattroTheme.Theme.text
                                            : QuattroTheme.Theme.textMuted

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 15
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1

                                    Text {
                                        Layout.fillWidth: true

                                        text:
                                            root.shortDeviceName(
                                                inputDeviceRow.modelData
                                            )

                                        color: QuattroTheme.Theme.text

                                        elide:
                                            Text.ElideRight

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 10
                                    }

                                    Text {
                                        Layout.fillWidth: true

                                        text:
                                            root.displayName(
                                                inputDeviceRow.modelData
                                            )

                                        color: QuattroTheme.Theme.textMuted

                                        elide:
                                            Text.ElideRight

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 8
                                    }
                                }

                                Text {
                                    visible:
                                        root.source ===
                                        inputDeviceRow.modelData

                                    text: "Default"

                                    color: QuattroTheme.Theme.textMuted

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 8
                                }
                            }

                            MouseArea {
                                id: inputRowMouse

                                anchors.fill: parent

                                enabled:
                                    inputDeviceRow.validDevice

                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor

                                onClicked: {
                                    Pipewire.preferredDefaultAudioSource =
                                        inputDeviceRow.modelData

                                    root.inputExpanded = false
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.leftMargin: 14
                Layout.rightMargin: 14
                Layout.topMargin: 17

                height: 1
                color: QuattroTheme.Theme.border
            }

            // ====================================================
            // APPLICATION MIXER
            // ====================================================

            ColumnLayout {
                Layout.fillWidth: true

                Layout.leftMargin: 18
                Layout.rightMargin: 18
                Layout.topMargin: 16
                Layout.bottomMargin: 18

                spacing: 10

                RowLayout {
                    Layout.fillWidth: true

                    Text {
                        text: "APPLICATIONS"

                        color: QuattroTheme.Theme.textMuted

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Text {
                        text: "Active streams"

                        color: QuattroTheme.Theme.textDim

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 8
                    }
                }

                Repeater {
                    model:
                        Pipewire.nodes

                    delegate: Rectangle {
                        id: streamRow

                        required property var modelData

                        property bool validStream:
                            root.isPlaybackStream(
                                modelData
                            )

                        property real streamVolume:
                            validStream
                            && modelData.audio
                                ? modelData.audio.volume
                                : 0.0

                        property bool streamMuted:
                            validStream
                            && modelData.audio
                                ? modelData.audio.muted
                                : false

                        visible:
                            validStream

                        Layout.fillWidth: true

                        implicitHeight:
                            validStream
                                ? 82
                                : 0

                        radius: QuattroTheme.Theme.cornerRadius

                        color: QuattroTheme.Theme.surface

                        border.width: 1
                        border.color: QuattroTheme.Theme.border

                        PwObjectTracker {
                            objects: [
                                streamRow.modelData
                            ]
                        }

                        ColumnLayout {
                            anchors.fill: parent

                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            anchors.topMargin: 9
                            anchors.bottomMargin: 9

                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    text: "󰎆"

                                    color: QuattroTheme.Theme.text

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 15
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1

                                    Text {
                                        Layout.fillWidth: true

                                        text:
                                            root.streamName(
                                                streamRow.modelData
                                            )

                                        color: QuattroTheme.Theme.text

                                        elide:
                                            Text.ElideRight

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }

                                    Text {
                                        Layout.fillWidth: true

                                        text:
                                            root.streamDescription(
                                                streamRow.modelData
                                            )

                                        color: QuattroTheme.Theme.textMuted

                                        elide:
                                            Text.ElideRight

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 8
                                    }
                                }

                                Text {
                                    text:
                                        root.volumePercent(
                                            streamRow.streamVolume
                                        )
                                        + "%"

                                    color: QuattroTheme.Theme.text

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 10
                                }

                                Rectangle {
                                    width: 30
                                    height: 30

                                    radius: QuattroTheme.Theme.cornerRadius

                                    color:
                                        streamMuteMouse.containsMouse
                                            ? QuattroTheme.Theme.border
                                            : QuattroTheme.Theme.hover

                                    border.width: 1
                                    border.color: QuattroTheme.Theme.border

                                    Text {
                                        anchors.centerIn: parent

                                        text:
                                            streamRow.streamMuted
                                                ? "󰖁"
                                                : "󰕾"

                                        color:
                                            streamRow.streamMuted
                                                ? QuattroTheme.Theme.textMuted
                                                : QuattroTheme.Theme.text

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 14
                                    }

                                    MouseArea {
                                        id: streamMuteMouse

                                        anchors.fill: parent

                                        enabled:
                                            streamRow.validStream
                                            && streamRow.modelData.audio !== null

                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor

                                        onClicked: {
                                            streamRow.modelData.audio.muted =
                                                !streamRow.modelData.audio.muted
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                Text {
                                    text:
                                        streamRow.streamMuted
                                            ? "󰖁"
                                            : "󰕾"

                                    color:
                                        streamRow.streamMuted
                                            ? QuattroTheme.Theme.textMuted
                                            : QuattroTheme.Theme.text

                                    font.family:
                                        "JetBrainsMono Nerd Font"

                                    font.pixelSize: 12
                                }

                                Item {
                                    Layout.fillWidth: true
                                    height: 28

                                    Rectangle {
                                        id: streamTrack

                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter

                                        height: 5
                                        radius: QuattroTheme.Theme.cornerRadius

                                        color: QuattroTheme.Theme.border

                                        Rectangle {
                                            width:
                                                parent.width
                                                * root.clamp(
                                                    streamRow.streamVolume,
                                                    0.0,
                                                    1.0
                                                )

                                            height: parent.height
                                            radius: parent.radius

                                            color:
                                                streamRow.streamMuted
                                                    ? QuattroTheme.Theme.textDim
                                                    : QuattroTheme.Theme.text
                                        }

                                        Rectangle {
                                            x:
                                                root.clamp(
                                                    streamRow.streamVolume,
                                                    0.0,
                                                    1.0
                                                )
                                                * (
                                                    streamTrack.width
                                                    - width
                                                )

                                            anchors.verticalCenter:
                                                parent.verticalCenter

                                            width: 12
                                            height: 12

                                            radius: QuattroTheme.Theme.cornerRadius

                                            color:
                                                streamSliderMouse.pressed
                                                    ? QuattroTheme.Theme.textStrong
                                                    : QuattroTheme.Theme.text

                                            border.width: 1
                                            border.color: QuattroTheme.Theme.textDim
                                        }
                                    }

                                    MouseArea {
                                        id: streamSliderMouse

                                        anchors.fill: parent

                                        enabled:
                                            streamRow.validStream
                                            && streamRow.modelData.audio !== null

                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor

                                        function updateVolume(mouseX) {
                                            if (
                                                !streamRow.modelData
                                                || !streamRow.modelData.audio
                                            ) {
                                                return
                                            }

                                            var value =
                                                root.clamp(
                                                    mouseX / width,
                                                    0.0,
                                                    1.0
                                                )

                                            streamRow.modelData.audio.volume =
                                                value

                                            if (
                                                streamRow.modelData.audio.muted
                                                && value > 0.0
                                            ) {
                                                streamRow.modelData.audio.muted =
                                                    false
                                            }
                                        }

                                        onPressed: function(mouse) {
                                            updateVolume(mouse.x)
                                        }

                                        onPositionChanged: function(mouse) {
                                            if (pressed)
                                                updateVolume(mouse.x)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
