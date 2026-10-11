# Changelog

## Unreleased — Intelligence Core 1.0.0

- Rebuild Quattro as an independent local-first knowledge, hybrid retrieval and persistent-memory service; remove agent execution/orchestration, model/provider/account routing, Jev/OmniRoute decisions, worker/session control and native client registration from the active product.
- Preserve and move the working SQLite/FTS5 retrieval/benchmark implementation into `quattro_core`; add explicit source/namespace ownership, atomic incremental indexing, full-tail/import/configuration units, current provenance and deduplication of overlapping evidence.
- Preserve historical records/vectors during version upgrades and explicit imports; quarantine unsafe namespace attribution rather than leaking global/other-project knowledge. Back up original Git history and six live databases before source retirement.
- Add structured episodic/semantic/procedural/shared memory with references, verification, private/project visibility, optimistic revisions, immutable fact identity, supersession/invalidation/deletion and transactional audit history.
- Add bounded independent stdio MCP and operator CLI for search/context, memory, source indexing/status, health/diagnostics and private backups/migrations. Default semantic status is honestly unavailable; optional local Nomic fusion remains operational without paid APIs.
- Enforce configured write/verification permissions, safe source opens, credential/exclusion filtering and complete context budgets. Fix fact-key/dedup/escaped-credential bypasses and cross-project migration mapping with regressions.
- Package only the intelligence core; install into an isolated virtual environment without global commands, native agent configuration, desktop/service deployment or future ecosystem installation.
- Document architecture, database/tool contracts, migration/retirement, operating procedures, independent client integration and executed baseline/acceptance evidence. Existing installed legacy desktop/execution consumers remain untouched.

## Historical execution architecture (pre-rebuild)

- Leave externally granted native tasks with their owning execution boundary;
  generic reconciliation and terminal workers cannot claim or launch them.
- Keep native repository probes to fixed identity queries and preserve unknown
  dirty state; prevent status hooks and clean filters from running on the host.
- Disable filesystem-monitor hooks in ordinary host Git metadata probes.

- Add a blind, resumable Intelligence evidence-review workflow with
  deficit-aware sampling, append-only consensus/adjudication, and explicit
  provenance and quality states.
- Add immutable chronological holdout sealing, opened-evidence tracking,
  connected-family contamination protection, and reproducible v11 dataset
  snapshot lineage.
- Extend Intelligence readiness with actionable global, class, category,
  complexity, human-gold, chronology, and sealed-holdout deficits while keeping
  deterministic routing authoritative.
- Add account-pinned GPT-6 Astra routes to the Codex picker with only low/high
  thinking choices, preserving either saved choice during managed dispatch.
- Keep Astra request and displayed reasoning effort aligned, including direct
  Responses calls and bounded escalation.
- Document OmniRoute custom model registration and the Codex client version
  required by the validated Astra integration.

## 0.2.0 — 2026-09-02 — Core/Desktop architecture separation

### Added

- Explicit `quattro.core`, adapter, platform, deployment, and CLI boundaries
  backed by the existing mature `quattro_agent` implementation.
- Independent Core and optional Linux Desktop deployment manifests with a
  one-time archival migration from the legacy combined manifest.
- Core and Desktop Linux installer profiles and native Python package
  installation guidance for Windows.
- Windows Core CI for packaging, imports, CLI startup, path handling, locking,
  routing, durability, recovery-compatible tests, and dependency boundaries.

### Changed

- Desktop executables and assets no longer participate in Core parity,
  deployment, rollback inventory, or doctor health.
- Executable discovery, user directories, advisory locks, and filesystem
  durability helpers now use centralized platform abstractions.
- `quattro-agent doctor` reports Desktop as optional instead of degrading Core
  when Hyprland, Quickshell, QML, or wallpapers are absent.

### Compatibility

- The repository, `quattro-agent` command, `quattro_agent` imports, MIT
  license, existing state paths, SQLite schemas, sessions, account homes,
  OmniRoute configuration, and release snapshots remain unchanged.
- Windows Core packaging and the bounded portable Core surface pass hosted CI.
  Linux-only managed process identity and recovery remain unsupported and are
  not misrepresented.

## 0.1.0 — Initial public OSS release

This is the first public OSS snapshot. The `v0.1.0` tag points to the exact
commit whose package metadata reports version `0.1.0`.

### Added

- Portable `pyproject.toml` packaging and the `quattro-agent` console script.
- Credential-free `config init`, `--version`, XDG path discovery, and explicit
  environment overrides.
- Public architecture, installation, configuration, routing, session, memory,
  security, troubleshooting, and development documentation.
- Tracked-artifact policy, MIT license, contributor governance, issue templates,
  pull-request checklist, and GitHub Actions validation.

### Changed

- Memory defaults to disabled and generated vault templates contain no
  maintainer-specific paths or project content.
- Codex/Pi child processes receive a documented environment allowlist instead of
  inheriting arbitrary parent variables.
- Desktop source uses generic command/XDG paths and theme-color fallbacks;
  unlicensed local wallpaper assets and personal review artifacts are not
  distributed.
- OmniRoute endpoint and catalog locations are configurable while endpoint
  validation remains loopback-only and credential-free.

### Removed

- Broken repository symlinks to a maintainer's home directory.
- Private review reports, local retrieval benchmark outputs, personal memory
  skill templates, and unverified artwork from the public tree.

## v1.0.0 — Historical private release

### Added

- Cheapest-capable OmniRoute request routing with capability, health, quota,
  cooldown, and context eligibility gates.
- Deterministic Quattro DIRECT/DELEGATE classifier and durable delegation
  metadata.
- DIRECT Responses path with bounded retrieval, selected-model preservation,
  no task creation, and no execution-agent launch.
- Durable Codex/Pi task lifecycle, cooperative session metadata, validation,
  failure summaries, recovery checkpoints, and bounded Pi specialist flow.
- Runtime catalog parity checks and display-safe release diagnostics.
- Bounded live-state context projections and release-hardening tests.

### Changed

- Codex account routing validates approved loopback OmniRoute configuration and
  the shared model catalog before execution.
- Live task/session retrieval uses compact state projections to preserve
  structured fields within context budgets.

### Security

- Preserved account isolation, explicit full-access confirmation, secret-safe
  display state, and Quattro-only orchestration authority.
- Documented the requirements for any future writable Pi profile without
  enabling one.
