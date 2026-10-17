#!/usr/bin/env python3
"""Operator-only native setup from explicit source registrations, never agent input."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from quattro_core.config import Config, Source, default_config_path
from install_native_clients import install_clients, write_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--install-clients", action="store_true", help="Explicitly register native omp/Codex integrations; review Codex hook trust afterward")
    args = parser.parse_args()
    base = Config.load(args.base)
    import sys
    raw = sys.stdin.buffer.read(128001)
    if len(raw)>128000:
        raise ValueError("registration manifest exceeds limit")
    manifest = json.loads(raw)
    sources = list(base.sources)
    projects = list(base.projects)
    for entry in manifest:
        source = Source(entry["id"],entry["project"],Path(entry["root"]),entry.get("kind","repository"),
                        tuple(entry.get("exclusions",[])),entry.get("authority",0.8),
                        entry.get("intent","undecided"),entry.get("exclusion_reason"))
        if source.id in {s.id for s in sources}:
            raise ValueError("duplicate source identifier")
        sources.append(source)
        if source.project not in projects:
            projects.append(source.project)
    config = replace(base,sources=tuple(sources),projects=tuple(projects),embedding="local-neural")
    config.save(args.config)
    clients = args.config.parent / "clients"
    for host in ("omp","codex"):
        replace(config,principal=host,writable=True,can_verify=False).save(clients / f"{host}.json")
    # Point global standalone commands at the isolated core, not historical adapters.
    python = Path(sys.executable).absolute()
    runtime = default_config_path().parent / "native-runtime.json"
    write_private(runtime,json.dumps({"python":str(python),"config_dir":str(args.config.parent)}) + "\n",mode=0o600)
    binary_dir = Path.home() / ".local/bin"
    binary_dir.mkdir(mode=0o755,parents=True,exist_ok=True)
    for name,module in (("quattro-intelligence","quattro_core.cli"),("quattro-intelligence-mcp","quattro_core.mcp"),("quattro-intelligence-native","quattro_core.native")):
        target = binary_dir / name
        write_private(target,f'#!{python}\nimport sys\nfrom {module} import main\nraise SystemExit(main(["--config", {str(args.config)!r}, *sys.argv[1:]]))\n',mode=0o755)
    result = {"config":str(args.config),"projects":projects,"sources":len(sources),
              "embedding":config.embedding,"clients":["omp","codex"],"can_verify":False}
    if args.install_clients:
        result["registration"] = install_clients(Path(__file__).resolve().parents[1],python,args.config.parent)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
