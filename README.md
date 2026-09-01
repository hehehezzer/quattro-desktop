# Quattro

Quattro is a local-first orchestration control plane for developer-facing AI
work. It turns a request into a deterministic routing and execution decision,
then supervises Codex or an optional Pi specialist through a durable task
lifecycle. It is not an AI provider and it does not replace Codex, Pi, or
OmniRoute.

The repository also contains an optional Linux desktop integration for
Hyprland and Quickshell. The orchestration engine is usable without that
desktop layer.

## Why Quattro?

- **Predictable decisions:** explanations can stay direct; repository changes
  become durable, observable tasks.
- **Tiered execution:** FAST, STANDARD, and REASONING select bounded effort and
  context budgets without duplicating provider routing.
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

## Requirements

- Linux with Python 3.11 or newer.
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

## Quick start

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
model choice inside the eligible pool. Details are in [routing](docs/routing.md).

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
