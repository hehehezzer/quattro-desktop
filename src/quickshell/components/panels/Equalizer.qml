import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../shared"
import "../../theme" as QuattroTheme

ColumnLayout {
    id: root
    readonly property var frequencies: ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"]
    property var snapshot: ({ gains: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], preset: "Flat", presets: [], active: false })
    readonly property bool active: Pipewire.nodes.values.some(node => node.name === "quattro_eq")
    property var gains: snapshot.gains
    property string error: ""
    property bool expanded: false
    property var pending: null
    property string outputName: ""
    spacing: 9

    function execute(args) {
        if (worker.running) {
            pending = args
            return
        }
        worker.command = ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_desktop_controls.py", "eq"].concat(args)
        worker.running = true
    }
    function selectOutput(name) { execute(["output", name]) }
    function adjust(index, value) {
        const next = gains.slice()
        next[index] = Math.round(value * 2) / 2
        gains = next
        debounce.restart()
    }
    Component.onCompleted: execute(["status"])
    onVisibleChanged: if (visible) execute(["status"])
    Timer {
        id: debounce
        interval: 160
        onTriggered: root.execute(["custom"].concat(root.gains.map(String)))
    }
    Process {
        id: worker
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text)
                    root.error = result.error || ""
                    if (!result.error) {
                        root.snapshot = result
                        if (!debounce.running && !root.pending)
                            root.gains = result.gains
                    }
                } catch (e) {
                    root.error = "Equalizer service unavailable"
                }
            }
        }
        onExited: {
            if (root.pending) {
                const next = root.pending
                root.pending = null
                Qt.callLater(() => root.execute(next))
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            Text {
                text: "Equalizer"
                color: QuattroTheme.Theme.textStrong
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 13
                font.bold: true
            }
            Text {
                text: root.error ? "Unavailable" : root.active
                    ? (root.outputName === "quattro_eq" ? "Active · " : "Select Equalizer output · ") + root.snapshot.preset
                    : "Off · original audio path"
                color: root.error ? QuattroTheme.Theme.danger : root.active ? QuattroTheme.Theme.success : QuattroTheme.Theme.textMuted
                font.pixelSize: 10
            }
        }
        DesktopButton {
            text: root.active ? "Disable" : "Enable"
            enabled: !worker.running
            onClicked: root.execute(root.active ? ["disable"] : ["custom"].concat(root.gains.map(String)))
        }
        DesktopButton {
            text: root.expanded ? "󰅃" : "󰅀"
            Accessible.name: root.expanded ? "Collapse equalizer" : "Expand equalizer"
            ToolTip.text: Accessible.name
            onClicked: root.expanded = !root.expanded
        }
    }

    Text {
        visible: !!root.error
        Layout.fillWidth: true
        text: root.error
        color: QuattroTheme.Theme.danger
        wrapMode: Text.Wrap
        font.pixelSize: 10
    }

    ColumnLayout {
        visible: root.expanded
        Layout.fillWidth: true
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text {
                text: "PROFILE"
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 9
                font.letterSpacing: 1
            }
            DesktopCombo {
                Layout.fillWidth: true
                model: root.snapshot.presets.concat(["Custom"])
                currentIndex: root.snapshot.presets.indexOf(root.snapshot.preset) >= 0
                    ? root.snapshot.presets.indexOf(root.snapshot.preset) : root.snapshot.presets.length
                enabled: !worker.running
                Accessible.name: "Equalizer preset"
                onActivated: if (currentText !== "Custom") root.execute(["preset", currentText])
            }
            DesktopButton {
                text: "Flat"
                ToolTip.text: "Reset all bands to zero"
                enabled: !worker.running
                onClicked: root.execute(["preset", "Flat"])
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "FREQUENCY RESPONSE"
                color: QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 9
                font.letterSpacing: 1
            }
            Text {
                text: "Headroom −" + (root.snapshot.headroom || 0) + " dB"
                color: (root.snapshot.headroom || 0) > 0 ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 9
            }
        }

        Flickable {
            id: response
            Layout.fillWidth: true
            Layout.preferredHeight: 166
            clip: true
            contentWidth: Math.max(width, 310)
            contentHeight: height
            boundsBehavior: Flickable.StopAtBounds

            Item {
                width: response.contentWidth
                height: response.height

            Rectangle {
                anchors.fill: parent
                color: QuattroTheme.Theme.surface
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                height: 1
                color: QuattroTheme.Theme.borderStrong
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                spacing: 1
                Repeater {
                    model: root.frequencies
                    delegate: ColumnLayout {
                        id: band
                        required property int index
                        required property string modelData
                        Layout.fillWidth: true
                        Layout.minimumWidth: 27
                        spacing: 1
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: (Number(root.gains[band.index]) > 0 ? "+" : "") + Number(root.gains[band.index]).toFixed(1)
                            color: Number(root.gains[band.index]) === 0 ? QuattroTheme.Theme.textMuted : QuattroTheme.Theme.textStrong
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                        }
                        Slider {
                            id: gainSlider
                            Layout.alignment: Qt.AlignHCenter
                            Layout.preferredWidth: 27
                            Layout.preferredHeight: 124
                            orientation: Qt.Vertical
                            from: -12
                            to: 12
                            stepSize: 0.5
                            value: root.gains[band.index]
                            Accessible.name: band.modelData + " hertz gain"
                            Accessible.description: "Gain in decibels"
                            onMoved: root.adjust(band.index, value)
                            onValueChanged: if (activeFocus) root.adjust(band.index, value)
                            background: Rectangle {
                                x: gainSlider.width / 2 - width / 2
                                y: gainSlider.topPadding
                                width: 4
                                height: gainSlider.availableHeight
                                color: QuattroTheme.Theme.border
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    y: parent.height / 2
                                    width: 10
                                    height: 1
                                    color: QuattroTheme.Theme.textMuted
                                }
                            }
                            handle: Rectangle {
                                x: gainSlider.width / 2 - width / 2
                                y: gainSlider.topPadding + (1 - (gainSlider.value + 12) / 24) * (gainSlider.availableHeight - height)
                                width: 17
                                height: 9
                                color: gainSlider.pressed || gainSlider.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.accent
                                border.width: gainSlider.activeFocus ? 2 : 0
                                border.color: QuattroTheme.Theme.background
                            }
                        }
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: band.modelData
                            color: QuattroTheme.Theme.textMuted
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 8
                        }
                    }
                }
            }
            }
        }
        Text {
            Layout.fillWidth: true
            text: "Positive gain automatically lowers preamp level to prevent clipping. Changes are saved."
            wrapMode: Text.Wrap
            color: QuattroTheme.Theme.textMuted
            font.pixelSize: 10
        }
    }
}
