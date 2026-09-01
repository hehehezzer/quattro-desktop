import Quickshell
import "components"

ShellRoot {
    ThemeController {}
    SystemStats {
        id: statsMonitor
    }

    Variants {
        model: Quickshell.screens

        ThemeBackground {
            property var modelData
            screen: modelData
        }
    }

    Variants {
        model: Quickshell.screens

        Bar {
            property var modelData
            screen: modelData
            systemStats: statsMonitor.snapshot
        }
    }

    SystemPanels {}
    Agents {}
    MainMenu {}
    Notifications {}
    Clipboard {}
}
