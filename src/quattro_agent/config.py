"""Strict, versioned validation and migration for Quattro ``ai.json``."""

from __future__ import annotations

import copy
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .errors import ConfigError
from .paths import codex_account_root


CURRENT_AI_CONFIG_VERSION = 3
MINIMUM_AI_CONFIG_VERSION = 1

_ACCOUNT_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_TOP_LEVEL = {
    "schemaVersion", "defaultAgent", "defaultCodexAccount", "defaultPolicyProfile",
    "fullAccessRequiresConfirmation", "deprecated",
    "accounts", "usageRefresh", "crossDeviceSync", "crashCapture", "dictation",
    "memory", "prReview", "delegation", "workspace",
    "cooperation", "routing",
}
_DEFAULT_POLICY_PROFILES = {
    "audit-read-only",
    "review-untrusted",
    "workspace-write",
    "desktop-config-write",
    "publication-capable",
}


def _fail(path: str, message: str) -> "NoReturn":
    raise ConfigError(f"{path}: {message}")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _mapping(value: Any, path: str, allowed: set[str], required: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    result = dict(value)
    unknown = sorted(set(result) - allowed)
    if unknown:
        _fail(path, f"unknown fields: {', '.join(unknown)}")
    missing = sorted((required or allowed) - set(result))
    if missing:
        _fail(path, f"missing fields: {', '.join(missing)}")
    return result


def _bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        _fail(path, "must be a boolean")
    return value


def _string(value: Any, path: str, *, nullable: bool = False, maximum: int = 4_096) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        _fail(path, f"must be a non-empty string up to {maximum} characters")
    return value


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(path, f"must be an integer between {minimum} and {maximum}")
    return value


def _enum(value: Any, path: str, allowed: set[str]) -> str:
    if value not in allowed:
        _fail(path, f"must be one of: {', '.join(sorted(allowed))}")
    return value


def _migrate_v1_to_v2(source: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(source)
    result["schemaVersion"] = 2
    memory = result.setdefault("memory", {})
    if isinstance(memory, dict):
        memory.setdefault("projectVaultPath", "~/.local/share/quattro/memory/projects")
    result.setdefault("prReview", {
        "runtime": "codex",
        "codexAccount": result.get("defaultCodexAccount", "account-1"),
        "githubAccount": None,
        "defaultRepository": None,
        "reviewMode": "comment",
        "automaticPublication": False,
        "maximumDepth": "full",
        "runTests": True,
        "securityScanning": True,
        "commentBehavior": "summary",
        "severityThreshold": "LOW",
        "model": None,
        "timeoutSeconds": 1_800,
        "maxFiles": 500,
        "maxDiffBytes": 5_000_000,
    })
    return result


def _migrate_v2_to_v3(source: dict[str, Any]) -> dict[str, Any]:
    """Remove global full access and retain only non-operative migration history."""
    result = copy.deepcopy(source)
    legacy_full_access = result.pop("codexFullAccess", False)
    result["schemaVersion"] = 3
    result["defaultPolicyProfile"] = "workspace-write"
    result["fullAccessRequiresConfirmation"] = True
    result["deprecated"] = {
        "legacyCodexFullAccess": {
            "removed": True,
            "previouslyEnabled": legacy_full_access is True,
        }
    }
    return result


_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
}


def migrate_ai_config(source: Mapping[str, Any], target_version: int = CURRENT_AI_CONFIG_VERSION) -> dict[str, Any]:
    """Return a migrated copy; never mutates the caller's mapping."""
    if not isinstance(source, Mapping):
        raise ConfigError("configuration root must be an object")
    result = copy.deepcopy(dict(source))
    version = result.get("schemaVersion")
    if type(version) is not int:
        raise ConfigError("schemaVersion must be an integer")
    if version < MINIMUM_AI_CONFIG_VERSION or version > CURRENT_AI_CONFIG_VERSION:
        raise ConfigError(f"unsupported schemaVersion: {version}")
    if target_version < version or target_version > CURRENT_AI_CONFIG_VERSION:
        raise ConfigError(f"unsupported migration target: {target_version}")
    while version < target_version:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            raise ConfigError(f"no migration from schemaVersion {version}")
        result = migration(result)
        version = result.get("schemaVersion")
    return result


def validate_ai_config(source: Mapping[str, Any], *, home: Path | None = None) -> dict[str, Any]:
    """Strictly validate schema v3 and return a defensive normalized copy."""
    root = _mapping(
        source, "$", _TOP_LEVEL,
        required=_TOP_LEVEL - {"deprecated", "delegation", "workspace", "cooperation", "routing"},
    )
    if root["schemaVersion"] != CURRENT_AI_CONFIG_VERSION:
        _fail("$.schemaVersion", f"must be {CURRENT_AI_CONFIG_VERSION}; migrate first")
    default_agent = _enum(root["defaultAgent"], "$.defaultAgent", {"codex", "pi"})
    default_account = _string(root["defaultCodexAccount"], "$.defaultCodexAccount")
    _enum(root["defaultPolicyProfile"], "$.defaultPolicyProfile", _DEFAULT_POLICY_PROFILES)
    confirmation = _bool(
        root["fullAccessRequiresConfirmation"], "$.fullAccessRequiresConfirmation"
    )
    if not confirmation:
        _fail(
            "$.fullAccessRequiresConfirmation",
            "must be true; unrestricted authority is always confirmed per task",
        )
    if "deprecated" in root:
        deprecated = _mapping(
            root["deprecated"], "$.deprecated", {"legacyCodexFullAccess"}
        )
        legacy = _mapping(
            deprecated["legacyCodexFullAccess"],
            "$.deprecated.legacyCodexFullAccess",
            {"removed", "previouslyEnabled"},
        )
        if _bool(legacy["removed"], "$.deprecated.legacyCodexFullAccess.removed") is not True:
            _fail("$.deprecated.legacyCodexFullAccess.removed", "must be true")
        _bool(
            legacy["previouslyEnabled"],
            "$.deprecated.legacyCodexFullAccess.previouslyEnabled",
        )

    accounts = root["accounts"]
    if not isinstance(accounts, list) or not accounts or len(accounts) > 16:
        _fail("$.accounts", "must contain 1-16 account objects")
    seen: set[str] = set()
    enabled: set[str] = set()
    account_root = (home / ".local/share/quattro-ai/codex/accounts") if home else codex_account_root()
    account_root = account_root.resolve(strict=False)
    normalized_accounts: list[dict[str, Any]] = []
    for index, raw in enumerate(accounts):
        path = f"$.accounts[{index}]"
        account = _mapping(raw, path, {"id", "alias", "codexHome", "enabled"})
        account_id = _string(account["id"], f"{path}.id", maximum=64)
        assert account_id is not None
        if not _ACCOUNT_ID.fullmatch(account_id):
            _fail(f"{path}.id", "has an invalid account id")
        if account_id in seen:
            _fail(f"{path}.id", "is duplicated")
        seen.add(account_id)
        alias = _string(account["alias"], f"{path}.alias", maximum=80)
        codex_home = _string(account["codexHome"], f"{path}.codexHome")
        is_enabled = _bool(account["enabled"], f"{path}.enabled")
        expanded = Path(os.path.expandvars(os.path.expanduser(str(codex_home)))).resolve(strict=False)
        try:
            expanded.relative_to(account_root)
        except ValueError:
            _fail(f"{path}.codexHome", f"must be inside {account_root}")
        if is_enabled:
            enabled.add(account_id)
        normalized_accounts.append({
            "id": account_id, "alias": alias, "codexHome": codex_home, "enabled": is_enabled,
        })
    if default_account not in enabled:
        _fail("$.defaultCodexAccount", "must reference an enabled account")

    usage = _mapping(root["usageRefresh"], "$.usageRefresh", {"enabled", "intervalMinutes"})
    _bool(usage["enabled"], "$.usageRefresh.enabled")
    _integer(usage["intervalMinutes"], "$.usageRefresh.intervalMinutes", 1, 1_440)

    sync = _mapping(root["crossDeviceSync"], "$.crossDeviceSync", {"enabled", "directory"})
    _bool(sync["enabled"], "$.crossDeviceSync.enabled")
    _string(sync["directory"], "$.crossDeviceSync.directory", nullable=True)
    if sync["enabled"] and sync["directory"] is None:
        _fail("$.crossDeviceSync.directory", "is required when sync is enabled")

    crash = _mapping(root["crashCapture"], "$.crashCapture", {"enabled", "automaticDiagnosis"})
    _bool(crash["enabled"], "$.crashCapture.enabled")
    _bool(crash["automaticDiagnosis"], "$.crashCapture.automaticDiagnosis")

    dictation = _mapping(
        root["dictation"], "$.dictation",
        {"engine", "modelPath", "maxRecordingSeconds", "retainAudio"},
    )
    _enum(dictation["engine"], "$.dictation.engine", {"whisper.cpp"})
    _string(dictation["modelPath"], "$.dictation.modelPath")
    _integer(dictation["maxRecordingSeconds"], "$.dictation.maxRecordingSeconds", 1, 600)
    _bool(dictation["retainAudio"], "$.dictation.retainAudio")

    memory = _mapping(
        root["memory"], "$.memory",
        {"enabled", "vaultPath", "projectVaultPath", "enforceOnLaunch"},
    )
    _bool(memory["enabled"], "$.memory.enabled")
    _string(memory["vaultPath"], "$.memory.vaultPath")
    _string(memory["projectVaultPath"], "$.memory.projectVaultPath")
    _bool(memory["enforceOnLaunch"], "$.memory.enforceOnLaunch")

    workspace = _mapping(
        root.get("workspace", {"projectRoot": "~/Projects"}),
        "$.workspace", {"projectRoot"},
    )
    project_root = _string(workspace["projectRoot"], "$.workspace.projectRoot")
    assert project_root is not None
    expanded_value = Path(os.path.expandvars(os.path.expanduser(project_root)))
    if not expanded_value.is_absolute():
        _fail("$.workspace.projectRoot", "must be an absolute or home-relative path")
    expanded_project_root = expanded_value.resolve(strict=False)
    if expanded_project_root == Path(expanded_project_root.anchor):
        _fail("$.workspace.projectRoot", "must resolve to a safe absolute directory")

    pr_fields = {
        "runtime", "codexAccount", "githubAccount", "defaultRepository", "reviewMode",
        "automaticPublication", "maximumDepth", "runTests", "securityScanning",
        "commentBehavior", "severityThreshold", "model", "timeoutSeconds", "maxFiles",
        "maxDiffBytes",
    }
    review = _mapping(root["prReview"], "$.prReview", pr_fields)
    _enum(review["runtime"], "$.prReview.runtime", {"codex"})
    review_account = _string(review["codexAccount"], "$.prReview.codexAccount")
    if review_account not in enabled:
        _fail("$.prReview.codexAccount", "must reference an enabled account")
    _string(review["githubAccount"], "$.prReview.githubAccount", nullable=True, maximum=80)
    _string(review["defaultRepository"], "$.prReview.defaultRepository", nullable=True, maximum=200)
    _enum(review["reviewMode"], "$.prReview.reviewMode", {"comment", "request-changes", "approve"})
    _bool(review["automaticPublication"], "$.prReview.automaticPublication")
    _enum(review["maximumDepth"], "$.prReview.maximumDepth", {"bounded", "full"})
    _bool(review["runTests"], "$.prReview.runTests")
    _bool(review["securityScanning"], "$.prReview.securityScanning")
    _enum(review["commentBehavior"], "$.prReview.commentBehavior", {"summary", "inline", "both"})
    _enum(review["severityThreshold"], "$.prReview.severityThreshold", {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
    _string(review["model"], "$.prReview.model", nullable=True, maximum=200)
    _integer(review["timeoutSeconds"], "$.prReview.timeoutSeconds", 30, 14_400)
    _integer(review["maxFiles"], "$.prReview.maxFiles", 1, 10_000)
    _integer(review["maxDiffBytes"], "$.prReview.maxDiffBytes", 1_024, 100_000_000)

    normalized = copy.deepcopy(root)
    delegation = _mapping(
        root.get("delegation", {"enabled": True, "maxWorkers": 3}),
        "$.delegation", {"enabled", "maxWorkers"},
    )
    _bool(delegation["enabled"], "$.delegation.enabled")
    _integer(delegation["maxWorkers"], "$.delegation.maxWorkers", 1, 3)
    normalized["delegation"] = copy.deepcopy(delegation)
    # Legacy worktree fields remain accepted only so existing schema-v3 files
    # continue to launch.  They are deliberately discarded: ordinary sessions
    # always use their requested directory, and worktrees are explicit-only.
    cooperation = _mapping(
        root.get("cooperation", {"globalLimit": 5, "perRepositoryLimit": 3}),
        "$.cooperation",
        {"globalLimit", "perRepositoryLimit", "worktreeIsolation", "worktreeRoot"},
        required={"globalLimit", "perRepositoryLimit"},
    )
    global_limit = _integer(cooperation["globalLimit"], "$.cooperation.globalLimit", 1, 32)
    repository_limit = _integer(
        cooperation["perRepositoryLimit"], "$.cooperation.perRepositoryLimit", 1, 16
    )
    if repository_limit > global_limit:
        _fail("$.cooperation.perRepositoryLimit", "must not exceed globalLimit")
    if "worktreeIsolation" in cooperation:
        _bool(cooperation["worktreeIsolation"], "$.cooperation.worktreeIsolation")
    if "worktreeRoot" in cooperation:
        _string(cooperation["worktreeRoot"], "$.cooperation.worktreeRoot")
    normalized["cooperation"] = {
        "globalLimit": global_limit,
        "perRepositoryLimit": repository_limit,
    }

    raw_routing = dict(root.get("routing", {
            "fastReasoningEffort": "low",
            "standardReasoningEffort": "medium",
            "reasoningReasoningEffort": "high",
            "exceptionalReasoningEffort": "ultra",
            "maxAutomaticEscalations": 2,
            "maxExceptionalEscalations": 1,
            "fastAutoRoute": "auto/coding:cheap",
            "standardAutoRoute": "auto/coding",
            "reasoningAutoRoute": "auto/reasoning",
            "fastContextBudgetTokens": 1_200,
            "standardContextBudgetTokens": 2_500,
            "reasoningContextBudgetTokens": 4_000,
        }))
    raw_routing.setdefault("fastContextBudgetTokens", 1_200)
    raw_routing.setdefault("standardContextBudgetTokens", 2_500)
    raw_routing.setdefault("reasoningContextBudgetTokens", 4_000)
    routing = _mapping(
        raw_routing,
        "$.routing",
        {"fastReasoningEffort", "standardReasoningEffort", "reasoningReasoningEffort", "exceptionalReasoningEffort", "maxAutomaticEscalations", "maxExceptionalEscalations", "fastAutoRoute", "standardAutoRoute", "reasoningAutoRoute", "fastContextBudgetTokens", "standardContextBudgetTokens", "reasoningContextBudgetTokens"},
    )
    routing = dict(routing)
    normal_efforts = {
        "fastReasoningEffort": "low",
        "standardReasoningEffort": "medium",
        "reasoningReasoningEffort": "high",
    }
    for field, expected in normal_efforts.items():
        value = _enum(
            routing[field], f"$.routing.{field}",
            {"low", "medium", "high", "xhigh", "max", "ultra"},
        )
        if value != expected:
            _fail(f"$.routing.{field}", f"must be {expected}; Quattro owns normal task effort")
    _enum(
        routing["exceptionalReasoningEffort"],
        "$.routing.exceptionalReasoningEffort", {"xhigh", "max", "ultra"},
    )
    _integer(routing["maxAutomaticEscalations"], "$.routing.maxAutomaticEscalations", 0, 2)
    _integer(routing["maxExceptionalEscalations"], "$.routing.maxExceptionalEscalations", 0, 1)
    for field in ("fastAutoRoute", "standardAutoRoute", "reasoningAutoRoute"):
        value = _string(routing[field], f"$.routing.{field}", maximum=200)
        if not str(value).startswith("auto/"):
            _fail(f"$.routing.{field}", "must be an OmniRoute auto route")
    for field in (
        "fastContextBudgetTokens", "standardContextBudgetTokens",
        "reasoningContextBudgetTokens",
    ):
        _integer(routing[field], f"$.routing.{field}", 512, 16_000)
    normalized["routing"] = copy.deepcopy(routing)
    normalized["workspace"] = {"projectRoot": project_root}
    normalized["defaultAgent"] = default_agent
    normalized["accounts"] = normalized_accounts
    return normalized


def load_ai_config(
    path: str | os.PathLike[str],
    *,
    migrate: bool = True,
    require_private: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    """Load JSON with duplicate-key detection, optional migration, and strict validation."""
    target = Path(path)
    if target.is_symlink():
        raise ConfigError(f"configuration must not be a symlink: {target}")
    try:
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigError(f"configuration is not a regular file: {target}")
        if require_private and metadata.st_mode & 0o077:
            raise ConfigError(f"configuration permissions must be 0600 or stricter: {target}")
        with target.open("r", encoding="utf-8") as stream:
            raw = json.load(stream, object_pairs_hook=_object_pairs)
    except ConfigError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot load configuration {target}: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be an object")
    candidate = migrate_ai_config(raw) if migrate else raw
    return validate_ai_config(candidate, home=home)
