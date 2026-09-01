"""Deployment profile ownership and legacy migration."""

from .migration import migrate_legacy_manifest
from .profiles import CORE_DEPLOYMENT_MAPPINGS, DESKTOP_DEPLOYMENT_MAPPINGS, DESKTOP_RETIRED_PATHS

__all__ = ["CORE_DEPLOYMENT_MAPPINGS", "DESKTOP_DEPLOYMENT_MAPPINGS", "DESKTOP_RETIRED_PATHS", "migrate_legacy_manifest"]
