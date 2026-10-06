"""Opt-in, bounded private-bus Wayland loading and focus/theme regression.
No windows are displayed; this does not prove compositor event pass-through.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
FIXTURE = r'''import Quickshell
import QtQuick
import QtQuick.Controls
import "components/shared"
import "theme" as T
ShellRoot {
 property int step: 0
 function check(ok, message) { if (!ok) { console.error("TOOLTIP_FAIL",message); Qt.quit(); } }
 FloatingWindow {
  id: window; visible: false; implicitWidth: 800; implicitHeight: 600
  DesktopButton { id: button; text: "Fixture"; ToolTip.text: "Hint" }
  HoverTooltip { id: tip; target: button; text: "Focus hint"; focusActive: true }
 }
 Timer {
  interval: 400; running: true; repeat: true
  onTriggered: {
   check(tip.requested && tip.revealed, "focus opens hint");
   check(tip.surface.mask.width === 0 && tip.surface.mask.height === 0, "empty mask");
   check(!tip.surface.focusable, "no focus theft");
   check(!button.ToolTip.visible && button.ToolTip.text === "Hint", "attached compatibility");
   const box = tip.surface.contentItem.children[0];
   check(box.color.toString() === T.Theme.panelSurface.toString(), "theme surface");
   check(box.children[0].item.color.toString() === T.Theme.textStrong.toString(), "theme ink");
   if (step < T.Theme.availableThemes.length) {
    T.Theme.current = T.Theme.availableThemes[step++].id;
   } else {
    tip.dismiss(); check(!tip.revealed && tip.dismissed, "escape dismissal state");
    tip.focusActive = false; check(!tip.requested && !tip.dismissed, "focus leave resets");
    tip.focusActive = true; check(tip.revealed, "focus reentry");
    console.log("TOOLTIP_RUNTIME_OK",step); Qt.quit();
   }
  }
 }
}'''

@unittest.skipUnless(os.environ.get("QUATTRO_QML_RUNTIME_TESTS") == "1"
                     and shutil.which("qs") and shutil.which("dbus-daemon"),
                     "Opt in with QUATTRO_QML_RUNTIME_TESTS=1 on a Wayland host")
class TooltipQmlRuntimeTests(unittest.TestCase):
    def test_loading_focus_input_mask_and_all_eight_themes(self):
        with tempfile.TemporaryDirectory(prefix="quattro-tooltip-") as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "src/quickshell/components/shared", root / "components/shared")
            shutil.copytree(ROOT / "src/quickshell/theme", root / "theme")
            assets = ROOT / "src/quickshell/assets/fonts"
            if assets.exists(): shutil.copytree(assets, root / "assets/fonts")
            (root / "shell.qml").write_text(FIXTURE)
            config = root / "bus.conf"
            config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' + str(root)
                + '</listen><policy context="default"><allow send_destination="*"/>'
                + '<allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
            bus = subprocess.Popen(["dbus-daemon", "--nofork", "--print-address=1", "--config-file="+str(config)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                address = bus.stdout.readline().strip()
                self.assertTrue(address, "private bus did not start")
                env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address,
                           QT_QPA_PLATFORM="wayland", XDG_CACHE_HOME=str(root / "cache"))
                result = subprocess.run(["qs", "-p", str(root / "shell.qml")],
                                        env=env, capture_output=True, text=True, timeout=12)
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                self.assertIn("TOOLTIP_RUNTIME_OK 8", output)
                self.assertNotIn("TOOLTIP_FAIL", output)
                self.assertNotIn("ERROR:", output)
            finally:
                bus.terminate()
                try: bus.communicate(timeout=3)
                except subprocess.TimeoutExpired: bus.kill(); bus.communicate()

if __name__ == "__main__": unittest.main()
