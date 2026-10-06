# Scoped OMP host tools

`quattro_agent.scoped_omp_runtime` is a Quattro-owned, bounded RPC bridge to
official OMP 18.6.3. It replaces the Pi SDK at this embedding boundary. It does
not itself install a runtime, change an existing Projects policy, admit a task,
or authorize an operation.

The reviewed deployment needs Bun 1.3.14 or newer and the official
`@oh-my-pi/pi-coding-agent@18.6.3` package dependency closure. The standalone
native OMP executable is insufficient for this SDK embedding. Deployment must
verify package provenance and pin Bun, the complete installed package closure,
and `data/scoped-omp-runtime.ts`. Installation must not execute unchecked package
scripts. The SDK uses native OMP authentication; missing authentication remains
a separate native user login. No Pi or Codex account file is copied.

## Closed SDK bootstrap

`sdk_command(bun, package_root, cwd=..., agent_dir=..., session_dir=...)` creates
literal argv for the bundled OMP-only bootstrap. All paths must be absolute.
`agent_dir` identifies the explicitly selected native OMP account directory;
it must not accidentally become a disposable worker directory when native
authentication is required. The bootstrap uses isolated settings, the bundled
model catalog and fixed `openai-codex/gpt-6.1-sol` with medium effort. It rejects
model fallback. Native sessions are in memory: `session_dir` is reserved launch
metadata and no prompt/response transcript is persisted there.

The worker uses a fresh private HOME created by `prepare_private_home(path)`.
Its `.omp/logs` is an owned 0600 regular sentinel file. The supported native
logger API disables file and console transports. OMP's HTTP400 raw-request dump
path independently attempts to write beneath the logs directory; the sentinel
makes that write fail with ENOTDIR, which the native helper catches. The
bootstrap verifies the actual SDK-derived logs path and sentinel identity
before prompting. It never changes the user's native logs directory. The native
auth directory remains separately selected; no account file is copied into
the private HOME.

The SDK is called with `toolNames: []`, `restrictToolNames: true`, disabled MCP
and LSP, no prepared extensions, no context files, rules, prompt templates or
slash commands, and an empty skill set. Advisor, automatic learning, workspace
tree inclusion and cache warming are disabled. A native CLI `--no-tools` alone
does not establish this boundary: it leaves the SDK unrestricted and can still
discover custom tools or MCP capabilities. The supported OMP RPC host-tool
registration remains available in the restricted SDK session.

Skills remain preserved in their original catalog during migration. The default
context-only bootstrap loads no skills. Projects embedding can supply
`VerifiedSkillCatalog(manifest, root, expected_digest=...)` to `sdk_command` and
`ScopedOMPRuntime` through `skills_catalog`. This verifies the pinned migration
manifest and every staged file, including original collision loaders, and fails
on inventory additions, links, unsafe file modes or content changes. The OMP
SDK's supported `loadSkillsFromDir` receives only that explicit catalog; the
resulting Skill list is passed directly to session construction. Startup checks
native `get_available_commands` metadata against every exact catalog alias.

Register `catalog.tool_definition()` and gate its `scoped_skill_read` callback
through the host's admitted binding before calling `catalog.read(arguments)`.
Only a known `skill://alias[/verified-relative-file]` is readable; offsets and
limits count lines. Metadata never returns the manifest's source or backup
paths. The `readsSkillUris` capability makes OMP include skill guidance without
granting native file tools. The model receives reference scripts as untrusted
data; this reader cannot execute them or provide an external app connection.
Missing app/tool capabilities must be reported honestly.

Projects mode accepts only exact known `/skill:<alias>` invocations. OMP handles
these through its supported RPC skill command and directly reads the verified
loader as context; the bootstrap rechecks the catalog, native profile and logs
sentinel before each ordinary or custom prompt. No other native slash command,
local shell action or model selection macro is admitted by this bridge.
Herdr can preserve the bridge process and its
in-memory conversation across client detach. Native session restart, automatic
resume, and history migration are not implemented by this bridge.

## Host authority interface

