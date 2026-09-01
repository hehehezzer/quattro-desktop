import Quickshell
import Quickshell.Io
import QtQuick
import "../theme" as QuattroTheme

Scope {
    id: root

    property string command: Quickshell.env("QUATTRO_THEME_COMMAND") || "quattro-theme"

    function setTheme(name) {
        if (!QuattroTheme.Theme.apply(name))
            return
        Quickshell.execDetached([root.command, "set", name])
    }

    function nextTheme() {
        root.setTheme(QuattroTheme.Theme.next())
    }

    Component.onCompleted: loadProcess.running = true

    Process {
        id: loadProcess
        command: [root.command, "current"]
        stdout: StdioCollector {
            onStreamFinished: root.setTheme(text.trim())
        }
    }

    IpcHandler {
        target: "theme"

        function set(name: string): void {
            root.setTheme(name)
        }

        function next(): void {
            root.nextTheme()
        }

        function current(): string {
            return QuattroTheme.Theme.current
        }
    }
}
