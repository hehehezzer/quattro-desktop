#!/usr/bin/env python3
"""Install the incident-fixed pip wheel after verifying its advisory checksum."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request


PIP_VERSION = "26.2.2"
MINIMUM_PIP_VERSION = (26, 2, 2, 4, 0)
PIP_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/3f/06/"
    "3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/"
    "pip-26.2.2-py3-none-any.whl"
)
PIP_WHEEL_SHA256 = "fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
MAX_WHEEL_BYTES = 8 * 1024 * 1024
SUBPROCESS_TIMEOUT_SECONDS = 300


def parse_version(value: str) -> tuple[int, int, int, int, int]:
    match = re.fullmatch(
        r"(\d+)\.(\d+)(?:\.(\d+))?"
        r"(?:(a|b|rc)(\d+))?(?:\.post(\d+))?(?:\.dev(\d+))?"
        r"(?:\+[A-Za-z0-9.]+)?",
        value.strip(),
    )
    if match is None:
        raise ValueError(f"Unrecognized pip version: {value!r}")
    major, minor, patch, prerelease, prerelease_number, post, dev = match.groups()
    release = (int(major), int(minor), int(patch or 0))
    if dev is not None:
        suffix = (0, int(dev))
    elif prerelease is not None:
        suffix = ({"a": 1, "b": 2, "rc": 3}[prerelease], int(prerelease_number))
    elif post is not None:
        suffix = (5, int(post))
    else:
        suffix = (4, 0)
    return release + suffix


def installed_pip_version(python: Path) -> str | None:
    try:
        probe = subprocess.run(
            [str(python), "-I", "-c", "import pip; print(pip.__version__)"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    if probe.returncode != 0:
        return None
    return probe.stdout.strip()


def download_verified_wheel(destination: Path) -> None:
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(PIP_WHEEL_URL, headers={"User-Agent": "quattro-secure-bootstrap/1"})
    try:
        with urllib.request.urlopen(
            request,
            context=ssl.create_default_context(),
            timeout=60,
        ) as response, destination.open("xb") as output:
            while chunk := response.read(64 * 1024):
                total += len(chunk)
                if total > MAX_WHEEL_BYTES:
                    raise ValueError("pip wheel exceeds the expected size bound")
                digest.update(chunk)
                output.write(chunk)
        actual = digest.hexdigest()
        if actual != PIP_WHEEL_SHA256:
            raise ValueError(
                f"pip wheel checksum mismatch: expected {PIP_WHEEL_SHA256}, got {actual}"
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def bootstrap_pip(python: Path) -> str:
    python = python.expanduser().absolute()
    if not python.is_file():
        raise FileNotFoundError(python)
    current = installed_pip_version(python)
    if current is not None and parse_version(current) >= MINIMUM_PIP_VERSION:
        return current

    with tempfile.TemporaryDirectory(prefix="quattro-pip-bootstrap-") as temporary:
        wheel = Path(temporary) / f"pip-{PIP_VERSION}-py3-none-any.whl"
        download_verified_wheel(wheel)
        if current is None:
            subprocess.run(
                [str(python), "-I", "-m", "ensurepip", "--upgrade", "--default-pip"],
                check=True,
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        subprocess.run(
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "--isolated",
                "--disable-pip-version-check",
                "install",
                "--no-index",
                "--no-deps",
                "--upgrade",
                str(wheel),
            ],
            check=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )

    installed = installed_pip_version(python)
    if installed is None or parse_version(installed) < MINIMUM_PIP_VERSION:
        raise RuntimeError(f"pip {PIP_VERSION} bootstrap did not produce a fixed pip installation")
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    version = bootstrap_pip(args.python)
    print(f"pip={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
