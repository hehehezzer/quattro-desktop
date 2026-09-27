import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../shared"
import "../../services"
import "../../theme" as QuattroTheme

Item {
    id: root

    property string fontFamily: "JetBrainsMono Nerd Font"

    property date currentDate: new Date()

    property date shownMonth: new Date(
        currentDate.getFullYear(),
        currentDate.getMonth(),
        1
    )

    property bool choosingLocation: false
    property bool compactHeight: calendarScroll.contentHeight > calendarScroll.height + 1
    signal requestFocus()
    function scrollBy(amount) {
        if (!compactHeight || choosingLocation)
            return false
        calendarScroll.contentY = Math.max(0, Math.min(
            calendarScroll.contentHeight - calendarScroll.height,
            calendarScroll.contentY + amount
        ))
        return true
    }
    onChoosingLocationChanged: {
        if (choosingLocation) locationPicker.begin();
        else DesktopWeather.searchQuery = "";
    }

    // ========================================================
    // DATE HELPERS
    // ========================================================

    function mondayOffset(year, month) {
        const day = new Date(
            year,
            month,
            1
        ).getDay()

        return (day + 6) % 7
    }

    function cellDate(weekIndex, dayIndex) {
        const year = shownMonth.getFullYear()
        const month = shownMonth.getMonth()

        const offset =
            mondayOffset(year, month)

        const day =
            1
            - offset
            + weekIndex * 7
            + dayIndex

        return new Date(
            year,
            month,
            day
        )
    }

    function isSameDay(a, b) {
        return (
            a.getFullYear() === b.getFullYear()
            && a.getMonth() === b.getMonth()
            && a.getDate() === b.getDate()
        )
    }

    function isCurrentMonth(date) {
        return (
            date.getFullYear()
                === shownMonth.getFullYear()
            && date.getMonth()
                === shownMonth.getMonth()
        )
    }

    function isoWeekNumber(date) {
        const workDate = new Date(
            Date.UTC(
                date.getFullYear(),
                date.getMonth(),
                date.getDate()
            )
        )

        let day = workDate.getUTCDay()

        if (day === 0)
            day = 7

        workDate.setUTCDate(
            workDate.getUTCDate()
            + 4
            - day
        )

        const yearStart = new Date(
            Date.UTC(
                workDate.getUTCFullYear(),
                0,
                1
            )
        )

        return Math.ceil(
            (
                (
                    workDate - yearStart
                )
                / 86400000
                + 1
            )
            / 7
        )
    }

    function weekDate(weekIndex) {
        return cellDate(
            weekIndex,
            0
        )
    }

    function visibleWeeks() {
        const year = shownMonth.getFullYear()
        const month = shownMonth.getMonth()
        const days = new Date(year, month + 1, 0).getDate()
        return Math.ceil((mondayOffset(year, month) + days) / 7)
    }

    function previousMonth() {
        shownMonth = new Date(
            shownMonth.getFullYear(),
            shownMonth.getMonth() - 1,
            1
        )

        requestFocus()
    }

    function nextMonth() {
        shownMonth = new Date(
            shownMonth.getFullYear(),
            shownMonth.getMonth() + 1,
            1
        )

        requestFocus()
    }

    function goToday() {
        currentDate = new Date()

        shownMonth = new Date(
            currentDate.getFullYear(),
            currentDate.getMonth(),
            1
        )

        requestFocus()
    }

    // Used whenever the popup is closed.
    // This ensures the next open always starts on today's month.
    function resetToToday() {
        choosingLocation = false
        currentDate = new Date()

        shownMonth = new Date(
            currentDate.getFullYear(),
            currentDate.getMonth(),
            1
        )
    }

    // ========================================================
    // KEEP CURRENT DATE UPDATED
    // ========================================================

    Timer {
        running: true
        repeat: true
        interval: 60000

        onTriggered: {
            root.currentDate = new Date()
        }
    }

    // ========================================================
    // WINDOWS-STYLE MONTH SCROLLING
    // ========================================================

    WheelHandler {
        enabled: !root.choosingLocation && !root.compactHeight
        target: null

        acceptedDevices:
            PointerDevice.Mouse
            | PointerDevice.TouchPad

        onWheel: function(event) {
            if (event.angleDelta.y > 0) {
                root.previousMonth()
            } else if (event.angleDelta.y < 0) {
                root.nextMonth()
            }

            event.accepted = true
        }
    }

    // ========================================================
    // CONTENT
    // ========================================================

    WeatherLocationPicker {
        id: locationPicker
        anchors.fill: parent
        visible: root.choosingLocation
        onDone: { root.choosingLocation = false; root.requestFocus(); }
    }

    Flickable {
        id: calendarScroll
        anchors.fill: parent
        visible: !root.choosingLocation
        clip: true
        contentWidth: width
        contentHeight: calendarContent.height
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height

        ScrollBar.vertical: ScrollBar {
            policy: calendarScroll.interactive ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
        }

    ColumnLayout {
        id: calendarContent
        width: calendarScroll.width
        height: Math.max(implicitHeight, 750, calendarScroll.height)

        spacing: 10

        // ====================================================
        // CURRENT DATE
        // ====================================================

        ColumnLayout {
            Layout.fillWidth: true

            spacing: 3

            Text {
                text:
                    Qt.formatDateTime(
                        root.currentDate,
                        "dddd"
                    )

                color: QuattroTheme.Theme.textStrong

                font.family:
                    root.fontFamily

                font.pixelSize: 20
                font.bold: true
            }

            Text {
                text:
                    Qt.formatDateTime(
                        root.currentDate,
                        "MMMM d, yyyy"
                    )

                color: QuattroTheme.Theme.textMuted

                font.family:
                    root.fontFamily

                font.pixelSize: 12
            }
        }

        Rectangle {
            Layout.fillWidth: true

            implicitHeight: 1

            color: QuattroTheme.Theme.border
        }

        // ====================================================
        // MONTH NAVIGATION
        // ====================================================

        RowLayout {
            Layout.fillWidth: true

            spacing: 8

            DesktopButton {
                implicitWidth: 36
                implicitHeight: 34
                text: "󰅁"
                font.pixelSize: 14
                Accessible.name: "Previous month"
                ToolTip.text: Accessible.name
                onClicked: root.previousMonth()
            }

            Text {
                Layout.fillWidth: true

                horizontalAlignment:
                    Text.AlignHCenter

                text:
                    Qt.formatDateTime(
                        root.shownMonth,
                        "MMMM yyyy"
                    )

                color: QuattroTheme.Theme.textStrong

                font.family:
                    root.fontFamily

                font.pixelSize: 15
                font.bold: true
            }

            DesktopButton {
                implicitWidth: 36
                implicitHeight: 34
                text: "󰅂"
                font.pixelSize: 14
                Accessible.name: "Next month"
                ToolTip.text: Accessible.name
                onClicked: root.nextMonth()
            }
        }

        // ====================================================
        // WEEKDAY HEADER
        // ====================================================

        RowLayout {
            Layout.fillWidth: true

            spacing: 5

            Text {
                Layout.preferredWidth: 32

                text: "Wk"

                horizontalAlignment:
                    Text.AlignHCenter

                color: QuattroTheme.Theme.textDim

                font.family:
                    root.fontFamily

                font.pixelSize: 10
            }

            Repeater {
                model: [
                    "Mo",
                    "Tu",
                    "We",
                    "Th",
                    "Fr",
                    "Sa",
                    "Su"
                ]

                delegate: Text {
                    required property string modelData

                    Layout.fillWidth: true

                    text: modelData

                    horizontalAlignment:
                        Text.AlignHCenter

                    color: QuattroTheme.Theme.textMuted

                    font.family:
                        root.fontFamily

                    font.pixelSize: 11
                }
            }
        }

        // ====================================================
        // CALENDAR WEEKS
        // ====================================================

        ColumnLayout {
            Layout.fillWidth: true

            spacing: 6

            Repeater {
                model: root.visibleWeeks()

                delegate: RowLayout {
                    id: weekRow

                    required property int index

                    property int weekIndex:
                        index

                    Layout.fillWidth: true

                    spacing: 5

                    Rectangle {
                        Layout.preferredWidth: 32
                        implicitHeight: 44

                        color: "transparent"

                        Text {
                            anchors.centerIn: parent

                            text:
                                root.isoWeekNumber(
                                    root.weekDate(
                                        weekRow.weekIndex
                                    )
                                )

                            color: QuattroTheme.Theme.textDim

                            font.family:
                                root.fontFamily

                            font.pixelSize: 10
                        }
                    }

                    Repeater {
                        model: 7

                        delegate: Rectangle {
                            id: dayCell

                            required property int index

                            property int dayIndex:
                                index

                            property date dateValue:
                                root.cellDate(
                                    weekRow.weekIndex,
                                    dayIndex
                                )

                            property bool today:
                                root.isSameDay(
                                    dateValue,
                                    root.currentDate
                                )

                            property bool inMonth:
                                root.isCurrentMonth(
                                    dateValue
                                )

                            Layout.fillWidth: true

                            implicitHeight: 44

                            radius: QuattroTheme.Theme.cornerRadius

                            color:
                                today
                                ? QuattroTheme.Theme.textStrong
                                : dayMouse.containsMouse
                                ? QuattroTheme.Theme.border
                                : "transparent"

                            Text {
                                anchors.centerIn: parent

                                text:
                                    dayCell.dateValue.getDate()

                                color:
                                    dayCell.today
                                    ? QuattroTheme.Theme.background
                                    : dayCell.inMonth
                                    ? QuattroTheme.Theme.text
                                    : QuattroTheme.Theme.textDim

                                font.family:
                                    root.fontFamily

                                font.pixelSize: 12

                                font.bold:
                                    dayCell.today
                            }

                            MouseArea {
                                id: dayMouse

                                anchors.fill: parent

                                hoverEnabled: true

                                cursorShape:
                                    Qt.PointingHandCursor

                                onClicked: {
                                    if (
                                        !dayCell.inMonth
                                    ) {
                                        root.shownMonth =
                                            new Date(
                                                dayCell.dateValue
                                                    .getFullYear(),
                                                dayCell.dateValue
                                                    .getMonth(),
                                                1
                                            )
                                    }

                                    root.requestFocus()
                                }
                            }
                        }
                    }
                }
            }
        }

        Item {
            Layout.fillHeight: true
        }

        Rectangle {
            Layout.fillWidth: true

            implicitHeight: 1

            color: QuattroTheme.Theme.border
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 7
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Text {
                        text: DesktopWeather.loading && !DesktopWeather.snapshot.temperature ? "—°" : DesktopWeather.label
                        color: QuattroTheme.Theme.textStrong
                        font.family: root.fontFamily
                        font.pixelSize: 22
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        text: DesktopWeather.condition || (DesktopWeather.error ? "Weather unavailable" : "Loading conditions…")
                        color: DesktopWeather.error ? QuattroTheme.Theme.warning : QuattroTheme.Theme.text
                        font.family: root.fontFamily
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 210
                    Layout.maximumWidth: 210
                    Layout.alignment: Qt.AlignRight | Qt.AlignVCenter
                    spacing: 1
                    Text {
                        Layout.fillWidth: true
                        text: DesktopWeather.placeLabel
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: QuattroTheme.Theme.textStrong
                        font.family: root.fontFamily
                        font.pixelSize: 10
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        text: DesktopWeather.snapshot.updated
                            ? (DesktopWeather.error ? "Cached" : "Updated") + " · " + Qt.formatDateTime(new Date(DesktopWeather.snapshot.updated * 1000), "hh:mm AP")
                            : "Celsius"
                        color: DesktopWeather.error ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
                        font.family: root.fontFamily
                        font.pixelSize: 9
                        horizontalAlignment: Text.AlignRight
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                visible: !!DesktopWeather.error || !!DesktopWeather.snapshot.defaultLocation
                text: DesktopWeather.error || "Default location · choose your city for local conditions"
                wrapMode: Text.Wrap
                color: DesktopWeather.error ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
                font.pixelSize: 9
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                DesktopButton {
                    Layout.fillWidth: true
                    text: "Change location"
                    Accessible.name: "Change weather location: " + DesktopWeather.placeLabel
                    ToolTip.text: DesktopWeather.placeLabel
                    onClicked: root.choosingLocation = true
                }
                DesktopButton {
                    text: DesktopWeather.loading ? "Refreshing…" : "Refresh"
                    enabled: !DesktopWeather.loading
                    Accessible.name: "Refresh weather"
                    onClicked: DesktopWeather.refresh(true)
                }
            }
        }

        // ====================================================
        // FOOTER
        // ====================================================

        RowLayout {
            Layout.fillWidth: true

            Text {
                text:
                    "ISO week "
                    + root.isoWeekNumber(
                        root.currentDate
                    )

                color: QuattroTheme.Theme.textDim

                font.family:
                    root.fontFamily

                font.pixelSize: 10
            }

            Item {
                Layout.fillWidth: true
            }

            DesktopButton {
                implicitHeight: 32
                text: "Today"
                Accessible.name: "Go to today"
                onClicked: root.goToday()
            }
        }
    }
    }
}
