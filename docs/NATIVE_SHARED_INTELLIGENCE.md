# Native shared intelligence audit

## Current direct-native integration (2026-09-30)

The current implementation is installed through the Core deployment and the
native configuration step in `install.sh`. It reuses
`quattro_agent.shared_intelligence`, `RetrievalStore`, the repository index,
the configured memory vaults, the existing RTK allowlist, the existing
`JevClient`, `DecisionSession`, credential resolver, and decision taxonomy.
It does not start `quattro-agent`, OmniRoute, a hidden agent, or a
machine-wide daemon when `codex` or `pi` is launched directly. Pi owns one
bounded helper child for the lifetime of its native session; that child exits
with the session and reuses the session's Jev worker rather than being a
background service.

Native Jev is enabled by default for the five implemented routine strategy
categories when credentials and the provider are available. An explicit native
OFF setting, or a persisted Pi session preference, still wins. This is
separate from managed model-routing preferences. Codex cannot be given an
ordinary-turn lifecycle hook by version 0.158.0, so its default-on integration
is a model-selectable MCP decision boundary; Pi has an automatic eligible-turn
boundary through its supported extension lifecycle.

| Capability | Direct Codex 0.158.0 | Direct Pi 0.87.1 | Quattro-managed | Evidence meaning |
| --- | --- | --- | --- | --- |
| Jev advisory | MCP tool configured; callable at a meaningful model-selected milestone | One cheap-admission lifecycle call per eligible non-trivial turn chooses the relevant context/execution/validation/progress category; tool is also available | Existing managed DecisionSession remains authoritative | `requested`/`provider_response`/`validated`/`accepted` are provider evidence; delivery/application are separately recorded |
| RAG/repository index | Shared MCP search tool | Shared extension tool; Jev `retrieve` advice can apply a bounded pre-turn search | Existing context assembly | Search records route, selected source categories, counts, freshness/partial coverage, estimated tokens, and host delivery |
| Shared/project/history memory | Through shared search route | Through shared search route | Existing memory and retrieval paths | Retrieved material is untrusted source material, never policy |
| RTK | `rtk_status` and bounded `rtk_run` MCP tools | `rtk_status` and bounded `rtk_run` extension tools | Existing bounded helper | Status checks and actual command executions are different event stages |
| Session trace | MCP process session id; delivery is `UNVERIFIED` at the MCP boundary | Pi session id, turn id, tool id, and supported host lifecycle delivery | Existing managed telemetry | No event is attributed to another session |
| Model/account/permissions/UI | Native | Native | Quattro-managed authority preserved | Shared intelligence does not imply Quattro model routing |

Codex 0.158.0 has no supported direct lifecycle callback for intercepting an
ordinary turn. Its Jev path is therefore a real native MCP tool, not a claimed
automatic hook. The MCP process already reuses one Jev worker per Codex MCP
session. Its tool contract and initialize instructions tell the native model
to prefer one call at a meaningful operational milestone, while trivial and
deterministic work remains local.

The Codex MCP input schema intentionally stays flat for compatibility with the
installed host. Category-specific action guidance is in the tool contract, and
the shared native validator still rejects invalid or cross-category actions.
When a caller supplies a valid category action list that accidentally omits the
safe `agent` fallback, the boundary adds only that fallback and records
`requestNormalized=agent_fallback_added`; malformed requests fail closed.

Pi exposes supported `session_start`, `before_agent_start`, `turn_start`,
`tool_result`, and `session_shutdown` events. The extension uses one local
category choice per eligible non-trivial prompt: retrieval/context questions
use `context_strategy`, multi-step or independent work uses
`execution_strategy`, verification prompts use `validation_strategy`, and the
remaining eligible progress prompts use `progress_strategy`. It records the
host boundary and applies only the bounded `context_strategy=retrieve` action
by supplying a bounded retrieval message. A session-owned helper reuses the
Jev worker and catalog across these calls, and is shut down with Pi. The model
may still ignore advice; telemetry labels model reliance as `UNKNOWN`.

Pi's compact footer status distinguishes `Jev ready`, `Jev calling`,
`Jev accepted`, `Jev fallback`, `Jev unavailable`, and `Jev off`. These are
activity indicators, not proof that an accepted action changed execution;
`native trace` remains authoritative for evidence stages.

Managed children receive `QUATTRO_MANAGED_SESSION=1`. The shared MCP keeps
knowledge/RTK tools available but omits the native operational Jev tool, and
managed Pi runs already disable the global extension. This prevents duplicate
native Jev work while preserving the existing managed decision authority.

