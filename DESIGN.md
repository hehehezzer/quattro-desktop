---
name: "Quattro Desktop — Instrument Sheet"
description: "A native keyboard-first Linux desktop rendered as a working instrument sheet."
colors:
  background: "#101112"
  surface: "#1b1c1c"
  surface-raised: "#252625"
  hover: "#2c2d2b"
  pressed: "#353634"
  border: "#494a47"
  border-strong: "#73746e"
  text-strong: "#ecece7"
  text: "#d8d8d2"
  text-muted: "#c0c0b8"
  text-dim: "#b3b3ad"
  attention-ink: "#ed8577"
  paper-background: "#f0efe8"
  paper-surface: "#e8e7df"
  paper-surface-raised: "#e1e0d8"
  paper-hover: "#dcdbd3"
  paper-pressed: "#d7d6cf"
  paper-border: "#b3b2a9"
  paper-border-strong: "#77786e"
  paper-text-strong: "#20211f"
  paper-text: "#343530"
  paper-text-muted: "#494a43"
  paper-text-dim: "#56574f"
  paper-attention-ink: "#96332a"
  ember-background: "#191514"
  ember-surface: "#241f1d"
  ember-surface-raised: "#2d2724"
  ember-hover: "#342d2a"
  ember-pressed: "#3b3230"
  ember-border: "#51443e"
  ember-border-strong: "#837167"
  ember-text-strong: "#ebe5db"
  ember-text: "#d8cfc3"
  ember-text-muted: "#c4b8ab"
  ember-text-dim: "#bbb0a6"
  ember-attention-ink: "#ee9b8b"
typography:
  display:
    fontFamily: "Doto"
    fontSize: "82px"
    fontWeight: 600
    fontVariation: "\"ROND\" 100, \"wght\" 600"
  headline:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "23px"
    fontWeight: 500
  monitoring-body:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "15px"
  micro:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "10px"
  body:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "11px"
  label:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "12px"
  icon-small:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "14px"
  icon-medium:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "16px"
  icon-large:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "20px"
  terminal:
    fontFamily: "JetBrainsMono Nerd Font"
    fontSize: "12pt"
rounded:
  instrument: "0px"
  legacy-control: "3px"
  legacy-panel: "7px"
spacing:
  2xs: "2px"
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  2xl: "32px"
  sheet-gutter: "26px"
components:
  button:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.instrument}"
    height: "32px"
  button-hover:
    backgroundColor: "{colors.hover}"
  button-pressed:
    backgroundColor: "{colors.pressed}"
  button-prominent:
    backgroundColor: "{colors.text-strong}"
    textColor: "{colors.background}"
    typography: "{typography.body}"
    rounded: "{rounded.instrument}"
    height: "32px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.text-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.instrument}"
    height: "32px"
  button-destructive:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.attention-ink}"
    typography: "{typography.body}"
    rounded: "{rounded.instrument}"
    height: "32px"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.instrument}"
    height: "32px"
    padding: "0px 8px"
  combo:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-strong}"
    typography: "{typography.body}"
    rounded: "{rounded.instrument}"
    height: "32px"
  panel-button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text-strong}"
    typography: "{typography.label}"
    rounded: "{rounded.instrument}"
    height: "44px"
  monitoring-tab:
    backgroundColor: "transparent"
    textColor: "{colors.text-muted}"
    typography: "{typography.monitoring-body}"
    height: "48px"
    width: "134px"
  monitoring-panel:
    backgroundColor: "{colors.background}"
    rounded: "{rounded.instrument}"
    width: "1360px"
  ledger-row:
    textColor: "{colors.text-strong}"
    typography: "{typography.monitoring-body}"
    height: "34px"
---

# Design System: Quattro Desktop

## Overview

**Creative North Star: "Instrument Sheet"**

Quattro Desktop is a native Hyprland/Quickshell desktop whose Instrument skins treat the screen as a working instrument sheet: a quiet ground, sharp fields, measured text, and ruled live information. The Instrument Sheet visual language supplies the composition; real host state supplies the content. This is a Linux desktop system. PRODUCT.md’s existing “adaptive” platform field does not imply an iOS or Android implementation.

