# Hermes Discord integration — partial rollout

**Not production-ready. Do not mark the full goal complete.** This increment installs
Hermes's normal runtime, an owner-only read-only knowledge connector, and a guarded
service. It does **not** implement live Discord worker execution/continuation.

## Boundaries

The official Hermes Discord adapter supplies normalized identity. A supported
`pre_gateway_dispatch` plugin enforces numeric owner **AND** exact destination,
rejects bots/attachments/quoted control content, deduplicates messages, and invokes
existing `quattro_agent.shared_intelligence` before project-dependent conversation.
The upstream owner allowlist is defense in depth. Incoming identity is checked
before retrieval or inference; policy is rechecked before deterministic replies.
Threads require their own explicitly allowlisted ID, not just an allowed parent.

No second RAG store, vault import, autonomous router, worktree, public endpoint,
recursive worker chain, or upstream patch is added. The transport ledger stores
hashed conversation identities, bounded retrieval metadata, dedup IDs, and pending
requests. It is not an execution scheduler. Native Codex/Pi and current Jev/
OmniRoute remain independent and unchanged.

Retrieved excerpts are untrusted data. They may be sent to the approved cloud
provider and replies are visible to anyone who can access the destination. This
is **not local-only inference**. The existing retrieval implementation refreshes
bounded repository/Shared/matching-project memory and recent history; it does not
expose the entire second brain. Partial coverage is reported, not hidden.

## Current installation

- Hermes v0.21.5 / v2026.9.24, official stable archive with root revision prefix
  `e3dd27e`; isolated Python 3.11.16 and locked messaging/MCP dependencies.
- Source/runtime: `~/.local/share/hermes-quattro/`.
- Dedicated profile: `~/.hermes/profiles/quattro-discord/`.
- Service: `hermes-gateway-quattro-discord.service`; installed, stopped, disabled.
- Mandatory drop-in: `quattro-guard.conf`; clean environment, private umask,
  startup admission, bounded restart attempts. Native Hermes stop/recovery remains.
- Upstream installer enabled user lingering; no reboot/logout test was performed.
- Actual machine evidence and archive digest: `~/.local/state/quattro-hermes/`.

Core installation uses `./install.sh --profile core`. It adds `hermes_bridge.py`
to the existing Core inventory; existing native registrations remain idempotent.
Profile installation uses the small explicit setup script, not an upstream edit:

```bash
~/.local/share/hermes-quattro/venv/bin/python scripts/configure_hermes_discord.py
```

Existing dedicated-profile files are backed up privately only when changed.
Re-running setup does not create another profile, service, or credential.
Do not reinstall the venv stage over an existing environment merely to rerun setup.

## Owner unblock checklist (LOCAL terminal only)

1. Create a **bot application**, not a self-bot, at
   <https://discord.com/developers/applications>. Keep it private. Enable Message
   Content for normal text chat. Do not enable privileged member/presence access
   merely for role-based authorization: roles are not used here. Invite it with
   `bot` scope and only View Channel, Send Messages, Read Message History, and
   thread send permission if a thread is explicitly configured. No Administrator,
   guild management, or public execution endpoint is required. Allow only the
   private destination in Discord's own channel permissions as defense in depth.
2. Enable Discord Developer Mode; copy numeric owner, server, and channel/thread
   IDs. Enter them and the bot token through the secure local prompt:

   ```bash
   cd /path/to/current/quattro-checkout
   ~/.local/share/hermes-quattro/venv/bin/python scripts/configure_hermes_discord.py \
     --owner-id YOUR_NUMERIC_USER_ID --guild-id YOUR_NUMERIC_SERVER_ID \
     --channel-id YOUR_NUMERIC_CHANNEL_OR_THREAD_ID --bot-token-prompt
   ```

   DMs are owner-only. Additional private destinations require repeating the
   ID options. Never paste bot tokens/passwords/OAuth credentials into Discord,
   command arguments, source, logs, or this repository.
