# Herdr, Quattro, and OMP

Herdr owns persistent terminals. Quattro owns routing and decisions. OMP runs the
coding workflow and native approval UI. A Jev recommendation is advisory;
it cannot grant host permission or answer an approval dialog.

The integration uses Herdr's documented Unix socket API, with an explicitly
selected named session. It does not address the user's default session, send
shell command text, alter an existing layout, or stop a running server.

## Runtime interface

`python scripts/stage_herdr_omp.py --skills /absolute/verified/skill-catalog`
creates a hash-pinned Core bundle and new `quattro-omp` and `quattro-herdr`
launchers beside the existing installation. It preserves existing launchers
and refuses to overwrite a different migration candidate. The staged aliases
use the bundled CLI, so an older installed `quattro-agent` need not be changed.
`quattro-omp PATH --confirm-native-access` opens the reviewed native route;
`quattro-herdr` takes the arguments below after the `herdr` subcommand.

The CLI exposes the staged contract with `quattro-agent herdr contract`.
Start a dedicated named Herdr server with `herdr --session quattro-omp server`.
Herdr reports its socket through `herdr session list`; use that exact socket:

```bash
quattro-agent herdr start PATH --socket /absolute/named/herdr.sock \
  --skills /absolute/verified/skill-catalog --confirm-native-access
quattro-agent herdr status --socket /absolute/named/herdr.sock \
  --workspace WORKSPACE_ID --pane PANE_ID
herdr --session quattro-omp
```

`--confirm-native-access` acknowledges the reviewed access change at launch.
OMP commands and writes retain native-user filesystem/network rights and require
actual OMP `always-ask` dialogs. A directory is not a sandbox. Headless approval
cannot replace a human response. OMP's native `/login openai-codex` remains a
separate user action if the provider is unavailable; no authentication file is
copied from Pi or Codex. The launcher rejects legacy policy overrides.

The explicit route locks Sol Medium; the bridge rejects model/effort changes.
Quattro supplies model-authored v2 Jev, hybrid retrieval and bounded RTK tools.
The OMP route does not reuse the legacy tool-disabling Pi input gate. Native
coding tools are subject to OMP approval. Unsupervised OMP subagents are denied.
The legacy durable task scheduler still uses its existing adapters; this staged
native route must not be described as a completed replacement of those adapters.

Use `scripts/migrate_omp_skills.py` to inventory, back up and stage original skill
directories. Verify its manifest before pointing the supported
`skills.customDirectories` mapping at the staged catalog. Same-name variants
receive distinct discovery names and preserve exact originals separately.
Discoverability does not establish availability of each skill's external app.
Missing tools must be reported honestly without inventing connector access.

`quattro_agent.herdr_runtime.HerdrRuntime(socket_path)` accepts an absolute,
current-user-owned, private Unix socket path. `start(argv, directory=Path(...))`
creates a workspace and an argv-backed terminal tab, returning a
`HerdrSession(workspace_id, pane_id)`. The executable must be an absolute path.
Callers supply the authorized Quattro launcher; the generic terminal API is
not an execution permission gate.

For example, an installed launcher can pass the Python executable followed by
`-m quattro_agent launch omp PATH`. Herdr launches a small Quattro terminal
helper which discards arbitrary inherited environment, API keys, loader hooks,
and foreign Python paths before executing that argument vector. Native account
stores remain in their original HOME. Herdr pane identity and explicit Quattro
configuration paths survive for lifecycle reporting and routing.

`status(handle)` returns only pane identity and semantic state. An unrecognized
state remains `unknown`; this is never proof of completion. `ping()` checks the
selected server. `close(handle)` accepts only a workspace created by that same
client and requires explicit caller intent. There is no approval-key sender,
server stopper, transcript reader, credential copier, or automatic retry.

I/O has a five-second default deadline and a one-MiB response bound. A timeout
or disconnection can leave a mutation's outcome uncertain. Inspect that named
session before retrying; do not create a second session blindly. A failure
between workspace creation and terminal creation can leave an empty workspace;
the integration intentionally retains it for diagnosis.

## Persistence and rollback

### Staged native session metadata

