# Changelog

## Unreleased — Production reliability and retrieval

- Distinguish registered, intended, pending, indexed, stale, failed and excluded source coverage. Preserve missing-root configurations for diagnosis, explicit scope decisions, structured failures and separate attempt/success timestamps.
- Enforce Git ignore policy and current source eligibility at retrieval; suppress deleted, changed, newly excluded and wrong-root evidence before delivery. Reconcile approved source moves atomically, detect mid-index changes, retain committed snapshots after interruption and bound transient retries.
- Add source inventory/deep freshness, sequential dry-run batch/retry controls, authorized source inspection and read-only doctor diagnostics with actionable storage, vector, lexical, coverage and client observations.
- Expose keyword/semantic/hybrid strategies and actual score contributions; require literal supporting evidence for exact identifier citations. Add diagnostic relevance feedback without changing ranking or memory authority.
- Persist content-free attempt/result/failure receipts with resolved project/source scope, evidence revisions and context bytes; separate Codex stdout submission from host acceptance and model use. Isolate adapter Python imports from untrusted workspaces.
- Add consistent private snapshots, manifest/schema/checksum checks and isolated restore, preserving vectors, source mappings, memory history and receipts. Enforce full-store source/project/private-memory export boundaries.
- Add a 64-case authorized, versioned evaluation corpus, baseline/final machine reports and fixed isolation/freshness/memory-eligibility/availability/held-out recall/no-evidence gates. Retain Nomic, llama.cpp and existing SQLite/memory architecture.
- Make the owner's branch → validation → commit → push → PR delivery requirement explicit in repository instructions, including remote-SHA and clean-worktree verification; merging and deployment remain separately authorized.
- Restore native Windows indexing with no-reparse handle traversal and pinned non-writable ancestors; validate real Windows storage ACLs, including future sidecar inheritance, rather than interpreting POSIX mode bits. Make the stdio regression harness pipe-portable and add native handle/ACL regressions.

## Preserved desktop and historical execution updates

- Restore Quickshell limit usage from native omp Codex reports instead of
  obsolete isolated-account authentication state. Share one bounded collector
  across monitor bars and the Agents meter, preserve private last-known-good
  limits on failure, and omit unknown windows or ambiguous account attribution.
  Include the helper and singleton in the Desktop deployment inventory.
- Add categorical operational preflight, scoped retrieval advice and repeated-failure
  recovery telemetry for native adapters. Keep host permissions and model plans
  authoritative; standalone Codex MCP advice remains explicit.
- Document the separate controlled Qiro worker relay and its limited tool coverage.

## Unreleased — Native intelligence clients

- Add opt-in retrieval-only native omp and Codex adapters: automatic bounded project/shared context, nine on-demand core operations, explicit native mutation approval, and Herdr pane attribution without historical orchestration/model pins.
- Add content-free native session/turn receipts with semantic availability, source coverage, returned results and independently observed delivery. Keep native diagnostic probes separate; never infer model reliance from availability or delivery.
- Add explicit operator source/client configuration and adapter installation, local Nomic embedding user-service configuration, and a native receipt CLI. Preserve existing databases and native account/model/permission state; never bypass Codex hook trust.
- Fix actual native MCP interoperability with standard `clientInfo.title` and request `_meta`; metadata cannot grant namespace/write/verification authority. Keep receipt metadata outside structured context budgets.
- Let established retrieval readers query committed evidence while atomic source replacement holds the writer lock. Keep potentially long indexing outside native prompt hooks; missing/stale coverage is explicit and indexing remains a native-approved operation.

## Unreleased — Intelligence Core 1.0.0

- Rebuild Quattro as an independent local-first knowledge, hybrid retrieval and persistent-memory service; remove agent execution/orchestration, model/provider/account routing, Jev/OmniRoute decisions, worker/session control and native client registration from the active product.
- Preserve and move the working SQLite/FTS5 retrieval/benchmark implementation into `quattro_core`; add explicit source/namespace ownership, atomic incremental indexing, full-tail/import/configuration units, current provenance and deduplication of overlapping evidence.
- Preserve historical records/vectors during version upgrades and explicit imports; quarantine unsafe namespace attribution rather than leaking global/other-project knowledge. Back up original Git history and six live databases before source retirement.
- Add structured episodic/semantic/procedural/shared memory with references, verification, private/project visibility, optimistic revisions, immutable fact identity, supersession/invalidation/deletion and transactional audit history.
- Add bounded independent stdio MCP and operator CLI for search/context, memory, source indexing/status, health/diagnostics and private backups/migrations. Default semantic status is honestly unavailable; optional local Nomic fusion remains operational without paid APIs.
- Enforce configured write/verification permissions, safe source opens, credential/exclusion filtering and complete context budgets. Fix fact-key/dedup/escaped-credential bypasses and cross-project migration mapping with regressions.
- Package only the intelligence core; install into an isolated virtual environment without global commands, native agent configuration, desktop/service deployment or future ecosystem installation.
- Document architecture, database/tool contracts, migration/retirement, operating procedures, independent client integration and executed baseline/acceptance evidence. Existing installed legacy desktop/execution consumers remain untouched.
- Correct commit provenance for untracked/ignored/dirty source content and refresh unchanged-file Git metadata without reembedding. Add real Git-transition regression and installed CLI proof.

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
