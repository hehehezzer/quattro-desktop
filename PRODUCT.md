# Quattro Desktop

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users

Primary user: a keyboard-first desktop user operating a personal Arch Linux workstation through Hyprland. They need fast, trustworthy control of audio, connectivity, display, processes, weather, calendar, applications, notifications, and local AI sessions without leaving the desktop context.

## Product Purpose

Quattro Desktop is a cohesive local-first desktop operating environment. It projects system state and safe controls through one persistent Quickshell process while preserving direct Linux integrations. Success means important state is legible at a glance, common actions are immediate, advanced or destructive actions remain deliberate, and the shell stays responsive and recoverable.

## Positioning

Unlike a generic dashboard or collection of tray popovers, Quattro is a unified control surface over real host capabilities: PipeWire DSP, Spotify over MPRIS, Open-Meteo, BlueZ, Hyprland windows/processes, system sessions, and local coding agents. Its UI must communicate authoritative host state rather than simulate functionality.

## Operating Context

Used continuously on a desktop, usually in compact 430 px side panels on 1920×1080 monitors, with keyboard shortcuts, pointer input, and focused-monitor placement. Panels coexist with active work and must be dense, quick to dismiss, and usable under variable window and monitor dimensions.

## Capabilities and Constraints

- One persistent Quickshell process; do not replace the shell architecture.
- Preserve existing bar, workspaces, tray, menu, notifications, clipboard, calendar, system panels, and Agents surface.
- Spotify control is product-facing Spotify only; no generic browser or unrelated MPRIS player presentation.
- Preserve real playback controls and metadata/progress where Spotify exposes them.
- Preserve ten-band PipeWire EQ, presets, Custom state, headroom protection, and persistence.
- Preserve Celsius weather, private cache, refresh, and location search/configuration.
- Preserve BlueZ power, discovery, pairing, trust, connect/disconnect, prompts, and failure behavior.
- Preserve exact-PID process controls, protected-process checks, confirmed SIGTERM, and explicit force escalation.
- Preserve date/time updates and focused-monitor panel behavior.
- Avoid continuous decorative animation, heavy blur, expensive effects, unnecessary polling, and startup delay.
- Do not fabricate backend capabilities or expose low-level implementation details in normal UI.

## Brand Commitments

The product name is Quattro Desktop. Existing selectable themes—Lo-Fi Noir, Graphite, Terminal, Cyberpunk 2077, and Avengers: Doomsday—remain supported. JetBrainsMono Nerd Font and the existing icon vocabulary are installed product assets. The shell uses sharp geometry and restrained, theme-aware color rather than generic SaaS cards, glassmorphism, or mobile styling.

## Evidence on Hand

The repository contains working QML components, theme tokens, native host integrations, hermetic tests, and deployment tooling under `src/quickshell/`, `src/quattro_agent/`, `scripts/`, and `tests/`. No approved external visual reference image is available for this redesign; existing runtime behavior and user requirements are authoritative.

## Product Principles

1. Host truth before decoration: visible states must reflect real integrations.
2. One environment, not a widget gallery: shared hierarchy and interaction grammar across every panel.
3. Dense but calm: prioritize scanability and progressive disclosure at actual panel dimensions.
4. Safe by default: destructive and privileged actions stay quiet until intentionally invoked.
5. Fast and resilient: immediate feedback, bounded work, graceful stale/offline/unavailable states.

## Accessibility & Inclusion

Support keyboard navigation, visible focus, semantic controls, labelled icon actions, keyboard-operable sliders, non-color-only state communication, readable contrast, and reduced-motion behavior. Pointer targets should remain comfortably operable in compact desktop panels.