3. Authorize a **fresh Hermes-owned** supported subscription OAuth session:

   ```bash
   hermes -p quattro-discord auth add openai-codex --type oauth --browser \
     --label hermes-discord-owner
   ```

   Use the official local browser callback flow. Do not import native Codex
   tokens. `auth.adopt_external_logins` is disabled. Keep logged-out accounts
   logged out. This does not establish which models/quotas the new grant permits;
   validate a real Hermes response separately before claiming subscription use.
4. Run profile/plugin checks and the local contract test, then conduct the
   required owner-authored Discord/model round-trip under the guarded service.
   Keep execution blocked while managed worker/native Pi gates are unresolved.

   ```bash
   hermes -p quattro-discord config check
   hermes -p quattro-discord plugins doctor quattro-discord --ci
   ~/.local/share/hermes-quattro/venv/bin/python scripts/verify_hermes_discord.py
   systemctl --user start hermes-gateway-quattro-discord.service
   ```

Only enable login startup after the live service gates have passed:
`systemctl --user enable hermes-gateway-quattro-discord.service`.

## Implemented message syntax

These are plain message commands intercepted before inference, **not a claim of
Discord-registered slash commands**:

```text
/quattro help
/quattro projects
/quattro project quattro
/quattro intelligence
/quattro jobs
/quattro run codex quattro bounded task description
/quattro approve REQUEST_ID
/quattro deny REQUEST_ID
/quattro status REQUEST_ID
/quattro cancel REQUEST_ID
```

`run` creates an expiring, owner/destination/project-bound **proposal only**.
`approve` currently returns **BLOCKED**; it cannot launch a worker. `status`,
`result`, `jobs`, and `cancel` currently concern proposals, not functioning workers.
Do not advertise worker progress/cancellation or follow-ups as implemented.
Native `/new`, `/reset`, and `/stop` remain available to the authorized owner;
reset invalidates pending proposals. `/stop` stops Hermes inference, not a worker.
Native provider/terminal/skill/goal mutations are blocked in this profile.

After real Discord/OAuth setup, conversational examples to validate:

- “What did we decide about Quattro's routing authority? Cite the source.”
- “Use my second brain and write an implementation prompt plus /goal prompt.”

Requests like “Use Codex in project quattro to run the tests and fix this issue”
currently produce a proposal, **not execution**. “Use Pi to review this module”
and automatic delegation are not yet completed runtime integrations.

## Authentication/billing evidence

Native Codex 0.158.0 reported ChatGPT login and completed an explicit `gpt-5.5`
read-only review. Its existing configured default was rejected by the live
subscription endpoint; no default was changed. Native Pi 0.99.1 completed real
`openai-codex/gpt-5.5` knowledge queries using its installed intelligence extension.
An ordinary routing-authority question retrieved five decision/documentation
sources with memory available and partial index coverage. These native checks
are **not** Hermes authentication or Discord-delegation evidence.

Hermes's own OAuth/model/account path is **NOT VERIFIED**. Profile configuration
pins `openai-codex`, disables external credential adoption and fallback models,
keeps conversational execution/external tools off (including native recovered
platform toolsets and a mandatory pre-tool veto), disables canonical-memory
mutation/title upgrades/automatic compression, and pins configured auxiliary
providers to the same subscription path. Service startup strips ambient billing
keys and rejects alternate providers, profile API keys, and unapproved auxiliary
providers. Upstream named profiles can inherit a global Hermes auth store;
startup/intake therefore refuse while that store exists. Do not delete another
profile/account's credentials to satisfy this check: a verified isolated-root or
credential-origin solution is a remaining production constraint. No global store
was present during discovery. This configuration is not proof of live
billing/account fidelity.

A later independent native Codex review hit the subscription usage limit and did
not complete. The provider supplied a retry time. No other account/runtime was
used to evade it, no paid fallback was enabled, and no credits were purchased.
Subscription quota information remains unavailable; there is no unlimited-use
claim and no account rotation or paid-API fallback.

