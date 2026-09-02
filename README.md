# Quattro

**Codex orchestration framework with an optional Linux desktop integration.**

Quattro is a Codex-centered agent orchestration framework providing durable
sessions, task routing, delegation, recovery, repository coordination, and
optional memory/RAG. It is not an AI provider and it does not replace Codex,
Pi, or OmniRoute.

The repository also contains an optional Linux desktop integration for
Hyprland and Quickshell. The orchestration engine is usable without that
desktop layer.

This repository retains the `quattro-desktop` name for continuity and existing
links. Quattro Core can be installed and used independently.

## Why Quattro?

- **Predictable decisions:** explanations can stay direct; repository changes
  become durable, observable tasks.
- **Evidence-aware execution:** a deterministic TaskProfile maps work to FAST,
  STANDARD, or REASONING quality requirements and combines OmniRoute runtime
  metadata, curated benchmark evidence, and local validated outcomes without
  duplicating provider dispatch.
- **Recoverable work:** SQLite/WAL task state, checkpoints, leases, cancellation,
  and bounded retries make interrupted work inspectable.
- **Safe boundaries:** provider credentials stay in native account homes;
  display projections contain no prompts, responses, secrets, or environments.
- **Small surface area:** the core uses Python's standard library and can run
  with Codex, Pi, and memory integrations disabled during local testing.

## Architecture

```text
User request
    │
    ▼
Quattro classifier ── DIRECT ──► OmniRoute Responses ──► final response
    │
    └─────────────── DELEGATE ──► durable task
                                      │
                                      ├─ FAST / STANDARD / REASONING
                                      ├─ Codex (primary) or bounded Pi worker
                                      ├─ policy, lease, and process supervision
                                      └─ validation, checkpoint, and projection
```

Quattro owns classification, agent selection, task lifecycle, policy, and
bounded context assembly. OmniRoute owns provider/model selection, health,
quota, cost, capability eligibility, and fallbacks. Codex and Pi execute; they
do not create Quattro tasks or select providers.

## Features in this release

- Deterministic DIRECT versus DELEGATE request classification.
- FAST/STANDARD/REASONING routing and bounded effort escalation.
- Codex and optional Pi adapters with task-scoped policy profiles.
- SQLite/WAL persistence, checkpoints, resume/recovery, cancellation, and
  terminal validation.
- Cooperative global/repository limits and repository-relative write scopes.
- Local hybrid retrieval with secret exclusion and repository/branch scoping.
- Optional Markdown/Obsidian memory with a no-memory default.
- Credential-safe OmniRoute contract and model-catalog validation.
- Evidence-gated GitHub PR review workflow when `gh` and Codex are configured.
- Optional Hyprland/Quickshell desktop projection under `src/quickshell/`.

## Quattro Core

The mature standard-library implementation remains in `quattro_agent` for
backward compatibility and is exposed through the `quattro.core` boundary.
Core owns routing, policy, durable SQLite/WAL state, sessions, recovery,
collaboration, retrieval, Codex/Pi adapters, OmniRoute contracts, PR review,
deployment, and the existing `quattro-agent` CLI.

## Quattro Desktop

Quattro Desktop is an optional Linux-only consumer of Core. Hyprland,
Quickshell/QML, themes, desktop helpers, and desktop systemd units have an
independent deployment inventory. Their absence is a valid Core state.

## Platform support

| Product | Linux | Windows | macOS |
| --- | --- | --- | --- |
| Quattro Core | Supported | Experimental (hosted Core CI) | Untested |
| Quattro Desktop | Supported where dependencies are installed | Unsupported | Unsupported |

Windows packaging, imports, CLI startup, platform paths, executable discovery,
SQLite/WAL state, routing, adapter contracts, portable recovery, file locking,
Core deployment, Desktop absence, and import boundaries pass hosted CI. Managed
process identity/recovery still uses Linux procfs and remains unsupported on
Windows.

## Requirements

- Python 3.11 or newer. Linux is currently the validated Core platform.
- Git for repository-aware scheduling and retrieval (optional for non-Git
  projects).
- Codex CLI 0.15x or a compatible newer release for Codex execution.
- Pi 0.8x or a compatible newer release only when delegated specialists are
  enabled. Pi is optional and writable Pi execution remains fail-closed unless
  the runtime can enforce the requested network policy.
- OmniRoute with the Responses-compatible local endpoint and the four Quattro
  route labels when direct or Codex execution is used. The endpoint and catalog
  are configurable; Quattro does not bundle OmniRoute.
- Optional desktop dependencies: Hyprland Lua integration, Quickshell 0.3.x,
  Foot, `wl-clipboard`, and the commands documented in `docs/desktop.md`.

## Core-only quick start

```bash
git clone https://github.com/OWNER/quattro-desktop.git
cd quattro-desktop
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --no-deps .

# Creates a 0600 credential-free starter config in XDG_CONFIG_HOME.
quattro-agent config init
quattro-agent config validate
quattro-agent --help
```

