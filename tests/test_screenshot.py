"""Screenshot captures temporarily suspend Quattro's compositor shader."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "quattro-screenshot"


class ScreenshotNightLightTests(unittest.TestCase):
    def run_capture(self, shader_kind, mode="fullscreen"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            home.mkdir()
            shader = home / ".config/quattro/night-light-shaders/soft.frag"
            if shader_kind == "foreign":
                shader = root / "other-shader.frag"
            log = root / "events"
            helpers = {
                "hyprctl": """#!/bin/sh
case "$1" in
  getoption) printf '{"str":"%s"}\\n' "$TEST_SHADER" ;;
  monitors) printf '[{"focused":true,"x":0,"y":0,"width":100,"height":100,"scale":1}]\\n' ;;
  eval) printf 'suspend\\n' >> "$TEST_LOG" ;;
esac
""",
                "quattro-night-light": "#!/bin/sh\nprintf 'restore\\n' >> \"$TEST_LOG\"\n",
                "grim": "#!/bin/sh\nprintf 'capture\\n' >> \"$TEST_LOG\"\nprintf 'png' > \"$3\"\n",
                "slurp": "#!/bin/sh\nexit 1\n",
                "hyprpicker": "#!/bin/sh\nsleep 3\n",
                "wl-copy": "#!/bin/sh\ncat >/dev/null\n",
                "notify-send": "#!/bin/sh\nexit 0\n",
            }
            for name, content in helpers.items():
                path = bin_dir / name
                path.write_text(content)
                path.chmod(0o755)
            env = dict(os.environ)
            env.update(
                HOME=str(home),
                XDG_PICTURES_DIR=str(root / "pictures"),
                TEST_SHADER=str(shader),
                TEST_LOG=str(log),
                PATH=f"{bin_dir}:{env['PATH']}",
            )
            result = subprocess.run(["bash", str(SCRIPT), mode], env=env,
                                    capture_output=True, text=True, timeout=8)
            return result.returncode, log.read_text().splitlines() if log.exists() else []

    def test_capture_restores_night_light(self):
        code, events = self.run_capture("quattro")
        self.assertEqual(code, 0)
        self.assertEqual(events, ["suspend", "capture", "restore"])

    def test_cancel_restores_night_light(self):
        code, events = self.run_capture("quattro", "region")
        self.assertEqual(code, 0)
        self.assertEqual(events, ["suspend", "restore"])

    def test_other_screen_shader_is_untouched(self):
        code, events = self.run_capture("foreign")
        self.assertEqual(code, 0)
        self.assertEqual(events, ["capture"])


if __name__ == "__main__":
    unittest.main()