The shared controls are compact and keyboard-operable. Monitoring opens as a broad sheet on the focused screen, with a dotted display title and readable monospaced measurements. Instrument, Instrument Paper, and Instrument Ember change material color while keeping the same hierarchy. The existing Lo-Fi Noir, Graphite, Terminal, Cyberpunk 2077, and Avengers: Doomsday skins retain their own palettes and background motifs; their authoritative values remain in src/quickshell/theme/Theme.qml.

**Key Characteristics:**

- Flat, square Instrument fields with thin neutral rules.
- Dotted display lettering separated from monospaced operational text and icon glyphs.
- Neutral active and healthy states; explicit text for unavailable, stale, and paused states.
- Live measurements and honest missing-data gaps, with bounded histories.

## Colors

The palette is deliberately near-neutral: matte charcoal in Instrument, warm paper and ink in Paper, and warm charcoal with bone text in Ember. The frontmatter records the reused Instrument-family primitives; unprefixed keys are Instrument, `paper-` selects Paper, and `ember-` selects Ember. Values are extracted from `instrumentPalettes` in Theme.qml. Theme.qml is the palette authority.

### Primary

- **Attention ink:** attention-ink and its Paper/Ember counterparts are the readable attention role. QML warning and danger resolve to these colors in Instrument skins.
- **Neutral emphasis:** text-strong also supplies the Instrument accent. It fills prominent controls and utilization gauges, underlines selected tabs, and marks focus. Strong emphasis is not automatically an alarm.

### Neutral

- **Matte / paper / ember ground:** background supplies opaque barSurface and panelSurface, keeping operational fields readable over the theme artwork.
- **Working field:** surface supplies text fields, full-width panel actions, and alternate process rows.
- **Raised field:** surface-raised supplies compact controls and combo popups. Its name describes a tonal step, not a shadow.
- **Hover / pressed fields:** hover and pressed communicate pointer interaction without introducing a new accent.
- **Rules:** border divides measurements and rows; border-strong marks stronger control edges and panel boundaries. Instrument panelBorder resolves to borderStrong.
- **Text hierarchy:** text-strong anchors titles and readings; text carries ordinary information; text-muted and text-dim keep secondary information legible. Instrument success resolves to textMuted.

**The Neutral State Rule.** In Instrument skins, ordinary active workspaces, selected tabs, focus, and healthy state text use the neutral palette. Attention ink identifies warning, failure, and destructive controls.

The monitoring Transmit sparkline currently uses danger as a series distinction. This isolated use is recorded as an implementation exception, not a reusable rule assigning red to ordinary network activity. Theme properties attention, attentionSurface, and onAttention are declared but not used by the sampled shipping components, so they are not promoted into this extracted token set.

## Typography

**Display Font:** bundled Doto, loaded through QML FontLoader from `src/quickshell/assets/fonts/Doto.ttf`.
**Body / Terminal Font:** JetBrainsMono Nerd Font.
**Icon Font:** separately bound iconFontFamily, currently JetBrainsMono Nerd Font.

The dotted display face gives Monitoring its identity while monospaced text keeps measurements, labels, and process columns aligned. The installed Nerd Font glyph vocabulary is a compatibility asset; it is not permission to invent new pictogram-based controls.

### Hierarchy

- **Display:** the monitoring title uses the display token and Doto’s round-dot and weight axes. At the narrow threshold it becomes (46 px). Monitoring text and geometry are multiplied by the panel’s unit factor.
- **Headline:** monitoring section headings use medium weight and the headline token.
- **Monitoring body:** readings, ledger labels, actions, and tabs use monitoring-body. Individual metric emphasis may be larger where the source establishes it.
- **Body / label / micro:** shared controls use body, full-width panel actions use label, and compact annotations use micro. This is a functional hierarchy rather than a mathematical scale.
- **Icons:** small, medium, and large roles remain independent of ordinary text. Existing glyphs use an optical correction of (-0.5 px) vertically.
- **Terminal:** Ghostty uses the terminal token in points. Do not confuse its (12 pt) setting with QML pixel-size roles.

**The Separate Faces Rule.** Use the bundled Doto face for the monitoring display title, JetBrainsMono Nerd Font for operational text, and the separate iconFontFamily role for existing installed glyph assets.

FontLoader falls back to the installed operational family if Doto cannot load. This is a resilience path, not the intended display style. Doto’s origin and SIL OFL 1.1 license are recorded in `src/quickshell/assets/fonts/origin.json` and `OFL.txt`. The bundled NDOT 47 face (inspired by NOTHING), by Interactivate, is licensed under SIL OFL1.1. It is loaded from `assets/fonts/ndot47` for navbar text only; Nothing’s official Ndot-Regular remains a distinct face. The terminal font is unchanged.

