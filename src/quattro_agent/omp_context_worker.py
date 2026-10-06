"""Fresh context-only OMP turn; prompts and answers stay on bounded private pipes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

if __package__ in (None, ""):
    # Isolated Python execution adds only the reviewed bundled package root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quattro_agent.scoped_omp_runtime import HostBinding, ScopedOMPError, ScopedOMPRuntime, prepare_private_home, sdk_command


MAX_INPUT = 131072


def run_context_turn(*, command, directory, agent_dir, task, run, prompt, timeout,
                     runtime_factory=ScopedOMPRuntime):
    """Run without host tools, native transcript persistence or detached children."""
    environment = {name: os.environ[name] for name in ("PATH", "LANG", "TERM") if name in os.environ}
    environment.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    environment["PI_CODING_AGENT_DIR"] = str(agent_dir)

    def deny(*_args):
        raise ScopedOMPError("context-only runtime grants no tool authority")

    with tempfile.TemporaryDirectory(prefix="quattro-omp-context-") as temporary:
        home = prepare_private_home(Path(temporary).resolve() / "home")
        environment["HOME"] = str(home)
        runtime = runtime_factory(command, cwd=directory, environment=environment,
                                  binding=HostBinding(task, run), tools=[], execute=deny,
                                  timeout=timeout, own_process_group=False)
        try:
            binding = runtime.start()
            outcome = runtime.prompt(prompt)
            text = outcome.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT:
                raise ScopedOMPError("bounded OMP answer unavailable")
            return {"type": "quattro.omp.result", "session_id": binding.native_session_id,
                    "status": "completed", "text": text}
        finally:
            runtime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bun", "package-root", "directory", "agent-dir", "session-dir", "task", "run",
                 "runtime-manifest", "runtime-manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if not 0 < args.timeout <= 300:
            raise ValueError()
        from quattro_agent.omp_deployment import verify_omp_runtime
        verify_omp_runtime(Path(args.runtime_manifest), Path(args.bun), Path(args.package_root),
                           expected_digest=args.runtime_manifest_sha256)
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError()
        prompt = raw.decode("utf-8")
        command = sdk_command(args.bun, args.package_root, cwd=args.directory,
                              agent_dir=args.agent_dir, session_dir=args.session_dir)
        result = run_context_turn(command=command, directory=Path(args.directory),
                                  agent_dir=Path(args.agent_dir), task=args.task, run=args.run,
                                  prompt=prompt, timeout=args.timeout)
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return 0
    except (OSError, ValueError, ScopedOMPError):
        sys.stderr.write("Closed OMP context runtime unavailable; no native CLI fallback.\n")
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
