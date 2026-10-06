import Quickshell
import Quickshell.Wayland
import QtQuick
import "../../theme" as QuattroTheme
import "TooltipPlacement.js" as Placement

// A passive hint. Actions always remain on the source control.
Item {
    id: root
    property Item target: parent
    property string text: ""
    property Component contentComponent: null
    property int preferredWidth: 320
    property int delay: 700
    property bool allowed: true
    property bool hoverActive: hover.hovered
    property bool focusActive: target && target.activeFocus
    readonly property bool requested: allowed && target && target.enabled && target.visible
        && (hoverActive || focusActive) && (text.length > 0 || contentComponent !== null)
    readonly property var sourceWindow: target ? target.QsWindow.window : null
    readonly property var sourceScreen: sourceWindow ? sourceWindow.screen : null
    readonly property alias surface: hint
    property bool revealed: false
    property bool dismissed: false
    property var placement: null
    readonly property bool showing: revealed && requested && !dismissed && placement !== null
        && !!sourceWindow && sourceWindow.visible

    function dismiss() { dismissed = true; revealed = false; wait.stop(); Placement.release(root); }
    // Window creation can resize content while the visibility binding is being
    // evaluated. Coalesce geometry work onto the next event turn to avoid reentry.
    function schedulePlacement() { Qt.callLater(root.updatePlacement); }
    function updatePlacement() {
        if (!target || !sourceScreen) { placement = null; return; }
        const transform = sourceWindow.windowTransform;
        const px = hoverActive ? hover.point.position.x : target.width / 2;
        const py = hoverActive ? hover.point.position.y : target.height / 2;
        let origin, position;
        // Wayland layer surfaces do not have reliable Qt global coordinates.
        // Resolve their documented anchors in monitor-local logical pixels.
        if (sourceWindow.anchors !== undefined && sourceWindow.margins !== undefined) {
            const panel = Placement.panelOrigin(sourceWindow.anchors, sourceWindow.margins,
                {width:sourceWindow.width, height:sourceWindow.height}, sourceScreen);
            const local = sourceWindow.mapFromItem(target, 0, 0);
            const pointer = sourceWindow.mapFromItem(target, px, py);
            origin = {x:panel.x+local.x, y:panel.y+local.y};
            position = {x:panel.x+pointer.x, y:panel.y+pointer.y};
        } else {
            const global = target.mapToGlobal(0, 0);
            const pointer = target.mapToGlobal(px, py);
            origin = {x:global.x-sourceScreen.x, y:global.y-sourceScreen.y};
            position = {x:pointer.x-sourceScreen.x, y:pointer.y-sourceScreen.y};
        }
        placement = Placement.place(
            {x:origin.x, y:origin.y, width:target.width, height:target.height}, position,
            {width:hint.implicitWidth, height:hint.implicitHeight}, sourceScreen, 16);
    }
    function refresh() {
        if (!requested) {
            wait.stop(); revealed = false; dismissed = false; placement = null;
            Placement.release(root);
        } else if (!dismissed) {
            updatePlacement();
            if (focusActive) { Placement.claim(root); revealed = true; }
            else if (!revealed && !wait.running) wait.start();
        }
    }
    onRequestedChanged: refresh()
    onFocusActiveChanged: refresh()
    onSourceScreenChanged: refresh()
    Component.onCompleted: refresh()
    Component.onDestruction: Placement.release(root)
    Connections {
        target: root.sourceWindow
        function onVisibleChanged() {
            if (!root.sourceWindow.visible) { root.revealed = false; wait.stop(); Placement.release(root); }
            else root.refresh();
        }
    }
    HoverHandler { id: hover; parent: root.target; onPointChanged: root.schedulePlacement() }
    Timer { id: wait; interval: root.delay; onTriggered: {
        if (root.requested && !root.dismissed) { Placement.claim(root); root.updatePlacement(); root.revealed = true; }
    } }
    // Poll only while displayed, to track parent scrolling and moving windows.
    Timer { interval: 50; repeat: true; running: root.showing; onTriggered: root.updatePlacement() }
    Shortcut { sequence: "Escape"; context: Qt.WindowShortcut; enabled: root.showing; onActivated: root.dismiss() }

    Text {
        id: measure
        visible: false
        text: root.text
        textFormat: Text.PlainText
        font.family: QuattroTheme.Theme.fontFamily
        font.pixelSize: QuattroTheme.Theme.typeBody
    }
    PanelWindow {
        id: hint
        visible: root.showing && !!root.sourceWindow && root.sourceWindow.visible
        screen: root.sourceScreen
        anchors.top: true
        anchors.left: true
        margins.left: root.placement ? Math.round(root.placement.x) : 0
        margins.top: root.placement ? Math.round(root.placement.y) : 0
        exclusionMode: ExclusionMode.Ignore
        focusable: false
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        WlrLayershell.namespace: "quattro-tooltip"
        mask: Region { width: 0; height: 0 }
        color: "transparent"
        implicitWidth: Math.max(1, Math.min(root.contentComponent ? root.preferredWidth : Math.ceil(measure.implicitWidth) + 18, root.preferredWidth,
            root.sourceScreen ? root.sourceScreen.width - 16 : root.preferredWidth))
        implicitHeight: Math.max(1, Math.min(body.implicitHeight + 16,
            root.sourceScreen ? root.sourceScreen.height - 16 : 600))
        onImplicitWidthChanged: root.schedulePlacement()
        onImplicitHeightChanged: root.schedulePlacement()

        Rectangle {
            anchors.fill: parent
            radius: QuattroTheme.Theme.panelRadius
            color: QuattroTheme.Theme.panelSurface
            border.color: QuattroTheme.Theme.panelBorder
            border.width: 1
            clip: true
            Loader {
                id: body
                x: 8; y: 8; width: parent.width - 16
                sourceComponent: root.contentComponent || plainHint
            }
        }
        Component {
            id: plainHint
            Text {
                text: root.text
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: QuattroTheme.Theme.textStrong
                font.family: QuattroTheme.Theme.fontFamily
                font.pixelSize: QuattroTheme.Theme.typeBody
                Accessible.role: Accessible.ToolTip
                Accessible.name: root.text
            }
        }
    }
}
