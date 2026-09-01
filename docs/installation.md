# Installation

## Requirements

Python 3.11+ and Git are required. Codex, Pi, OmniRoute, and desktop commands
are optional until their corresponding features are used.
No Python runtime dependency beyond the standard library is required.
Linux `bubblewrap` is additionally required for the optional GitHub PR review
workflow; the workflow refuses to run uncontained.

## Install from a clone

### Core only (Linux)

```bash
git clone https://github.com/OWNER/quattro-desktop.git
cd quattro-desktop
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --no-deps .
quattro-agent --help
quattro-agent config init
quattro-agent config validate
```

The Linux convenience wrapper performs the same Core package installation:

```bash
./install.sh --profile core
```

### Core only (Windows, planned / hosted CI unverified)

Use Python packaging, not the Bash installer:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install --no-deps .
.venv\Scripts\quattro-agent config init
.venv\Scripts\quattro-agent --help
```

### Optional Linux Desktop

```bash
./install.sh --profile desktop
```

Desktop deployment requires a clean source revision. It installs Core first,
then activates the independent Desktop deployment manifest. It does not alter
Core's SQLite databases, sessions, account homes, or memory data.

`config init` writes a 0600 credential-free starter configuration. It does not
log in to Codex, create a memory vault, contact OmniRoute, or enable Pi.

## Source checkout without installation

```bash
PYTHONPATH=src ./src/quattro-agent --help
PYTHONPATH=src ./src/quattro-agent config init
```

## Configure external runtimes

1. Authenticate Codex using the Codex CLI in each account's own home.
2. Configure that home with the provider shape in
   `examples/codex-config.toml`.
3. Install or point `QUATTRO_MODEL_CATALOG` at the shared catalog containing
   `auto`, `auto/coding:cheap`, `auto/coding`, and `auto/reasoning`.
4. Start OmniRoute separately and confirm its loopback Responses endpoint.
5. Run `quattro-agent doctor --json`.

Never paste provider credentials into Quattro configuration and never copy
Codex authentication files into this repository.

## Verify a clean machine

```bash
python scripts/check_public_artifacts.py
python -m unittest discover -s tests -p 'test_*.py'
```
