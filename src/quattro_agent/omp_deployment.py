"""Verify a reviewed OMP SDK dependency closure before launching native code.

This verifies installation metadata only. It never opens native account stores,
grants execution permission, or treats a mutable manifest as its own authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_MANIFEST = 8 * 1024 * 1024
MAX_FILES = 40_000
MAX_FILE = 256 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}")


def _canonical(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path.resolve(strict=True) != path:
        raise ValueError("canonical reviewed OMP path required")
    return path


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink, info.st_uid)


def _read(path: Path, limit: int, *, content=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid != os.getuid() or before.st_mode & (0o022 | stat.S_ISUID | stat.S_ISGID)
                or before.st_size > limit):
            raise ValueError("owned regular bounded OMP artifact required")
        digest, chunks, size = hashlib.sha256(), [], 0
        while chunk := os.read(descriptor, min(1024 * 1024, limit + 1 - size)):
            size += len(chunk)
            if size > limit:
                raise ValueError("OMP artifact bound exceeded")
            digest.update(chunk)
            if content:
                chunks.append(chunk)
        if (_signature(before) != _signature(os.fstat(descriptor))
                or _signature(before) != _signature(path.stat(follow_symlinks=False))):
            raise ValueError("OMP artifact changed during verification")
        return digest.hexdigest(), b"".join(chunks), size
    finally:
        os.close(descriptor)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate OMP manifest key")
        result[key] = value
    return result


def _relative(value):
    if (not isinstance(value, str) or not value or "\0" in value
            or Path(value).is_absolute() or any(part in {".", ".."} for part in value.split("/"))):
        raise ValueError("closed OMP manifest relative path required")
    return value


def review_omp_runtime(bun: Path, package_root: Path, closure_root: Path) -> dict:
    """Build a review artifact, not an execution grant or automatic activation."""
    bun, package_root, root = map(_canonical, (bun, package_root, closure_root))
    if not package_root.is_relative_to(root) or not root.is_dir():
        raise ValueError("OMP SDK must be inside its reviewed dependency closure")
    files, links, total = {}, {}, 0
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in (*directories, *names):
            path = Path(directory) / name
            relative, info = str(path.relative_to(root)), path.lstat()
            _relative(relative)
            if info.st_uid != os.getuid():
                raise ValueError("owned OMP dependency required")
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    raise ValueError("OMP dependency link escapes its closure")
                links[relative] = target
            elif stat.S_ISREG(info.st_mode):
                digest, _, size = _read(path, MAX_FILE)
                files[relative], total = digest, total + size
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError("special OMP dependency forbidden")
            elif info.st_mode & 0o022:
                raise ValueError("writable shared OMP dependency directory forbidden")
            if len(files) + len(links) > MAX_FILES or total > MAX_TOTAL:
                raise ValueError("OMP dependency closure bound exceeded")
    digest, _, _ = _read(bun, MAX_FILE)
    return {"version": 1, "bun": {"path": str(bun), "sha256": digest},
            "packageRoot": str(package_root), "closureRoot": str(root),
            "files": files, "symlinks": links}


def verify_omp_runtime(manifest: Path, bun: Path, package_root: Path, *, expected_digest: str) -> None:
    """Reject changed/extra dependencies against the caller's reviewed digest."""
    if not isinstance(expected_digest, str) or not _SHA.fullmatch(expected_digest):
        raise ValueError("explicit reviewed OMP manifest digest required")
    manifest, bun, package_root = map(_canonical, (manifest, bun, package_root))
    digest, raw, _ = _read(manifest, MAX_MANIFEST, content=True)
    if digest != expected_digest:
        raise ValueError("reviewed OMP manifest changed")
    data = json.loads(raw, object_pairs_hook=_object)
    if (not isinstance(data, dict) or set(data) != {"version", "bun", "packageRoot", "closureRoot", "files", "symlinks"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["bun"], dict) or set(data["bun"]) != {"path", "sha256"}
            or data["bun"]["path"] != str(bun)
            or data["packageRoot"] != str(package_root)
            or not isinstance(data["closureRoot"], str)
            or not isinstance(data["files"], dict) or not isinstance(data["symlinks"], dict)):
        raise ValueError("closed reviewed OMP manifest required")
    if not isinstance(data["bun"]["sha256"], str) or not _SHA.fullmatch(data["bun"]["sha256"]):
        raise ValueError("reviewed Bun digest required")
    for name, value in data["files"].items():
        _relative(name)
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise ValueError("reviewed dependency digest required")
    for name, value in data["symlinks"].items():
        _relative(name)
        if not isinstance(value, str) or "\0" in value:
            raise ValueError("reviewed dependency link required")
    if review_omp_runtime(bun, package_root, Path(data["closureRoot"])) != data:
        raise ValueError("reviewed OMP installation changed")
    _, metadata, _ = _read(package_root / "package.json", 1024 * 1024, content=True)
    package = json.loads(metadata, object_pairs_hook=_object)
    if (not isinstance(package, dict) or package.get("name") != "@oh-my-pi/pi-coding-agent"
            or package.get("version") != "18.6.3"):
        raise ValueError("reviewed official OMP SDK version required")