### Native controls and inspection

These are implemented commands, not proposed names:

```bash
# Passive; reads configuration and local evidence only.
quattro-agent native status

# Exact session required; status lists all sessions and never guesses a latest session.
quattro-agent native trace --session SESSION_ID --limit 100

# Opt-in diagnostic activity. It is marked diagnostic and excluded from ordinary counters.
quattro-agent native probe --directory "$PWD" --query "your bounded retrieval question"

# Global native Jev preference, separate from managed routing.jev.
quattro-agent native set --jev off
quattro-agent native set --jev on
```

`native status` prints the effective native config, direct host paths/versions,
Codex MCP registrations, Pi extension path, credential metadata (`configured`
or `missing` only), per-session counters, ordinary lifetime totals, diagnostic
totals, and current fallback conditions. It does not call Jev, run retrieval,
refresh an index, or execute RTK. The Pi session-local command is
`/quattro-jev status`, `/quattro-jev off`, or `/quattro-jev on`; it persists in
that Pi session and does not change the global setting. Codex has no supported
native slash/status surface, so use the local command above and `codex mcp list`.

The native trace stages mean:

* Availability: `configured`, `loaded`, and `callable` describe setup, not use.
* Retrieval: `retrieval_requested`, `retrieval_completed`, `sources_selected`,
  `result_returned`, and `context_delivery`. A returned server response is
  not model reliance; Codex delivery is `UNVERIFIED`, while Pi host delivery
  is `CONFIRMED` only at its supported result/message boundary.
* Jev: `requested`, `provider_response`, `validated`, `accepted` or
  `rejected`, `advice_delivered`, and `action_applied`. Rejected events carry
  the bounded fallback reason. A policy-accepted answer is not proof that the
  model applied it; unobservable stages remain `UNVERIFIED` or `UNKNOWN`.
  Cached advice is marked `CACHED` and is not a new provider call.
* RTK: `status_checked` is only an installation/health check. `executed` and
  `command_result` require an actual bounded RTK command.

Telemetry is local SQLite under the Quattro private state directory, mode
`0700`/`0600`, with bounded 30-day/5,000-event retention and concurrent-write
handling. It stores hashes and bounded categories/counts, not raw prompts,
code, transcripts, credentials, full tool output, or absolute source paths.
Exact token counts are not available from the retrieval boundary; context
sizes are labeled `estimated`. Diagnostic probes are separate from ordinary
adoption metrics.

### Install and rollback

From the repository checkout, the supported installation path is:

```bash
./install.sh --profile core
quattro-agent deployment status --profile core
codex mcp list
quattro-agent native status
```

The installer preserves existing Codex TOML tables, Pi settings, native
authentication, and explicit native Jev OFF settings. It configures the
effective `$CODEX_HOME` in addition to the default and numbered Quattro homes,
and installs the Pi extension under `$PI_CODING_AGENT_DIR` or
`~/.pi/agent/extensions/`. A deployment records a rollback release; after
checking the exact revision, use the existing guarded command:

```bash
quattro-agent deployment rollback --profile core REVISION --confirm
```

The TypeSafe prerequisite is the existing restrictive
`environment.d/60-quattro-typesafe.conf`; no Codex or Pi authentication file
is read or copied.

## Before-state capability matrix (2026-09-28)

Evidence: clean source `a781b27`, installed Codex 0.157.1, Pi 0.87.1,
RTK 0.45.0, native `~/.codex/config.toml`, native `~/.pi/agent/settings.json`,
both isolated Quattro Codex account configurations, and runtime CLI probes.
`PARTIAL` means the capability exists through a native shell or repository file
but is not registered as the shared tool/context service.

| Capability | Quattro | Native Codex | Native Pi |
| --- | --- | --- | --- |
| Local RAG and relevance routing | AVAILABLE | MISSING | MISSING |
| Bounded context assembly | AVAILABLE | MISSING | MISSING |
| Repository index and code graph | AVAILABLE | MISSING | MISSING |
| Shared and project knowledge vaults | AVAILABLE | PARTIAL | PARTIAL |
| Episodic and explicit knowledge search | AVAILABLE | MISSING | MISSING |
| RTK CLI | PARTIAL | PARTIAL | PARTIAL |
| Shared MCP/tools | PARTIAL | MISSING | MISSING |
| Image MCP | AVAILABLE | MISSING | MISSING |
| Native shell/repository tools | AVAILABLE | AVAILABLE | AVAILABLE |
| Skills and repository instructions | AVAILABLE | AVAILABLE | AVAILABLE |
| Prompt caching | UNKNOWN | UNKNOWN | UNKNOWN |
| Quattro model routing | AVAILABLE | MISSING | MISSING |
| Delegation and supervision | AVAILABLE | MISSING | MISSING |
| Quattro validation authority | AVAILABLE | MISSING | MISSING |

