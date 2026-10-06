/*
THESIS: A keyboard-first desktop as a working instrument sheet.
OWN-WORLD: Approved Instrument Sheet; seed 866ec5eb, position 7/7.
STORY: Read machine health, inspect real processes, return to work.
FIRST VIEWPORT: A flat black sheet anchored right: large MONITORING,
wide CPU field, memory column, filesystem/network and sensor ledger.
FORM: Seed 866ec5eb; neutral rules, square controls, measured type; red means attention.
The sheet pauses and resumes live histories without invented measurements.
unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
*/
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
    Monitoring {}
    Notifications {}
    Clipboard {}
}
