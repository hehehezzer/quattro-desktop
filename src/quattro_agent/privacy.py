"""Boundaries for data that may be projected to Quickshell or status JSON."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import PrivacyError


_SENSITIVE_KEY = re.compile(
    r"(?:^|[_-])(?:prompt|response|environment|env|credential|credentials|secret|"
    r"token|password|authorization|cookie|oauth|auth_json|private_key|recovery_code)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TITLE_ATTACHMENT = re.compile(
    r"(?:<image\b[^>]*>|\[image\s*#?\d+\])", re.IGNORECASE
)
_TITLE_MARKUP = re.compile(r"^(?:#{1,6}|>|[-*+]\s|\d+[.)]\s)+")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\b(?:authorization|password|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|client[_-]?secret)\s*[:=]\s*(?:bearer\s+)?[^\s]+"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

MAX_DISPLAY_DEPTH = 6
MAX_DISPLAY_ITEMS = 100
MAX_DISPLAY_STRING = 2_000
MAX_DISPLAY_JSON_BYTES = 32_768


def redact_secret_text(value: str) -> tuple[str, bool]:
    """Remove credential-shaped values from untrusted autonomous text."""
    result = value
    for pattern in _SECRET_VALUE_PATTERNS:
        result = pattern.sub("[REDACTED BY QUATTRO]", result)
    return result, result != value


def summarize_display_title(
    value: str, *, fallback: str, maximum: int = 88
) -> str:
    """Create a compact, secret-redacted label from a task's first prompt.

    This is deliberately deterministic and local. It never sends prompt text to
    another model, and it retains the opaque task/session ids for internal use.
    """
    if maximum < 16:
        raise ValueError("title maximum must be at least 16 characters")
    safe, _redacted = redact_secret_text(value if isinstance(value, str) else "")
    safe = _TITLE_ATTACHMENT.sub(" ", safe)
    candidates: list[str] = []
    fenced = False
    for raw_line in safe.replace("\r", "\n").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not line:
            continue
        line = _TITLE_MARKUP.sub("", line).strip(" \t\"'`")
        if line:
            candidates.append(line)
    title = " ".join(candidates[:2]) if candidates else fallback
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        title = fallback
    if len(title) > maximum:
        cut = title.rfind(" ", 0, maximum - 1)
        if cut < maximum // 2:
            cut = maximum - 1
        title = title[:cut].rstrip(" ,;:-") + "…"
    return display_text(title, field="display_title", maximum=maximum)


def _is_sensitive_key(key: str) -> bool:
    if _SENSITIVE_KEY.search(key):
        return True
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return (
        compact.startswith(("prompt", "response", "environment"))
        or compact in {"env", "cookie", "authorization"}
        or compact.endswith((
            "accesstoken", "refreshtoken", "apitoken", "oauth", "oauthtoken",
            "password", "secret", "credential", "credentials", "privatekey",
            "recoverycode", "authjson",
        ))
    )


def display_text(value: str, *, field: str = "text", maximum: int = MAX_DISPLAY_STRING) -> str:
    """Validate a bounded human-readable string for a display-safe surface."""
    if not isinstance(value, str):
        raise PrivacyError(f"{field} must be a string")
    if len(value) > maximum:
        raise PrivacyError(f"{field} exceeds {maximum} characters")
    if _CONTROL.search(value):
        raise PrivacyError(f"{field} contains control characters")
    return value


def _validate(value: Any, path: str, depth: int) -> None:
    if depth > MAX_DISPLAY_DEPTH:
        raise PrivacyError(f"{path} exceeds the display-safe nesting limit")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        display_text(value, field=path)
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_DISPLAY_ITEMS:
            raise PrivacyError(f"{path} contains too many fields")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                raise PrivacyError(f"{path} contains an invalid field name")
            if _is_sensitive_key(key):
                raise PrivacyError(f"{path}.{key} is private and cannot be displayed")
            _validate(item, f"{path}.{key}", depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        if len(value) > MAX_DISPLAY_ITEMS:
            raise PrivacyError(f"{path} contains too many items")
        for index, item in enumerate(value):
            _validate(item, f"{path}[{index}]", depth + 1)
        return
    raise PrivacyError(f"{path} contains unsupported display data: {type(value).__name__}")


def display_json(value: Mapping[str, Any] | None) -> str:
    """Return canonical JSON after rejecting private keys and unbounded values."""
    candidate: Mapping[str, Any] = value or {}
    _validate(candidate, "$", 0)
    encoded = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_DISPLAY_JSON_BYTES:
        raise PrivacyError("display-safe JSON exceeds the byte limit")
    return encoded


def private_json(value: Mapping[str, Any] | None) -> str:
    """Serialize task-private JSON without exposing it through projections.

    Private payloads are still bounded to prevent accidental state-file abuse.
    They are never returned by display projection methods.
    """
    candidate = value or {}
    if not isinstance(candidate, Mapping):
        raise PrivacyError("private payload must be a mapping")
    encoded = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > 1_048_576:
        raise PrivacyError("private payload exceeds 1 MiB")
    return encoded


def decode_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise PrivacyError("stored JSON payload is not an object")
    return decoded
