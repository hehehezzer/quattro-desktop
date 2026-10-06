#!/usr/bin/env python3
"""Stage a hash-pinned Quattro runtime beside existing native installations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "src"))
from quattro.deployment.profiles import CORE_DEPLOYMENT_MAPPINGS


def safe_path(path: Path, *, directory: bool = False) -> None:
    """Reject links at every level and nonregular existing destinations."""
    for parent in path.parents:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError("staging paths must have unlinked directory ancestors")
    if path.is_symlink():
        raise ValueError("staging paths must not contain symbolic links")
    if path.exists() and not (path.is_dir() if directory else path.is_file()):
        raise ValueError("staging path must be a directory" if directory else "Core source or destination must be a regular file")


def stage(source: Path, home: Path, skills: Path) -> dict:
    """Copy only public Core artifacts; never inspect account stores/history."""
    source, home, skills = source.resolve(strict=True), home.resolve(strict=True), skills.resolve(strict=True)
    if not skills.is_dir():
        raise ValueError("verified skill catalog directory required")
    payload = {}
    for relative in sorted({item[0] for item in CORE_DEPLOYMENT_MAPPINGS.values()}):
        path = source / relative
        safe_path(path)
        if not path.is_file():
            raise ValueError("Core source must be a regular file")
        name = (Path(relative).relative_to("src") if Path(relative).parts[0] == "src"
                else Path("resources") / relative)
        payload[str(name)] = path.read_bytes()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    root = home / ".local/lib/quattro-herdr-omp" / digest
    safe_path(root, directory=True)
    manifest = root / "manifest.json"
    manifest_data = (json.dumps({"bundleSha256": digest, "files": hashes}, sort_keys=True) + "\n").encode()
    wrappers = {}
    for name, arguments in (
            ("quattro-omp", "'launch', 'omp', *sys.argv[1:], " + f"'--skills', {str(skills)!r}"),
            ("quattro-herdr", "'herdr', *sys.argv[1:]")):
        binary = home / ".local/bin" / name
        wrappers[binary] = ("#!/usr/bin/python3\nimport sys\nsys.dont_write_bytecode = True\n"
                           f"sys.path.insert(0, {str(root)!r})\n"
                           "from quattro_agent.cli import main\n"
                           f"sys.argv = [sys.argv[0], {arguments}]\nraise SystemExit(main())\n").encode()
    # Preflight the entire bundle and launcher inventory before any writes or
    # chmods: checking only a leaf misses a linked package or bin directory.
    for name, data in payload.items():
        target = root / name
        safe_path(target)
        if target.exists() and target.read_bytes() != data:
            raise ValueError("existing bundle differs; preserved without overwrite")
    safe_path(manifest)
    if manifest.exists() and manifest.read_bytes() != manifest_data:
        raise ValueError("existing bundle manifest differs; preserved without overwrite")
    for binary, wrapper in wrappers.items():
        safe_path(binary)
        if binary.exists() and binary.read_bytes() != wrapper:
            raise ValueError("existing migration launcher preserved; review update separately")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in payload.items():
        target = root / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(data)
        target.chmod(0o400)
    if not manifest.exists():
        manifest.write_bytes(manifest_data)
    manifest.chmod(0o400)
    for binary, wrapper in wrappers.items():
        binary.parent.mkdir(parents=True, exist_ok=True)
        if not binary.exists():
            binary.write_bytes(wrapper)
            binary.chmod(0o700)
    binary = home / ".local/bin/quattro-omp"
    return {"bundleSha256": digest, "files": len(payload), "launcher": str(binary),
            "herdrLauncher": str(home / ".local/bin/quattro-herdr"),
            "bundle": str(root), "existingLaunchersChanged": False,
            "authenticationAccessed": False, "nativeExecutionApproved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--skills", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.home, args.skills), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