## Layout

The persistent bar spans each screen (40 px high), with controls (30 px high). Shared compact controls are (32 px), and full-width panel actions are (44 px). Ordinary side-panel geometry uses panelWidth (430 px) and panelInset (16 px). The main menu instead uses its implemented (520 px) width and fixed page-dependent heights. Use the extracted spacing rhythm for shared controls; Monitoring has a separate recurring sheet gutter.

Monitoring opens top-right on the focused monitor. Its width is the lesser of (1360 px) and screen width minus (48 px). Its top margin is clamped against the bar and screen height, its right margin is capped at (36 px), and its height is capped at (956 px) while respecting available screen height. It is not a full-screen web dashboard.

The sheet uses a wide CPU region beside memory, followed by storage/network and full-width thermals/process ledgers. This is the implemented monitoring composition, not a mandatory layout for every future panel. At panel width (900 px) or below, overview grids collapse to one column and the title loses its adjacent header-status block. The footer retains state and update time. The unit factor is `max(0.8, min(1, panel.width / 1360))`. The body scrolls vertically without a horizontal scrollbar; header, tabs, and footer retain explicit scaled heights.

## Elevation & Depth

Instrument uses no panel shadows. Depth comes from neutral field steps, borders, selected-state rules, and focus strokes. Legacy themes retain their existing gradient grounds, static planes, Canvas motifs, and optional user-local wallpaper handling. Those materials remain scoped to those themes; Instrument keeps those native fallback motifs disabled; generated material wallpapers cover all eight themes. Artwork sits behind opaque panels and text fields.

**The Flat Sheet Rule.** Instrument panels are flat fields. The desktop uses original material wallpapers. Show structure with tonal changes and rules rather than adding shadows, blur, or decorative background motifs.

Immediate control color changes use motionFast (90 ms). Shared palette changes use transitionDuration (150 ms). Existing legacy atmospheric color and wallpaper-opacity changes use motionAtmosphere (260 ms), with QML OutCubic easing on wallpaper opacity. These are short state reactions, not continuous decorative animation.

## Shapes

Instrument controls and panels use the square radius token. Structural rules and resting Instrument control borders are (1 px); keyboard focus strokes are (2 px). Gauges and dividers share the sharp ruled language. Legacy controls and panels retain their separate radius tokens. Keep established target sizes when using square geometry.

## Components

### Buttons

DesktopButton uses surface-raised at rest, hover/pressed fields for pointer states, and text-strong labels. Prominent buttons invert the ground/text relationship; quiet buttons are transparent at rest. Destructive labels and borders use danger, resolving to attention-ink in Instrument. Disabled controls use opacity (0.46). Keyboard focus is a strong neutral stroke, and accessible names follow the labels.

PanelButton is a full-width surface action with label typography and shared horizontal margins. SmallButton is a compact labelled action with a neutral inverted accent variant. Monitoring Action buttons are transparent with strong borders and scaled sizing. Pause becomes Resume when sampling stops; Close exposes Escape in its visible label.

### Inputs / Fields

DesktopField uses surface, strong text, muted placeholders, and a bordered square background. Selected text stays strong over hover color. DesktopCombo uses the same geometry and palette; opened/hovered combos use the hover field, and popups use surface-raised with a strong border. Option rows are (32 px), popup padding uses xs spacing, and popup height is capped at (200 px) before scrolling. Both controls preserve disabled opacity and visible focus.

### Navigation

The Instrument bar presents the literal QUATTRO menu label and zero-padded workspace identifiers. Active workspaces use a raised neutral field and rule, while keyboard focus uses a strong neutral border. The menu retains the existing theme list, swatches, active label, and keyboard access.

Monitoring’s Overview, Processes, Thermals, and GPU tabs use a neutral selected underline (2 px), muted inactive text, hover field, and visible focus border. At narrow width their preferred width changes from (134 px) to (112 px), before multiplication by the unit factor.

### Panels / Containers

Monitoring is one flat ruled sheet rather than a collection of cards. Other panels reuse the selected theme’s surfaces and shared controls. TemporaryPanel participates in PopupManager focus and dismissal, opens on demand, and exposes Escape dismissal. Do not add a second persistent shell process to display new surfaces.

