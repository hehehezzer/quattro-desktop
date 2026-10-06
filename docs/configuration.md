# Configuration

Quattro reads strict schema-versioned JSON. The full public example is
`examples/ai.json`; `quattro-agent config init` creates the same safe shape in
your XDG config directory.

## Precedence

For paths, the order is:

1. command-line directory/policy options,
2. `QUATTRO_*` environment overrides,
3. `ai.json`,
4. XDG defaults.

Environment values are for local deployment and CI; do not commit a local
`.env` file.

## Important locations

| Purpose | Default | Override |
| --- | --- | --- |
| Config | `$XDG_CONFIG_HOME/quattro/ai.json` | `QUATTRO_CONFIG` |
| Runtime state | `$XDG_STATE_HOME/quattro/agents` | `QUATTRO_STATE_DIR` |
| Quattro data | `$XDG_DATA_HOME/quattro` | `QUATTRO_DATA_DIR` |
| Codex data/catalog | `$XDG_DATA_HOME/quattro-ai/codex` | `QUATTRO_CODEX_DATA_DIR`, `QUATTRO_MODEL_CATALOG` |
| Command workspace | current directory | `QUATTRO_WORKSPACE` |
| OmniRoute endpoint | `http://localhost:20128/api/v1` | `QUATTRO_OMNIROUTE_BASE_URL` |

`XDG_*` falls back to `~/.config`, `~/.local/state`, and `~/.local/share`.
Quattro creates state directories mode 0700 and private files mode 0600.

`QUATTRO_WORKSPACE` sets the command workspace used by status, prompt, and
deployment commands; otherwise it is the process current directory. The separate
`workspace.projectRoot` configuration sets the default project destination used
by mandatory-context resolution.

## Configuration groups

- `accounts`: enabled Codex account aliases and homes. Homes must remain below
  the configured Quattro account root and are never read for authentication
  data.
- `defaultPolicyProfile`: strict default such as `workspace-write`.
- `memory`: disabled by default; paths are user-owned when enabled.
- `delegation`: optional bounded specialist settings: required `enabled` and
  `maxWorkers` (maximum three), plus optional `workerAgent` (`pi` or `omp`).
  Set `workerAgent: "omp"` while keeping `defaultAgent: "codex"` to replace Pi
  specialists without changing the writable primary runtime. If omitted, the
  worker defaults to `omp` when the primary is `omp`, otherwise `pi`.
- `cooperation`: global and per-repository top-level session limits.
- `routing`: Quattro's three tiers, effort, route labels, and context budgets.
  Optional `jev: {"mode": "OFF", "timeoutMs": 300}` enables direct TypeSafe
  classification in `SHADOW` or controlled `COOPERATIVE` mode. Credentials use
  the existing TypeSafe resolver; see [Jev routing](JEV_ROUTING.md).
  `experimentalValidationOrder: true` inside `jev` opts into the gated
  [host validation-order experiment](JEV_RUNTIME_MILESTONES.md), only in
  `COOPERATIVE` mode. It is absent/disabled by default and has not demonstrated
  useful agent-reasoning offload; do not enable it in production.
- `prReview`: review-only by default; publication requires an explicit CLI flag.

Unknown fields, unsafe account paths, disabled default accounts, invalid route
labels, and unconfirmed full access are rejected.

## Optional native session selection

The optional strict `nativeSession` section selects an interactive harness and
an existing named Herdr server. It does not change `defaultAgent` (`codex` or
`pi`), durable task adapters, account selection, or sandbox policy profiles.
All three fields are required when the section is present:

```json
"nativeSession": {
  "preferredAgent": "omp",
  "skillsCatalog": "/opt/quattro/skills",
  "herdrSocket": "/run/user/1000/herdr/quattro.sock"
}
```

`preferredAgent` accepts `codex` or `omp`. Both paths must be explicit absolute
paths, without home/environment expansion or traversal. Set them to your
verified complete skills catalog and your named private Herdr socket. Catalog
existence and socket ownership/privacy are checked when launching; configuration
validation does not connect to Herdr or read skills. These example paths are
placeholders, not a deployment recommendation.

With this section, `quattro-agent launch` offers Codex, OMP, and explicit Pi
compatibility; non-terminal callers use `preferredAgent`. Without it, the
existing Codex/Pi chooser and default remain unchanged. Choosing OMP requires
`quattro-agent launch --confirm-native-access` at action time and starts a
persistent terminal through the configured socket. Configuring a preference
never supplies that confirmation. `--skills` and `--socket` can explicitly select
a catalog and named socket for an individual OMP launch. Explicit
`quattro-agent launch omp --skills /absolute/catalog --confirm-native-access`
without a configured socket retains the staged direct interactive route.

OMP uses the reviewed locked Sol 6.1 Medium route, native-user filesystem/network
rights, and native always-ask dialogs. Its working directory is not a sandbox.
Legacy `--policy` and `--confirm-full-access` overrides are rejected for OMP;
native access flags are rejected for Codex/Pi. Authentication remains a separate
native login, and real native approvals must still be given by the human. This
opt-in selection is not a persistent-policy approval or a full Pi replacement.
