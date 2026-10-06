"""Geometry and passive input contract for the shared desktop tooltip."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
SHARED = ROOT / "src/quickshell/components/shared"

@unittest.skipUnless(shutil.which("node"), "Node required for QML JavaScript geometry")
class TooltipPlacementTests(unittest.TestCase):
    def test_bounds_pointer_target_and_monitor_local_coordinates(self):
        script = (SHARED / "TooltipPlacement.js").read_text().replace(".pragma library", "")
        script += r"""
const assert = require('assert');
let checks = 0;
for (const viewport of [{width:1920,height:1080},{width:1280,height:720},{width:430,height:600}]) {
 for (const x of [0,8,100,viewport.width-32]) {
  for (const y of [0,8,100,viewport.height-32]) {
   for (const size of [{width:150,height:35},{width:320,height:160}]) {
    const target = {x,y,width:32,height:32};
    const pointer = {x:x+16,y:y+16};
    const result = place(target,pointer,size,viewport,16);
    if (result) {
     const rect = {...result,...size};
     assert(result.x >= 8 && result.y >= 8);
     assert(result.x+size.width <= viewport.width-8);
     assert(result.y+size.height <= viewport.height-8);
     assert(!overlaps(rect,target));
     assert(!overlaps(rect,{x:pointer.x-16,y:pointer.y-16,width:32,height:32}));
    }
    checks++;
   }
  }
 }
}
assert(place({x:100,y:100,width:32,height:32},{x:116,y:116},{width:150,height:35},{width:1920,height:1080},16));
assert.equal(place({x:0,y:0,width:32,height:32},{x:16,y:16},{width:500,height:500},{width:100,height:100},16),null);
assert.equal(place({x:-100,y:0,width:32,height:32},{x:-84,y:16},{width:80,height:35},{width:1920,height:1080},16),null);
// Screen origins cancel before placement, including a monitor left of primary.
for (const origin of [-1920,0,1920]) {
 const localX = (origin+100)-origin;
 assert.deepEqual(place({x:localX,y:100,width:32,height:32},{x:localX+16,y:116},{width:150,height:35},{width:1920,height:1080},16),{x:132,y:148});
}
// Actual layer surfaces: right/top, centered, bottom/left, full-width bar.
const viewport={width:1920,height:1080};
for (const [anchors,margins,size,expected] of [
 [{right:true,top:true},{right:420,top:360},{width:360,height:150},{x:1140,y:360}],
 [{},{},{width:520,height:620},{x:700,y:230}],
 [{left:true,bottom:true},{left:40,bottom:80},{width:360,height:150},{x:40,y:850}],
 [{left:true,right:true,top:true},{left:0,top:0},{width:1920,height:40},{x:0,y:0}]
]) {
 const panel=panelOrigin(anchors,margins,size,viewport); assert.deepEqual(panel,expected);
 const target={x:panel.x+20,y:panel.y+20,width:140,height:32};
 const pointer={x:target.x+70,y:target.y+16};
 const result=place(target,pointer,{width:320,height:45},viewport,16);
 assert(result); assert(!overlaps({...result,width:320,height:45},target));
 assert(Math.abs(result.y-target.y)<=77);
}
const one = {dismiss() { this.dismissed = true; }};
const two = {dismiss() { this.dismissed = true; }};
claim(one); claim(two); assert(one.dismissed); release(one); assert.equal(owner,two); release(two); assert.equal(owner,null);
console.log(checks);
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "96")

    def test_native_input_and_motion_contract(self):
        source = (SHARED / "HoverTooltip.qml").read_text()
        for required in ["mask: Region { width: 0; height: 0 }", "focusable: false",
                         "WlrLayershell.keyboardFocus: WlrKeyboardFocus.None",
                         "exclusionMode: ExclusionMode.Ignore", "screen: root.sourceScreen"]:
            self.assertIn(required, source)
        self.assertNotIn("Animation", source)
        button = (SHARED / "DesktopButton.qml").read_text()
        self.assertIn("ToolTip.visible: false", button)
        self.assertIn("text: root.ToolTip.text", button)
        self.assertIn("Accessible.description: ToolTip.text", button)

if __name__ == "__main__": unittest.main()
