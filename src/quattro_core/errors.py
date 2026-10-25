"""Explicit caller/domain rejections, separate from unexpected runtime failures."""
from __future__ import annotations

from typing import Any


class InvalidRequestError(ValueError):
    """Caller input failed a trusted validation guard."""


class PermissionDeniedError(PermissionError):
    """Configured authority does not permit the requested operation."""


class MemoryNotFoundError(KeyError):
    """An absent or inaccessible memory, without disclosing which."""


class MemoryConflictError(ValueError):
    """A rejected transition with safe, authorized identifiers, never content."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class OperationUnavailableError(RuntimeError):
    """An infrastructure failure, regardless of the underlying exception type."""
