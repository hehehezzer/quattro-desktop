import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import Quickshell.Hyprland
import Quickshell.Wayland
import Quickshell.Services.SystemTray
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as QuattroTheme
import "../services"

PanelWindow {
    id: root
    WlrLayershell.namespace: "quattro-bar"

    anchors {
        top: true
        left: true
        right: true
    }

    implicitHeight: QuattroTheme.Theme.barHeight
    color: "transparent"

    property string fontFamily: QuattroTheme.Theme.fontFamily

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
    property real systemStatsPopupX: 0
    property bool systemStatsPopupPositioned: false
    property double countdownNow: Date.now()

    function gibibytes(bytes) {
        return (Number(bytes || 0) / 1073741824).toFixed(1)
    }

    function positionSystemStatsPopup() {
        if (root.hoveredSystemStat === "") {
            root.systemStatsPopupPositioned = false
            return
        }

        const target = root.hoveredSystemStat === "cpu"
            ? cpuStatsItem
            : ramStatsItem
        const point = target.mapToItem(
            root.contentItem,
            target.width / 2,
            0
        )
        const desiredX = point.x - systemStatsPopup.implicitWidth / 2
        root.systemStatsPopupX = Math.max(
            8,
            Math.min(
                root.width - systemStatsPopup.implicitWidth - 8,
                desiredX
            )
        )
        root.systemStatsPopupPositioned = true
    }

    onHoveredSystemStatChanged: root.positionSystemStatsPopup()

    function resetCountdown(window) {
        if (!window || window.resetAt === undefined || window.resetAt === null)
            return "Reset time unavailable"

        let resetMs = Number(window.resetAt)
        if (!isFinite(resetMs))
            return "Reset time unavailable"
        if (resetMs < 1000000000000)
            resetMs *= 1000

        const totalMinutes = Math.max(0, Math.ceil((resetMs - root.countdownNow) / 60000))
        if (totalMinutes === 0)
            return "Resets now"

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
            window && window.usedPercent !== undefined && window.resetAt !== undefined
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
            verticalCenter: parent.verticalCenter
            leftMargin: QuattroTheme.Theme.spaceSm
        }

        spacing: QuattroTheme.Theme.space2xs

        Rectangle {
            width: QuattroTheme.Theme.compactTarget
            height: QuattroTheme.Theme.barControlHeight
            radius: QuattroTheme.Theme.cornerRadius

            color:
                menuMouse.containsMouse
                ? QuattroTheme.Theme.hover
                : "transparent"

            Accessible.role: Accessible.Button
            Accessible.name: "Open Quattro menu"

            Text {
                anchors.centerIn: parent

                text: "󰣇"

                color: QuattroTheme.Theme.textStrong

                font.family: root.fontFamily
                font.pixelSize: QuattroTheme.Theme.iconMedium
                anchors.verticalCenterOffset: QuattroTheme.Theme.iconOpticalOffsetY
            }

            MouseArea {
                id: menuMouse

                anchors.fill: parent

                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor

                onClicked: {
                    PopupManager.request("menu")
                }
            }
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
                    modelData.active
                    ? 26
                    : 20

                implicitHeight: QuattroTheme.Theme.barControlHeight

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    modelData.active
                    ? QuattroTheme.Theme.accent
                    : workspaceMouse.containsMouse
                    ? QuattroTheme.Theme.hover
                    : "transparent"

                Accessible.role: Accessible.Button
                Accessible.name: "Workspace " + modelData.id

                Text {
                    anchors.centerIn: parent

                    text: workspaceButton.modelData.id

                    color:
                        workspaceButton.modelData.active
                        ? QuattroTheme.Theme.background
                        : QuattroTheme.Theme.text

                    font.family: root.fontFamily
                    font.pixelSize: QuattroTheme.Theme.typeBody
                }

                MouseArea {
                    id: workspaceMouse

                    anchors.fill: parent

                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor

                    onClicked: {
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
        x: leftGroup.x + leftGroup.width + QuattroTheme.Theme.spaceSm
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, Math.min(player ? 390 : 136,
            clockArea.x - x - QuattroTheme.Theme.spaceSm))
        visible: width >= (player ? 220 : 126)
        onOpenRequested: PopupManager.request("spotify")
    }

    Item {
        id: clockArea
        x: Math.max(leftGroup.x + leftGroup.width + QuattroTheme.Theme.spaceSm,
            Math.min((root.width - width) / 2,
                rightGroup.x - width - QuattroTheme.Theme.spaceMd))
        anchors.verticalCenter: parent.verticalCenter

        width: clockButton.implicitWidth
        height: QuattroTheme.Theme.barHeight

        Rectangle {
            id: clockButton

            anchors.centerIn: parent

            implicitWidth: clockWeatherRow.implicitWidth + 16
            implicitHeight: QuattroTheme.Theme.barControlHeight

            radius: QuattroTheme.Theme.cornerRadius

            color:
                clockMouse.containsMouse
                ? QuattroTheme.Theme.hover
                : "transparent"

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
                    font.pixelSize: QuattroTheme.Theme.typeLabel
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
                    font.pixelSize: QuattroTheme.Theme.typeMeta
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
            verticalCenter: parent.verticalCenter
            rightMargin: QuattroTheme.Theme.spaceSm
        }

        spacing: QuattroTheme.Theme.space2xs

        RunningApps { barWindow: root }

        Rectangle {
            id: systemStatsButton
            visible: root.width >= 1000
            implicitWidth: systemStatsRow.implicitWidth + 14
            implicitHeight: QuattroTheme.Theme.barControlHeight
            radius: QuattroTheme.Theme.cornerRadius
            color: root.hoveredSystemStat !== "" ? QuattroTheme.Theme.hover : "transparent"

            Row {
                id: systemStatsRow
                anchors.centerIn: parent
                spacing: QuattroTheme.Theme.spaceSm

                Item {
                    id: cpuStatsItem
                    implicitWidth: cpuStatsLabel.implicitWidth
                    implicitHeight: QuattroTheme.Theme.barControlHeight

                    Text {
                        id: cpuStatsLabel
                        anchors.centerIn: parent
                        text: root.systemStats && root.systemStats.available
                            ? "󰍛 " + Math.round(root.systemStats.cpuPercent) + "%"
                            : "󰍛 --"
                        color: QuattroTheme.Theme.text
                        font.family: root.fontFamily
                        font.pixelSize: QuattroTheme.Theme.typeBody
                    }

                    MouseArea {
                        id: cpuStatsMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.ArrowCursor
                    }
                }

                Item {
                    id: ramStatsItem
                    implicitWidth: ramStatsLabel.implicitWidth
                    implicitHeight: QuattroTheme.Theme.barControlHeight

                    Text {
                        id: ramStatsLabel
                        anchors.centerIn: parent
                        text: root.systemStats && root.systemStats.available
                            ? "󰘚 " + Math.round(root.systemStats.ramPercent) + "%"
                            : "󰘚 --"
                        color: QuattroTheme.Theme.text
                        font.family: root.fontFamily
                        font.pixelSize: QuattroTheme.Theme.typeBody
                    }

                    MouseArea {
                        id: ramStatsMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.ArrowCursor
                    }
                }
            }
        }

        Rectangle {
            id: agentUsageButton
            visible: root.width >= 1200
            implicitWidth: agentLabel.implicitWidth + 14
            implicitHeight: QuattroTheme.Theme.barControlHeight
            radius: QuattroTheme.Theme.cornerRadius
            color: agentMouse.containsMouse ? QuattroTheme.Theme.hover : "transparent"

            Text {
                id: agentLabel
                anchors.centerIn: parent
                text: {
                    const usage = root.agentUsage || {}
                    const windows = [usage.primary, usage.secondary].filter(window =>
                        window && window.usedPercent !== undefined
                    )
                    if (windows.length === 0)
                        return "󰚩 --"
                    return "󰚩 " + windows.map(window =>
                        (window.label || "Usage") + " " + Math.round(100 - window.usedPercent) + "%"
                    ).join("  ")
                }
                color: root.agentUsage && root.agentUsage.stale
                    ? QuattroTheme.Theme.warning
                    : root.agentUsage && root.agentUsage.loggedIn
                    ? QuattroTheme.Theme.success
                    : QuattroTheme.Theme.text
                font.family: root.fontFamily
                font.pixelSize: QuattroTheme.Theme.typeBody
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
                onClicked: PopupManager.request("agents")
            }
        }

        Repeater {
            model: SystemTray.items

            delegate: Rectangle {
                id: trayEntry

                required property var modelData

                implicitWidth: QuattroTheme.Theme.compactTarget
                implicitHeight: QuattroTheme.Theme.barControlHeight

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    trayMouse.containsMouse
                    ? QuattroTheme.Theme.hover
                    : "transparent"

                Image {
                    anchors.centerIn: parent

                    width: QuattroTheme.Theme.iconMedium
                    height: QuattroTheme.Theme.iconMedium

                    source: trayEntry.modelData.icon

                    sourceSize.width: QuattroTheme.Theme.iconMedium
                    sourceSize.height: QuattroTheme.Theme.iconMedium

                    fillMode: Image.PreserveAspectFit

                    smooth: true
                }

                MouseArea {
                    id: trayMouse

                    anchors.fill: parent

                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor

                    acceptedButtons:
                        Qt.LeftButton
                        | Qt.MiddleButton
                        | Qt.RightButton

                    function openMenu() {
                        const item = trayEntry.modelData

                        if (!item.hasMenu)
                            return

                        const pos = trayEntry.mapToItem(
                            root.contentItem,
                            0,
                            trayEntry.height
                        )

                        PopupManager.closeActive()
                        item.display(
                            root,
                            pos.x,
                            pos.y
                        )
                    }

                    onClicked: mouse => {
                        const item = trayEntry.modelData

                        if (mouse.button === Qt.LeftButton) {
                            if (
                                item.onlyMenu
                                && item.hasMenu
                            ) {
                                openMenu()
                            } else {
                                item.activate()
                            }

                            return
                        }

                        if (mouse.button === Qt.MiddleButton) {
                            item.secondaryActivate()
                            return
                        }

                        if (mouse.button === Qt.RightButton) {
                            openMenu()
                        }
                    }

                    onWheel: wheel => {
                        trayEntry.modelData.scroll(
                            wheel.angleDelta.y,
                            false
                        )
                    }
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

    PopupWindow {
        id: systemStatsPopup

        visible: !PopupManager.activePanel && root.hoveredSystemStat !== "" && root.systemStatsPopupPositioned
        color: "transparent"
        anchor.window: root
        anchor.rect.x: Math.round(root.systemStatsPopupX)
        anchor.rect.y: QuattroTheme.Theme.barHeight + 4
        implicitWidth: 190
        implicitHeight: 52

        Rectangle {
            anchors.fill: parent
            radius: QuattroTheme.Theme.panelRadius
            color: QuattroTheme.Theme.panelSurface
            border.color: QuattroTheme.Theme.panelBorder
            border.width: 1

            Column {
                anchors.centerIn: parent
                spacing: 3

                Text {
                    text: root.hoveredSystemStat === "cpu"
                        ? "CPU usage · " + Math.round((root.systemStats && root.systemStats.cpuPercent) || 0) + "%"
                        : "RAM usage · " + Math.round((root.systemStats && root.systemStats.ramPercent) || 0) + "%"
                    color: QuattroTheme.Theme.textStrong
                    font.family: root.fontFamily
                    font.pixelSize: 10
                }

                Text {
                    text: root.hoveredSystemStat === "cpu"
                        ? "Aggregate processor load"
                        : root.gibibytes(root.systemStats && root.systemStats.ramUsedBytes)
                            + " / " + root.gibibytes(root.systemStats && root.systemStats.ramTotalBytes) + " GiB in use"
                    color: QuattroTheme.Theme.text
                    font.family: root.fontFamily
                    font.pixelSize: 10
                }
            }
        }
    }

    PopupWindow {
        id: agentUsagePopup

        visible: !PopupManager.activePanel && agentMouse.containsMouse
        color: "transparent"
        anchor.window: root
        anchor.rect.x: Math.round(agentUsageButton.mapToItem(root.contentItem, 0, 0).x + agentUsageButton.width - implicitWidth)
        anchor.rect.y: QuattroTheme.Theme.barHeight + 4
        implicitWidth: 122
        implicitHeight: Math.max(24, root.usageWindowList.length * 15 + 8)

        Rectangle {
            anchors.fill: parent
            radius: QuattroTheme.Theme.panelRadius
            color: QuattroTheme.Theme.panelSurface
            border.color: QuattroTheme.Theme.panelBorder
            border.width: 1

            Column {
                id: agentUsagePopupContent
                anchors.centerIn: parent
                spacing: 1

                Repeater {
                    model: root.usageWindowList

                    delegate: Text {
                        required property var modelData
                        text: (modelData.label || "Usage") + " · " + root.resetCountdown(modelData).replace("Resets in ", "")
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

        color:
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

            font.family: root.fontFamily
            font.pixelSize: QuattroTheme.Theme.iconMedium
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }

        Accessible.role: Accessible.Button
        Accessible.name: iconRoot.accessibleName

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

        ToolTip.visible: iconMouse.containsMouse
        ToolTip.delay: 700
        ToolTip.text: iconRoot.accessibleName
    }
}
