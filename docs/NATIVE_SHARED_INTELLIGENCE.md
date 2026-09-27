# Native shared intelligence audit

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
to prompts: the model discovers and calls tools when useful.

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
