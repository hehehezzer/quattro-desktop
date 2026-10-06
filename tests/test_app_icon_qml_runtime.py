"""Private-bus, windowless checks: app branding resolution never launches apps."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(os.environ.get("QUATTRO_APP_TEST_ROOT", Path(__file__).resolve().parents[1]))

@unittest.skipUnless(shutil.which("qs") and shutil.which("dbus-run-session"), "Quickshell and private bus required")
class AppIconRuntimeTests(unittest.TestCase):
    def test_real_missing_and_empty_icons(self):
        with tempfile.TemporaryDirectory(prefix="quattro-app-icon-") as folder:
            work = Path(folder)
            (work / "runtime").mkdir(mode=0o700)
            (work / "components").mkdir()
            shutil.copy2(ROOT / "src/quickshell/components/AppIcon.qml", work / "components/AppIcon.qml")
            # Preserve the real selected theme's font and palette roles.
            (work / "theme").symlink_to(ROOT / "src/quickshell/theme", target_is_directory=True)
            fixture = work / "fixture.svg"
            fixture.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" fill="red"/></svg>')
            (work / "shell.qml").write_text("""import QtQuick
import Quickshell
import "components"
Scope {
    AppIcon { id: empty }
    AppIcon { id: missing; iconName: "quattro-definitely-missing-icon-91489" }
    AppIcon { id: actual; iconName: "application-x-executable" }
    Component.onCompleted: actual.iconName = Qt.resolvedUrl("fixture.svg").toString().replace("file://", "")
    Timer { interval: 300; running: true; onTriggered: {
        if (empty.resolvedSource !== "" || missing.resolvedSource !== "") {
            console.log("CHECK_FAILED", "missing metadata fallback"); Qt.exit(1); return
        }
        if (!actual.resolvedSource || !actual.children[0].visible
            || actual.resolvedSource !== Quickshell.iconPath(actual.iconName, true)) {
            console.log("CHECK_FAILED", "real theme resolution"); Qt.exit(1); return
        }
        console.log("APP_ICON_TEST_PASS"); Qt.quit()
    } }
}
""")
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="basic",
                       QT_QUICK_CONTROLS_STYLE="Basic", XDG_RUNTIME_DIR=str(work / "runtime"),
                       XDG_CACHE_HOME=str(work / "cache"), XDG_CONFIG_HOME=str(work / "config"),
                       QS_NO_RELOAD_POPUP="1")
            env.pop("WAYLAND_DISPLAY", None)
            result = subprocess.run(["dbus-run-session", "--", "qs", "-p", str(work / "shell.qml"), "--no-color"],
                                    env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("APP_ICON_TEST_PASS", result.stdout)
            for error in ("CHECK_FAILED", "TypeError", "ReferenceError", "Failed to load configuration"):
                self.assertNotIn(error, result.stdout)

if __name__ == "__main__":
    unittest.main()
