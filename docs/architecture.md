# Architecture

Quattro is a local control plane, not a model gateway. The Python package
contains the classifier, routing policy, durable store, scheduler, repository
coordinator, retrieval index, process supervisor, adapters, and projections.

```text
request
  ├─ classifier ── DIRECT ──► local OmniRoute Responses transport
  └─ classifier ── DELEGATE ─► SQLite task
                                  ├─ tier and policy
                                  ├─ scheduler and repository lease
                                  ├─ Codex or bounded Pi adapter
                                  ├─ process supervision
                                  └─ validation/checkpoint/projection
```

## Ownership boundaries

- **Quattro:** request classification, agent choice, task lifecycle, policy,
  context budgets, leases, recovery, and display-safe state.
- **OmniRoute:** provider/model selection, capability eligibility, health,
  quota, cost, cooldowns, and provider fallbacks.
- **Codex/Pi:** execution runtimes. Their native credential stores remain
  outside Quattro state.
- **Memory/RAG:** optional user-owned context and disposable derived indexes;
  repository and Markdown files remain authoritative.
- **Desktop integration:** optional Hyprland/Quickshell projection. It is not a
  second orchestration daemon.

The CLI is the stable integration boundary. `quattro_harness.py` remains a
compatibility facade while the `quattro_agent` package contains reusable
primitives.