### Metric Plots / Gauges / Ledgers

MetricPlot is semantic QML Canvas: thin grid rules, a measured trace (1.5 px), visible single-sample marks (2 px), and a bounded (120 s) history window. Invalid or missing samples break the line; intervals above (6000 ms) do not connect. CPU has a fixed percentage maximum; Receive and Transmit have independent, explicitly labelled dynamic scales. A missing measurement does not fabricate a gauge fill.

ValueRow and the process ledger align values right and labels left. Alternating process rows use surface for scanability. Monitoring’s process ledger is read-only, searchable by name/PID and sortable by RAM, name or PID; do not add destructive row controls. Existing process-management actions elsewhere remain governed by their own implementation.

The service exposes Loading, Live, Paused, Stale, and Unavailable. It collects only while visible and unpaused, retains up to (60) history samples, retries a lost worker, and labels state and latest update. These states belong to the component’s visual contract. Reference artwork guides composition; the shipping sheet is QML/Canvas.

## Do's and Don'ts

### Do:

- **Do** apply the complete selected theme palette to shared controls and panels.
- **Do** keep Instrument control and panel corners square, with neutral focus and selected-state cues.
- **Do** preserve visible keyboard focus, accessible names, Escape dismissal, and labelled state text.
- **Do** show unavailable measurements as an em dash or an explicit message, and retain valid samples when monitoring pauses.
- **Do** use source tokens as color authority; night-light settings can alter perceived screenshot colors.
- **Do** preserve the five original themes and their own backgrounds alongside the three Instrument skins.

### Don’t:

- **Don’t** use attention ink as the default active, focus, or healthy-state accent.
- **Don’t** replace Instrument’s flat operational panels with gradients, glass, blur, decorative texture, or rounded dashboard cards; desktop artwork follows the selected theme.
- **Don’t** fill chart gaps, invent sensor or process data, or imply a fixed network bandwidth.
- **Don’t** replace native semantic controls or Canvas plots with reference artwork.
- **Don’t** identify NDOT47 as Nothing’s official Ndot-Regular; the monitoring display face remains Doto.
- **Don’t** infer a mobile platform or new widgets from the existing PRODUCT.md platform field or from the reference composition.


### Desktop artwork and individual process memory

The terminal retains JetBrainsMono Nerd Font at 12 points. Ghostty uses 24/20-point
balanced padding and the current material wallpaper at 24% opacity over an opaque
palette background. The optional Ghostty-only Bash startup prompt uses builtins;
existing shells keep their current live prompt. No application font changes.

All eight theme wallpapers are original builtin image generation outputs at
1672×941, rendered independently on each screen with aspect crop.
Theme selection and artwork persist through the existing controller. `assets/wallpapers/origin.json` records public source information and file hashes.
Published PNGs omit embedded generation text. A user-local wallpaper directory can override
the set; missing artwork retains the native theme-color fallback. Panels stay
opaque, so wallpaper highlights do not impair operational text contrast.

The Processes tab lists accessible active processes within fixed count/time
limits, with a virtualized scrolling table, name/PID search and useful sorting.
Memory is resident set size (RSS), shown in MiB/GiB and as physical-RAM percentage.
Shared pages may appear in multiple rows; the list never substitutes an RSS sum
for system-used memory. Partial scans and omitted unreadable/exited entries are
explicit. Overview preserves its short top-process ledger.


### Notifications, application panel and passive hints

Notifications extend the existing flat Instrument controls and selected palette.
The focused-monitor panel uses ordinary body typography, a scrollable saved
notice ledger, explicit clear/remove/dismiss actions and truthful empty/storage
states. A thin remaining-time line and seconds label represent actual timed
expiry; critical/persistent notices display Until dismissed. Hover pauses the
remaining lifetime. The local archive is private, bounded and excludes transient
notices and executable action objects. Earlier discarded history is unavailable.

Navbar Apps and Notifications controls preserve NDOT47 text and the independent
icon role. Real application/tray icons belong inside the application panel;
missing desktop metadata has a generic fallback. Tray actions remain native.

Passive hints use theme body/surface/border tokens, no animation and an empty
native input region. Placement stays within the source monitor, offset from the
pointer and outside the complete target. Focus reveal and Escape dismissal keep
the source keyboard accessible. A hint that cannot fit safely stays hidden;
full details remain in the source panel.
