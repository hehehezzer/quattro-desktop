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
    property var snapshot: ({
            gains: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            preset: "Flat",
            presets: [],
            active: false
        })
    readonly property bool active: Pipewire.nodes.values.some(node => node.name === "quattro_eq")
    property var gains: snapshot.gains
    property string error: ""
    property bool expanded: false
    property var pending: null
    property string outputName: ""
    spacing: 8
    function execute(args) {
        if (worker.running) {
            pending = args;
            return;
        }
        worker.command = ["python3", Quickshell.env("HOME") + "/.local/bin/quattro_desktop_controls.py", "eq"].concat(args);
        worker.running = true;
    }
    function selectOutput(name) {
        execute(["output", name]);
    }
    function adjust(index, value) {
        const next = gains.slice();
        next[index] = Math.round(value * 2) / 2;
        gains = next;
        debounce.restart();
    }
    Component.onCompleted: execute(["status"])
    onVisibleChanged: if (visible)
        execute(["status"])
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
                    const result = JSON.parse(text);
                    root.error = result.error || "";
                    if (!result.error) {
                        root.snapshot = result;
                        if (!debounce.running && !root.pending)
                            root.gains = result.gains;
                    }
                } catch (e) {
                    root.error = "Equalizer service unavailable";
                }
            }
        }
        onExited: {
            if (root.pending) {
                const next = root.pending;
                root.pending = null;
                Qt.callLater(() => root.execute(next));
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        DesktopButton {
            Layout.fillWidth: true
            text: root.expanded ? "Equalizer ▴" : "Equalizer ▾"
            onClicked: root.expanded = !root.expanded
        }
        DesktopButton {
            text: root.active ? "Disable" : "Enable"
            enabled: !worker.running
            onClicked: root.execute(root.active ? ["disable"] : ["custom"].concat(root.gains.map(String)))
        }
    }
    Text {
        Layout.fillWidth: true
        text: root.error || (root.active ? (root.outputName === "quattro_eq" ? "Active" : "Bypassed · select Quattro Equalizer output") + " · " + root.snapshot.preset + " · headroom −" + (root.snapshot.headroom || 0) + " dB" : "Off · original audio path")
        wrapMode: Text.Wrap
        color: root.error ? QuattroTheme.Theme.danger : QuattroTheme.Theme.textMuted
        font.pixelSize: 10
    }
    ColumnLayout {
        visible: root.expanded
        Layout.fillWidth: true
        RowLayout {
            Layout.fillWidth: true
            DesktopCombo {
                Layout.fillWidth: true
                model: root.snapshot.presets.concat(["Custom"])
                currentIndex: root.snapshot.presets.indexOf(root.snapshot.preset) >= 0 ? root.snapshot.presets.indexOf(root.snapshot.preset) : root.snapshot.presets.length
                enabled: !worker.running
                Accessible.name: "Equalizer preset"
                onActivated: if (currentText !== "Custom")
                    root.execute(["preset", currentText])
            }
            DesktopButton {
                text: "Reset / Flat"
                enabled: !worker.running
                onClicked: root.execute(["preset", "Flat"])
            }
        }
        Text {
            Layout.fillWidth: true
            text: "Adjustments enable EQ. Positive bands reduce preamp gain to protect against clipping."
            wrapMode: Text.Wrap
            color: QuattroTheme.Theme.textMuted
            font.pixelSize: 10
        }
        Repeater {
            model: ["31 Hz", "62 Hz", "125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz"]
            delegate: RowLayout {
                required property int index
                required property string modelData
                Layout.fillWidth: true
                Text {
                    text: modelData
                    Layout.preferredWidth: 50
                    color: QuattroTheme.Theme.text
                    font.pixelSize: 11
                }
                Slider {
                    id: bandSlider
                    Layout.fillWidth: true
                    from: -12
                    to: 12
                    stepSize: 0.5
                    value: root.gains[index]
                    Accessible.name: modelData + " gain in decibels"
                    onMoved: root.adjust(index, value)
                    background: Rectangle {
                        x: bandSlider.leftPadding
                        y: bandSlider.topPadding + bandSlider.availableHeight / 2 - height / 2
                        width: bandSlider.availableWidth
                        height: 4
                        color: QuattroTheme.Theme.border
                        Rectangle {
                            width: parent.width * ((root.gains[index] + 12) / 24)
                            height: parent.height
                            color: QuattroTheme.Theme.text
                        }
                    }
                    handle: Rectangle {
                        x: bandSlider.leftPadding + bandSlider.visualPosition * (bandSlider.availableWidth - width)
                        y: bandSlider.topPadding + bandSlider.availableHeight / 2 - height / 2
                        width: 12
                        height: 16
                        color: bandSlider.pressed ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.text
                        border.width: 1
                        border.color: bandSlider.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.border
                    }
                }
                Text {
                    text: Number(root.gains[index]).toFixed(1) + " dB"
                    Layout.preferredWidth: 54
                    horizontalAlignment: Text.AlignRight
                    color: QuattroTheme.Theme.text
                    font.pixelSize: 10
                }
            }
        }
    }
}
