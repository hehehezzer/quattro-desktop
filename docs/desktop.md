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

The bar's media control and the dedicated Now Playing panel select Spotify's
MPRIS endpoint only. Cover art is fetched by `quattro_spotify_art.py` from
Spotify's image CDN into the user's private cache and then displayed from a
local file. A failed fetch leaves the Spotify fallback artwork visible. This
avoids the host Qt/OpenSSL crash observed with direct HTTPS QML images.

Lyrics sample Quickshell's Spotify playback position every 50 ms while playing.
Pause/resume, seeks, rate changes and completed track changes update immediately;
there is no separate extrapolation clock or global lyric offset. The clock still
depends on Spotify reporting playback changes; unreported buffering or inaccurate
source lyric timestamps cannot be corrected by a UI sampling interval.

Usage displays distinguish live limits, saved limits, unavailable limits and a
native account requiring sign-in. Refresh failures preserve the last successful
snapshot and show a bounded recovery message, never a raw provider response.
Missing/non-finite percentages are unavailable, not zero usage. Reauthenticate
the selected account with native `codex login` using its configured isolated
`CODEX_HOME`, then run `quattro-agent usage refresh --account ACCOUNT_ID`.
The panel refreshes only the displayed account; the background timer can still
refresh all enabled accounts. Refreshing limits does not sign an account in or
change account selection.
