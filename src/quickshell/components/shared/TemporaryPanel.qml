import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../services"

PanelWindow {
    id: root
    required property string panelName
    property string dismissalId: "0-0"
    WlrLayershell.namespace: "quattro-popup-" + dismissalId
    signal dismissed
    visible: false
    exclusionMode: ExclusionMode.Ignore
    focusable: true
    // Keyboard-only focus while visible. Pointer input is never grabbed.
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
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
