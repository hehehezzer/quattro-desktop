"""Private temporary configuration and nondefault native store selection."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))
from quattro_core.config import Config, Source
from quattro_core.knowledge import KnowledgeService
import install_native_clients


@unittest.skipUnless(os.name=="posix","Native desktop registration uses POSIX paths and permissions")
class NativeInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_codex_configuration_replaces_semantically_equivalent_headers(self):
        spellings = (
            "mcp_servers.quattro_intelligence",
            'mcp_servers."quattro_intelligence"',
            "'mcp_servers'.'quattro_intelligence'",
            '"mcp_servers" . "quattro_intelligence"',
            r'mcp_servers."quattro\u005fintelligence"',
        )
        before = '''# Native controls stay byte-for-byte intact.
model = "keep-native-model" # native choice
approval_policy = "on-request"
sandbox_mode = "workspace-write"
description = """
[mcp_servers.quattro_intelligence]
This is string content, not a server declaration.
"""

[model_providers.native]
name = "unchanged account"
'''
        after = '''# Keep this neighboring server and its inline comments.
[mcp_servers."quattro_intelligence.other"] # literal dotted name
command = "other-server" # do not rewrite
[mcp_servers."another]server"]
command = "bracket-server"
[[profiles.native.accounts]]
name = "account-one"
[profiles.native.permissions]
approval_policy = "never" # owner policy

'''
        for header in spellings:
            with self.subTest(header=header):
                original = before + f'''[{header}] # replace old registration
command = "obsolete-mcp"
[{header}."env"]
QUATTRO_NATIVE_HOST = "obsolete-host"
[{header}.'tools'."search_knowledge"]
approval_mode = "obsolete-mode"
[[{header}.tools."custom.tool"]]
description = """
[profiles.should_not_escape_discard]
obsolete-multiline-content
"""
''' + after
                output = install_native_clients.codex_configuration(original,"/new/mcp","/new/config.json")
                self.assertTrue(output.startswith(before))
                self.assertIn(after,output)
                self.assertNotIn("obsolete-",output)
                parsed = tomllib.loads(output)
                server = parsed["mcp_servers"]["quattro_intelligence"]
                self.assertEqual(server["command"],"/new/mcp")
                self.assertEqual(server["env"],{"QUATTRO_NATIVE_HOST":"codex"})
                for tool in install_native_clients.READ_TOOLS:
                    self.assertEqual(server["tools"][tool]["approval_mode"],"approve")
                for tool in install_native_clients.WRITE_TOOLS:
                    self.assertEqual(server["tools"][tool]["approval_mode"],"prompt")
                self.assertEqual(install_native_clients.codex_configuration(output,"/new/mcp","/new/config.json"),output)

    def test_repeated_native_installation_preserves_config_and_permissions(self):
        home = self.root/"home"
        codex = home/".codex"
        codex.mkdir(parents=True)
        config = codex/"config.toml"
        native = '''model = "native-model" # keep inline text
approval_policy = "on-request"
sandbox_mode = "read-only"
[accounts."native.account"]
name = "native-account"
[profiles.native.permissions]
approval_policy = "never"
'''
        config.write_text(native + '''["mcp_servers" . 'quattro_intelligence'.env]
QUATTRO_NATIVE_HOST = "old-host"
['mcp_servers'."quattro_intelligence".tools.'save_memory']
approval_mode = "old-mode"
''')
        config.chmod(0o640)
        hooks = codex/"hooks.json"
        native_hook = {"type":"command","command":"native-command","timeout":15}
        hooks.write_text(json.dumps({"hooks":{"UserPromptSubmit":[{"hooks":[native_hook]}]}}))
        hooks.chmod(0o640)
        python = self.root/"environment/bin/python"
        config_dir = self.root/"selected-config"
        with patch.object(Path,"home",return_value=home):
            install_native_clients.install_clients(ROOT,python,config_dir)
            first_config,first_hooks = config.read_text(),hooks.read_text()
            install_native_clients.install_clients(ROOT,python,config_dir)
        self.assertTrue(first_config.startswith(native))
        self.assertEqual(config.read_text(),first_config)
        self.assertEqual(hooks.read_text(),first_hooks)
        self.assertEqual(stat.S_IMODE(config.stat().st_mode),0o640)
        self.assertEqual(stat.S_IMODE(hooks.stat().st_mode),0o640)
        parsed = tomllib.loads(first_config)
        self.assertEqual(parsed["approval_policy"],"on-request")
        self.assertEqual(parsed["sandbox_mode"],"read-only")
        self.assertEqual(parsed["profiles"]["native"]["permissions"]["approval_policy"],"never")
        self.assertEqual(parsed["mcp_servers"]["quattro_intelligence"]["command"],str(python.parent/"quattro-intelligence-mcp"))
        handlers = json.loads(first_hooks)["hooks"]["UserPromptSubmit"]
        self.assertEqual(handlers[0]["hooks"],[native_hook])
        self.assertEqual(len(handlers),2)

    def test_private_configuration_copy_is_private_from_creation(self):
        directory = self.root/"traversable"
        directory.mkdir(mode=0o755)
        target = directory/"config.toml"
        target.write_text('model = "unchanged"\n')
        target.chmod(0o600)
        observed = []
        original_open,original_fdopen = io.open,os.fdopen

        def observed_open(*args,**kwargs):
            stream = original_open(*args,**kwargs)
            if isinstance(args[0],(str,Path)) and str(args[0]).endswith(".quattro-new"):
                observed.append(stat.S_IMODE(os.fstat(stream.fileno()).st_mode))
            return stream

        def observed_fdopen(*args,**kwargs):
            stream = original_fdopen(*args,**kwargs)
            observed.append(stat.S_IMODE(os.fstat(stream.fileno()).st_mode))
            return stream

        previous = os.umask(0o022)
        try:
            with patch("io.open",side_effect=observed_open),patch("os.fdopen",side_effect=observed_fdopen):
                install_native_clients.write_private(target,'model = "retained-private"\n')
        finally:
            os.umask(previous)
        self.assertEqual(observed,[0o600])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        self.assertIn("retained-private",target.read_text())

    def test_nondefault_installation_retrieves_selected_store_not_stale_default(self):
        home = self.root/"home"
        (home/".codex").mkdir(parents=True)
        (home/".omp/agent").mkdir(parents=True)
        (home/".codex/config.toml").write_text('model = "keep-native-model"\napproval_policy = "on-request"\n')
        project = self.root/"project"
        project.mkdir()
        (project/"journal.md").write_text("# Journal\nChosen journal preserves committed facts across restart.")
        config = Config(self.root/"selected-state",(Source("code","alpha",project),),("alpha",),principal="operator",writable=True)
        with closing(KnowledgeService(config)) as service:
            service.index_source("code")
        base = self.root/"base.json"
        config.save(base)
        stale_root = self.root/"stale-project"
        stale_root.mkdir()
        (stale_root/"journal.md").write_text("# Journal\nUnrelated stale-default journal.")
        stale = Config(self.root/"stale-state",(Source("old","beta",stale_root),),("beta",),writable=True)
        with closing(KnowledgeService(stale)) as service:
            service.index_source("old")
        default_dir = home/".config/quattro"
        stale.save(default_dir/"intelligence.json")
        stale.save(default_dir/"clients/codex.json")

        environment = self.root/"venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        python = environment/("Scripts/python.exe" if os.name=="nt" else "bin/python")
        site = subprocess.run([str(python),"-c","import sysconfig;print(sysconfig.get_path('purelib'))"],check=True,capture_output=True,text=True).stdout.strip()
        (Path(site)/"quattro-source.pth").write_text(str(ROOT/"src")+"\n")
        (default_dir/"native-runtime.json").write_text(json.dumps({"python":str(python),"config_dir":str(default_dir)}))
        selected = self.root/"operator-selected/intelligence.json"
        env = {"HOME":str(home),"PATH":os.defpath,"QUATTRO_DIAGNOSTIC":"1"}
        manifest = [{"id":"excluded","project":"alpha","root":str(project),"intent":"excluded","exclusion_reason":"private scope"}]
        installed = subprocess.run([str(python),str(ROOT/"scripts/configure_native.py"),"--base",str(base),"--config",str(selected),"--install-clients"],input=json.dumps(manifest),env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(installed.returncode,0,installed.stderr)
        self.assertEqual(Config.load(selected).source("excluded").intent,"excluded")
        # Local lexical fixtures make path/authorization behavior independent of an embedding server.
        for path in (selected,selected.parent/"clients/codex.json",selected.parent/"clients/omp.json"):
            replace(Config.load(path),embedding="lexical").save(path)
        command = home/".local/bin/quattro-intelligence"
        queried = subprocess.run([str(command),"query","--project","alpha","--limit","1","journal"],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(queried.returncode,0,queried.stderr)
        self.assertIn("Chosen journal",json.loads(queried.stdout)["results"][0]["content"])
        hooks = json.loads((home/".codex/hooks.json").read_text())
        handler = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        # Hostile workspaces must not shadow the helper's installed Python package.
        shadow = project/"quattro_core"
        shadow.mkdir()
        marker = self.root/"shadow-executed"
        (shadow/"__init__.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\n")
        event = {"hook_event_name":"UserPromptSubmit","cwd":str(project),"prompt":"journal committed facts","session_id":"selected-store-session","turn_id":"turn-1"}
        hooked = subprocess.run(shlex.split(handler["command"]),input=json.dumps(event),env=env,cwd=project,capture_output=True,text=True,timeout=20)
        context = json.loads(hooked.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Chosen journal",context)
        self.assertNotIn("stale-default",context)
        self.assertFalse(marker.exists(), "workspace code executed before source authorization")
        locator = json.loads((default_dir/"native-runtime.json").read_text())
        self.assertEqual(Path(locator["config_dir"]),selected.parent)


if __name__=="__main__":
    unittest.main()