`quattro_agent.omp_sessions.OMPSessionRegistry` provides a separate private,
bounded JSON registry for the staged native route. It does not migrate or modify
the Codex/Pi task database. A trusted launcher records intent with `begin`, then
binds `created` to its actual successful Herdr start receipt. A failed or timed
out start becomes `launch_uncertain`; the registry never retries it or adopts an
unrelated pane. Socket ownership, private permissions and filesystem identity,
workspace/pane identity and the original directory identity remain bound.

Native OMP identity stays `pending` until a trusted native session-start hook
calls `observe_native` with the exact recorded tuple. Model assertions and
terminal text are not identity evidence. `verify_attachment` permits selection
of that existing pane only when its recorded native identity matches and Herdr
reports an active semantic state. It does not launch a process, approve a tool,
or establish machine-restart/native-resume support. Status is metadata only.

`begin_close` and `finish_close` record explicit owning-client close outcomes;
they never promote a handle into a new Herdr client's ownership set. An
uncertain close cannot be replayed. Registry files and locks are mode 0600 in a
mode-0700 owner directory, reject links and invalid preimages, and use bounded
locking with atomic durable writes. This module requires Unix file locking only
when instantiated. Coordination and native restart/resume remain explicitly
unsupported; registering a terminal does not claim durable scheduler capacity
or a repository write scope.

An interactive Herdr client can detach and reattach while the server-owned
terminal continues. To attach a known named session, use
`herdr --session NAME`. Detach through Herdr's normal UI. Closing an outer
terminal does not itself stop its managed pane.

Machine/server restart is a different lifecycle: the original process does not
survive. Herdr can restore layout and resume supported native agents. Resume
support for the combined Quattro launcher must be verified separately; merely
restoring an OMP pane is not proof that Quattro's routing authority resumed.
The integration does not claim crash recovery from a detach test.

Keep Pi installed until a real Herdr → Quattro → OMP workflow has passed model,
skill, policy, retrieval, edit, and regression acceptance. Preserve native
accounts, history, original skill roots, and backed-up configuration. Rollback
selects the retained prior launcher. Archive only Pi-exclusive installation and
launch configuration after replacement acceptance; shared skill roots and
Codex remain intact.

## Validation

Hermetic coverage verifies literal argument handling, ownership cleanup,
environment filtering, request identity correlation, bounded responses,
redacted protocol errors, unavailable capabilities, and rejection before
mutation. Run:

```bash
python -m unittest discover -s tests -p test_herdr_runtime.py
```

A real runtime check must additionally create an isolated named Herdr server,
launch the Quattro OMP route through `start`, observe the actual native model
and approval behavior, disconnect/reconnect the client, and verify that the
same pane/process continues. Synthetic socket coverage does not satisfy that
acceptance. Do not stop or upgrade an unrelated live server.

## Verified staging acceptance

Herdr 0.9.3 (installed from the verified official release) passed a real local
staging check in the isolated named session `quattro-omp-stage`:

- `workspace.create`, `layout.apply` with literal argv, `pane.get`, and owned
  `workspace.close` matched the installed protocol-22 schema.
- A harmless Python heartbeat kept the same process ID and advanced from tick
  1 to tick 66 across two actual Herdr TUI attach/detach cycles. Both detached
  clients exited successfully; a new socket client saw the same managed pane.
- The test workspace was closed through its owning client. The named server
  remained running for the migration owner's subsequent acceptance work.

This proves live terminal persistence across client disconnection. It does not
prove provider authentication, model execution, Quattro policy behavior, OMP
skills, or machine-restart recovery. Those require the combined-route acceptance
and any applicable action-time approval. No OMP process or access grant was
created by this staging check.

## Sources

The current interface was checked against Herdr's official
[repository](https://github.com/herdrdev/herdr),
[CLI reference](https://herdr.dev/docs/cli-reference/),
[socket API](https://herdr.dev/docs/socket-api/), and
[session lifecycle documentation](https://herdr.dev/docs/session-state/).
The installed binary and its `herdr api schema --json` remain authoritative for
version-specific behavior. Unsupported methods fail explicitly; they do not
justify changing permissions or replacing a running server.
