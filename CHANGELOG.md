# Changelog

All notable Quattro orchestration changes are documented here.

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
