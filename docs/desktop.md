# Optional desktop integration

The repository contains the original single-process Hyprland/Quickshell
projection as an optional integration. It is not required by the Python
orchestrator and is not installed by `pip`.

The source tree uses generic XDG paths and command names. Install helper
commands into `PATH` or set `QUATTRO_*_COMMAND` overrides before starting
Quickshell. The `ThemeBackground` component ships an original material wallpaper for every
registered theme from `assets/wallpapers`. Set `QUATTRO_WALLPAPER_DIR` to
override that set; missing images retain the native theme-color fallback.

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

The OMP menu entry invokes `quattro-projects-omp --choose-project`, or the
command selected by `QUATTRO_PROJECTS_OMP_COMMAND`. Install the reviewed scoped
Projects launcher before deploying this menu change. That launcher selects a
directory within the existing approved Projects root, starts Quattro's protected
OMP host console in a named Herdr workspace, and attaches a terminal client.
Project selection does not grant access. Quattro retains repository and command
authority; registered commands still require their actual human confirmation.
The menu does not supply the general native-access confirmation flag.

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

## Ghostty terminal integration

The desktop launch shortcut and startup terminal use Ghostty. The terminal keeps
the account's Bash startup files, JetBrainsMono Nerd Font at 12 points, clipboard
shortcuts, and an opaque Quattro palette. `quattro-theme` writes a separate
Ghostty palette so font and shell preferences remain user-owned. Theme changes
reload verified Ghostty windows through the documented Ctrl+Shift+Comma action.
New windows use balanced 24/20-point padding, a steady cursor and no GTK
titlebar. Matching wallpaper appears at 24% over an opaque theme-color base.
The generated include clears old artwork if a theme image is missing.
A builtin-only two-line Bash prompt can be sourced from
`~/.config/ghostty/quattro-prompt.bash` when `TERM_PROGRAM=ghostty`; other
terminal prompts stay unchanged. Existing shells keep their live prompt until
their next normal startup. Foot stays installed and existing Foot sessions remain discoverable.

Quattro workers use a separate Ghostty instance with a valid dotted application
class and an argument-safe `-e` command; working directories and task identities
are preserved. Session focusing recognizes both old Foot and new Ghostty classes.
Permission-pinned scoped Pi packages are not rewritten by terminal migration;
their inherited terminal handles work in Ghostty, but any internal legacy Foot
launchers remain unchanged until an approved package update.

`TERMINAL=ghostty` is the session preference. The XDG terminal priority file names
`com.mitchellh.ghostty.desktop`; consumers of that specification additionally need
the optional `xdg-terminal-exec` reference implementation. Native Files context
menus require the separate optional `ghostty-nautilus` package. These integrations
must be verified individually rather than assuming a single universal Linux
default terminal setting.

## Instrument desktop and monitoring

Instrument, Instrument Paper and Instrument Ember add flat fields, square controls and neutral active states. Red is reserved for attention. The original five skins remain selectable. The Style menu applies the matching shell, compositor borders and terminal palette without restarting the desktop.

Open Monitoring from the main menu, the CPU/memory readout, or Super+Ctrl+M. Escape closes the sheet. Overview, Processes, Thermals and GPU read actual local counters through `quattro-monitor`; the monitor has no process termination or system control actions. Sampling stops while paused or hidden. Missing rates and unsupported GPU counters show unavailable values; temperature uses degrees Celsius, and first CPU/network samples have no invented rate. Process rows expose PID, executable name and usage without command lines or environments.

The navbar uses the bundled **NDOT 47 (inspired by NOTHING)** face by Interactivate under SIL OFL1.1. It is bundled with all archive notices and its origin metadata; it is not Nothing’s official Ndot-Regular. The installed JetBrainsMono Nerd Font supplies readable terminal and shell measurement text; the shell display heading loads Doto, a dot-matrix face distributed by Google Fonts under SIL OFL1.1, from the bundled local font file. This is a matching display fallback, not Ndot. Icons have an independent font role. No application or browser font preferences are changed.

### Theme artwork and process memory

All eight existing themes have generated original artwork. Published PNGs omit
embedded generation text; `assets/wallpapers/origin.json` records public provenance
and file hashes. No third-party stock or
franchise artwork is downloaded. Originals are 1672×941, the builtin tool's
returned resolution, and are aspect-cropped to each output. This set
uses matching independent monitor backgrounds rather than a stretched panorama.
Theme selection persists in the existing theme.json and updates both shell and
Ghostty artwork; source and live assets are included in Desktop deployment.

Processes shows individual resident memory (RSS), explicit MiB/GiB units and a
percentage of physical RAM, with name/PID search, sorting and a scrolling list.
Accessible active processes are sampled within fixed count/time limits. Exited,
zombie and unreadable entries are omitted, and partial scans are labeled. RSS
counts shared pages separately per process and must not be summed as system-used
memory. Sampling pauses while hidden or paused; first CPU rates remain unavailable.


## Notifications, application icons and passive hints

The bar's Notifications button opens saved notices on the focused monitor.
The archive keeps up to 100 plain notices for 24 hours in
`$XDG_STATE_HOME/quattro/notifications/history.json` (normally
`~/.local/state/quattro/notifications/history.json`). Its directory is private
0700 and its atomically replaced file is 0600. Native actions and commands are
never archived or replayed. Transient notices are excluded. Clear/remove affects
history; Dismiss closes a current native notice. If storage fails, a visible
message identifies session-only retention. Previously discarded notices cannot
be recovered.

Timed toasts use the sender's duration (or the five-second default), with a
remaining-time label and progress line. Hover pauses and resumes that remaining
time. Critical and zero-timeout notices stay until dismissed and show no fake
countdown. Replacements update one current record. Default card activation and
other live native actions remain available; expiry and user dismissal emit their
distinct native close reasons. `qs ipc call notifications status`, `open` and
`toggle` expose bounded state and panel opening without notice text.

The Apps button retains the application panel. Individual native tray icons
have moved from the bar into that panel, retaining their menus and primary,
secondary and scroll actions. Installed-app and running-window rows resolve
real desktop-entry icons; missing metadata uses an explicit generic fallback.
Window class lookup may be approximate; names and PIDs remain authoritative.

Hover hints use a pointer-transparent overlay with no keyboard focus, a
16-logical-pixel pointer gap and an 8-pixel monitor inset. They avoid the source
control and hide when no safe placement fits. Keyboard focus reveals the same
hint, Escape dismisses it, and the source retains its accessible labels/actions.
Existing `DesktopButton.ToolTip.text` callers share this behavior. Full usage and
monitoring detail remains available in the source panels. See
[hover-tooltips.md](hover-tooltips.md) for the passive rich-content contract.
