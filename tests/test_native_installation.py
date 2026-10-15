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
        installed = subprocess.run([str(python),str(ROOT/"scripts/configure_native.py"),"--base",str(base),"--config",str(selected),"--install-clients"],input="[]",env=env,capture_output=True,text=True,timeout=30)
        self.assertEqual(installed.returncode,0,installed.stderr)
        # Local lexical fixtures make path/authorization behavior independent of an embedding server.
        for path in (selected,selected.parent/"clients/codex.json",selected.parent/"clients/omp.json"):
            replace(Config.load(path),embedding="lexical").save(path)
        command = home/".local/bin/quattro-intelligence"
        queried = subprocess.run([str(command),"query","--project","alpha","--limit","1","journal"],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(queried.returncode,0,queried.stderr)
        self.assertIn("Chosen journal",json.loads(queried.stdout)["results"][0]["content"])
        hooks = json.loads((home/".codex/hooks.json").read_text())
        handler = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        event = {"hook_event_name":"UserPromptSubmit","cwd":str(project),"prompt":"journal committed facts","session_id":"selected-store-session","turn_id":"turn-1"}
        hooked = subprocess.run(shlex.split(handler["command"]),input=json.dumps(event),env=env,capture_output=True,text=True,timeout=20)
        context = json.loads(hooked.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Chosen journal",context)
        self.assertNotIn("stale-default",context)
        locator = json.loads((default_dir/"native-runtime.json").read_text())
        self.assertEqual(Path(locator["config_dir"]),selected.parent)


if __name__=="__main__":
    unittest.main()
