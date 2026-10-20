# Quattro Intelligence

Local-first knowledge retrieval and persistent project memory for independent clients. Quattro indexes explicitly registered code, documentation and notes, returns cited context, and stores deliberate memories in SQLite. Python 3.11+, no third-party Python runtime dependencies, and no mandatory paid API.

Quattro does **not** choose models or providers, launch agents, route tasks, manage accounts, or take over client permissions. Use its CLI or bounded stdio MCP server with the tools you already use. The optional Arch desktop is a separate setup profile, not a requirement for Intelligence.

## Install Intelligence

```bash
git clone https://github.com/hehehezzer/quattro-desktop.git
cd quattro-desktop
./install.sh --core
```

This installs into the checkout's isolated `.venv`. It does not change global commands, agent settings, desktop services or existing databases. Without flags, an interactive terminal offers the core or Arch setup; noninteractive use retains the core install. See the [operating guide](docs/installation.md) for a different virtual environment destination.

Create a new operator configuration, register this checkout as an explicit source, and index it:

```bash
Q="$PWD/.venv/bin/quattro-intelligence"
C="$PWD/.quattro/intelligence.json"
"$Q" --config "$C" config-init --database-dir "$PWD/.quattro/state" \
  --project quattro --principal operator --writable --can-verify
"$Q" --config "$C" register-source --project quattro --id code --root "$PWD" \
  --kind repository --intent intended --exclude '.quattro/**' --exclude 'benchmarks/**'
"$Q" --config "$C" index code
"$Q" --config "$C" query --project quattro 'QueryRouter'
"$Q" --config "$C" doctor --project quattro
```

`config-init` refuses to overwrite an existing configuration. The example deliberately grants operator write and verification authority; create a separate, narrowly scoped reader configuration for clients. Never register an entire home directory or private vault by accident.

### Connect a client

Start MCP with an absolute configuration path:

```bash
.venv/bin/quattro-intelligence-mcp --config "$PWD/.quattro/intelligence.json"
```

The server uses JSON-lines on stdin/stdout and opens no network listener. Clients start it themselves. Missing configuration fails closed. All nine MCP tools enforce configured project/source and write permissions; indexing accepts registered source IDs, not caller-supplied roots. Retrieved content is untrusted evidence, never authorization.

For optional native omp/Codex context integration, source registration, hook trust and approval requirements, follow the [integration guide](docs/INTEGRATION.md). Native clients keep their own models, accounts, execution, permissions and delegation.

## What Intelligence provides

- Exact and lexical retrieval using SQLite FTS5/BM25, paths, filenames, symbols, imports and configuration identifiers.
- Optional local Nomic embeddings and hybrid ranking. Lexical mode works independently and reports semantic unavailability honestly.
- Incremental, atomic indexing with exclusions, source ownership, provenance, freshness reporting and citations.
- Episodic, semantic, procedural and shared memory with references, visibility, revisions, verification and explicit supersession.
- Budgeted context, source/memory inspection, diagnostics, and checksummed backup/restore into a new directory.

Quattro does not automatically record whole conversations or treat retrieved text as verified fact. See the [memory contract](docs/memory.md) and [security boundaries](docs/security.md).

## Optional Arch desktop

On an **already installed Arch Linux system**, clone the repository as above, then run:

```bash
./install.sh --arch --dry-run
./install.sh --arch
```

This is desktop configuration, **not an Arch OS installer**: it does not partition disks, install a bootloader, create users or replace the operating system. Run as your normal user, not with `sudo`; package installation requests privilege separately. Review the dry-run package/file plan before applying it.

Use a normal account with `sudo` and working official Arch mirrors. If Python is missing, normal Arch setup offers its pacman prerequisite first; dry-run/help and file-only staging never install it implicitly.

In a terminal, setup asks which features to keep; press Enter for `desktop,intelligence`. Select an exact set with flags to skip that chooser:

```bash
./install.sh --arch --features desktop --dry-run
./install.sh --arch --features desktop,intelligence,applications
```

| Feature | Purpose |
|---|---|
| `desktop` | Hyprland/Quickshell baseline and retained desktop configuration/assets; requires compatible Arch packages, including Hyprland's Lua configuration support. |
| `intelligence` | Isolated Quattro Intelligence installation; does not register or index private sources automatically. |
| `applications` | Optional nonessential desktop applications; requires `desktop`. |
| `native` | Explicit native-client integration; requires `intelligence` and `--native-config PATH` pointing to an existing authorized configuration with at least one registered source. Read the integration guide first. |

`--yes` accepts the displayed configuration changes without interactive confirmation; pacman retains its own package prompts. Changed existing target files are backed up under the user's XDG state directory at `quattro/setup-backups/<id>`, with a rollback manifest; they are not silently discarded. `--skip-packages` applies configuration without package installation. An alternate `--home PATH` stages an isolated home instead of changing the current one and does not install system packages or native clients.

Native setup requires the current home and standard `~/.config` location; a custom `XDG_CONFIG_HOME` is rejected for that feature. Installed native reader configurations have writes and verification disabled. A desktop-only selection keeps the Intelligence panel available but reports the core as unavailable until configured; it does not restore retired agent controls.

Setup does not restart the current desktop, enable services, change native permissions or migrate old execution consumers. Choose when to start the configured desktop yourself. Some retained desktop controls depend on separately installed services/apps and historical execution integrations are not provisioned. See [desktop maintenance and asset notices](docs/desktop.md).

The Intelligence feature creates a lexical, read-only starter configuration in `~/.config/quattro/intelligence.json`, with an empty `local` namespace. Register your own sources and review project/write permissions using the configuration and operating guides; setup never copies the author's notes, accounts or databases. GPU drivers, display-manager installation, system service activation and machine-specific storage remain host choices.

### Optional JEV

JEV is an independent, optional external client/tool, not a bundled Quattro runtime or installer feature. Quattro works without it. This repository does not currently provide a supported JEV installation or `--features jev`; configure external tools separately against the documented MCP boundary without reviving retired routing or granting them additional permissions.

## Guides

| Need | Guide |
|---|---|
| Install, configure sources, operate and recover | [Operating guide](docs/installation.md) · [Configuration](docs/configuration.md) |
| Connect independent/native clients | [Integration](docs/INTEGRATION.md) · [MCP contract](docs/MCP.md) |
| Understand retrieval and memory | [Retrieval](docs/RETRIEVAL.md) · [Memory](docs/memory.md) |
| Maintain the implementation safely | [Architecture](docs/architecture.md) · [Development](docs/development.md) · [Security](docs/security.md) |
| Preserve data from older versions | [Migration](docs/MIGRATION.md) |
| Maintain optional desktop assets | [Desktop](docs/desktop.md) · [Design reference](DESIGN.md) |

The repository retains the historical `quattro-desktop` URL. Intelligence is the active standalone Python product; retained desktop assets are separate from its distribution. Old execution/orchestration code is retired. Do not delete live databases or reconnect historical execution consumers to the new API.

## Development and support

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution boundaries and [development](docs/development.md) for checks. The [test report](docs/TEST_REPORT.md) records historical executed checks and measured limits, not a guarantee for every environment. Linux runtime has been exercised; Windows CI covers the portable memory/MCP surface. Windows indexing and macOS operation are not claimed as locally verified.

[MIT license](LICENSE) · [Security reporting](SECURITY.md) · [Code of conduct](CODE_OF_CONDUCT.md)
