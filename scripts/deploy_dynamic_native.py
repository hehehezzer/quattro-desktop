#!/usr/bin/env python3
"""Install dynamic native helpers without changing reviewed scoped-Pi packages.

Preview is the default. Existing command paths and extension registration are
retained; no settings, policy pins, credentials or running processes are touched.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import deque

OVERRIDES = (
    "decision_taxonomy.py", "decision_checkpoint.py", "jev.py", "jev_worker.py", "decision_service.py",
    "native_intelligence.py", "native_cli.py", "jev_shadow.py",
    "operational_advice.py", "operational_native.py",
    "shared_intelligence.py", "decision_mcp.py", "turn_gate.py", "turn_routing.py",
    "routing_signals.py", "runtime_milestones.py", "recovering_test.py",
)


def safe_path(path: Path) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("deployment paths must not be symlinks")


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    safe_path(path)
    descriptor, name = tempfile.mkstemp(prefix=".dynamic-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def native_closure(candidates: dict[Path, bytes]) -> dict[Path, bytes]:
    """Static intra-Quattro imports, including lazy imports, plus package parents."""
    modules = {}
    for path in candidates:
        if path.suffix == ".py":
            parts = path.with_suffix("").parts
            modules[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    # The decision session launches this file as a subprocess; import analysis
    # alone cannot discover that runtime dependency.
    queue = deque(["quattro_agent.shared_intelligence", "quattro_intelligence_mcp",
                   "quattro_agent.jev_worker", "quattro_agent.native_cli"])
    included = {}
    while queue:
        name = queue.popleft()
        path = modules.get(name)
        if path is None or path in included:
            continue
        included[path] = candidates[path]
        parts = name.split(".")
        queue.extend(".".join(parts[:end]) for end in range(1, len(parts)))
        package = parts if path.name == "__init__.py" else parts[:-1]
        for node in ast.walk(ast.parse(candidates[path], filename=str(path))):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names if alias.name in modules)
            elif isinstance(node, ast.ImportFrom):
                base = (".".join(package[:len(package) - node.level + 1])
                        if node.level else "")
                imported = ".".join(part for part in (base, node.module) if part)
                if imported in modules:
                    queue.append(imported)
                queue.extend(imported + "." + alias.name for alias in node.names
                             if imported + "." + alias.name in modules)
    for path, data in candidates.items():
        if path.suffix != ".py" and path.parts[0] == "quattro_agent":
            included[path] = data
    return included


def verify_imports(version: Path, home: Path) -> None:
    program = (
        "import sys; from pathlib import Path; root=Path(sys.argv[1]); "
        "sys.path.insert(0,str(root)); "
        "import quattro_agent.shared_intelligence, quattro_intelligence_mcp, "
        "quattro_agent.jev_worker, quattro_agent.native_cli; "
        "assert all(Path(module.__file__).resolve().is_relative_to(root) "
        "for name,module in sys.modules.items() "
        "if name.startswith('quattro') and getattr(module,'__file__',None))"
    )
    result = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(version)],
                            env={"HOME": str(home), "PATH": os.defpath},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=10, check=False)
    if result.returncode:
        raise ValueError("native bundle dependency verification failed")
    # Exercise the actual standalone launch with a synthetic key and no
    # decision. EOF after setup closes the client without a provider request.
    worker = subprocess.run(
        [sys.executable, "-B", str(version / "quattro_agent/jev_worker.py"), "--session"],
        input=b'{"key":"synthetic-test-key","timeout_seconds":0.1}\n',
        env={}, cwd=version / "quattro_agent",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
    )
    if worker.returncode or worker.stdout or worker.stderr:
        raise ValueError("native worker dependency verification failed")


def deploy(source: Path, home: Path, *, apply: bool = False) -> dict:
    source, home = source.resolve(strict=True), home.resolve(strict=True)
    installed = home / ".local/bin/quattro_agent"
    target_root = home / ".local/lib/quattro-dynamic-native"
    destinations = [home / ".local/bin/quattro-intelligence",
                    home / ".local/bin/quattro-intelligence-mcp",
                    home / ".pi/agent/extensions/quattro-intelligence.ts"]
    receipt = target_root / "current.json"
    for path in (installed, target_root, target_root / "versions", receipt, *destinations):
        safe_path(path)
    if receipt.exists() and not receipt.is_file():
        raise ValueError("native receipt must be a regular file")
    if not installed.is_dir() or any(not path.is_file() for path in destinations):
        raise ValueError("existing native installation required")
    contents = {}
    # Preserve installed retrieval/metadata hardening. Do not import or mutate
    # the separately reviewed scoped authority into this native-only bundle.
    for path in installed.rglob("*"):
        relative = path.relative_to(installed)
        if (not path.is_file() or path.is_symlink() or "__pycache__" in relative.parts
                or path.name.startswith("scoped")):
            continue
        contents[Path("quattro_agent") / relative] = path.read_bytes()
    for name in OVERRIDES:
        contents[Path("quattro_agent") / name] = (source / "src/quattro_agent" / name).read_bytes()
    contents[Path("quattro_intelligence_mcp.py")] = (source / "src/quattro_intelligence_mcp.py").read_bytes()
    # Pin the native dependency closure rather than silently relying on the
    # mutable original installation through the wrapper's import search path.
    for path in (installed.parent / "quattro").rglob("*.py"):
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
            contents[Path("quattro") / path.relative_to(installed.parent / "quattro")] = path.read_bytes()
    for path in installed.parent.glob("quattro_*.py"):
        if path.is_file() and not path.is_symlink() and path.name != "quattro_intelligence_mcp.py":
            contents[Path(path.name)] = path.read_bytes()
    contents = native_closure(contents)
    hashes = {str(path): hashlib.sha256(data).hexdigest() for path, data in sorted(contents.items())}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    version = target_root / "versions" / digest
    safe_path(version)
    prefix = ("#!/usr/bin/python3\nimport sys\nsys.dont_write_bytecode = True\n"
              "sys.path.insert(0, " + repr(str(version)) + ")\n")
    updates = {
        destinations[0]: (prefix + "from quattro_agent.shared_intelligence import cli_main\nraise SystemExit(cli_main())\n").encode(),
        destinations[1]: (prefix + "from quattro_intelligence_mcp import main\nraise SystemExit(main())\n").encode(),
        destinations[2]: (source / "adapters/pi/quattro-intelligence.ts").read_bytes(),
    }
    report = {"bundle_sha256": digest, "bundle": str(version), "members": len(contents),
              "scope": "ordinary_native_helpers_only", "scoped_authorities_changed": False,
              "settings_changed": False, "sessions_restarted": False,
              "updates": [{"path": str(path), "before_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "after_sha256": hashlib.sha256(data).hexdigest()} for path, data in updates.items()],
              "applied": False}
    if not apply:
        return report
    target_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    (target_root / "versions").mkdir(mode=0o700, exist_ok=True)
    if version.exists():
        safe_path(version)
        inventory = list(version.rglob("*"))
        if (any(path.is_symlink() or not (stat.S_ISREG(path.stat().st_mode) or path.is_dir()) for path in inventory)
                or {path.relative_to(version) for path in inventory if path.is_file()} != set(contents)
                or any(not (version / path).is_file() or (version / path).read_bytes() != data for path, data in contents.items())):
            raise ValueError("existing native bundle does not match its digest")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=".stage-", dir=target_root / "versions"))
        try:
            for path, data in contents.items():
                output = temporary / path
                output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                output.write_bytes(data)
            temporary.rename(version)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    verify_imports(version, home)
    report["dependency_imports_verified"] = True
    backup = Path(tempfile.mkdtemp(prefix="backup-", dir=target_root))
    originals = {path: (path.read_bytes(), path.stat().st_mode & 0o777) for path in updates}
    previous_receipt = (receipt.read_bytes(), receipt.stat().st_mode & 0o777) if receipt.exists() else None
    for index, path in enumerate(updates):
        shutil.copy2(path, backup / str(index))
    (backup / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        for path, data in updates.items():
            atomic_write(path, data, originals[path][1])
        if any(path.read_bytes() != data for path, data in updates.items()):
            raise ValueError("native deployment verification failed")
        report.update(applied=True, backup=str(backup), hashes_verified=True)
        atomic_write(receipt, (json.dumps(dict(report, hashes=hashes), indent=2) + "\n").encode(), 0o600)
    except Exception:
        for path, (data, mode) in originals.items():
            atomic_write(path, data, mode)
        if previous_receipt is not None:
            atomic_write(receipt, *previous_receipt)
        else:
            receipt.unlink(missing_ok=True)
        raise
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    print(json.dumps(deploy(Path(__file__).resolve().parents[1], args.home, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
