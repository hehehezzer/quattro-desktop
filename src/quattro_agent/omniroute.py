"""Fail-closed validation for Quattro's canonical Codex transport."""

from __future__ import annotations

import os
import json
import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ConfigError
from .paths import model_catalog_path, omniroute_base_url


APPROVED_PROVIDER_ID = "omniroute"
APPROVED_BASE_URL = omniroute_base_url()
APPROVED_CATALOG = model_catalog_path()
REQUIRED_QUATTRO_ROUTES = (
    "auto",
    "auto/coding:cheap",
    "auto/coding",
    "auto/reasoning",
)
MAX_CATALOG_BYTES = 2_000_000


def _validate_loopback_endpoint(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/api/")
    ):
        raise ConfigError("OmniRoute endpoint must be an HTTP(S) loopback URL without credentials")


@dataclass(frozen=True, slots=True)
class OmniRouteContract:
    provider_id: str
    base_url: str
    wire_api: str
    model_catalog: Path


def validate_model_catalog(path: Path) -> tuple[str, ...]:
    """Validate the one shared Codex picker registry without contacting providers."""
    try:
        if path.stat().st_size > MAX_CATALOG_BYTES:
            raise ConfigError("OmniRoute model catalog exceeds the safe size limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError("OmniRoute model catalog is invalid") from error
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ConfigError("OmniRoute model catalog must contain a models list")
    slugs: list[str] = []
    for model in models:
        slug = model.get("slug") if isinstance(model, dict) else None
        if not isinstance(slug, str) or not slug.strip():
            raise ConfigError("OmniRoute model catalog contains an invalid model entry")
        slugs.append(slug)
    if len(slugs) != len(set(slugs)):
        raise ConfigError("OmniRoute model catalog contains duplicate model routes")
    missing = [route for route in REQUIRED_QUATTRO_ROUTES if route not in slugs]
    if missing:
        raise ConfigError(
            "OmniRoute model catalog is missing required Quattro routes: " + ", ".join(missing)
        )
    return tuple(slugs)


def validate_catalog_parity(source_catalog: Path, active_catalog: Path = APPROVED_CATALOG) -> str | None:
    """Reject a stale runtime catalog when the tracked release source exists.

    Test harnesses and installed-only environments may not contain a checkout;
    those intentionally return ``None`` rather than inventing source state.
    """
    if not source_catalog.is_file():
        return None
    try:
        expected = source_catalog.read_bytes()
        active = active_catalog.read_bytes()
    except OSError as error:
        raise ConfigError("OmniRoute catalog parity cannot be checked") from error
    if hashlib.sha256(expected).digest() != hashlib.sha256(active).digest():
        raise ConfigError(
            "OmniRoute catalog deployment drift: tracked and active catalogs differ; "
            "release the tracked catalog before delegated execution"
        )
    return hashlib.sha256(active).hexdigest()


def _regular_confined_file(path: Path, root: Path, label: str) -> Path:
    if path.is_symlink():
        raise ConfigError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ConfigError(f"{label} escapes its approved root") from error
    if not resolved.is_file():
        raise ConfigError(f"{label} is not a regular file")
    return resolved


def validate_omniroute_contract(
    account_home: str | os.PathLike[str],
    *,
    expected_base_url: str | None = None,
    approved_catalog: Path | None = None,
) -> OmniRouteContract:
    """Validate the effective Codex provider before any child receives context.

    Authentication files are intentionally not opened.  Only the non-secret
    routing configuration and approved shared model catalog are inspected.
    """
    home = Path(account_home).expanduser()
    if home.is_symlink():
        raise ConfigError("Codex account home must not be a symlink")
    try:
        resolved_home = home.resolve(strict=True)
    except OSError as error:
        raise ConfigError("Codex account home is unavailable") from error
    config_path = _regular_confined_file(resolved_home / "config.toml", resolved_home, "Codex config")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError("Codex routing configuration is invalid") from error

    provider_id = config.get("model_provider")
    if provider_id != APPROVED_PROVIDER_ID:
        raise ConfigError(f"Codex must use the approved provider {APPROVED_PROVIDER_ID!r}")
    providers = config.get("model_providers")
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    if not isinstance(provider, dict):
        raise ConfigError("approved OmniRoute provider configuration is missing")
    base_url = provider.get("base_url")
    parsed = urlsplit(base_url) if isinstance(base_url, str) else None
    expected_url = expected_base_url or APPROVED_BASE_URL
    _validate_loopback_endpoint(expected_url)
    expected_catalog = (approved_catalog or APPROVED_CATALOG).resolve(strict=False)
    if (
        parsed is None
        or base_url != expected_url
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("OmniRoute endpoint must be the approved credential-free loopback URL")
    if provider.get("wire_api") != "responses":
        raise ConfigError("OmniRoute must use the Responses wire API")
    if provider.get("requires_openai_auth") is not False:
        raise ConfigError("OmniRoute must not receive native OpenAI authentication")

    catalog_value = config.get("model_catalog_json")
    if not isinstance(catalog_value, str) or not catalog_value:
        raise ConfigError("approved OmniRoute model catalog is required")
    catalog_path = Path(os.path.expandvars(os.path.expanduser(catalog_value)))
    if catalog_path.is_symlink():
        raise ConfigError("OmniRoute model catalog must not be a symlink")
    try:
        catalog = catalog_path.resolve(strict=True)
    except OSError as error:
        raise ConfigError("OmniRoute model catalog is unavailable") from error
    if catalog != expected_catalog or not catalog.is_file():
        raise ConfigError("OmniRoute model catalog is not the approved shared catalog")
    validate_model_catalog(catalog)
    return OmniRouteContract(provider_id, base_url, "responses", catalog)
