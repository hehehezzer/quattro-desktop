# Optional desktop integration

The repository contains the original single-process Hyprland/Quickshell
projection as an optional integration. It is not required by the Python
orchestrator and is not installed by `pip`.

The source tree uses generic XDG paths and command names. Install helper
commands into `PATH` or set `QUATTRO_*_COMMAND` overrides before starting
Quickshell. The `ThemeBackground` component uses theme colors on a clean
machine; supply local artwork with `QUATTRO_WALLPAPER_DIR` if desired.

After changing desktop files on a configured Linux desktop:

```bash
qmllint src/quickshell --import-path /usr/lib/qt6/qml  # if available
quickshell -p src/quickshell/shell.qml
qs ipc show
pgrep -a quickshell
```

Keep exactly one persistent Quickshell process. Existing bar, workspace, tray,
notification, system-panel, clipboard, and Agents IPC behavior must remain
available. Hyprland-specific reloads require a running compositor and are not
part of the hermetic CI gate.

System panels and the calendar open on the currently focused Hyprland monitor,
including when their controls are clicked on a secondary display.
