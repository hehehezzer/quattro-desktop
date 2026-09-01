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
| Workspace default | current directory | `QUATTRO_WORKSPACE` or `workspace.projectRoot` |
| OmniRoute endpoint | `http://localhost:20128/api/v1` | `QUATTRO_OMNIROUTE_BASE_URL` |

`XDG_*` falls back to `~/.config`, `~/.local/state`, and `~/.local/share`.
Quattro creates state directories mode 0700 and private files mode 0600.

## Configuration groups

- `accounts`: enabled Codex account aliases and homes. Homes must remain below
  the configured Quattro account root and are never read for authentication
  data.
- `defaultPolicyProfile`: strict default such as `workspace-write`.
- `memory`: disabled by default; paths are user-owned when enabled.
- `delegation`: optional bounded Pi worker limit, maximum three.
- `cooperation`: global and per-repository top-level session limits.
- `routing`: Quattro's three tiers, effort, route labels, and context budgets.
- `prReview`: review-only by default; publication requires an explicit CLI flag.

Unknown fields, unsafe account paths, disabled default accounts, invalid route
labels, and unconfirmed full access are rejected.
