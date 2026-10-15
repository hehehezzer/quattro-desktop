#!/usr/bin/env python3
"""Install only the intelligence wheel into an isolated virtual environment."""
from __future__ import annotations

import os
import argparse
import json
from pathlib import Path
import subprocess
import venv


ROOT = Path(__file__).resolve().parents[1]


def reject_symlink_components(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ValueError(f"Symlinked installation path is not allowed: {component}")


def validate_environment(destination: Path) -> Path:
    config = destination / "pyvenv.cfg"
    commands = destination / ("Scripts" if os.name == "nt" else "bin")
    for path in (config, commands):
        reject_symlink_components(path)
    if not config.is_file() or not commands.is_dir():
        raise ValueError(f"Destination is not a virtual environment: {destination}")
    settings = {
        key.strip().lower(): value.strip().lower()
        for line in config.read_text().splitlines() if "=" in line
        for key, value in [line.split("=", 1)]
    }
    if settings.get("include-system-site-packages", "false") != "false":
        raise ValueError("Virtual environment must not enable system site packages")
    python = commands / ("python.exe" if os.name == "nt" else "python")
    probe = subprocess.run(
        [str(python), "-I", "-c", "import json,sys,sysconfig; print(json.dumps({'prefix':sys.prefix,'paths':{k:sysconfig.get_path(k) for k in ('scripts','purelib','platlib')}}))"],
        check=True, capture_output=True, text=True,
    )
    layout = json.loads(probe.stdout)
    if Path(layout["prefix"]).resolve() != destination:
        raise ValueError("Interpreter does not belong to the destination virtual environment")
    for location in layout["paths"].values():
        path = Path(location)
        reject_symlink_components(path)
        if not path.resolve().is_relative_to(destination):
            raise ValueError(f"Virtual environment installation path escapes destination: {path}")
    for name in ("quattro-intelligence", "quattro-intelligence-mcp", "quattro-intelligence-native"):
        for suffix in ("", ".exe", "-script.py"):
            reject_symlink_components(commands / (name + suffix))
    return python


def install(destination: Path) -> Path:
    destination = destination.expanduser().absolute()
    reject_symlink_components(destination)
    destination = destination.resolve()
    if destination.exists() and not (destination / "pyvenv.cfg").is_file():
        raise ValueError(f"Destination is not a virtual environment: {destination}")
    if not destination.exists():
        venv.EnvBuilder(with_pip=True).create(destination)
    python = validate_environment(destination)
    subprocess.run(
        [str(python), "-I", "-m", "pip", "--isolated", "install", "--no-deps", str(ROOT)],
        check=True,
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / ".venv",
                        help="Isolated virtual environment (default: repository .venv)")
    args = parser.parse_args()
    try:
        destination = install(args.destination)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Installation failed: {error}\n")
    print(f"Installed intelligence core in {destination}")
    print("No desktop, service, native-agent, or global command registration was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