Quattro's retrieval implementation lives in `quattro_agent.retrieval`. The
launcher and harness own when retrieval runs, indexing orchestration, context
assembly, and injection into managed Codex/Pi requests. The retrieval classes
themselves do not require model routing or OmniRoute. The existing CLI exposed
search for humans, but native clients had no discovery entry for it. The native
Codex configuration contained no MCP server; the Quattro account homes only
registered `quattro_images`. Native Pi had no extensions configured. RTK is an
installed CLI, with project/isolated-account instructions, not an MCP server or
library. None of these findings imply that native model calls pass through
Quattro routing.

## Shared boundary

### Tool inventory

| Tool surface | Classification | Native exposure |
| --- | --- | --- |
| `quattro-agent retrieval` / indexed memory | SHAREABLE | Shared knowledge tool |
| Installed `rtk` CLI | GLOBAL, SHAREABLE | Shared RTK tools and native shell |
| `quattro_images.generate_image` | SHAREABLE, optional OmniRoute image transport | Native Codex MCP and native Pi image tool |
| `quattro_decisions.operational_decision` | QUATTRO-SPECIFIC | Never share |
| `quattro_decisions.quattro_test` | QUATTRO-SPECIFIC | Never share |
| Native Codex shell/edit/web and native Pi read/bash/edit/write | CODEX-SPECIFIC / PI-SPECIFIC | Remain native |
| Quattro task, routing, delegation, supervisor and validation commands | QUATTRO-SPECIFIC | Never share |


`quattro_agent.shared_intelligence` owns the client-neutral tool operations and
reuses the existing router, indexer, store, and context assembler. It performs
no work at import/startup. A search lazily refreshes a Git-scoped index under
the existing five-second index budget. Routes that permit institutional memory
also refresh the configured shared and matching project vaults, if available.
Historical routes refresh a bounded recent slice of display-safe project tasks,
events, and checkpoints directly from the durable SQLite database, without
starting Quattro routing. `refresh_history` performs an explicit complete
project backfill when older episodes are needed. Explicit and consolidated
memories remain durable in the retrieval store. The search result labels its
automatic episode refresh `recent_only` rather than claiming complete history.
The search applies route-specific source filters
and returns at most eight results under a maximum 4,000-token context budget.
Trivial prompts classified `no_retrieval` open no database and return zero
retrieval tokens. Search failures are tool errors and do not prevent either
native client from starting. The `quattro_intelligence_mcp` adapter exposes
this surface to Codex; the Pi extension registers native Pi tools that invoke
the same shared CLI. RTK runs through its installed binary with argument-array
execution, bounded time and output. Quattro's authoritative routing,
delegation, scheduler, supervision, and validation remain in the harness.

Quattro's existing retrieval CLI remains available. It and the native adapters
currently call the same underlying retrieval components; future changes should
consolidate duplicated call assembly in `shared_intelligence` once parity is
verified. The native surface does not automatically prepend repository content
to every prompt: the model discovers and calls tools when useful. Pi's
supported `before_agent_start` path may apply one bounded Jev-approved
retrieval message for an eligible turn; Codex remains model-invoked through
MCP.

## Installation

Deploy the Core profile at the merged commit, then run
`python scripts/configure_native_intelligence.py` from that same commit. The
Core inventory installs the intelligence and image MCP executables plus Pi's extension. The configuration
script registers the optional stdio server in native `~/.codex` and existing
numbered Quattro account homes without reading authentication files. It grants
the bounded search and RTK status tools automatic approval; RTK command,
complete history refresh, and image generation retain prompt approval. Existing configurations are preserved, and
an incompatible server entry or malformed TOML produces an actionable error.

Native `codex` and `pi` then load the shared tools through their own MCP and
extension mechanisms. Neither command invokes `quattro-agent` or its native
turn routing. To inspect registration, use `codex mcp list` and Pi's `/tools`
view. To test the local service directly, use `quattro-intelligence rtk_status`
and `quattro-intelligence search_knowledge '{"query":"where is QueryRouter defined"}'`.
