#!/usr/bin/env python3
"""Emit one bounded clipboard entry for the shell's wl-paste watcher."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

LIMIT = 16 * 1024 * 1024
payload = sys.stdin.buffer.read(LIMIT + 1)
if not payload or len(payload) > LIMIT or os.environ.get("CLIPBOARD_STATE") == "sensitive":
    raise SystemExit(0)
kind = sys.argv[1] if len(sys.argv) == 2 else ""
if kind == "text":
    try:
        entry = {"type": "text", "text": payload.decode("utf-8")}
    except UnicodeDecodeError:
        raise SystemExit(0)
elif kind == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
    directory = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "quickshell/clipboard-images"
    if any(part.is_symlink() for part in (directory, *directory.parents)):
        raise SystemExit("Refusing symbolic-link clipboard storage")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / (hashlib.sha256(payload).hexdigest() + ".png")
    if not target.exists():
        descriptor, temporary = tempfile.mkstemp(prefix=".capture-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    entry = {"type": "image", "mime": "image/png", "path": str(target)}
else:
    raise SystemExit(0)
print(json.dumps(entry))