On Windows, use a native PowerShell or Command Prompt environment:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install --no-deps .
.venv\Scripts\quattro-agent config init
.venv\Scripts\quattro-agent --help
```

`install.sh` is a Linux convenience wrapper; it is not the Windows installer.

## Linux Desktop quick start

From a clean clone on Linux:

```bash
./install.sh --profile desktop
quattro-agent doctor
quattro-agent deployment status --profile desktop
```

The script installs Core first, then deploys only the Desktop profile. Use
`./install.sh --profile core` for the equivalent Linux Core-only convenience
path.

The starter config has memory disabled and does not authenticate Codex. Set up
each native Codex account separately, copy the shape in
`examples/codex-config.toml`, install the shared catalog, then run
`quattro-agent doctor`. See [installation](docs/installation.md) for a clean
machine walkthrough.

## Configuration and paths

Configuration is strict schema version 3 JSON. Use `QUATTRO_CONFIG` to select a
file, otherwise Quattro uses `$XDG_CONFIG_HOME/quattro/ai.json` (or
`~/.config/quattro/ai.json`). Runtime state defaults to
`$XDG_STATE_HOME/quattro/agents`; rebuildable retrieval and task databases are
private there. `QUATTRO_STATE_DIR`, `QUATTRO_DATA_DIR`,
`QUATTRO_CODEX_HOME_ROOT`, `QUATTRO_MODEL_CATALOG`,
`QUATTRO_OMNIROUTE_BASE_URL`, and `QUATTRO_WORKSPACE` provide explicit
portable overrides. See [configuration](docs/configuration.md).

Precedence is: explicit command-line directory or policy option, environment
override, config file, then the documented XDG default. Quattro never infers a
clone destination from the maintainer's machine; project-root defaults are
user-configurable.

## Common commands

```text
quattro-agent doctor [--json]
quattro-agent prompt [codex|pi] "Explain this repository"
quattro-agent submit --agent auto --directory PATH --prompt "Implement ..."
quattro-agent task list|show|events|artifacts|cancel|retry TASK_ID
quattro-agent checkpoint SESSION_ID
quattro-agent resume [SESSION_OR_PROJECT]
quattro-agent recover SESSION_ID
quattro-agent sessions status|clean|stop [SESSION_ID]
quattro-agent collab status|claim --summary TEXT --scope PATH
quattro-agent retrieval search "query" --directory PATH
quattro-agent memory status|init
```

`prompt` stays direct only when the deterministic classifier can answer without
execution. A mutating or repository request creates a durable task. Empty
interactive launches remain launcher controls rather than user work.

## Routing

When the selected Codex model is exactly `auto`, Quattro requests:

| Tier | Route label | Default effort |
| --- | --- | --- |
| FAST | `auto/coding:cheap` | `low` |
| STANDARD | `auto/coding` | `medium` |
| REASONING | `auto/reasoning` | `high` |

A concrete `/model` selection is preserved, while Quattro still controls the
managed task's effective reasoning effort. OmniRoute makes the provider and
model choice inside the eligible pool. Quattro stores sanitized versioned
decision snapshots and supports `quattro-agent routing profile`, `explain`,
`replay`, `refresh-evidence`, `record-outcome`, and `status`. Details are in
[routing](docs/ROUTING.md).

Standard OmniRoute remains supported for tier-based routing. For full
evidence-aware adaptive routing, candidate observability, expected
completion-cost ordering, and capability-aware fallback, use the
[Quattro-compatible OmniRoute fork](https://github.com/hehehezzer/OmniRoute).
Compatibility is detected automatically; no custom-mode switch is required.

## Memory

Memory is optional and disabled by the generated starter configuration. If
enabled, users supply their own long-term and project Markdown vaults. Quattro
may index derived, redacted content locally, but it never ships or requires a
specific Obsidian vault. Prompts, responses, credentials, authentication files,
and arbitrary environments must never be stored. See [memory](docs/memory.md).

## Security

Codex authentication remains native to Codex account homes. Quattro reads only
approved non-secret routing metadata, never copies `auth.json`, never forwards
native credentials to OmniRoute, and does not place secrets in QML, SQLite
projections, logs, or memory. Full access is per-task and confirmation-gated.
The native Codex sandbox is write-scoped rather than a complete host read
sandbox; ordinary workspace tasks are trusted-user operations. Untrusted PR
reviews use a bubblewrap filesystem boundary and fail closed if it is missing.
Report vulnerabilities through the process in [SECURITY.md](SECURITY.md).

## Development

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q src
python scripts/check_python.py
python scripts/check_public_artifacts.py
git diff --check
```

Contributions and release checks are documented in [CONTRIBUTING.md](CONTRIBUTING.md)
and [development](docs/development.md).

## License

Quattro is released under the MIT License. Desktop artwork is intentionally
not bundled; local artwork can be supplied with `QUATTRO_WALLPAPER_DIR`.
