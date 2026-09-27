# Desktop system controls

## Scope and architecture

This extends the existing single Quickshell process and theme, not a replacement
shell. UI mode is **Operate**: compact, stable-width media at the left, clock and
weather at the center, existing controls at the right. Existing sharp corners,
semantic theme colors and Nerd Font icon vocabulary remain authoritative. The
requested reference image was unavailable on this host; only its written brief
could be used. No mock metadata or fabricated successful operations are shipped.

Validated host: Arch Linux, Lua Hyprland 0.56.2, Quickshell, PipeWire 1.6.8,
WirePlumber, pipewire-pulse, BlueZ and an unblocked adapter. Python 3 with
`python-gobject`/Gio is already available. The helpers are Linux-only and the
portable Core remains unchanged apart from deployment inventory metadata.

### Media

`services/DesktopMedia.qml` shares Quickshell's native MPRIS service across bars.
D-Bus discovery/property events drive metadata and capability-aware previous,
play/pause and next controls. Selection favors playing players, then recent
activity, then the preferred identifier. Initial playing players seed recency,
so pausing Spotify does not accidentally switch the next Play command to an
inactive browser. A one-second local position timer runs only during playback;
there are no `playerctl` polling subprocesses. Unsupported progress is omitted.
The strip collapses without a player or when insufficient width remains.

`qs ipc call media status|playPause|next|previous` uses the same state/actions as
the buttons. The status is display-safe media metadata, not a diagnostic dump.

### Weather and clock

The clock remains local and live, with seconds. Calendar retains month/week
navigation and adds latitude/longitude settings and Refresh. No location is
inferred from personal data, IP address or unrelated project content.

`quattro_desktop_controls.py weather` uses HTTPS Open-Meteo current weather,
Celsius and WMO weather codes. No API key is required or exposed. Location is
validated and stored in `~/.config/quattro/weather.json`; results are atomically
cached in `~/.cache/quattro/weather.json`. A changed location cannot display the
previous location's cached weather. Requests have a 12-second timeout and bounded
response size. One shared QML singleton refreshes every 30 minutes, retaining
and marking stale last-known results on failure. Missing location is explicit.

### Audio and real EQ

The existing native PipeWire master/microphone mute and volume, input/output
selectors and application-stream mixer are preserved. A ten-band equalizer uses
**PipeWire's built-in `libpipewire-module-filter-chain`**, not EasyEffects,
LADSPA downloads or UI-only sliders:

- 31, 62, 125, 250, 500, 1000, 2000, 4000, 8000 and 16000 Hz;
- stereo cascade of `bq_peaking` filters, Q=1.414, gains −12…+12 dB;
- Flat, Bass Boost, More Bass, Treble Boost, More Treble, Vocal Clarity, Music,
  Gaming, Movie and persisted Custom;
- a `mixer` preamp attenuates by the **sum of positive band gains**, a conservative
  bound on cascade boost, rather than allowing preset boosts to clip;
- Flat sets every gain to zero and the preamp to unity;
- live SPA Props updates through `pw-cli set-param`, coalesced at 160 ms while
  adjusting; no graph restart for ordinary gain changes;
- `quattro_eq` is the virtual sink; `quattro_eq_output` targets the selected
  physical sink. Existing playback streams move into EQ when it is enabled;
- selecting a physical output while EQ is active retargets the filter, including
  Bluetooth sinks supplied by WirePlumber; retargeting briefly restarts the graph;
- Disable moves streams back and disables the service. Selecting the virtual
  sink uses native preferred-default selection;
- private atomic `equalizer.json` and `equalizer.conf`, with a mutation lock;
- `quattro-equalizer.service` is enabled only by an EQ action and restores the
  saved graph after login/service restart. It does not restart the main server.

The active indicator observes native PipeWire node existence. An externally
selected non-EQ default is explicitly described as bypassing EQ. Target loss is
fail-closed (`node.dont-fallback`): audio is not silently sent to another physical
device. Select another available output if the saved target is disconnected.
Physical-output volume is retained; while EQ is the default, master volume
controls the virtual sink. Conservative headroom can noticeably reduce loudness.
This is peak-gain protection, not a guarantee against already-clipped source
material, arbitrary transient overshoot, or external volume amplification.

PipeWire uses SPA-JSON, not ordinary comma-separated JSON arrays. Also, an idle
filter can defer reporting new control values until instantiated by an audio
stream: command success alone is not proof of DSP. The live validation below
measures captured audio through the graph.

### Running applications and safe termination

The new running-applications button opens the compositor's real window list.
Right-click (or keyboard Menu key) exposes Open, Close window and Kill Process.
Open/Close use Lua Hyprland typed dispatchers with a strictly validated hexadecimal
window address. Kill requires confirmation, sends SIGTERM, waits at most two
seconds, then offers a separate explicitly confirmed Force kill if needed.

The helper rechecks exact compositor address/PID association, same-user ownership,
`/proc` start ticks and the executable, and pins the kernel process with `pidfd`
before signalling. No fuzzy names, `pkill`, process-tree guessing or process-group
termination is used. Only the selected PID is terminated; all windows sharing it
may close. Shell/compositor/system manager/audio/session-critical executables and
the helper's ancestors are protected. Window lifecycle events refresh the list;
there is no background process-list poll. Closing an app's GUI process does not
claim to clean up every independent child process it may have spawned.

