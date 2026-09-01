"""Cross-platform advisory file locking."""
from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, TextIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

LockStream = BinaryIO | TextIO


def _lock(stream: LockStream) -> None:
    if sys.platform == "win32":
        stream.seek(0)
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write("0" if "b" not in getattr(stream, "mode", "") else b"0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _unlock(stream: LockStream) -> None:
    if sys.platform == "win32":
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def lock_stream(stream: LockStream) -> None:
    """Acquire an exclusive lock released automatically when the stream closes."""
    _lock(stream)


def lock_file_descriptor(descriptor: int) -> None:
    """Acquire an exclusive lock on an open descriptor until it is closed."""
    if sys.platform == "win32":
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_EX)


@contextlib.contextmanager
def locked_stream(stream: LockStream) -> Iterator[LockStream]:
    _lock(stream)
    try:
        yield stream
    finally:
        _unlock(stream)


@contextlib.contextmanager
def exclusive_lock(path: Path, mode: int = 0o600) -> Iterator[LockStream]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, mode)
    with os.fdopen(descriptor, "r+") as stream, locked_stream(stream):
        yield stream
