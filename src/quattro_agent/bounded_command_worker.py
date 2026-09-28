"""Set Linux parent-death ownership before execing a host-approved argument vector."""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(2)
    child = None
    def cleanup_child_group():
        if child is None:
            return
        if os.name == "posix":
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif child.poll() is None:
            child.kill()
    def stop_group(_signum, _frame):
        cleanup_child_group()
        raise SystemExit(128 + _signum)
    signal.signal(signal.SIGTERM, stop_group)
    if sys.platform == "linux":
        import ctypes
        parent = os.getppid()
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise SystemExit(2)
        if parent == 1 or os.getppid() != parent:
            raise SystemExit(2)
    child = subprocess.Popen(sys.argv[1:], start_new_session=os.name == "posix",
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
    try:
        code = child.wait()
    finally:
        cleanup_child_group()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