### Bluetooth

The installed native Quickshell Bluetooth API was audited but lacks Agent1
interaction and operation-error signals needed for truthful pairing UX on this
version. `quattro_bluetooth.py` therefore provides one Gio/BlueZ D-Bus bridge,
owned by the existing Bluetooth panel, with newline JSON on stdin/stdout.

ObjectManager and PropertiesChanged signals drive adapters, devices, RSSI,
power, paired/trusted/connected state and service-loss recovery. Signals are
coalesced for 150 ms. There is no `bluetoothctl` command parsing or periodic scan
loop. Only paths currently enumerated with the expected BlueZ interface can be
actioned. Power/trust property writes, discovery, Pair, Connect, Disconnect and
RemoveDevice use bounded D-Bus calls and propagate actual exceptions. Discovery
ends after 20 seconds or panel close. Removing a paired device requires a second
confirmation. Pairing does not silently trust or claim an audio connection.

A registered KeyboardDisplay Agent1 handles PIN/passkey entry, displayed codes,
confirmation, authorization, rejection and cancellation. User replies require the
current request ID; unanswered prompts expire after 60 seconds. Pair is bounded
at 65 seconds and cancellation is attempted on failure; connect/disconnect at
20 seconds; other calls at five seconds. The bridge follows BlueZ name-owner
changes and re-registers after service return. Parent-death signalling prevents
shell restarts from leaving orphan default agents. On missing dependencies the
UI reports unavailability and retries at five-second intervals.

WirePlumber owns Bluetooth audio profiles and device creation. A genuinely
connected audio device appears in the existing PipeWire output selector; no fake
Bluetooth sink is created by the shell.

## Validation, 2026-09-27

- Repository unit suite: **719 tests, five skipped** (after final Lua regression).
  Desktop backend/BlueZ tests include stale PID, protected process, exact pidfd
  SIGTERM, explicit escalation, weather/cache isolation, graph validation,
  authentication rejection, stale prompt IDs, service loss and bounded scanning.
- Python compile, hygiene, public-artifact policy and diff whitespace: passed.
- Qt 6 QML formatter ran on new/replaced components. Qt 6 qmllint exited zero;
  existing Quickshell plugin-type/unqualified-access warnings remain. The PATH
  `qmllint` was Qt 5 and exited 255 silently; use `/usr/lib/qt6/bin/qmllint`.
- Installed shell loaded; one persistent shell and one owned BlueZ bridge.
- Spotify real metadata, play/pause, next/previous, track changes and progress:
  passed. Brave discovery also observed. Real-player exit/no-player transition
  remains not manually exercised (native model lifecycle is used).
- Open-Meteo retrieval and cache hit: passed with isolated **test coordinates**;
  offline/cached/unconfigured behavior covered by tests. The user's location is
  unset and no real local weather claim is made.
- UI-backed native volume 95% and mute were verified with wpctl and restored.
- All nine preset gain vectors were read back from the active SPA graph; Custom
  survived service restart; Disable restored the physical default; Flat restored.
- `python scripts/validate_desktop_dsp.py`: **passed**, isolated null-sink proof at
  125 Hz: Flat RMS 706.21, +6 dB RMS 1409.06, reset RMS 706.21. Default output was
  preserved. The script tears down its graph, null sink and temporary files.
- Disposable Foot window: exact PID mapping, typed Lua focus, graceful Close and
  SIGTERM exit passed; unrelated sleep process survived. Context menu and keyboard
  opening rendered. Real SIGKILL against a hung GUI remains not exercised.
- Real Bluetooth adapter power off/on and scan start/stop: passed through the
  shipped bridge. Radio returned to its original powered-on state.
- **Hardware blocked:** no newly discoverable pairing-mode device; real pairing,
  connection/disconnection, unpairing and Bluetooth-audio playback are unverified.
  The existing saved speaker bond was not removed merely to produce a test pass.
- System panels/Calendar, bar, tray, launcher IPC and Hyprland config checks passed.
  Shutdown/logout/suspend/lock and exhaustive network/notification regression were
  not destructively exercised. Existing Clipboard `file://undefined` and portal
  registration warnings were observed outside this scope.

## UX review

Impeccable was used in existing-world/Operate mode, with an in-thread finish
review because no subagent tool was available. Native QML is outside the web
HTML/CSS detector. Local captures were inspected at the host's 1920×1080 scale.
Review fixes: unreadable stock fields/menu and blue stock slider styling were
replaced by semantic theme controls; the context menu gained explicit width and
window-relative positioning. Scored fixes are resolved; this is not a claim of
pixel matching the absent reference or validating every monitor size. Captures
contain private desktop content and are intentionally not committed.

## Resource impact and limitations

Media and Bluetooth are event-driven; clock/progress are local one-second timers;
weather is one request per 30 minutes. Process lists refresh only while open on
window events. One idle BlueZ bridge is added; the filter-chain process exists
only when enabled. Sampled shell lifetime CPU was about 0.3%, RSS about 348 MiB;
filter service systemd memory about 3.8 MiB. These are observations under changing
live workload, not a controlled before/after performance benchmark.

Before considering end-to-end validation complete, configure the user's weather
coordinates and test with a physical Bluetooth device in pairing mode, including
headphone output selection. Reference-image fidelity remains blocked until the
actual file is supplied. Do not merge on the basis of unperformed hardware tests.
