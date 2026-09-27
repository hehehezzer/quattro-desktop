import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../shared"
import "../../services"
import "../../theme" as QuattroTheme

ColumnLayout {
    id: root
    signal done
    spacing: 12
    function begin() {
        search.text = "";
        DesktopWeather.searchQuery = "";
        Qt.callLater(() => search.forceActiveFocus());
    }
    function choose(place) {
        DesktopWeather.selectPlace(place);
        root.done();
    }
    RowLayout {
        Layout.fillWidth: true
        Text {
            text: "Weather location"
            color: QuattroTheme.Theme.textStrong
            font.pixelSize: 17
            Layout.fillWidth: true
        }
        DesktopButton {
            text: "Back"
            onClicked: root.done()
        }
    }
    Text {
        Layout.fillWidth: true
        text: "Search cities and places worldwide. Your desktop clock stays on system time."
        wrapMode: Text.Wrap
        color: QuattroTheme.Theme.textMuted
        font.pixelSize: 12
    }
    DesktopField {
        id: search
        Layout.fillWidth: true
        implicitHeight: 38
        placeholderText: "Search city or place…"
        Accessible.name: "Search weather location"
        maximumLength: 100
        onTextChanged: {
            results.currentIndex = 0;
            DesktopWeather.searchQuery = text;
        }
        Keys.onDownPressed: results.currentIndex = Math.min(results.count - 1, results.currentIndex + 1)
        Keys.onUpPressed: results.currentIndex = Math.max(0, results.currentIndex - 1)
        onAccepted: {
            if (results.count && !DesktopWeather.searching)
                root.choose(DesktopWeather.searchResults[Math.max(0, results.currentIndex)]);
        }
    }
    Text {
        Layout.fillWidth: true
        visible: !results.count || DesktopWeather.searching
        text: DesktopWeather.searchError || (DesktopWeather.searching ? "Searching…" : search.text.trim().length < 2 ? "Try Manila, Imus or any city worldwide. Enter at least 2 characters." : "No places found. Try a nearby city or another spelling.")
        wrapMode: Text.Wrap
        color: DesktopWeather.searchError ? QuattroTheme.Theme.warning : QuattroTheme.Theme.textMuted
        font.pixelSize: 12
    }
    DesktopButton {
        visible: DesktopWeather.searchError.length > 0
        text: "Retry search"
        onClicked: {
            DesktopWeather.searchPending = true;
            DesktopWeather.searchError = "";
            DesktopWeather.startSearch();
        }
    }
    ListView {
        id: results
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 4
        model: DesktopWeather.searchResults
        currentIndex: 0
        ScrollBar.vertical: ScrollBar {}
        delegate: DesktopButton {
            required property var modelData
            required property int index
            width: ListView.view.width
            implicitHeight: resultText.implicitHeight + 22
            text: modelData.label
            Accessible.name: modelData.label
            highlighted: results.currentIndex === index
            contentItem: Column {
                id: resultText
                spacing: 4
                Text {
                    width: parent.width
                    text: modelData.name
                    textFormat: Text.PlainText
                    color: QuattroTheme.Theme.textStrong
                    font.pixelSize: 14
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: [modelData.admin2, modelData.admin1, modelData.country].filter((v, i, a) => v && a.indexOf(v) === i).join(", ")
                    textFormat: Text.PlainText
                    color: QuattroTheme.Theme.textMuted
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }
            background: Rectangle {
                color: parent.hovered || parent.highlighted ? QuattroTheme.Theme.hover : QuattroTheme.Theme.surface
                border.width: 1
                border.color: parent.activeFocus ? QuattroTheme.Theme.textStrong : QuattroTheme.Theme.border
            }
            onClicked: root.choose(modelData)
        }
    }
    Text {
        text: "Location search by Open-Meteo · GeoNames"
        color: QuattroTheme.Theme.textMuted
        font.pixelSize: 10
    }
}
