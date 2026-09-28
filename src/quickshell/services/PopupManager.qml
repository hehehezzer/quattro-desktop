pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

QtObject {
    id: root
    property var activePanel: null
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
        panel.dismissalId = String(Date.now()) + "-" + revision;
        activePanel = panel;
    }
    function release(panel) {
        if (activePanel !== panel)
            return;
        revision++;
        activePanel = null;
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
        function dismiss(token: string): void {
            if (root.activePanel && root.activePanel.dismissalId === token)
                root.closeActive();
        }
        function status(): string {
            return JSON.stringify({
                panel: root.activePanel ? root.activePanel.panelName : "",
                screen: root.activePanel && root.activePanel.screen ? root.activePanel.screen.name : "",
                token: root.activePanel ? root.activePanel.dismissalId : "",
                pointerGrab: false
            });
        }
    }
}
