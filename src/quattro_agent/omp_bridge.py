"""Quattro-owned OMP launch contract; native approvals remain authoritative.

This module neither installs software nor reads authentication stores. An OMP
launch must use the explicit route and approval flags here. Native OMP tools
execute in OMP, while shared intelligence remains owned by Quattro.
"""
from __future__ import annotations

from pathlib import Path
import re


OMP_PROVIDER = "openai-codex"
OMP_MODEL = "gpt-6.1-sol"
OMP_EFFORT = "medium"
OMP_APPROVAL_MODE = "always-ask"
OMP_TOOLS = ("read", "bash", "edit", "write", "glob", "grep", "operational_decision",
             "decision_capabilities", "search_knowledge", "rtk_status", "rtk_run", "refresh_history")


def _path(value: str | Path, *, kind: str) -> str:
    text = str(value)
    if not text or len(text) > 4096 or "\0" in text or not Path(text).is_absolute():
        raise ValueError(f"absolute {kind} path required")
    return str(Path(text))


def extension_path() -> Path:
    """Packaged supported OMP extension, without activating persistent hooks."""
    return Path(__file__).resolve().parent / "data" / "omp-intelligence.ts"


def native_policy_overlay(*, skill_roots=()) -> dict:
    """Require native per-call approval and close headless delegation escapes.

    OMP subagents normally inherit a yolo tier boundary after parent task
    approval. They are unavailable until Quattro supplies separately reviewed
    task supervision. eval can spawn agents too, and is denied here.
    """
    if type(skill_roots) not in (tuple, list) or len(skill_roots) > 128:
        raise ValueError("bounded skill roots required")
    roots = list(dict.fromkeys(_path(root, kind="skill") for root in skill_roots))
    return {"skills": {"enabled": True, "customDirectories": roots, "enableCodexUser": True,
                       "ignoredSkills": [], "includeSkills": []},
            "bash": {"patterns": []},
            "tools": {"approvalMode": OMP_APPROVAL_MODE, "approval": {
        "bash": "prompt", "edit": "prompt", "write": "prompt", "rtk_run": "prompt",
        "refresh_history": "prompt", "eval": "deny", "task": "deny",
        "computer": "deny", "browser": "prompt",
    }}}


def omp_arguments(binary: str | Path, *, extension: str | Path | None = None,
                  config_overlay: str | Path, skill_roots=(),
                  session: str | Path | None = None, prompt: str | None = None) -> list[str]:
    """Return argument-safe interactive launch flags, never arbitrary extras.

    A caller must write the reviewed native_policy_overlay into config_overlay.
    No shell evaluation is used, and positional input follows an explicit --.
    Existing native skills/context discovery is left enabled. Skill roots must
    be encoded in native_policy_overlay; OMP --skills filters names, not paths.
    """
    executable = str(binary)
    if (not executable or len(executable) > 4096 or "\0" in executable or
            not (Path(executable).is_absolute() or re.fullmatch(r"[A-Za-z0-9_.-]+", executable))):
        raise ValueError("OMP executable path or command name required")
    argv = [executable, "--provider", OMP_PROVIDER, "--model", OMP_MODEL,
            "--thinking", OMP_EFFORT, "--approval-mode", OMP_APPROVAL_MODE,
            "--profile", "quattro", "--no-extensions", "--no-prewalk", "--no-title",
            "--tools", ",".join(OMP_TOOLS),
            "--config", _path(config_overlay, kind="overlay"),
            "--extension", _path(extension or extension_path(), kind="extension")]
    if type(skill_roots) not in (tuple, list) or len(skill_roots) > 128:
        raise ValueError("bounded skill roots required")
    for root in skill_roots:
        _path(root, kind="skill")
    if session is not None:
        argv.extend(["--session", _path(session, kind="session")])
    if prompt is not None:
        if type(prompt) is not str or not prompt.strip() or len(prompt) > 131072 or "\0" in prompt:
            raise ValueError("bounded text prompt required")
        argv.extend(["--", prompt])
    return argv


def bridge_contract() -> dict:
    """Public-safe ownership and capability metadata; no runtime attestation."""
    return {"schemaVersion": 1, "decisionAuthority": "quattro",
            "sessionRuntime": "herdr", "executionHarness": "omp",
            "route": {"provider": OMP_PROVIDER, "model": OMP_MODEL, "effort": OMP_EFFORT},
            "approvalMode": OMP_APPROVAL_MODE, "adviceGrantsPermission": False,
            "nativeToolsAvailable": "host_observed_only",
            "headlessApproval": "required_prompt_fails_closed",
            "delegation": "unavailable_pending_supervised_route"}
