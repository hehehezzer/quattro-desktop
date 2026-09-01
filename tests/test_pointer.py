import importlib.machinery
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "quattro-pointer"
LOADER = importlib.machinery.SourceFileLoader("quattro_pointer", str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
pointer = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(pointer)


class PointerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = pathlib.Path(self.temp.name) / "pointer.json"
        self.path_patch = mock.patch.object(pointer, "CONFIG_PATH", self.config)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_default_is_normal(self):
        self.assertEqual(pointer.current_preset(), "normal")

    def test_write_and_read_valid_preset(self):
        pointer.write_preset("low")
        self.assertEqual(pointer.current_preset(), "low")
        self.assertEqual(
            json.loads(self.config.read_text(encoding="utf-8")),
            {"schemaVersion": 1, "preset": "low", "sensitivity": -0.5},
        )

    def test_invalid_or_mismatched_state_falls_back(self):
        self.config.write_text(
            json.dumps({"preset": "low", "sensitivity": 0}), encoding="utf-8"
        )
        self.assertEqual(pointer.current_preset(), "normal")

    def test_apply_uses_fixed_hyprland_expression(self):
        completed = mock.Mock(returncode=0)
        with mock.patch.object(pointer.subprocess, "run", return_value=completed) as run:
            self.assertTrue(pointer.apply_hyprland("very-low"))
        self.assertEqual(
            run.call_args.args[0],
            ["hyprctl", "eval", "hl.config({ input = { sensitivity = -0.8 } })"],
        )

    def test_set_persists_when_live_apply_is_unavailable(self):
        with mock.patch.object(pointer, "apply_hyprland", return_value=False):
            with mock.patch.object(pointer.sys, "argv", ["quattro-pointer", "set", "low"]):
                self.assertEqual(pointer.main(), 0)
        self.assertEqual(pointer.current_preset(), "low")


if __name__ == "__main__":
    unittest.main()
