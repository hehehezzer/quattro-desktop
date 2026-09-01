#!/usr/bin/env python3
"""Small standard-library Python hygiene gate for environments without Ruff."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def check(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        return [f"{path}: {error}"]
    for number, line in enumerate(source.splitlines(), 1):
        if line.rstrip() != line:
            findings.append(f"{path}:{number}: trailing whitespace")
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name) and function.id in {"eval", "exec"}:
                findings.append(f"{path}:{node.lineno}: dynamic code execution is forbidden")
            if isinstance(function, ast.Attribute) and function.attr == "system":
                findings.append(f"{path}:{node.lineno}: os.system is forbidden")
            if any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            ):
                findings.append(f"{path}:{node.lineno}: shell=True is forbidden")
    return findings


def main() -> int:
    roots = (Path("src"), Path("scripts"), Path("tests"))
    findings = [finding for root in roots for path in root.rglob("*.py") for finding in check(path)]
    if findings:
        print("Python hygiene: FAIL", file=sys.stderr)
        print("\n".join(f"- {finding}" for finding in findings), file=sys.stderr)
        return 1
    print("Python hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
