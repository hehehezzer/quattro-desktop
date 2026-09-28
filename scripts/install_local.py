#!/usr/bin/env python3
"""Dependency-free user-local installer for hosts where Python omits pip."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
PACKAGES = ("quattro", "quattro_agent")
MODULES = (
    "quattro_deployment.py", "quattro_harness.py", "quattro_image_mcp.py",
    "quattro_memory.py", "quattro_pr_review.py", "quattro_release.py",
)


def install(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quattro-install-", dir=target) as temporary:
        stage = Path(temporary)
        for package in PACKAGES:
            shutil.copytree(SOURCE / package, stage / package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for module in MODULES:
            shutil.copy2(SOURCE / module, stage / module)
        shutil.copy2(SOURCE / "quattro-agent", stage / "quattro-agent")
        (stage / "quattro-agent").chmod(0o755)
        names = (*PACKAGES, *MODULES, "quattro-agent")
        backups = {}
        installed = []
        try:
            for name in names:
                destination = target / name
                backup = target / (".quattro-old-" + name.replace("/", "_"))
                if backup.exists():
                    shutil.rmtree(backup) if backup.is_dir() else backup.unlink()
                if destination.exists():
                    os.replace(destination, backup)
                    backups[name] = backup
                os.replace(stage / name, destination)
                installed.append(name)
        except BaseException:
            for name in reversed(installed):
                destination = target / name
                if destination.exists():
                    shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
                if name in backups:
                    os.replace(backups[name], destination)
            for name, backup in backups.items():
                destination = target / name
                if backup.exists() and not destination.exists():
                    os.replace(backup, destination)
            raise
        for backup in backups.values():
            if backup.exists():
                shutil.rmtree(backup) if backup.is_dir() else backup.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path,
                        default=Path.home() / ".local" / "bin")
    args = parser.parse_args()
    install(args.target.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
