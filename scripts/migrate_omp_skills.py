#!/usr/bin/env python3
"""Preserve explicit skill roots and stage them for OMP customDirectories.

Only immediate directories containing SKILL.md are inventoried. Give nested
catalogs (for example Codex .system) their own --root. Evidence is private and
must stay outside the repository. No native account files are read. Originals
remain untouched. Source labels namespace collisions; OMP's name frontmatter
is adjusted only in staged copies, with the original retained beside it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil


FORBIDDEN = {"auth.json", "auth.db", "credentials.json", ".env", "sessions", "history", "prompts", "responses"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def skill_files(directory: Path) -> list[Path]:
    """Fail closed for links, credential names and nonregular entries."""
    files = []
    for current, directories, names in os.walk(directory, followlinks=False):
        parent = Path(current)
        directories[:] = [name for name in directories if name not in {"__pycache__", ".git"}]
        for name in directories + names:
            path = parent / name
            if name.lower() in FORBIDDEN or path.is_symlink():
                raise ValueError(f"unsafe skill entry: {path}")
        for name in names:
            path = parent / name
            if not path.is_file():
                raise ValueError(f"nonregular skill entry: {path}")
            files.append(path)
    return sorted(files)


def invocation_name(directory: Path) -> str:
    text = (directory / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---\n"):
        match = re.search(r"^name:\s*([^\n]+)$", text.split("---", 2)[1], re.MULTILINE)
        if match:
            return match.group(1).strip().strip("\"'")
    return directory.name


def renamed_skill(text: str, name: str) -> str:
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise ValueError("OMP custom-directory skills require YAML frontmatter")
    boundary = text.index("\n---", 4)
    header = text[4:boundary]
    if not re.search(r"^description:\s*\S", header, re.MULTILINE):
        raise ValueError("OMP custom-directory skill needs description")
    if re.search(r"^name:", header, re.MULTILINE):
        header = re.sub(r"^name:.*$", f"name: {name}", header, flags=re.MULTILINE)
    else:
        header = f"name: {name}\n" + header
    return "---\n" + header + text[boundary:]


def migrate(roots: dict[str, Path], evidence: Path, stage: Path | None = None) -> dict:
    if evidence.exists() or (stage is not None and stage.exists()):
        raise ValueError("use fresh evidence/staging directories; never overwrite")
    entries = []
    for label, root in roots.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", label):
            raise ValueError("root labels must be lowercase letters, digits and hyphens")
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"invalid skill root: {root}")
        for directory in sorted(root.iterdir()):
            if directory.is_dir() and (directory / "SKILL.md").is_file():
                if directory.is_symlink():
                    raise ValueError(f"linked skill directory: {directory}")
                files = skill_files(directory)
                entries.append({"label": label, "source": str(directory.resolve()),
                                "name": invocation_name(directory),
                                "files": {str(p.relative_to(directory)): digest(p) for p in files}})
    names: dict[str, int] = {}
    for entry in entries:
        names[entry["name"]] = names.get(entry["name"], 0) + 1
    destinations = set()
    for entry in entries:
        name = entry["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError(f"unsupported skill name: {name}")
        alias = f'{entry["label"]}-{name}' if names[name] > 1 else name
        if alias in destinations:
            raise ValueError(f"duplicate migration alias: {alias}")
        destinations.add(alias)
        entry["omp_name"] = alias
        # Preflight every loader before creating any evidence or copies.
        renamed_skill((Path(entry["source"]) / "SKILL.md").read_text(encoding="utf-8"), alias)
    evidence.mkdir(parents=True, mode=0o700)
    evidence.chmod(0o700)
    if stage is not None:
        stage.mkdir(parents=True, mode=0o700)
        stage.chmod(0o700)
    for entry in entries:
        source = Path(entry["source"])
        backup = evidence / "backup" / entry["label"] / source.name
        shutil.copytree(source, backup, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        entry["backup"] = str(backup)
        if stage is not None:
            destination = stage / entry["omp_name"]
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", ".git"))
            original = destination / "SKILL.md"
            if invocation_name(source) != entry["omp_name"]:
                if (destination / "SKILL.original.md").exists():
                    raise ValueError("reserved SKILL.original.md already exists")
                shutil.copy2(original, destination / "SKILL.original.md")
                original.write_text(renamed_skill(original.read_text(encoding="utf-8"), entry["omp_name"]), encoding="utf-8")
            entry["staged"] = str(destination)
            entry["staged_loader_sha256"] = digest(original)
    manifest = {"version": 1, "roots": {k: str(v.resolve()) for k, v in roots.items()}, "skills": entries}
    path = evidence / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    errors = verify(manifest)
    if errors:
        raise ValueError("parity failed: " + "; ".join(errors))
    return manifest


def verify(manifest: dict) -> list[str]:
    errors = []
    for entry in manifest["skills"]:
        expected_files = set(entry["files"])
        for field in ["source", "backup", "staged"]:
            if field not in entry:
                continue
            directory = Path(entry[field])
            try:
                actual_files = {str(p.relative_to(directory)) for p in skill_files(directory)}
                if field == "staged" and "SKILL.original.md" in actual_files:
                    actual_files.remove("SKILL.original.md")
                if actual_files != expected_files:
                    errors.append(f"file inventory changed: {directory}")
            except (OSError, ValueError) as error:
                errors.append(str(error))
        for relative, expected in entry["files"].items():
            targets = [Path(entry["source"]) / relative, Path(entry["backup"]) / relative]
            if "staged" in entry:
                staged = Path(entry["staged"])
                if relative == "SKILL.md" and (staged / "SKILL.original.md").exists():
                    targets.append(staged / "SKILL.original.md")
                else:
                    targets.append(staged / relative)
            for path in targets:
                if not path.is_file() or path.is_symlink() or digest(path) != expected:
                    errors.append(f"content changed: {path}")
        if "staged" in entry:
            loader = Path(entry["staged"]) / "SKILL.md"
            if not loader.is_file() or loader.is_symlink() or digest(loader) != entry["staged_loader_sha256"]:
                errors.append(f"loader changed: {loader}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--verify", type=Path, help="private manifest.json")
    args = parser.parse_args()
    try:
        if args.verify:
            errors = verify(json.loads(args.verify.read_text(encoding="utf-8")))
            print(json.dumps({"parity": not errors, "errors": errors}))
            return int(bool(errors))
        if not args.evidence or not args.root:
            parser.error("--root and --evidence required for migration")
        pairs = [value.split("=", 1) for value in args.root]
        if any(len(pair) != 2 for pair in pairs) or len({p[0] for p in pairs}) != len(pairs):
            raise ValueError("roots require unique LABEL=PATH values")
        manifest = migrate({label: Path(path).expanduser() for label, path in pairs}, args.evidence, args.stage)
        print(json.dumps({"skills": len(manifest["skills"]), "files": sum(len(s["files"]) for s in manifest["skills"]), "parity": True}))
        return 0
    except (OSError, ValueError) as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
