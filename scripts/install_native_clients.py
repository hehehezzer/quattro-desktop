"""Opt-in native client registration; preserve models, accounts and permission policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import tomllib


READ_TOOLS = ("search_knowledge","get_project_context","get_index_status","recall_memory")
WRITE_TOOLS = ("index_source","save_memory","update_memory","invalidate_memory","delete_memory")


def _regular(path):
    if any(part.is_symlink() for part in (path,*path.parents)):
        raise ValueError("native registration refuses symbolic-link paths")


def write_private(path, content, *, mode=None):
    _regular(path)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temporary = path.with_name(path.name+".quattro-new")
    _regular(temporary)
    descriptor = os.open(temporary,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    permissions = mode if mode is not None else path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary.chmod(permissions)
    temporary.replace(path)


def codex_configuration(original, executable, config):
    # Parse complete statements, not physical lines: a multiline string can itself
    # contain text that looks like a table header. Keep unrelated source verbatim.
    tomllib.loads(original)
    lines = []
    discard = False
    statement = ""
    for line in original.splitlines(keepends=True):
        statement += line
        try:
            parsed = tomllib.loads(statement)
        except tomllib.TOMLDecodeError:
            continue
        if statement.lstrip().startswith("["):
            # tomllib resolves quoted, escaped and dotted header keys identically.
            discard = "quattro_intelligence" in parsed.get("mcp_servers",{})
        if not discard or statement.lstrip().startswith("#"):
            lines.append(statement)
        statement = ""
    output = "".join(lines)
    if output and not output.endswith("\n\n"):
        output += "\n" if output.endswith("\n") else "\n\n"
    output += "[mcp_servers.quattro_intelligence]\n"
    output += f"command = {json.dumps(str(executable))}\nargs = [\"--config\", {json.dumps(str(config))}]\nrequired = true\ntool_timeout_sec = 1800\n"
    output += '\n[mcp_servers.quattro_intelligence.env]\nQUATTRO_NATIVE_HOST = "codex"\n'
    for name in (*READ_TOOLS,*WRITE_TOOLS):
        mode = "approve" if name in READ_TOOLS else "prompt"
        output += f'\n[mcp_servers.quattro_intelligence.tools.{name}]\napproval_mode = "{mode}"\n'
    tomllib.loads(output)
    return output


def install_clients(repository: Path, python: Path, config_dir: Path):
    home = Path.home()
    omp = home/".omp/agent"
    profiles = home/".omp/profiles"
    omp_roots = [omp] if omp.is_dir() else []
    if profiles.is_dir():
        omp_roots += [path/"agent" for path in sorted(profiles.iterdir()) if (path/"agent").is_dir() and not path.is_symlink()]
    for root in omp_roots:
        target = root/"extensions/quattro-intelligence.ts"
        write_private(target,(repository/"adapters/omp/quattro-intelligence.ts").read_text(encoding="utf-8"))
    codex_homes = [home/".codex"]
    accounts = home/".local/share/quattro-ai/codex/accounts"
    if accounts.is_dir():
        codex_homes += [path for path in sorted(accounts.iterdir()) if re.fullmatch(r"account-[0-9]+",path.name) and path.is_dir() and not path.is_symlink()]
    installed = []
    hook_arguments = [str(python),str(repository/"adapters/codex/context_hook.py")]
    if config_dir != home/".config/quattro":
        hook_arguments.extend(["--config",str(config_dir/"clients/codex.json")])
    hook_command = shlex.join(hook_arguments)
    for root in codex_homes:
        config = root/"config.toml"
        if not config.is_file():
            continue
        _regular(config)
        updated = codex_configuration(config.read_text(encoding="utf-8"),python.parent/"quattro-intelligence-mcp",config_dir/"clients/codex.json")
        write_private(config,updated)
        hooks_path = root/"hooks.json"
        _regular(hooks_path)
        hooks = json.loads(hooks_path.read_text(encoding="utf-8")) if hooks_path.exists() else {}
        groups = hooks.setdefault("hooks",{}).setdefault("UserPromptSubmit",[])
        for group in groups:
            group["hooks"] = [handler for handler in group.get("hooks",[]) if handler.get("statusMessage") != "Retrieving Quattro project intelligence"]
        groups[:] = [group for group in groups if group.get("hooks")]
        groups.append({"hooks":[{"type":"command","command":hook_command,"timeout":130,
            "statusMessage":"Retrieving Quattro project intelligence","additionalContextLimit":4500}]})
        write_private(hooks_path,json.dumps(hooks,indent=2)+"\n")
        installed.append(str(root))
    return {"omp_agent_directories":[str(path) for path in omp_roots],"codex_homes":installed,
            "hook_trust":"Review the exact new hook in native Codex /hooks; no trust hashes or permissions were changed."}
