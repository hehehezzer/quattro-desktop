import Quickshell
import Quickshell.Io
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as QuattroTheme

Scope {
    id: root

    property bool opened: false
    property string query: ""
    property int selectedIndex: 0
    property var history: []

    // Maximum number of clipboard entries retained.
    property int historyLimit: 500

    property string stateDir:
        (Quickshell.env("XDG_STATE_HOME") ||
            (Quickshell.env("HOME") + "/.local/state"))
        + "/quickshell"

    property string historyFile:
        stateDir + "/clipboard-history.json"

    // ============================================================
    // WINDOW
    // ============================================================

    PanelWindow {
        id: window

        visible: root.opened

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        color: "transparent"

        exclusionMode:
            ExclusionMode.Ignore

        focusable: true

        Shortcut {
            id: clipboardEscapeShortcut

            sequence: "Escape"
            enabled: root.opened
            context: Qt.WindowShortcut

            onActivated: {
                root.close()
            }
        }

        // ========================================================
        // BACKDROP
        // ========================================================

        Rectangle {
            anchors.fill: parent

            color: QuattroTheme.Theme.overlay

            MouseArea {
                anchors.fill: parent

                onClicked: {
                    root.close()
                }
            }
        }

        // ========================================================
        // MAIN CARD
        // ========================================================

        Rectangle {
            id: card

            anchors.centerIn: parent

            width:
                Math.min(
                    window.width - 80,
                    900
                )

            height:
                Math.min(
                    window.height - 100,
                    620
                )

            radius: QuattroTheme.Theme.cornerRadius

            color: QuattroTheme.Theme.background

            border.width: 1
            border.color: QuattroTheme.Theme.border

            // ----------------------------------------------------
            // Prevent clicks anywhere inside the card from reaching
            // the fullscreen backdrop MouseArea.
            //
            // Interactive controls declared later remain above this
            // absorber and still receive their own events.
            // ----------------------------------------------------

            MouseArea {
                id: cardClickAbsorber

                anchors.fill: parent

                acceptedButtons:
                    Qt.LeftButton
                    | Qt.RightButton
                    | Qt.MiddleButton

                propagateComposedEvents: false

                onPressed: function(mouse) {
                    mouse.accepted = true
                }

                onClicked: function(mouse) {
                    mouse.accepted = true
                }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18

                spacing: 12

                // =================================================
                // HEADER
                // =================================================

                RowLayout {
                    Layout.fillWidth: true

                    Text {
                        text: "Clipboard"

                        color: QuattroTheme.Theme.text

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 18
                        font.bold: true
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Text {
                        text: "Esc"

                        color: QuattroTheme.Theme.textMuted

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 10
                    }
                }

                // =================================================
                // SEARCH
                // =================================================

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 42

                    radius: QuattroTheme.Theme.cornerRadius

                    color: QuattroTheme.Theme.surface

                    border.width: 1

                    border.color:
                        searchInput.activeFocus
                            ? QuattroTheme.Theme.textDim
                            : QuattroTheme.Theme.border

                    RowLayout {
                        anchors.fill: parent

                        anchors.leftMargin: 12
                        anchors.rightMargin: 12

                        spacing: 8

                        Text {
                            text: "󰍉"

                            color: QuattroTheme.Theme.textMuted

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 14
                        }

                        TextInput {
                            id: searchInput

                            Layout.fillWidth: true

                            text:
                                root.query

                            color: QuattroTheme.Theme.text

                            selectionColor: QuattroTheme.Theme.textDim
                            selectedTextColor: QuattroTheme.Theme.textStrong

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 12

                            clip: true

                            onTextChanged: {
                                root.query = text
                                root.selectedIndex = 0
                            }

                            Keys.onPressed: function(event) {
                                if (
                                    event.key === Qt.Key_Escape
                                ) {
                                    root.close()
                                    event.accepted = true
                                    return
                                }

                                if (
                                    event.key === Qt.Key_Down
                                ) {
                                    root.moveSelection(1)
                                    event.accepted = true
                                    return
                                }

                                if (
                                    event.key === Qt.Key_Up
                                ) {
                                    root.moveSelection(-1)
                                    event.accepted = true
                                    return
                                }

                                if (
                                    event.key === Qt.Key_Return
                                    || event.key === Qt.Key_Enter
                                ) {
                                    if (
                                        event.modifiers
                                        & Qt.ShiftModifier
                                    ) {
                                        root.copySelected(false)
                                    } else {
                                        root.copySelected(true)
                                    }

                                    event.accepted = true
                                    return
                                }

                                if (
                                    event.key === Qt.Key_Delete
                                ) {
                                    if (
                                        event.modifiers
                                        & Qt.ShiftModifier
                                    ) {
                                        root.clearHistory()
                                    } else {
                                        root.deleteSelected()
                                    }

                                    event.accepted = true
                                }
                            }
                        }
                    }
                }

                // =================================================
                // BODY
                // =================================================

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    spacing: 12

                    // =================================================
                    // HISTORY LIST
                    // =================================================

                    Rectangle {
                        Layout.preferredWidth:
                            card.width * 0.48

                        Layout.fillHeight: true

                        radius: QuattroTheme.Theme.cornerRadius

                        color: QuattroTheme.Theme.surface

                        border.width: 1
                        border.color: QuattroTheme.Theme.border

                        ListView {
                            id: historyList

                            anchors.fill: parent
                            anchors.margins: 6

                            clip: true

                            spacing: 5

                            model:
                                root.filteredHistory()

                            currentIndex:
                                root.selectedIndex

                            ScrollBar.vertical:
                                ScrollBar {
                                    policy:
                                        ScrollBar.AsNeeded
                                }

                            delegate: Rectangle {
                                required property var modelData
                                required property int index

                                width:
                                    historyList.width

                                height: 62

                                radius: QuattroTheme.Theme.cornerRadius

                                color:
                                    index === root.selectedIndex
                                        ? QuattroTheme.Theme.border
                                        : itemMouse.containsMouse
                                            ? QuattroTheme.Theme.hover
                                            : "transparent"

                                border.width:
                                    index === root.selectedIndex
                                        ? 1
                                        : 0

                                border.color: QuattroTheme.Theme.textDim

                                RowLayout {
                                    anchors.fill: parent

                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10

                                    spacing: 10

                                    Text {
                                        text:
                                            modelData.type === "image"
                                                ? "󰋩"
                                                : "󰦨"

                                        color: QuattroTheme.Theme.text

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 16
                                    }

                                    ColumnLayout {
                                        Layout.fillWidth: true

                                        spacing: 2

                                        Text {
                                            Layout.fillWidth: true

                                            text:
                                                modelData.type === "image"
                                                    ? "Image"
                                                    : root.previewText(
                                                        modelData.text
                                                    )

                                            color: QuattroTheme.Theme.text

                                            elide:
                                                Text.ElideRight

                                            font.family:
                                                "JetBrainsMono Nerd Font"

                                            font.pixelSize: 10
                                        }

                                        Text {
                                            Layout.fillWidth: true

                                            text:
                                                modelData.capturedAt
                                                    ? modelData.capturedAt
                                                    : ""

                                            color: QuattroTheme.Theme.textMuted

                                            elide:
                                                Text.ElideRight

                                            font.family:
                                                "JetBrainsMono Nerd Font"

                                            font.pixelSize: 8
                                        }
                                    }
                                }

                                Rectangle {
                                    id: rowPinButton

                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter

                                    width:
                                        modelData.pinned
                                            ? 58
                                            : 42

                                    height: 28

                                    z: 20

                                    radius: QuattroTheme.Theme.cornerRadius

                                    color:
                                        modelData.pinned
                                            ? QuattroTheme.Theme.border
                                            : rowPinMouse.containsMouse
                                                ? QuattroTheme.Theme.border
                                                : QuattroTheme.Theme.hover

                                    border.width: 1

                                    border.color:
                                        modelData.pinned
                                            ? QuattroTheme.Theme.textDim
                                            : QuattroTheme.Theme.border

                                    Text {
                                        anchors.centerIn: parent

                                        text:
                                            modelData.pinned
                                                ? "PINNED"
                                                : "PIN"

                                        color:
                                            modelData.pinned
                                                ? QuattroTheme.Theme.text
                                                : QuattroTheme.Theme.textMuted

                                        font.family:
                                            "JetBrainsMono Nerd Font"

                                        font.pixelSize: 8
                                        font.bold: modelData.pinned
                                    }

                                    MouseArea {
                                        id: rowPinMouse

                                        anchors.fill: parent

                                        hoverEnabled: true

                                        cursorShape:
                                            Qt.PointingHandCursor

                                        acceptedButtons:
                                            Qt.LeftButton

                                        onPressed: function(mouse) {
                                            mouse.accepted = true
                                        }

                                        onClicked: function(mouse) {
                                            mouse.accepted = true
                                            root.togglePin(modelData)
                                        }
                                    }
                                }

                                MouseArea {
                                    id: itemMouse

                                    anchors.fill: parent
                                    anchors.rightMargin: 74

                                    z: 1

                                    hoverEnabled: true

                                    cursorShape:
                                        Qt.PointingHandCursor
                                    onClicked: {
                                        root.selectedIndex = index
                                        root.copyEntry(modelData, false)
                                    }

                                    onDoubleClicked: {
                                        root.selectedIndex = index
                                        root.copySelected(true)
                                    }
                                }
                            }
                        }
                    }

                    // =================================================
                    // PREVIEW
                    // =================================================

                    Rectangle {
                        id: previewPanel

                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        radius: QuattroTheme.Theme.cornerRadius

                        color: QuattroTheme.Theme.surface

                        border.width: 1
                        border.color: QuattroTheme.Theme.border

                        clip: true

                        property var selected:
                            root.selectedEntry()

                        // ---------------------------------------------
                        // TEXT PREVIEW
                        // ---------------------------------------------

                        ScrollView {
                            id: textPreviewScroll

                            anchors.fill: parent
                            anchors.margins: 14

                            visible:
                                previewPanel.selected
                                && previewPanel.selected.type === "text"

                            clip: true

                            ScrollBar.vertical.policy:
                                ScrollBar.AsNeeded

                            ScrollBar.horizontal.policy:
                                ScrollBar.AlwaysOff

                            TextArea {
                                id: textPreview

                                readOnly: true

                                text:
                                    previewPanel.selected
                                        ? previewPanel.selected.text
                                        : ""

                                color: QuattroTheme.Theme.text

                                background: null

                                padding: 0

                                wrapMode:
                                    TextEdit.WrapAnywhere

                                selectByMouse: true

                                persistentSelection: true

                                font.family:
                                    "JetBrainsMono Nerd Font"

                                font.pixelSize: 11
                            }
                        }

                        // ---------------------------------------------
                        // IMAGE PREVIEW
                        // ---------------------------------------------

                        Item {
                            anchors.fill: parent
                            anchors.margins: 14

                            visible:
                                previewPanel.selected
                                && previewPanel.selected.type === "image"

                            clip: true

                            Image {
                                anchors.fill: parent

                                source:
                                    previewPanel.selected
                                        ? "file://"
                                            + previewPanel.selected.path
                                        : ""

                                fillMode:
                                    Image.PreserveAspectFit

                                asynchronous: true
                                cache: false
                            }
                        }

                        // ---------------------------------------------
                        // EMPTY STATE
                        // ---------------------------------------------

                        Text {
                            anchors.centerIn: parent

                            visible:
                                !previewPanel.selected

                            text:
                                "Clipboard history is empty"

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                "JetBrainsMono Nerd Font"

                            font.pixelSize: 11
                        }
                    }
                }

                // =================================================
                // FOOTER
                // =================================================

                RowLayout {
                    Layout.fillWidth: true

                    spacing: 12

                    Text {
                        text: "↑↓ Navigate"

                        color: QuattroTheme.Theme.textDim

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 8
                    }

                    Text {
                        text: "Enter Paste"

                        color: QuattroTheme.Theme.textDim

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 8
                    }

                    Text {
                        text: "Shift+Enter Copy"

                        color: QuattroTheme.Theme.textDim

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 8
                    }

                    Text {
                        text: "Del Remove"

                        color: QuattroTheme.Theme.textDim

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 8
                    }

                    Text {
                        text: "Shift+Del Clear"

                        color: QuattroTheme.Theme.textDim

                        font.family:
                            "JetBrainsMono Nerd Font"

                        font.pixelSize: 8
                    }

                    Item {
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    // ============================================================
    // TEXT WATCHER
    // ============================================================

    Process {
        id: textWatcher

        running: true

        command: [
            "bash",
            "-lc",
            "wl-paste --type text --watch "
            + root.shellQuote(
                (Quickshell.env("QUATTRO_CLIPBOARD_CAPTURE_COMMAND") ||
                    ((Quickshell.env("XDG_CONFIG_HOME") ||
                        (Quickshell.env("HOME") + "/.config")) +
                        "/quickshell/scripts/clipboard-capture.sh"))
            )
            + " text"
        ]

        stdout: SplitParser {
            onRead: data => {
                root.consumeCapture(data)
            }
        }
    }

    // ============================================================
    // IMAGE WATCHER
    // ============================================================

    Process {
        id: imageWatcher

        running: true

        command: [
            "bash",
            "-lc",
            "wl-paste --type image/png --watch "
            + root.shellQuote(
                (Quickshell.env("QUATTRO_CLIPBOARD_CAPTURE_COMMAND") ||
                    ((Quickshell.env("XDG_CONFIG_HOME") ||
                        (Quickshell.env("HOME") + "/.config")) +
                        "/quickshell/scripts/clipboard-capture.sh"))
            )
            + " image/png"
        ]

        stdout: SplitParser {
            onRead: data => {
                root.consumeCapture(data)
            }
        }
    }

    // ============================================================
    // IPC
    // ============================================================

    IpcHandler {
        target: "clipboard"

        function open(): void {
            root.open()
        }

        function close(): void {
            root.close()
        }

        function toggle(): void {
            if (root.opened)
                root.close()
            else
                root.open()
        }
    }

    // ============================================================
    // FILE READ
    // ============================================================

    Process {
        id: loadHistoryProcess

        command: [
            "bash",
            "-lc",
            "mkdir -p "
            + root.shellQuote(root.stateDir)
            + "; if [ -f "
            + root.shellQuote(root.historyFile)
            + " ]; then cat "
            + root.shellQuote(root.historyFile)
            + "; else printf '[]'; fi"
        ]

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var parsed =
                        JSON.parse(text)

                    if (Array.isArray(parsed))
                        root.history = parsed
                    else
                        root.history = []
                } catch (e) {
                    console.warn(
                        "Clipboard history load failed:",
                        e
                    )

                    root.history = []
                }
            }
        }
    }

    // ============================================================
    // HELPERS
    // ============================================================

    function shellQuote(value) {
        var s = String(value)

        return "'"
            + s.replace(
                /'/g,
                "'\\''"
            )
            + "'"
    }

    // ============================================================
    // FUNCTIONS
    // ============================================================

    function open() {
        opened = true

        query = ""
        selectedIndex = 0

        Qt.callLater(function() {
            searchInput.forceActiveFocus()
        })
    }

    function close() {
        opened = false

        query = ""
        selectedIndex = 0
    }

    function previewText(text) {
        if (!text)
            return ""

        var value =
            text.replace(
                /\s+/g,
                " "
            ).trim()

        if (value.length > 70)
            return value.substring(0, 70) + "…"

        return value
    }

    function consumeCapture(line) {
        if (
            !line
            || line.trim().length === 0
        ) {
            return
        }

        try {
            var entry = JSON.parse(line)

            if (
                !entry
                || !entry.type
            ) {
                return
            }

            var list = history.slice()
            var wasPinned = false

            // Preserve pin state if this exact item already exists.
            list = list.filter(function(item) {
                var same = false

                if (
                    entry.type === "text"
                    && item.type === "text"
                ) {
                    same = item.text === entry.text
                } else if (
                    entry.type === "image"
                    && item.type === "image"
                ) {
                    same = item.path === entry.path
                }

                if (same && item.pinned)
                    wasPinned = true

                return !same
            })

            entry.pinned = wasPinned
            entry.capturedAt = new Date().toLocaleString()

            list.unshift(entry)

            history = trimHistory(list)

            saveHistory()
        } catch (e) {
            console.warn(
                "Clipboard capture parse failed:",
                e
            )
        }
    }

    function entryKey(entry) {
        if (!entry)
            return ""

        if (entry.type === "text")
            return "text:" + String(entry.text)

        if (entry.type === "image")
            return "image:" + String(entry.path)

        return entry.type + ":" + JSON.stringify(entry)
    }

    function trimHistory(list) {
        var result = list.slice()

        while (result.length > historyLimit) {
            var removeIndex = -1

            // FIFO: search backwards for the oldest unpinned item.
            for (var i = result.length - 1; i >= 0; --i) {
                if (!result[i].pinned) {
                    removeIndex = i
                    break
                }
            }

            // If literally every stored item is pinned, preserve the
            // pins rather than silently deleting one.
            if (removeIndex < 0)
                break

            result.splice(removeIndex, 1)
        }

        return result
    }

    function togglePin(entry) {
        if (!entry)
            return

        var key = entryKey(entry)
        var list = history.slice()

        for (var i = 0; i < list.length; ++i) {
            if (entryKey(list[i]) === key) {
                var updated = Object.assign({}, list[i])
                updated.pinned = !updated.pinned
                list[i] = updated
                break
            }
        }

        history = list
        saveHistory()
    }

    function filteredHistory() {
        var q = query.trim().toLowerCase()

        var pinned = []
        var normal = []

        for (var i = 0; i < history.length; ++i) {
            if (history[i].pinned)
                pinned.push(history[i])
            else
                normal.push(history[i])
        }

        // Pinned entries are ALWAYS first.
        var list = pinned.concat(normal)

        if (!q)
            return list

        return list.filter(function(item) {
            if (item.type === "text") {
                return (
                    item.text
                    && item.text
                        .toLowerCase()
                        .indexOf(q) !== -1
                )
            }

            if (item.type === "image") {
                return (
                    "image".indexOf(q) !== -1
                    || (
                        item.path
                        && item.path
                            .toLowerCase()
                            .indexOf(q) !== -1
                    )
                )
            }

            return false
        })
    }

    function selectedEntry() {
        var list =
            filteredHistory()

        if (
            selectedIndex < 0
            || selectedIndex >= list.length
        ) {
            return null
        }

        return list[selectedIndex]
    }

    function moveSelection(delta) {
        var list =
            filteredHistory()

        if (list.length === 0) {
            selectedIndex = 0
            return
        }

        selectedIndex =
            Math.max(
                0,
                Math.min(
                    list.length - 1,
                    selectedIndex + delta
                )
            )

        historyList.positionViewAtIndex(
            selectedIndex,
            ListView.Contain
        )
    }

    function copyEntry(entry, pasteAfter) {
        if (!entry)
            return

        if (entry.type === "text") {
            Quickshell.execDetached([
                "bash",
                "-lc",
                "printf '%s' "
                + root.shellQuote(entry.text)
                + " | wl-copy"
                + (
                    pasteAfter
                        ? "; sleep 0.08; "
                            + "wtype -M shift -k Insert -m shift"
                        : ""
                )
            ])
        } else if (entry.type === "image") {
            Quickshell.execDetached([
                "bash",
                "-lc",
                "wl-copy --type "
                + root.shellQuote(entry.mime)
                + " < "
                + root.shellQuote(entry.path)
                + (
                    pasteAfter
                        ? "; sleep 0.08; "
                            + "wtype -M shift -k Insert -m shift"
                        : ""
                )
            ])
        }

        if (pasteAfter)
            close()
    }

    function copySelected(pasteAfter) {
        copyEntry(
            selectedEntry(),
            pasteAfter
        )
    }

    function deleteSelected() {
        var entry =
            selectedEntry()

        if (!entry)
            return

        var list =
            history.filter(function(item) {
                if (
                    item.type === "text"
                    && entry.type === "text"
                ) {
                    return item.text !== entry.text
                }

                if (
                    item.type === "image"
                    && entry.type === "image"
                ) {
                    return item.path !== entry.path
                }

                return true
            })

        history = list

        if (
            selectedIndex
            >= filteredHistory().length
        ) {
            selectedIndex =
                Math.max(
                    0,
                    filteredHistory().length - 1
                )
        }

        saveHistory()
    }

    function clearHistory() {
        history = []
        selectedIndex = 0

        saveHistory()
    }

    function saveHistory() {
        var payload =
            JSON.stringify(
                history
            )

        Quickshell.execDetached([
            "bash",
            "-lc",
            "mkdir -p "
            + root.shellQuote(stateDir)
            + "; printf '%s' "
            + root.shellQuote(payload)
            + " > "
            + root.shellQuote(historyFile)
        ])
    }

    Component.onCompleted: {
        loadHistoryProcess.running = true
    }
}
