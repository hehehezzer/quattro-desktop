import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../services"

PanelWindow {
    id: root
    required property string panelName
    property string dismissalId: "0-0"
    property bool opened: false
    onOpenedChanged: {
        if (opened) {
            PopupManager.open(root);
            visible = true;
        } else {
            visible = false;
            PopupManager.release(root);
        }
    }
    WlrLayershell.namespace: "quattro-popup-" + dismissalId
    signal dismissed
    visible: false
    exclusionMode: ExclusionMode.Ignore
    focusable: true
    // Keyboard-only focus while visible. Pointer input is never grabbed.
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    Component.onDestruction: PopupManager.release(root)
    Shortcut {
        sequence: "Escape"
        context: Qt.ApplicationShortcut
        enabled: root.visible && PopupManager.activePanel === root
        onActivated: PopupManager.close(root)
    }
}
