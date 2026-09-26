# Quattro Development

## Repository layout

- `src/quattro-agent` — command-line control-plane entry point.
- `src/quattro_harness.py` — durable task lifecycle, context assembly, and
  execution supervision.
- `src/quattro_agent/` — policy, adapters, routing, persistence, retrieval,
  collaboration, recovery, and validation primitives.
- `src/quickshell/` — the single Quickshell UI.
- `src/hypr/` — Hyprland Lua configuration.
- `tests/` — Python unit and integration tests.
- `docs/` — operational and architecture documentation.

## Development workflow

1. Read project instructions and institutional memory.
2. Inspect current source and runtime state; preserve unrelated dirty changes.
3. Make the smallest compatible change and add focused regression coverage.
4. Run focused tests, then the full suite for release candidates.
5. Validate syntax and whitespace.
6. Update durable project memory only after validation.

```text
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile src/quattro-agent src/quattro_harness.py
python -m py_compile src/quattro_agent/*.py
git diff --check
```

## Interactive agent sessions

Run `quattro-agent` or `quattro-agent launch` in the intended workspace for a
**new** native agent launch. On a terminal, Quattro resolves and displays
the workspace, then asks whether to use Codex or Pi. The `defaultAgent` from
`ai.json` is marked as the default and selected by Enter. Non-TTY launches use
that configured default without prompting. Choose directly with
`quattro-agent launch codex` or `quattro-agent launch pi`; an optional workspace
path may follow the agent. Cancelling the chooser with `q`, `quit`, `exit`,
Ctrl-D, or Ctrl-C exits before a durable session is created.

After selection Quattro replaces itself with the real Codex or Pi executable in
the current terminal. Quattro does not render a chat prompt, proxy terminal
input, or open another terminal. Native stdin/stdout/stderr, signals, resizing,
streaming, approvals, commands, and exit behavior therefore remain intact. Pi
uses the bounded read-only native profile with extensions and tools disabled.

Native persistent sessions retain the selected Codex account home, its
configured OmniRoute provider/model, mandatory policy context, workspace, and
safe launcher environment. They do **not** receive a fresh locked Quattro
ExecutionPlan per turn because neither native persistent CLI exposes that
request boundary to the launcher. Locked per-turn guarantees remain available
through one-shot managed commands such as `prompt` and `submit`; native launch
does not silently claim them or force legacy routing mode.

Native launch provenance is recorded in runtime/recent state under a `qsession_*`
identifier, but it is not presented as a durable logical task session. Codex's
native rollout is discovered afterward and associated with the launcher account
using the unique workspace/start marker. Native Pi uses a credential-free,
ephemeral configuration and OmniRoute `auto`; native Pi resume is explicitly
unavailable until Quattro stores a stable Pi home and native session reference.

`quattro-agent resume` lists durable recoverable sessions. Codex logical
sessions hand the terminal to native Codex; unsupported Pi logical resume fails
clearly. `quattro-agent --help` displays
command help; `quattro-agent prompt` remains the one-shot scripting path.
Launching does not create or switch Git branches or worktrees. Verify a clean
`dev` checkout and create the intended feature branch before coding.

## Branch and worktree policy

Keep two persistent branches: `main`, which tracks the authoritative production
state on `origin/main`, and `dev`, which is the clean baseline for new work and
tracks `origin/dev`. Keep `dev` at the latest intended `main` baseline. Preserve
unfinished work before removing its branch or worktree; do not clean a checkout
just to make its status look empty.

Start each feature from `dev`:

```bash
git switch dev
git pull --ff-only
git status --short
git switch -c feature/<name>
```

The `git status --short` output must be empty before creating a feature branch
or worktree. If it prints anything, stop feature creation. Preserve unrelated
work in its owning branch or worktree, or through another explicit recovery
mechanism, before returning to a clean `dev`; never automatically stash it or
silently carry it into a new task.

For isolated work, create one clean worktree per task:

```bash
git worktree add ../quattro-<name> -b feature/<name> dev
git -C ../quattro-<name> status --short
```

The status command must print nothing before work begins. Each task owns one
branch and, when isolation is needed, one worktree. Do not let a task inherit
another task's uncommitted changes.

Push the feature branch and open a pull request targeting `main`. After the
pull request is validated and merged, remove the completed feature branch and
task worktree, then prune stale worktree metadata. Synchronize the persistent
branches with fast-forward updates:

```bash
git switch main
git pull --ff-only
git switch dev
git merge --ff-only main
git push origin dev
```

Delete completed feature branches after merge. Keep only `main` and `dev` as
persistent local branches; retain other branches only for active work or an
explicitly documented archival reason.

## Release procedure

1. Ensure the intended source changes are reviewed and committed.
2. Confirm `git status` is clean and no secret or generated artifact is staged.
3. Run the full test suite and release checks.
4. Use `quattro-agent deployment deploy` from the exact clean commit. It
   creates a private rollback release, installs the validated source mapping,
   and removes paths retired by the new release; do not copy a dirty working
   tree into the runtime.
5. Verify manifest source/deployed parity and both Codex account contracts.
6. Smoke-test DIRECT and a non-mutating delegated Codex task in a disposable
   repository.
7. Only then create and push a reviewed annotated release tag such as `v1.0.0`.

## Commit organization

When the working tree is fully reviewed, prefer coherent commits rather than
mechanical splitting: runtime/architecture, tests, documentation, then release
metadata. Do not commit unrelated desktop assets, credentials, generated
artifacts, or temporary diagnostics merely to obtain a clean tree.
