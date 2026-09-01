"""Portable filesystem locations used by the Quattro control plane.

All locations are user-scoped by default and can be overridden for tests,
containers, or multiple independent Quattro installations.  The module does
not create anything; callers remain responsible for applying permissions and
atomic-write rules.
"""

from __future__ import annotations

import os
from pathlib import Path


def _home_relative(value: str) -> Path:
    """Expand a user-supplied path without requiring it to exist."""
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve(strict=False)


def _xdg_home(name: str, fallback: str) -> Path:
    value = os.environ.get(name, fallback)
    if not value.strip():
        value = fallback
    return _home_relative(value)


def xdg_config_home() -> Path:
    return _xdg_home("XDG_CONFIG_HOME", "~/.config")


def xdg_state_home() -> Path:
    return _xdg_home("XDG_STATE_HOME", "~/.local/state")


def xdg_data_home() -> Path:
    return _xdg_home("XDG_DATA_HOME", "~/.local/share")


def config_path() -> Path:
    return _home_relative(os.environ.get("QUATTRO_CONFIG", str(xdg_config_home() / "quattro/ai.json")))


def state_root() -> Path:
    return _home_relative(os.environ.get("QUATTRO_STATE_DIR", str(xdg_state_home() / "quattro/agents")))


def data_root() -> Path:
    return _home_relative(os.environ.get("QUATTRO_DATA_DIR", str(xdg_data_home() / "quattro")))


def codex_data_root() -> Path:
    """Return the Quattro-owned parent for account-isolated Codex homes."""
    return _home_relative(
        os.environ.get("QUATTRO_CODEX_DATA_DIR", str(xdg_data_home() / "quattro-ai/codex"))
    )


def codex_account_root() -> Path:
    override = os.environ.get("QUATTRO_CODEX_HOME_ROOT")
    return _home_relative(override) if override else codex_data_root() / "accounts"


def model_catalog_path() -> Path:
    override = os.environ.get("QUATTRO_MODEL_CATALOG")
    return _home_relative(override) if override else codex_data_root() / "omniroute-model-catalog.json"


def omniroute_base_url() -> str:
    """Return the configured local OmniRoute endpoint.

    Endpoint validation still rejects credentials, query strings, fragments,
    and non-loopback hosts.  This value only supplies the expected URL; it does
    not grant network access.
    """
    return os.environ.get("QUATTRO_OMNIROUTE_BASE_URL", "http://localhost:20128/api/v1").strip()


def omniroute_dashboard_url() -> str:
    base = omniroute_base_url().rstrip("/")
    return base.removesuffix("/api/v1") + "/dashboard"


def default_workspace() -> Path:
    """Choose a portable workspace without assuming a maintainer directory."""
    value = os.environ.get("QUATTRO_WORKSPACE")
    return _home_relative(value) if value else Path.cwd().resolve()
