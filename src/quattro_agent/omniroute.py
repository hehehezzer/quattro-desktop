"""Fail-closed validation for Quattro's canonical Codex transport."""

from __future__ import annotations

import os
import json
import hashlib
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
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
ROUTING_MODE_ENV = "OMNIROUTE_ROUTING_MODE"
MAX_CAPABILITY_BYTES = 64_000


class OmniRouteRoutingMode(StrEnum):
    """How the gateway is allowed to interpret a Quattro request.

    ``passthrough`` is the authoritative path: Quattro supplies one locked
    target and OmniRoute only transports it. ``legacy`` is an explicit
    migration escape hatch for older clients that still rely on OmniRoute's
    automatic routing engine. The environment variable is intentionally
    process-scoped so the compatibility switch does not become task state.
    """

    PASSTHROUGH = "passthrough"
    LEGACY = "legacy"


def omniroute_routing_mode(value: str | None = None) -> OmniRouteRoutingMode:
    """Return the validated gateway mode, defaulting to Quattro authority."""
    raw = value if value is not None else os.environ.get(ROUTING_MODE_ENV, "passthrough")
    try:
        return OmniRouteRoutingMode(str(raw).strip().lower())
    except ValueError as error:
        raise ConfigError(
            f"{ROUTING_MODE_ENV} must be one of: passthrough, legacy"
        ) from error


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


@dataclass(frozen=True, slots=True)
class OmniRouteRuntimeCapabilities:
    """Security-relevant capabilities reported by the running gateway."""

    routing_mode: str
    locked_target_supported: bool
    receipt_supported: bool
    target_rerouting: bool


def validate_omniroute_runtime_capabilities(
    base_url: str = APPROVED_BASE_URL,
    *,
    timeout_seconds: float = 3.0,
) -> OmniRouteRuntimeCapabilities:
    """Prove that the running gateway supports Quattro-owned passthrough.

    Local configuration is not runtime evidence.  Passthrough therefore fails
    closed when the endpoint is absent, malformed, or advertises any target
    selection authority.  Explicit legacy mode remains the only compatibility
    boundary that skips this check.
    """
    _validate_loopback_endpoint(base_url)
    endpoint = f"{base_url.rstrip('/')}/routing/status"
    request = urllib.request.Request(endpoint, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read(MAX_CAPABILITY_BYTES + 1).decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError,
            UnicodeDecodeError) as error:
        raise ConfigError("OmniRoute passthrough capability handshake failed") from error
    if not isinstance(payload, dict) or len(json.dumps(payload)) > MAX_CAPABILITY_BYTES:
        raise ConfigError("OmniRoute passthrough capability response is invalid")
    capabilities = OmniRouteRuntimeCapabilities(
        routing_mode=str(payload.get("routing_mode", "")),
        locked_target_supported=payload.get("locked_target_supported") is True,
        receipt_supported=payload.get("receipt_supported") is True,
        target_rerouting=payload.get("target_rerouting") is True,
    )
    if capabilities != OmniRouteRuntimeCapabilities(
        routing_mode="passthrough",
        locked_target_supported=True,
        receipt_supported=True,
        target_rerouting=False,
    ):
        raise ConfigError(
            "OmniRoute runtime is incompatible with locked passthrough: expected "
            "routing_mode=passthrough, locked_target_supported=true, "
            "receipt_supported=true, target_rerouting=false"
        )
    return capabilities


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


def catalog_model_metadata(path: Path, slug: str) -> dict[str, object] | None:
    """Return one sanitized local catalog row without contacting a provider."""
    validate_model_catalog(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError("OmniRoute model catalog is invalid") from error
    for row in payload.get("models", []):
        if isinstance(row, dict) and row.get("slug") == slug:
            allowed = {
                "slug", "context_window", "max_context_window",
                "effective_context_window_percent", "input_modalities",
                "shell_type", "tool_mode", "apply_patch_tool_type",
                "supports_search_tool", "experimental_supported_tools",
            }
            return {key: row[key] for key in allowed if key in row}
    return None


def validate_manual_route_requirements(
    path: Path,
    slug: str,
    *,
    required_capabilities: tuple[str, ...],
    estimated_tokens: int,
) -> None:
    """Fail clearly when an explicit model is known to miss a hard requirement.

    Unknown fields remain an OmniRoute interface gap rather than guessed
    incompatibility. Automatic routes are evaluated dynamically by OmniRoute.
    """
    if slug == "auto" or slug.startswith("auto/"):
        return
    metadata = catalog_model_metadata(path, slug)
    if metadata is None:
        raise ConfigError(f"explicit model route is not in the approved catalog: {slug}")
    required = set(required_capabilities)
    modalities = metadata.get("input_modalities")
    if "vision" in required and isinstance(modalities, list) and "image" not in modalities:
        raise ConfigError(f"explicit model route {slug!r} does not support vision input")
    execution_required = bool(required & {
        "repository_read", "repository_write", "shell", "git", "tool_calling",
    })
    if execution_required:
        shell_type = metadata.get("shell_type")
        tool_mode = metadata.get("tool_mode")
        if shell_type == "none" and tool_mode == "none":
            raise ConfigError(f"explicit model route {slug!r} has no verified execution tool contract")
    limits = [
        int(value) for value in (
            metadata.get("context_window"), metadata.get("max_context_window")
        ) if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    if limits:
        practical = min(limits)
        percent = metadata.get("effective_context_window_percent")
        if isinstance(percent, (int, float)) and not isinstance(percent, bool) and 1 <= percent <= 100:
            practical = int(practical * float(percent) / 100)
        if estimated_tokens > practical:
            raise ConfigError(
                f"explicit model route {slug!r} practical context limit {practical} "
                f"is below the estimated requirement {estimated_tokens}"
            )


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
