import QtQuick
import QtQuick.Controls
import QtTest
import "../../src/quickshell/components/shared" as Shared
import "../../src/quickshell/theme" as QuattroTheme

Item {
    id: surface
    width: 430
    height: 600

    Shared.DesktopCombo {
        id: combo
        x: 64
        y: 200
        width: 260
        model: ["Flat", "Bass Boost", "More Bass", "Treble Boost", "More Treble",
                "Vocal Clarity", "Music", "Gaming", "Movie", "Custom"]
        currentIndex: 9
    }

    TestCase {
        name: "DesktopComboPopup"
        when: windowShown

        function test_preset_list_uses_panel_surface_and_scrolls() {
            combo.popup.open()
            wait(100)
            verify(combo.popup.visible)
            compare(combo.popup.width, combo.width)
            verify(combo.popup.height <= 200)
            compare(combo.popup.background.color, QuattroTheme.Theme.surfaceRaised)
            compare(combo.popup.contentItem.count, combo.model.length)
            verify(combo.popup.contentItem.contentHeight > combo.popup.contentItem.height)
            combo.popup.close()
        }
    }
}
