-- ============================================================
-- QUATTRO SYSTEM PANELS
-- ============================================================

hl.bind(
    "SUPER + CTRL + A",
    hl.dsp.exec_cmd("qs ipc call panel audio")
)

hl.bind(
    "SUPER + CTRL + B",
    hl.dsp.exec_cmd("qs ipc call panel bluetooth")
)

hl.bind(
    "SUPER + CTRL + W",
    hl.dsp.exec_cmd("qs ipc call panel network")
)

hl.bind(
    "SUPER + CTRL + D",
    hl.dsp.exec_cmd("qs ipc call panel display")
)

hl.bind(
    "SUPER + CTRL + P",
    hl.dsp.exec_cmd("qs ipc call panel power")
)

hl.bind(
    "SUPER + CTRL + ALT + D",
    hl.dsp.exec_cmd("qs ipc call panel clock")
)

-- ============================================================
-- QUATTRO AI
-- ============================================================

hl.bind(
    "SUPER + SHIFT + CTRL + A",
    hl.dsp.exec_cmd("qs ipc call agents toggle")
)

hl.bind(
    "SUPER + SHIFT + CTRL + SPACE",
    hl.dsp.exec_cmd("qs ipc call agents newTask")
)

hl.bind(
    "SUPER + CTRL + G",
    hl.dsp.exec_cmd("quattro-agent chatgpt")
)

hl.bind(
    "SUPER + CTRL + X",
    hl.dsp.exec_cmd("quattro-agent dictation toggle")
)

-- ============================================================
-- QUATTRO CAPTURE
-- ============================================================

-- Cycle the live Quickshell and Hyprland dark theme.
hl.bind(
    "SUPER + SHIFT + CTRL + T",
    hl.dsp.exec_cmd("qs ipc call theme next")
)

-- Smart screenshot.
--
-- Press once:
--   freeze screen and start picker.
--
-- Press again while picker is active:
--   cancel screenshot.
hl.bind(
    "SUPER + SHIFT + S",
    hl.dsp.exec_cmd("quattro-screenshot smart")
)

-- ============================================================
-- Quattro-style Hyprland bindings
-- ============================================================

-- Lock the graphical session and move to the recovery TTY. The Hyprland
-- process remains alive, so `resume` returns to the same desktop state.
hl.bind(
    "SUPER + L",
    hl.dsp.exec_cmd("quattro-session lock")
)

-- Applications
hl.bind(
    "SUPER + RETURN",
    hl.dsp.exec_cmd("foot")
)

hl.bind(
    "SUPER + SHIFT + F",
    hl.dsp.exec_cmd("env GDK_BACKEND=x11 XDG_SESSION_TYPE=x11 nautilus --new-window")
)

-- Window controls
hl.bind(
    "SUPER + W",
    hl.dsp.window.close()
)

hl.bind(
    "SUPER + F",
    hl.dsp.window.fullscreen()
)

hl.bind(
    "SUPER + T",
    hl.dsp.window.float({
        action = "toggle"
    })
)

hl.bind(
    "SUPER + P",
    hl.dsp.window.pseudo()
)

-- Dwindle layout toggle
hl.bind(
    "SUPER + J",
    hl.dsp.layout("togglesplit")
)

-- Focus windows with arrows
hl.bind(
    "SUPER + left",
    hl.dsp.focus({
        direction = "left"
    })
)

hl.bind(
    "SUPER + right",
    hl.dsp.focus({
        direction = "right"
    })
)

hl.bind(
    "SUPER + up",
    hl.dsp.focus({
        direction = "up"
    })
)

hl.bind(
    "SUPER + down",
    hl.dsp.focus({
        direction = "down"
    })
)

-- Move windows
hl.bind(
    "SUPER + SHIFT + left",
    hl.dsp.window.move({
        direction = "left"
    })
)

hl.bind(
    "SUPER + SHIFT + right",
    hl.dsp.window.move({
        direction = "right"
    })
)

hl.bind(
    "SUPER + SHIFT + up",
    hl.dsp.window.move({
        direction = "up"
    })
)

hl.bind(
    "SUPER + SHIFT + down",
    hl.dsp.window.move({
        direction = "down"
    })
)

-- Workspaces 1-10
for i = 1, 10 do
    local key = i % 10

    hl.bind(
        "SUPER + " .. key,
        hl.dsp.focus({
            workspace = i
        })
    )

    hl.bind(
        "SUPER + SHIFT + " .. key,
        hl.dsp.window.move({
            workspace = i
        })
    )
end

-- Scroll between workspaces
hl.bind(
    "SUPER + mouse_down",
    hl.dsp.focus({
        workspace = "e+1"
    })
)

hl.bind(
    "SUPER + mouse_up",
    hl.dsp.focus({
        workspace = "e-1"
    })
)

-- Move/resize with mouse
hl.bind(
    "SUPER + mouse:272",
    hl.dsp.window.drag(),
    {
        mouse = true
    }
)

hl.bind(
    "SUPER + mouse:273",
    hl.dsp.window.resize(),
    {
        mouse = true
    }
)

-- Main menu
hl.bind(
    "SUPER + SPACE",
    hl.dsp.exec_cmd(
        "qs ipc call menu toggle"
    )
)

-- Clipboard history
hl.bind(
    "SUPER + V",
    hl.dsp.exec_cmd(
        "qs ipc call clipboard toggle"
    )
)

-- Applications
hl.bind(
    "SUPER + ALT + SPACE",
    hl.dsp.exec_cmd(
        "qs ipc call menu apps"
    )
)

-- Keybindings / Help
hl.bind(
    "SUPER + K",
    hl.dsp.exec_cmd(
        "qs ipc call menu keybindings"
    )
)

-- System
hl.bind(
    "SUPER + ESCAPE",
    hl.dsp.exec_cmd(
        "qs ipc call menu system"
    )
)

-- Refresh Quickshell
hl.bind(
    "SUPER + R",
    hl.dsp.exec_cmd(
        "restart-quickshell"
    )
)
