# Hermes–Discord integration progress

Overall: **PARTIAL / BLOCKED**, not deployed as a functioning Discord agent.

## Baseline (2026-09-30)

| Surface | Observed baseline |
| --- | --- |
| OS/service | Arch Linux; systemd user manager |
| Quattro checkout | `fc06170`; original branch `feat/native-jev-latency` |
| Unrelated work | `src/hypr/popup-dismissal.lua` (Escape non-consuming fix), preserved in place; no cleanup/stash/worktree |
| Task branch | `feat/hermes-discord-integration` |
| Hermes | Previously absent, empty `~/.hermes`; stable v0.21.5 / v2026.9.24 installed in dedicated user directory using upstream venv stage and locked messaging/MCP dependencies |
| Native Codex | 0.158.0; `codex login status`: ChatGPT; configured default rejected by live subscription endpoint; explicit gpt-5.5 read-only review succeeded; defaults unchanged |
| Native Pi | 0.99.1; openai-codex default; explicit gpt-5.5 live shared retrieval succeeded |
| Intelligence | Existing `quattro_agent.shared_intelligence`, native Codex MCP, global Pi extension; no new RAG database |
| Second brain | Actual shared and project vault roots were resolved from the existing Quattro config; existing bounded search indexes Shared and matching project notes, not the entire vault. Private machine paths stay in the local discovery report. |
| Jev | Native enabled/credential configured; managed preferences untouched |
| Discord | No integration bot/profile credentials or numeric owner/destination IDs discovered in the empty Hermes home |

Private evidence is in `~/.local/state/quattro-hermes/`; do not publish transcripts or source excerpts. Upstream release metadata, exact archive, installer logs, native status and deployment rollback manifest are retained there. Account authentication files were not read/copied. Existing services and live sessions were not restarted.

## Phase checklist

- [x] Discover repository policies, existing native intelligence, memory roots, binaries, authentication status, services, dirty paths.
- [x] Check current upstream provider/Discord/MCP docs and stable source.
- [x] Install isolated stable Hermes Python environment and locked messaging/MCP dependencies; CLI starts.
- [x] Create dedicated `quattro-discord` profile without cloning credentials/defaults.
- [x] Live native Codex read-only review and Pi knowledge retrieval (NOT Discord delegation acceptance).
- [ ] Hermes own OAuth and real model/tool response.
- [x] Deploy read-only connector/Core inventory and dedicated profile; upstream Plugin Doctor and real hook/local fixture contract pass (synthetic Discord identity, NOT a live Discord round-trip).
- [ ] Audit managed billing/worker inheritance before activating Discord execution.
- [ ] Real owner Discord chat, natural retrieval, prompt-only generation.
- [ ] Real Codex AND Pi reversible writable jobs through controller, lifecycle/follow-ups/approvals.
- [x] Repository regression checks (938 tests, five existing skips), private service admission exit 78, native model/retrieval baselines.
- [ ] Real gateway restart/disconnection, worker failure/concurrency, and final deployment parity/live availability gates.
- [x] Document implemented/proposal-only syntax, secure owner unblock, acceptance matrix, operations and rollback in `HERMES_DISCORD.md`; focused local task commit.
- [ ] PR/publication: starting checkout contains nine unrelated native-Jev commits beyond main; do not silently include/publish them in this task's PR.
- [ ] All 17 live/automated acceptance gates; complete only after deployed live verification.

## Known constraints and gaps

- Upstream Discord channel-only allowlisting can authorize users; configure numeric owner allowlist AND destination filtering, plus deterministic plugin intake checks.
- Plugin `pre_gateway_dispatch` runs before gateway auth/session inference, but upstream catches hook exceptions and continues: connector must catch its own failures and return skip; service startup must verify mandatory plugin load and policy. Native allowlisting is defense in depth, not a substitute.
- Hermes automatic external credential adoption defaults on upstream: explicitly disable it and use fresh profile-owned OAuth. Do not import Codex refresh credentials.
- Existing managed Pi specialist is read-only and disables global extensions. This is not proof of the requested writable/native-Pi extension path; do not claim that gate passed.
- Quattro reconciliation can dispatch queued tasks: do not call global reconcile merely to inspect Discord-owned jobs.
- Independent native login/model checks are not Hermes authentication or Discord worker integration evidence.
