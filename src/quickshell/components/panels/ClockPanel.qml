import QtQuick
import QtQuick.Layouts
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

    signal requestFocus()

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

    ColumnLayout {
        anchors.fill: parent

        spacing: 14

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

            Rectangle {
                implicitWidth: 36
                implicitHeight: 34

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    previousMouse.containsMouse
                    ? QuattroTheme.Theme.border
                    : QuattroTheme.Theme.surface

                Text {
                    anchors.centerIn: parent

                    text: "󰅁"

                    color: QuattroTheme.Theme.text

                    font.family:
                        root.fontFamily

                    font.pixelSize: 14
                }

                MouseArea {
                    id: previousMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        root.previousMonth()
                    }
                }
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

            Rectangle {
                implicitWidth: 36
                implicitHeight: 34

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    nextMouse.containsMouse
                    ? QuattroTheme.Theme.border
                    : QuattroTheme.Theme.surface

                Text {
                    anchors.centerIn: parent

                    text: "󰅂"

                    color: QuattroTheme.Theme.text

                    font.family:
                        root.fontFamily

                    font.pixelSize: 14
                }

                MouseArea {
                    id: nextMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        root.nextMonth()
                    }
                }
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
                model: 6

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

            Rectangle {
                implicitWidth:
                    todayText.implicitWidth + 22

                implicitHeight: 32

                radius: QuattroTheme.Theme.cornerRadius

                color:
                    todayMouse.containsMouse
                    ? QuattroTheme.Theme.border
                    : QuattroTheme.Theme.surface

                Text {
                    id: todayText

                    anchors.centerIn: parent

                    text: "Today"

                    color: QuattroTheme.Theme.text

                    font.family:
                        root.fontFamily

                    font.pixelSize: 11
                }

                MouseArea {
                    id: todayMouse

                    anchors.fill: parent

                    hoverEnabled: true

                    cursorShape:
                        Qt.PointingHandCursor

                    onClicked: {
                        root.goToday()
                    }
                }
            }
        }
    }
}
