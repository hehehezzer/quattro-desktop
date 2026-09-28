# Quattro Desktop Control Surface

## Source audit

| Source | Observation | Decision | Confidence |
|---|---|---|---|
| `src/quickshell/theme/Theme.qml` | Five named palettes, sharp geometry, but color-only atmosphere and incomplete type/control tokens | Keep theme identities; add semantic geometry, type, icon, state, material, and atmosphere tokens | High |
| `SystemPanels.qml` | One 430 px right-side host and clock host; duplicated chrome | Unify panel frame, header, footer, and responsive margins | High |
| Audio/EQ/Spotify | Real PipeWire DSP and MPRIS behavior; controls lack hierarchy | Preserve integrations; compose around listening state and frequency response | High |
| Clock/Weather | Rich calendar and weather data; weather settings compete with current conditions | Current conditions first; settings and freshness secondary | High |
| Bluetooth/RunningApps | Strong safety behavior; flat lists and equally weighted actions | Connected/running state first; contextual and destructive actions recede | High |
| User brief | Premium, cohesive, dense desktop control center; Spotify-only | Treat every surface as one precision instrument bay, not a card dashboard | Binding |

## Direction

**Mode:** Operate. **World:** architectural drafting desk at dusk—a mineral control plane organized by datum lines, measured spacing, quiet drawing plates, and one restrained material accent. This replaces “widgets in cards” with one continuous working surface. Impeccable direction seed `a1d9f03c` assigned the sixth grounded candidate; the brief's premium, restrained daily-use requirements ruled out decorative racing language while retaining its commitment to decisive state and motion.

The interface is used beside active work under mixed room light; dark mineral surfaces reduce distraction while high-contrast text and theme accent identify current state. Expression comes from exact alignment, frequency scales, transport geometry, datum lines, and theme-specific background plates. Blur, glow, and continuous effects are excluded.

Raises retained from declined challengers: **Cathode discipline:** state changes snap clearly and stale state visibly decays. **Teletext discipline:** keyboard paths and tabular readouts remain exact. **Atlas discipline:** scale and position carry data hierarchy. **Manual discipline:** progressive layers expose advanced controls. **Cloud discipline:** color is confined to meaningful state edges. **Alphabet discipline:** motion transforms state rather than decorating containers.

## Tokens

- Geometry: 3 px control radius, 7 px panel radius, 1 px structural line, 2 px focus ring, 44 px primary target, 32 px compact target, 40 px bar.
- Space: 2, 4, 8, 12, 16, 24, 32 px. Panel inset 16 px; compact inset 12 px.
- Surfaces: `background` host, `surface` grouped bay, `surfaceRaised` interactive control, `hover` hover/pressed, `border` quiet separator, `borderStrong` structural boundary.
- Content: `textStrong` primary identity, `text` values/body, `textMuted` metadata, `textDim` disabled/tertiary.
- State: `accent` selected/current, `success` connected/healthy, `warning` stale/pending/headroom, `danger` failed/destructive. State always includes text or iconography.
- Type: JetBrainsMono Nerd Font remains the installed desktop face. 20 px/700 primary value; 15 px/700 panel title; 13 px/600 item title; 11 px body/control; 10 px metadata; 9 px technical label. Tabular numerals for time, levels, durations, and gains.

## Composition

A panel is a continuous frame with a 44 px command header, one structural divider, a content rail, and a quiet shortcut footer. Internal grouping uses spacing and low-contrast bays rather than nested bordered cards. Compact information modules use 96–180 px height; interactive modules use 220–360 px; expanded controls consume the remaining scrollable area. At widths below 390 px, metadata wraps or hides before controls shrink; transport and sliders retain targets.

## Component matrix

