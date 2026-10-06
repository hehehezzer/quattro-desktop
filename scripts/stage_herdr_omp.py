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


def stage(source: Path, home: Path, skills: Path) -> dict:
    """Copy only public Core artifacts; never inspect account stores/history."""
    source, home, skills = source.resolve(strict=True), home.resolve(strict=True), skills.resolve(strict=True)
    if not skills.is_dir():
        raise ValueError("verified skill catalog directory required")
    payload = {}
    for relative in sorted({item[0] for item in CORE_DEPLOYMENT_MAPPINGS.values()}):
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("Core source must be a regular file")
        name = (Path(relative).relative_to("src") if Path(relative).parts[0] == "src"
                else Path("resources") / relative)
        payload[str(name)] = path.read_bytes()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    root = home / ".local/lib/quattro-herdr-omp" / digest
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("staging destination must not contain symbolic links")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in payload.items():
        target = root / name
        if target.exists():
            if target.is_symlink() or target.read_bytes() != data:
                raise ValueError("existing bundle differs; preserved without overwrite")
        else:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(data)
        target.chmod(0o400)
    manifest = root / "manifest.json"
    manifest_data = (json.dumps({"bundleSha256": digest, "files": hashes}, sort_keys=True) + "\n").encode()
    if manifest.exists():
        if manifest.is_symlink() or manifest.read_bytes() != manifest_data:
            raise ValueError("existing bundle manifest differs; preserved without overwrite")
    else:
        manifest.write_bytes(manifest_data)
    manifest.chmod(0o400)
    wrappers = {}
    for name, arguments in (
            ("quattro-omp", "'launch', 'omp', *sys.argv[1:], " + f"'--skills', {str(skills)!r}"),
            ("quattro-herdr", "'herdr', *sys.argv[1:]")):
        binary = home / ".local/bin" / name
        wrappers[binary] = ("#!/usr/bin/python3\nimport sys\nsys.dont_write_bytecode = True\n"
                           f"sys.path.insert(0, {str(root)!r})\n"
                           "from quattro_agent.cli import main\n"
                           f"sys.argv = [sys.argv[0], {arguments}]\nraise SystemExit(main())\n").encode()
    # Check every destination before changing any launcher.
    for binary, wrapper in wrappers.items():
        if binary.exists() or binary.is_symlink():
            if binary.is_symlink() or binary.read_bytes() != wrapper:
                raise ValueError("existing migration launcher preserved; review update separately")
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
