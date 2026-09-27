pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

QtObject {
    id: root
    property var activePanel: null
    property var bars: []
    property int revision: 0
    signal requested(string name)
    function request(name) {
        revision++;
        requested(name);
    }
    function open(panel) {
        if (activePanel === panel)
            return;
        closeActive();
        revision++;
        activePanel = panel;
        // Activate with only the panel so keyboard focus cannot land on a bar.
        grab.windows = [panel];
        const token = revision;
        Qt.callLater(() => {
            if (root.revision === token && root.activePanel === panel && panel.visible)
                grab.active = true;
        });
    }
    function release(panel) {
        if (activePanel !== panel)
            return;
        revision++;
        grab.active = false;
        activePanel = null;
        grab.windows = [];
    }
    function close(panel) {
        if (!panel || activePanel !== panel)
            return;
        release(panel);
        panel.dismissed();
    }
    function closeActive() {
        close(activePanel);
    }
    function registerBar(bar) {
        bars = bars.concat([bar]);
    }
    function unregisterBar(bar) {
        bars = bars.filter(item => item !== bar);
    }
    function barTapped(token) {
        // Buttons dispatch synchronously; a blank/workspace click dismisses only
        // the panel present at press time, never the one that this click opened.
        Qt.callLater(() => {
            if (revision === token)
                closeActive();
        });
    }
    function focusedScreen() {
        for (const screen of Quickshell.screens)
            if (Hyprland.monitorFor(screen) === Hyprland.focusedMonitor)
                return screen;
        return Quickshell.screens[0];
    }
    property HyprlandFocusGrab grab: HyprlandFocusGrab {
        onActiveChanged: {
            if (active && root.activePanel)
                windows = [root.activePanel].concat(root.bars);
        }
        onCleared: root.closeActive()
    }
    property Connections monitorEvents: Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (["workspacev2", "activespecial", "monitorremoved", "fullscreen"].indexOf(event.name) >= 0)
                root.closeActive();
        }
    }
    property IpcHandler ipc: IpcHandler {
        target: "popups"
        function close(): void {
            root.closeActive();
        }
        function status(): string {
            return JSON.stringify({
                panel: root.activePanel ? root.activePanel.panelName : "",
                screen: root.activePanel && root.activePanel.screen ? root.activePanel.screen.name : "",
                grabbed: grab.active
            });
        }
    }
}