Create `ScopedOMPRuntime(command, cwd=..., environment=..., binding=HostBinding(
task_id, session_id), tools=..., execute=..., timeout=...)`. The environment is
an explicit small allowlist; inherited credentials and loader settings are
rejected. `start()` observes the actual native session identity and registers
the exact supplied host-tool definitions with OMP `set_host_tools`. It checks
the fixed model and effort before any prompt. `prompt(text)` accepts
bounded plain input or an explicitly verified known skill invocation, serves correlated host calls, and returns a completed
settled turn and final assistant text. It does not log that text. Plain prompt
input cannot invoke runtime configuration commands, local shell actions or model
mentions. `close()` terminates the owned process group. A supervised context
worker can set `own_process_group=False` so its child stays in the supervisor's
process group.

The callback signature is `execute(binding, tool_name, arguments, tool_call_id)`.
The callback must own and enforce current Quattro admission, validated argument
schemas, repository roots, preimages, consultations, host approvals, expiration,
command budgets and cancellation. It must impose an execution deadline itself;
the synchronous bridge cannot interrupt arbitrary Python callbacks. A registered
tool is discoverability metadata, never a permission grant. Callback exceptions
produce a constant denied tool result. Identity mismatch, protocol mismatch,
duplicate requests, unknown tools, oversized frames, timeout or disconnection
close the worker. Protocol diagnostics do not include provider payloads.

## Existing protected Projects integration

The installed Projects authority can be connected without copying private
configuration into this repository. Replace only the pinned Pi launch/dependency
and SDK-wrapper boundary with this OMP bootstrap and bridge. Keep the existing
host approval, grant, consultation, preimage, containment-proof and expiry
checks. A trusted closure retains the capability, verifies the exact approved
host binding and current retained launch proof, maps `scoped_OPERATION` to the
existing operation, and invokes the existing service's
`execute(capability, task_id, session_id, request_id, operation, arguments)`.
Generate and retain a host request identity; do not assume an arbitrary OMP tool
call ID satisfies the old host ID schema. Host pending owner-approval results
remain pending. Neither model output nor a registered tool can resolve them.

The retained launch proof must be updated to describe the actual OMP process,
its reviewed closure, observed native identity and lifetime. A Pi-specific
`ManagedPiRuntime` type check or Pi dependency hash cannot be reused as evidence
for OMP. The legacy confirmed-command surface needs a separate host-backed
operation-ID tool; it must not be replaced by native arbitrary `bash`. Native
OMP auth has its own refresh/store behavior, so the old Pi read-only OAuth-store
property is not automatically preserved. Review that concrete auth delta before
activating a protected deployment.

The current bridge does not modify or activate that installed deployment.

## Validation

Hermetic `test_scoped_omp_runtime.py` covers authority binding, exact arguments,
duplicate calls, profile changes, foreign prompt results, oversized frames,
unregistered tools, denied callbacks, command-like input, known skill aliases,
URI traversal, original and loader drift, added files, links and manifest drift. Official staged
Bun/OMP startup, fixed profile observation and empty host-tool registration also
passed in a temporary account directory with no model-backed request. This does
not establish provider authentication or model execution acceptance.
The official rejected-request helper also passed a synthetic HTTP400 fixture:
it handled the sentinel ENOTDIR failure and retained the regular sentinel,
without persisting the request dump.
The verified catalog of 241 staged skills passed exact OMP native command
metadata parity and host skill-reader registration under the actual official
SDK, in an isolated account directory without a model-backed prompt. This proves
catalog discovery and the closed reader mapping; it does not establish every
skill's external app capabilities or permission to execute its reference scripts.

The version-specific API evidence is official OMP `docs/sdk.md`, `docs/rpc.md`
(host-tool subprotocol), `packages/coding-agent/src/sdk.ts` (restricted tool
discovery), and `src/session/session-tools.ts` (RPC host-tool refresh). The
official package's wildcard subpath export exposes
`modes/rpc/rpc-mode`; its root modes barrel intentionally omits the server.
