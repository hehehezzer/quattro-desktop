"""Passive compositor dismissal contracts; live pointer delivery is checked separately."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).parents[1]


class PopupArchitectureTests(unittest.TestCase):
    def test_all_major_hosts_use_shared_boundary(self):
        for name in ["SystemPanels", "RunningApps", "MainMenu", "Clipboard", "Agents"]:
            text = (ROOT / f"src/quickshell/components/{name}.qml").read_text()
            self.assertIn("TemporaryPanel {", text, name)
            self.assertNotIn("HyprlandFocusGrab", text, name)
            self.assertNotIn("WlrKeyboardFocus.Exclusive", text, name)
        host = (ROOT / "src/quickshell/components/shared/TemporaryPanel.qml").read_text()
        self.assertIn("WlrKeyboardFocus.OnDemand", host)
        self.assertLess(host.index("PopupManager.open(root)"), host.index("visible = true"))
        manager = (ROOT / "src/quickshell/services/PopupManager.qml").read_text()
        self.assertIn("root.activePanel.dismissalId === token", manager)
        self.assertNotIn("Timer {", manager)
        self.assertNotIn("HyprlandFocusGrab", manager)

    @unittest.skipUnless(shutil.which("lua"), "Requires Lua for compositor contract")
    def test_passive_inside_outside_multimonitor_and_escape(self):
        script = r'''
local binds, events, commands, layers = {}, {}, {}, {}
local cursor = {x = 0, y = 0}
hl = {
    get_cursor_pos = function() return cursor end,
    get_layers = function() return layers end,
    exec_cmd = function(command) commands[#commands + 1] = command end,
    on = function(event, callback) events[event] = callback end,
    bind = function(key, callback, options)
        local bind = {callback = callback, options = options, enabled = true}
        function bind:set_enabled(value) self.enabled = value end
        binds[key] = bind
        return bind
    end,
}
dofile(arg[1])
assert(not binds.Escape.enabled)
for _, code in ipairs({272, 273, 274}) do
    assert(binds["mouse:" .. code].options.non_consuming)
    assert(binds["mouse:" .. code].options.ignore_mods)
end
local click = binds["mouse:272"].callback
click()
assert(#commands == 0) -- Idle never spawns a helper.
layers = {
    {namespace = "quattro-popup-123-4", mapped = true, x = 3400, y = 38, w = 430, h = 560},
    {namespace = "quattro-bar", mapped = true, x = 1920, y = 0, w = 1920, h = 32},
}
events["layer.opened"]()
assert(binds.Escape.enabled)
cursor = {x = 3500, y = 100}; click(); assert(#commands == 0)
cursor = {x = 2000, y = 16}; click()
assert(commands[1] == "qs ipc call popups dismiss 123-4")
commands = {}
cursor = {x = 500, y = 500}; click()
assert(commands[1] == "qs ipc call popups dismiss 123-4")
binds.Escape.callback()
assert(commands[2] == "qs ipc call popups dismiss 123-4")
layers[1].mapped = false
events["layer.closed"]()
assert(not binds.Escape.enabled)
click(); assert(#commands == 2)
layers[1].mapped = true
layers[1].namespace = "quattro-popup-123;unsafe"
click(); assert(#commands == 2) -- Names are untrusted; only numeric tokens pass.
'''
        result = subprocess.run(["lua", "-", str(ROOT / "src/hypr/popup-dismissal.lua")], input=script, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
