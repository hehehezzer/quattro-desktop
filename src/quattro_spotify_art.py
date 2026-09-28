#!/usr/bin/env python3
"""Fetch Spotify cover art into a small local cache for Quickshell.

Qt's network image loader can crash in the host OpenSSL backend. Only Spotify's
image CDN is accepted here; the QML Image component receives a local file URI.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
IMAGE_PATH = re.compile(r"/image/([0-9a-f]{20,128})\Z")


def cache_path(url: str, home: Path) -> Path | None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "i.scdn.co" or parsed.query or parsed.fragment:
        return None
    match = IMAGE_PATH.fullmatch(parsed.path)
    if not match:
        return None
    return home / ".cache" / "quattro" / "spotify-art" / f"{match.group(1)}.jpg"


def fetch(url: str, home: Path) -> str:
    target = cache_path(url, home)
    if target is None:
        return ""
    if target.is_file() and 0 < target.stat().st_size <= MAX_BYTES:
        return target.as_uri()

    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "QuattroDesktop/1.0"})
    temp_name = ""
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.geturl() != url:
                return ""
            if not response.headers.get("Content-Type", "").lower().startswith("image/jpeg"):
                return ""
            data = response.read(MAX_BYTES + 1)
        if not data.startswith(b"\xff\xd8\xff") or len(data) > MAX_BYTES:
            return ""
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".art-", delete=False) as temp:
            temp_name = temp.name
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, target)
        return target.as_uri()
    except (OSError, ValueError, urllib.error.URLError):
        return ""
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    print(fetch(sys.argv[1] if len(sys.argv) == 2 else "", Path.home()))
