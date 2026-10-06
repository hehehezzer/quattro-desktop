pragma ComponentBehavior: Bound

import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import Quickshell.Hyprland
import Quickshell.Wayland
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as QuattroTheme
import "../services"
import "shared"

PanelWindow {
    id: root
    WlrLayershell.namespace: "quattro-bar"
    // Permit deliberate pointer/keyboard use without claiming startup focus.
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    anchors {
        top: true
        left: true
        right: true
    }

    readonly property bool inlineLyricsAvailable: LyricsController.state === "synced"
        && LyricsController.lines.length > 0

    implicitHeight: QuattroTheme.Theme.barHeight
    color: "transparent"

    property string fontFamily: QuattroTheme.Theme.navbarFontFamily

    Rectangle {
        anchors.fill: parent
        color: QuattroTheme.Theme.barSurface

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: QuattroTheme.Theme.structuralLine
            color: QuattroTheme.Theme.panelBorder
            opacity: 0.72
        }
    }

    // Show the full date and time by default; right-click toggles to HH:mm.
    property bool alternateClockFormat: true
    property var agentUsage: ({})
    property var usageWindowList: []
    property var systemStats: ({
        "cpuPercent": 0,
        "ramPercent": 0,
        "ramUsedBytes": 0,
        "ramTotalBytes": 0,
        "available": false
    })
    property string hoveredSystemStat: cpuStatsMouse.containsMouse
        ? "cpu"
        : ramStatsMouse.containsMouse
        ? "ram"
        : ""
    property double countdownNow: Date.now()

    function gibibytes(bytes) {
        return (Number(bytes || 0) / 1073741824).toFixed(1)
    }

    function resetCountdown(window, saved) {
        if (!window || window.resetAt === undefined || window.resetAt === null)
            return "Reset time unavailable"

        let resetMs = Number(window.resetAt)
        if (!isFinite(resetMs))
            return "Reset time unavailable"
        if (resetMs < 1000000000000)
            resetMs *= 1000

        const totalMinutes = Math.max(0, Math.ceil((resetMs - root.countdownNow) / 60000))
        if (totalMinutes === 0)
            return saved ? "Reset passed" : "Resets now"

        const days = Math.floor(totalMinutes / 1440)
        const hours = Math.floor((totalMinutes % 1440) / 60)
        const minutes = totalMinutes % 60
        if (days > 0)
            return "Resets in " + days + "d " + hours + "h"
        if (hours > 0)
            return "Resets in " + hours + "h " + minutes + "m"
        return "Resets in " + minutes + "m"
    }

    function usageResetTooltip() {
        const windows = usageWindows()
        if (windows.length === 0)
            return "Usage reset unavailable"
        return windows.map(window =>
            (window.label || "Usage") + " · " + root.resetCountdown(window).replace("Resets in ", "")
        ).join("\n")
    }

    function usageWindows(usageValue) {
        const usage = usageValue || root.agentUsage || {}
        return [usage.primary, usage.secondary].filter(window =>
            window && typeof window.usedPercent === "number" && isFinite(window.usedPercent)
        )
    }

    Component.onCompleted: usageProcess.running = true
    TapHandler {
        property int pressRevision: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onPressedChanged: if (pressed) pressRevision = PopupManager.revision
        onTapped: PopupManager.barTapped(pressRevision)
    }

    Process {
        id: usageProcess
        command: [Quickshell.env("HOME") + "/.local/bin/quattro-agent", "usage", "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const parsed = JSON.parse(text)
                    root.agentUsage = parsed
                    root.usageWindowList = root.usageWindows(parsed)
                } catch (error) {
                    root.agentUsage = ({ "stale": true })
                    root.usageWindowList = []
                }
            }
        }
    }

    Timer {
        running: true
        repeat: true
        // Re-read the selected account promptly after account set/switch actions.
        interval: 2000
        onTriggered: {
            root.countdownNow = Date.now()
            usageProcess.running = false
            usageProcess.running = true
        }
    }

    function refreshClock() {
        clock.text = Qt.formatDateTime(
            new Date(),
            alternateClockFormat
                ? (root.width >= 1500 ? "dddd, MMM d  hh:mm:ss AP" : "MMM d  hh:mm:ss AP")
                : "HH:mm"
        )
    }

    PwObjectTracker {
        id: barAudioTracker

        objects: [
            Pipewire.defaultAudioSink
        ]
    }

    // ========================================================
    // LEFT
    // ========================================================

    RowLayout {
        id: leftGroup
        anchors {
            left: parent.left
            top: parent.top
            leftMargin: QuattroTheme.Theme.spaceSm
            topMargin: (QuattroTheme.Theme.barHeight - QuattroTheme.Theme.barControlHeight) / 2
        }

        spacing: QuattroTheme.Theme.space2xs

        Rectangle {
            id: menuButton
            implicitWidth: QuattroTheme.Theme.isInstrument ? 76 : QuattroTheme.Theme.compactTarget
            implicitHeight: QuattroTheme.Theme.barControlHeight
            radius: QuattroTheme.Theme.cornerRadius

            color:
                menuMouse.pressed ? QuattroTheme.Theme.pressed
                : menuMouse.containsMouse
                ? QuattroTheme.Theme.hover
                : "transparent"

            Accessible.role: Accessible.Button
            Accessible.name: "Open Quattro menu"
            Accessible.onPressAction: PopupManager.request("menu")
            activeFocusOnTab: true
            border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
            border.color: QuattroTheme.Theme.textStrong
            Keys.onReturnPressed: PopupManager.request("menu")
            Keys.onEnterPressed: PopupManager.request("menu")
            Keys.onSpacePressed: PopupManager.request("menu")

            Text {
                anchors.centerIn: parent

                text: QuattroTheme.Theme.isInstrument ? "QUATTRO" : "󰣇"

                color: QuattroTheme.Theme.textStrong

                font.family: QuattroTheme.Theme.isInstrument ? root.fontFamily : QuattroTheme.Theme.iconFontFamily
                font.pixelSize: QuattroTheme.Theme.isInstrument ? 16 : QuattroTheme.Theme.iconMedium
                anchors.verticalCenterOffset: QuattroTheme.Theme.isInstrument ? 0 : QuattroTheme.Theme.iconOpticalOffsetY
            }

            MouseArea {
                id: menuMouse

                anchors.fill: parent

                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor

                onClicked: {
                    menuButton.forceActiveFocus(Qt.MouseFocusReason)
                    PopupManager.request("menu")
                }
            }
        }

        Rectangle {
            visible: QuattroTheme.Theme.isInstrument
            implicitWidth: 1
            implicitHeight: 22
            color: QuattroTheme.Theme.borderStrong
            Layout.leftMargin: QuattroTheme.Theme.spaceXs
            Layout.rightMargin: QuattroTheme.Theme.spaceSm
        }

        Repeater {
            model: ScriptModel {
                values: Hyprland.workspaces.values.filter(
                    workspace =>
                        workspace.id > 0
                        && workspace.id <= 10
                        && workspace.monitor
                            === Hyprland.monitorFor(root.screen)
                )
            }

            delegate: Rectangle {
                id: workspaceButton

                required property var modelData

                implicitWidth:
                    QuattroTheme.Theme.isInstrument ? 28 :
                    modelData.active
                    ? 26
                    : 20

                implicitHeight: QuattroTheme.Theme.barControlHeight

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    workspaceMouse.pressed ? QuattroTheme.Theme.pressed :
                    modelData.active
                    ? (QuattroTheme.Theme.isInstrument ? QuattroTheme.Theme.surfaceRaised : QuattroTheme.Theme.accent)
                    : workspaceMouse.containsMouse
                    ? QuattroTheme.Theme.hover
                    : "transparent"

                Accessible.role: Accessible.Button
                Accessible.name: "Workspace " + modelData.id
                Accessible.description: modelData.active ? "Current workspace" : "Switch workspace"
                Accessible.onPressAction: modelData.activate()
                activeFocusOnTab: true
                border.width: activeFocus ? QuattroTheme.Theme.focusLine
                    : QuattroTheme.Theme.isInstrument && modelData.active ? 1 : 0
                border.color: activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.borderStrong
                Keys.onReturnPressed: modelData.activate()
                Keys.onEnterPressed: modelData.activate()
                Keys.onSpacePressed: modelData.activate()

                Text {
                    anchors.centerIn: parent

                    text: QuattroTheme.Theme.isInstrument
                        ? String(workspaceButton.modelData.id).padStart(2, "0") : workspaceButton.modelData.id

                    color:
                        workspaceButton.modelData.active && !QuattroTheme.Theme.isInstrument
                        ? QuattroTheme.Theme.background
                        : QuattroTheme.Theme.text

                    font.family: root.fontFamily
                    font.pixelSize: 14
                }

                MouseArea {
                    id: workspaceMouse

                    anchors.fill: parent

                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor

                    onClicked: {
                        workspaceButton.forceActiveFocus(Qt.MouseFocusReason)
                        workspaceButton.modelData.activate()
                    }
                }
            }
        }
    }

    // ========================================================
    // CENTER CLOCK
    // ========================================================

    MediaStrip {
        id: mediaStrip
        fontFamily: root.fontFamily
        textPixelSize: 12
        x: leftGroup.x + leftGroup.width + QuattroTheme.Theme.spaceSm
        y: (QuattroTheme.Theme.barHeight - height) / 2
        readonly property real availableWidth: Math.max(0, clockArea.x - x - QuattroTheme.Theme.spaceSm)
        readonly property real lyricsReserve: root.inlineLyricsAvailable
            && availableWidth >= (player ? 286 : 126) + 220 + QuattroTheme.Theme.spaceMd
            ? 220 + QuattroTheme.Theme.spaceMd : 0
        width: Math.min(player ? 390 : 136, availableWidth - lyricsReserve)
        visible: width >= (player ? 220 : 126)
        onOpenRequested: PopupManager.request("spotify")
    }

    Item {
        id: inlineLyrics
        x: mediaStrip.x + mediaStrip.width + QuattroTheme.Theme.spaceMd
        y: 0
        width: Math.max(0, clockArea.x - x - QuattroTheme.Theme.spaceSm)
        height: QuattroTheme.Theme.barHeight
        visible: root.inlineLyricsAvailable && width >= 220
        clip: true
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: "Synchronized Spotify lyrics"
        Accessible.description: "Open Spotify and full lyrics"
        Accessible.onPressAction: PopupManager.request("spotify")
        Keys.onReturnPressed: PopupManager.request("spotify")
        Keys.onEnterPressed: PopupManager.request("spotify")
        Keys.onSpacePressed: PopupManager.request("spotify")
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: inlineLyrics.activeFocus ? QuattroTheme.Theme.focusLine : 0
            border.color: QuattroTheme.Theme.textStrong
        }

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: QuattroTheme.Theme.structuralLine
            height: QuattroTheme.Theme.barControlHeight - QuattroTheme.Theme.spaceSm
            color: QuattroTheme.Theme.border
        }

        Text {
            anchors.fill: parent
            anchors.leftMargin: QuattroTheme.Theme.spaceSm
            anchors.rightMargin: QuattroTheme.Theme.spaceXs
            text: LyricsController.lines.length > 0
                ? LyricsController.lines[Math.min(LyricsController.lines.length - 1,
                    Math.max(0, LyricsController.activeIndex))].text : ""
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideNone
            horizontalAlignment: Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
            color: QuattroTheme.Theme.textStrong
            font.family: root.fontFamily
            font.pixelSize: 14
            font.bold: false
            fontSizeMode: Text.Fit
            minimumPixelSize: QuattroTheme.Theme.typeMicro
        }

        HoverHandler { id: inlineLyricsHover }
        TapHandler { onTapped: PopupManager.request("spotify") }
        HoverTooltip {
            target: parent
            hoverActive: inlineLyricsHover.hovered
            text: "Open Spotify and full lyrics"
        }
    }

    Item {
        id: clockArea
        x: Math.max(leftGroup.x + leftGroup.width + QuattroTheme.Theme.spaceSm,
            Math.min((root.width - width) / 2,
                rightGroup.x - width - QuattroTheme.Theme.spaceMd))
        y: 0

        width: clockButton.implicitWidth
        height: QuattroTheme.Theme.barHeight

        Rectangle {
            id: clockButton

            anchors.centerIn: parent

            implicitWidth: clockWeatherRow.implicitWidth + 16
            implicitHeight: QuattroTheme.Theme.barControlHeight

            radius: QuattroTheme.Theme.cornerRadius

            color:
                clockMouse.pressed ? QuattroTheme.Theme.pressed :
                clockMouse.containsMouse
                ? QuattroTheme.Theme.hover
                : "transparent"
            activeFocusOnTab: true
            border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
            border.color: QuattroTheme.Theme.textStrong
            Accessible.role: Accessible.Button
            Accessible.name: "Date, time and weather"
            Accessible.onPressAction: PopupManager.request("clock")
            Keys.onReturnPressed: PopupManager.request("clock")
            Keys.onEnterPressed: PopupManager.request("clock")
            Keys.onSpacePressed: PopupManager.request("clock")
            Keys.onMenuPressed: {
                root.alternateClockFormat = !root.alternateClockFormat
                root.refreshClock()
            }

            Row {
                id: clockWeatherRow
                anchors.centerIn: parent
                spacing: QuattroTheme.Theme.spaceSm

                Text {
                    id: clock

                text: Qt.formatDateTime(
                    new Date(),
                    root.alternateClockFormat
                        ? (root.width >= 1500 ? "dddd, MMM d  hh:mm:ss AP" : "MMM d  hh:mm:ss AP")
                        : "HH:mm"
                )

                color: QuattroTheme.Theme.textStrong

                font.family: root.fontFamily
                    font.pixelSize: 16
                }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 1
                    height: 12
                    color: QuattroTheme.Theme.border
                }

                Text {
                    id: weatherLabel
                    text: DesktopWeather.label
                    color: DesktopWeather.snapshot.stale
                        ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
                    font.family: root.fontFamily
                    font.pixelSize: 14
                }
            }

            Timer {
                running: true
                repeat: true
                interval: 1000

                onTriggered: {
                    root.refreshClock()
                }
            }

            MouseArea {
                id: clockMouse

                anchors.fill: parent

                hoverEnabled: true

                acceptedButtons:
                    Qt.LeftButton
                    | Qt.RightButton
                    | Qt.MiddleButton

                cursorShape: Qt.PointingHandCursor

                onClicked: function(mouse) {
                    clockButton.forceActiveFocus(Qt.MouseFocusReason)
                    if (mouse.button === Qt.LeftButton) {
                        PopupManager.request("clock")

                        return
                    }

                    if (mouse.button === Qt.RightButton) {
                        root.alternateClockFormat =
                            !root.alternateClockFormat

                        root.refreshClock()
                        return
                    }

                    // Reserved for timezone selector.
                }
            }
        }
    }

    // ========================================================
    // RIGHT
    // ========================================================

    RowLayout {
        id: rightGroup
        anchors {
            right: parent.right
            top: parent.top
            rightMargin: QuattroTheme.Theme.spaceSm
            topMargin: (QuattroTheme.Theme.barHeight - QuattroTheme.Theme.barControlHeight) / 2
        }

        spacing: QuattroTheme.Theme.space2xs

        RunningApps {
            barWindow: root
            text: "Apps"
            implicitWidth: 64
            font.family: root.fontFamily
            font.pixelSize: 14
        }
        DesktopButton {
            id: notificationsButton
            text: "󰂚"
            quiet: true
            implicitWidth: QuattroTheme.Theme.compactTarget
            implicitHeight: QuattroTheme.Theme.barControlHeight
            font.pixelSize: QuattroTheme.Theme.iconSmall
            Accessible.name: "Notifications" + (NotificationHistory.unseenCount > 0
                ? " · " + NotificationHistory.unseenCount + " unread" : "")
            ToolTip.text: Accessible.name
            onClicked: PopupManager.request("notifications")
            Rectangle {
                anchors { top: parent.top; right: parent.right; margins: 3 }
                width: 5; height: 5; radius: 2.5
                visible: NotificationHistory.unseenCount > 0
                color: QuattroTheme.Theme.textStrong
            }
        }


        Rectangle {
            id: systemStatsButton
            visible: root.width >= 1000
            implicitWidth: systemStatsRow.implicitWidth + 14
            implicitHeight: QuattroTheme.Theme.barControlHeight
            radius: QuattroTheme.Theme.cornerRadius
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: "Open monitoring"
            Keys.onReturnPressed: PopupManager.request("monitoring")
            Keys.onSpacePressed: PopupManager.request("monitoring")
            border.width: activeFocus ? 2 : 0
            border.color: QuattroTheme.Theme.textStrong
            color: root.hoveredSystemStat !== "" ? QuattroTheme.Theme.hover : "transparent"

            Row {
                id: systemStatsRow
                anchors.centerIn: parent
                spacing: QuattroTheme.Theme.spaceSm

                Item {
                    id: cpuStatsItem
                    implicitWidth: cpuStatsContent.implicitWidth
                    implicitHeight: QuattroTheme.Theme.barControlHeight

                    Row {
                        id: cpuStatsContent
                        anchors.centerIn: parent
                        spacing: QuattroTheme.Theme.spaceXs
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
                            text: "󰍛"
                            color: QuattroTheme.Theme.text
                            font.family: QuattroTheme.Theme.iconFontFamily
                            font.pixelSize: QuattroTheme.Theme.iconSmall
                        }
                        Text {
                            id: cpuStatsLabel
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.systemStats && root.systemStats.available
                                ? Math.round(root.systemStats.cpuPercent) + "%" : "--"
                            color: QuattroTheme.Theme.text
                            font.family: root.fontFamily
                            font.pixelSize: 14
                        }
                    }

                    MouseArea {
                        id: cpuStatsMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: PopupManager.request("monitoring")
                    }
                }

                Item {
                    id: ramStatsItem
                    implicitWidth: ramStatsContent.implicitWidth
                    implicitHeight: QuattroTheme.Theme.barControlHeight

                    Row {
                        id: ramStatsContent
                        anchors.centerIn: parent
                        spacing: QuattroTheme.Theme.spaceXs
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
                            text: "󰘚"
                            color: QuattroTheme.Theme.text
                            font.family: QuattroTheme.Theme.iconFontFamily
                            font.pixelSize: QuattroTheme.Theme.iconSmall
                        }
                        Text {
                            id: ramStatsLabel
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.systemStats && root.systemStats.available
                                ? Math.round(root.systemStats.ramPercent) + "%" : "--"
                            color: QuattroTheme.Theme.text
                            font.family: root.fontFamily
                            font.pixelSize: 14
                        }
                    }

                    MouseArea {
                        id: ramStatsMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: PopupManager.request("monitoring")
                    }
                }
            }
        }

        Rectangle {
            id: agentUsageButton
            visible: root.width >= 1200
            implicitWidth: agentUsageContent.implicitWidth + 14
            implicitHeight: QuattroTheme.Theme.barControlHeight
            radius: QuattroTheme.Theme.cornerRadius
            color: agentMouse.pressed ? QuattroTheme.Theme.pressed
                : agentMouse.containsMouse ? QuattroTheme.Theme.hover : "transparent"
            activeFocusOnTab: true
            border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
            border.color: QuattroTheme.Theme.textStrong
            Accessible.role: Accessible.Button
            Accessible.name: "AI usage limits"
            Accessible.onPressAction: PopupManager.request("agents")
            Keys.onReturnPressed: PopupManager.request("agents")
            Keys.onEnterPressed: PopupManager.request("agents")
            Keys.onSpacePressed: PopupManager.request("agents")

            Row {
                id: agentUsageContent
                anchors.centerIn: parent
                spacing: QuattroTheme.Theme.spaceXs
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
                    text: "󰚩"
                    color: agentLabel.color
                    font.family: QuattroTheme.Theme.iconFontFamily
                    font.pixelSize: QuattroTheme.Theme.iconSmall
                }
                Text {
                    id: agentLabel
                    anchors.verticalCenter: parent.verticalCenter
                    text: {
                        const usage = root.agentUsage || {}
                        const windows = root.usageWindows(usage)
                        if (usage.authenticationRequired)
                            return "Sign in"
                        if (windows.length === 0)
                            return "--"
                        return windows.map(window =>
                            (window.label || "Usage") + " " + Math.round(100 - window.usedPercent) + "%"
                        ).join("  ") + (usage.stale ? " · saved" : "")
                    }
                    color: root.agentUsage && root.agentUsage.stale
                        ? QuattroTheme.Theme.warning
                        : root.agentUsage && root.agentUsage.loggedIn
                        ? QuattroTheme.Theme.success
                        : QuattroTheme.Theme.text
                    font.family: root.fontFamily
                    font.pixelSize: 14
                }
            }

            MouseArea {
                id: agentMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onContainsMouseChanged: {
                    if (containsMouse)
                        root.countdownNow = Date.now()
                }
                onClicked: {
                    agentUsageButton.forceActiveFocus(Qt.MouseFocusReason)
                    PopupManager.request("agents")
                }
            }
        }


        BarIcon {
            glyph: "󰂯"
            accessibleName: "Bluetooth"

            onClicked: {
                PopupManager.request("bluetooth")
            }
        }

        BarIcon {
            glyph: "󰖩"
            accessibleName: "Network"

            onClicked: {
                PopupManager.request("network")
            }
        }

        BarIcon {
            accessibleName: "Audio"
            glyph:
                !Pipewire.defaultAudioSink
                || !Pipewire.defaultAudioSink.audio
                ? "󰖁"
                : Pipewire.defaultAudioSink.audio.muted
                ? "󰖁"
                : Pipewire.defaultAudioSink.audio.volume <= 0.0
                ? "󰕿"
                : Pipewire.defaultAudioSink.audio.volume < 0.34
                ? "󰕿"
                : Pipewire.defaultAudioSink.audio.volume < 0.67
                ? "󰖀"
                : "󰕾"

            onClicked: PopupManager.request("audio")
            onMiddleClicked: PopupManager.request("audio")

            onRightClicked: {
                Quickshell.execDetached([
                    "wpctl",
                    "set-mute",
                    "@DEFAULT_AUDIO_SINK@",
                    "toggle"
                ])
            }

            onWheelUp: {
                Quickshell.execDetached([
                    "wpctl",
                    "set-volume",
                    "-l",
                    "1.0",
                    "@DEFAULT_AUDIO_SINK@",
                    "5%+"
                ])
            }

            onWheelDown: {
                Quickshell.execDetached([
                    "wpctl",
                    "set-volume",
                    "-l",
                    "1.0",
                    "@DEFAULT_AUDIO_SINK@",
                    "5%-"
                ])
            }
        }

        BarIcon {
            glyph: "󰍹"
            accessibleName: "Display"

            onClicked: {
                PopupManager.request("display")
            }
        }

        BarIcon {
            glyph: ""
            accessibleName: "Power"

            onClicked: {
                PopupManager.request("power")
            }
        }
    }

    HoverTooltip {
        target: root.hoveredSystemStat === "ram" ? ramStatsItem : cpuStatsItem
        allowed: !PopupManager.activePanel
        hoverActive: root.hoveredSystemStat !== ""
        focusActive: systemStatsButton.activeFocus
        preferredWidth: 220
        contentComponent: Component {
            Column {
                spacing: 3
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: root.hoveredSystemStat === "ram"
                        ? "RAM usage · " + Math.round((root.systemStats && root.systemStats.ramPercent) || 0) + "%"
                        : "CPU usage · " + Math.round((root.systemStats && root.systemStats.cpuPercent) || 0) + "%"
                    color: QuattroTheme.Theme.textStrong
                    font.family: root.fontFamily
                    font.pixelSize: 10
                }
                Text {
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: root.hoveredSystemStat === "ram"
                        ? root.gibibytes(root.systemStats && root.systemStats.ramUsedBytes)
                            + " / " + root.gibibytes(root.systemStats && root.systemStats.ramTotalBytes) + " GiB in use"
                        : "Aggregate processor load"
                    color: QuattroTheme.Theme.text
                    font.family: root.fontFamily
                    font.pixelSize: 10
                }
                Text {
                    width: parent.width
                    visible: systemStatsButton.activeFocus && root.hoveredSystemStat === ""
                    wrapMode: Text.Wrap
                    text: "RAM usage · " + Math.round((root.systemStats && root.systemStats.ramPercent) || 0) + "% · "
                        + root.gibibytes(root.systemStats && root.systemStats.ramUsedBytes)
                        + " / " + root.gibibytes(root.systemStats && root.systemStats.ramTotalBytes) + " GiB in use"
                    color: QuattroTheme.Theme.text
                    font.family: root.fontFamily
                    font.pixelSize: 10
                }
            }
        }
    }

    HoverTooltip {
        target: agentUsageButton
        allowed: !PopupManager.activePanel
        hoverActive: agentMouse.containsMouse
        preferredWidth: 220
        contentComponent: Component {
            Column {
                id: agentUsagePopupContent
                Accessible.role: Accessible.ToolTip
                Accessible.name: root.agentUsage.message || "Current usage limits"
                spacing: 4

                Text {
                    width: parent.width
                    text: root.agentUsage.message || (root.usageWindowList.length ? "Current usage limits" : "Usage limits unavailable")
                    color: root.agentUsage.stale ? QuattroTheme.Theme.warning : QuattroTheme.Theme.text
                    font.family: root.fontFamily
                    font.pixelSize: 10
                    wrapMode: Text.Wrap
                }

                Repeater {
                    model: root.usageWindowList

                    delegate: Text {
                        required property var modelData
                        width: parent.width
                        wrapMode: Text.Wrap
                        text: (root.agentUsage.stale ? "Saved " : "") + (modelData.label || "Usage") + " · "
                            + root.resetCountdown(modelData, root.agentUsage.stale).replace("Resets in ", "")
                        color: QuattroTheme.Theme.text
                        font.family: root.fontFamily
                        font.pixelSize: 10
                    }
                }
            }
        }
    }

    component BarIcon: Rectangle {
        id: iconRoot

        required property string glyph
        required property string accessibleName

        signal clicked()
        signal rightClicked()
        signal middleClicked()
        signal wheelUp()
        signal wheelDown()

        implicitWidth: QuattroTheme.Theme.compactTarget
        implicitHeight: QuattroTheme.Theme.barControlHeight

        radius: QuattroTheme.Theme.cornerRadius
        activeFocusOnTab: true
        border.width: activeFocus ? QuattroTheme.Theme.focusLine : 0
        border.color: QuattroTheme.Theme.textStrong
        Keys.onReturnPressed: iconRoot.clicked()
        Keys.onEnterPressed: iconRoot.clicked()
        Keys.onSpacePressed: iconRoot.clicked()
        Keys.onMenuPressed: iconRoot.rightClicked()

        color:
            iconMouse.pressed ? QuattroTheme.Theme.pressed :
            iconMouse.containsMouse
            ? QuattroTheme.Theme.hover
            : "transparent"

        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
            width: parent.width
            height: parent.height

            text: iconRoot.glyph

            color: QuattroTheme.Theme.text

            font.family: QuattroTheme.Theme.iconFontFamily
            font.pixelSize: QuattroTheme.Theme.iconMedium
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        Accessible.role: Accessible.Button
        Accessible.name: iconRoot.accessibleName
        Accessible.onPressAction: iconRoot.clicked()

        MouseArea {
            id: iconMouse

            anchors.fill: parent

            hoverEnabled: true

            acceptedButtons:
                Qt.LeftButton
                | Qt.RightButton
                | Qt.MiddleButton

            cursorShape: Qt.PointingHandCursor

            onClicked: function(mouse) {
                iconRoot.forceActiveFocus(Qt.MouseFocusReason)
                if (mouse.button === Qt.LeftButton) {
                    iconRoot.clicked()
                } else if (mouse.button === Qt.RightButton) {
                    iconRoot.rightClicked()
                } else if (mouse.button === Qt.MiddleButton) {
                    iconRoot.middleClicked()
                }
            }

            onWheel: function(wheel) {
                if (wheel.angleDelta.y > 0) {
                    iconRoot.wheelUp()
                } else if (wheel.angleDelta.y < 0) {
                    iconRoot.wheelDown()
                }

                wheel.accepted = true
            }
        }

        HoverTooltip {
            target: iconRoot
            hoverActive: iconMouse.containsMouse
            text: iconRoot.accessibleName
        }
    }
}
