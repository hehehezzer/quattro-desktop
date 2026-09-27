import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../services"

PanelWindow {
    id: root
    required property string panelName
    signal dismissed
    visible: false
    exclusionMode: ExclusionMode.Ignore
    focusable: true
    // The native grab owns temporary focus; never leave an exclusive layer.
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    Connections {
        target: root
        function onVisibleChanged() {
            if (root.visible)
                PopupManager.open(root);
            else
                PopupManager.release(root);
        }
    }
    Component.onDestruction: PopupManager.release(root)
    Shortcut {
        sequence: "Escape"
        context: Qt.ApplicationShortcut
        enabled: root.visible && PopupManager.activePanel === root
        onActivated: PopupManager.close(root)
    }
}