## Validation and all mandatory acceptance gates

`python scripts/verify_hermes_discord.py` must use the Hermes venv interpreter.
It uses real upstream hook discovery and real existing retrieval with a file-only
randomized fixture, but **synthetic platform identities and local collected sends**.
It does not pass Discord/model delivery gates. Unit tests supplement that check.

| Gate | Current result |
| --- | --- |
| 1 deployed actual owner Discord reply | NOT VERIFIED: bot/IDs unavailable |
| 2 Hermes own subscription model response | NOT VERIFIED: owner OAuth unavailable |
| 3 delegated native Codex account/billing | NOT VERIFIED; independent native baseline passed |
| 4 delegated native Pi + extension | NOT VERIFIED; independent native baseline passed |
| 5 ordinary Hermes question retrieves | AUTOMATED host hook + real local fixture passed; live Discord not verified |
| 6 grounded second-brain Hermes answer | NOT VERIFIED; native Pi memory retrieval passed separately |
| 7 controlled fixture + approved source | Real local randomized fixture and actual native project/memory retrieval passed; Hermes provider delivery UNKNOWN |
| 8 prompt-only, no workers/edits | AUTOMATED VERIFIED at boundary; live Discord/model output not verified |
| 9 each worker reversible writable task through Discord | NOT VERIFIED / NOT IMPLEMENTED |
| 10 follow-ups/session/project isolation | Conversation/project isolation automated; worker follow-ups NOT IMPLEMENTED |
| 11 active job status/cancel/replay | Proposal cancellation/expiry automated; active worker lifecycle NOT IMPLEMENTED |
| 12 unauthorized/spoofed/duplicate/untrusted controls | AUTOMATED VERIFIED for implemented intake; real Discord abuse gate NOT VERIFIED |
| 13 restart preserves/reconciles workers | Dedup restart automated; worker recovery NOT IMPLEMENTED |
| 14 actionable runtime failures/no surprise billing | Config/owner/RAG failure paths fail closed; full live failure matrix NOT VERIFIED |
| 15 regression-free native operation | CLI/auth and native Codex/Pi model/retrieval checks passed; full production regression gate not claimed |
| 16 terminal-close/startup/recovery deployment | Unit installation/admission checked; live gateway availability/recovery NOT VERIFIED |
| 17 tests and secret scan | Repository checks pass; see private validation report for latest counts and artifact scan |

## Operations and rollback

```bash
systemctl --user status hermes-gateway-quattro-discord.service
systemctl --user stop hermes-gateway-quattro-discord.service
journalctl --user -u hermes-gateway-quattro-discord.service -n 50
hermes -p quattro-discord logs
```

Renew Hermes OAuth with the same fresh native auth command above. Native Codex/Pi
keep their own stores/renewal flows; never copy refresh tokens across homes.
Expired auth/quota must remain an actionable blocked state, not trigger account
rotation or a paid API. Reconnection/restart still requires live testing.

Rollback: stop and disable this **dedicated** service, remove only its Quattro
service drop-in if restoring upstream behavior is deliberately desired, and use
existing guarded `quattro-agent deployment rollback --profile core REVISION
--confirm` with the exact previous revision from `deployment status`. Preserve
profile backups/state for inspection. Removing the dedicated Hermes source/profile
is optional and must never delete shared intelligence, second-brain sources,
Codex/Pi stores, or other services. Do not globally undo user lingering: another
user service may depend on it.

This PC-hosted service is unreachable while powered off, asleep, offline, or
disconnected. No VPS or 24/7 availability has been introduced.

## Git/release boundary

The task uses a dedicated branch and focused commits; the unrelated desktop Lua
edit is preserved. The starting checkout contains nine pre-existing native-Jev
commits beyond `main`. A PR-to-main must not silently absorb/publish that unrelated
history. Remote publication/PR and merge remain blocked on safe base reconciliation;
no unrelated PR was merged and no remote write was performed in this increment.