- **Panel frame:** title + optional live status + dismiss hint; no duplicate child title.
- **Button:** quiet, primary, icon, danger variants; hover, pressed, focus, disabled, busy. Icon-only actions require `Accessible.name` and tooltip.
- **Segment control:** presets and modes; selected segment uses accent surface/line plus weight.
- **Slider:** 6 px track, center/zero datum where relevant, 16–20 px handle, keyboard focus, numeric readout.
- **State lamp:** 6 px marker plus explicit label for connected, active, stale, failed, pending.
- **List row:** identity and state in first line, metadata second, primary action at trailing edge; contextual actions revealed by selection/menu.
- **Popover/menu:** surface-raised, one structural border, 32 px rows, keyboard navigation; danger isolated after separator.
- **Loading/empty/error:** preserve layout; concise state and recovery action. Never replace the panel with an alarm card.
- **Tooltip:** delayed, concise, never sole source of required information.

## Widget rules

- **Spotify:** only Spotify MPRIS identities/desktop entries qualify. Artwork is the visual anchor. Track and artist lead; album/context is tertiary. Transport remains one centered row; progress includes elapsed and duration. Closed, reconnecting, metadata-loading, missing-art, and paused states stay calm.
- **EQ:** ten aligned vertical bands form one response field at normal width; compact widths permit a horizontally scrollable calibrated field rather than tiny controls. Presets are integrated as a segmented/scrolling rail. Zero line and gain readouts communicate response; headroom is a warning state, not debug copy.
- **Weather:** condition, temperature, location, high/low first. Freshness and provider are tertiary. Location/refresh live in a quiet action rail.
- **Time:** time, day, date use descending hierarchy without oversized display type.
- **Bluetooth:** power, connected, available, discovery. Pair/trust/remove are progressively disclosed. Connecting and failure use text plus state color.
- **Processes:** application identity and PID scan cleanly. Open is primary. Terminate appears only contextually and requires confirmation; force is escalation only.
- **Audio/network/display/power/calendar/agents/clipboard/notifications/menu:** inherit the same frame, type, target, divider, focus, state, and disclosure grammar.

## Iconography

Use installed Nerd Font symbols consistently at 16 px for row icons and 18–20 px for primary transport. Decorative symbols are hidden from accessibility; icon controls carry accessible names. No emoji.

## Motion

State response 90 ms stepped/snap; color/focus 120–150 ms; panel/menu entry 150 ms maximum. No continuously running decorative motion. Connecting, scanning, and refreshing may pulse text/state at a bounded cadence. Reduced-motion mode removes nonessential transitions.

## Responsive behavior

- 430+ px: full metadata, centered transport, ten-band EQ response field.
- 390–429 px: shorter labels, secondary metadata wraps, compact action labels.
- 320–389 px: action rail reflows; EQ field scrolls horizontally with usable bands; artwork remains at least 72 px; controls stay ≥32 px and primary controls ≥44 px.
- Short panels: body scrolls; header/footer and destructive confirmations remain visible when practical. No nested vertical scrollers except long device/application lists.

## Accessibility

Keyboard focus is a 2 px accent/strong outline. Controls expose roles and names. Sliders preserve arrow-key behavior and values. Contrast targets WCAG AA. Status is never color-only. Focus order follows visual order. Destructive actions name the affected process/device and consequence. Error messages include a recovery path when one exists.

## Do / don’t

Do align baselines, use tabular data, reserve accent for current state, and keep advanced controls progressive. Don’t introduce rounded card grids, glass, glow, gradients, oversized type, raw implementation jargon, permanently prominent destructive actions, or controls below usable size.

## Implementation checklist

- [x] Audit integrations and visible panels
- [x] Define shared tokens and hierarchy
- [x] Refine shared controls and panel frame
- [x] Make Spotify selection product-exclusive
- [x] Recompose Spotify, EQ, weather, Bluetooth, and processes
- [x] Normalize the primary panels to shared tokens and material
- [x] Validate loading/empty/error/disabled/focus states
- [x] Validate QML, Python, tests, runtime, keyboard, responsive collapse rules, and visual output
