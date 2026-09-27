"""BlueZ protocol/error contracts without radio or device mutations."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

bridge_module = None
if sys.platform == "linux":
    try:
        spec = importlib.util.spec_from_file_location("desktop_bluetooth", Path(__file__).parents[1] / "src/quattro_bluetooth.py")
        bridge_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge_module)
    except ImportError:
        bridge_module = None


@unittest.skipIf(bridge_module is None, "BlueZ tests require Linux python-gobject")
class BluetoothTests(unittest.TestCase):
    def setUp(self):
        self.bridge = bridge_module.Bridge.__new__(bridge_module.Bridge)
        self.bridge.pending = None
        self.bridge.emit = Mock()
        self.bridge.objects = {}
        self.bridge.busy = False
        self.bridge.refresh = Mock()
        self.bridge.call = Mock()
        self.bridge.scan_path = None
        self.bridge.bus = Mock()

    def test_unknown_device_rejected(self):
        self.bridge.dispatch({"action": "pair", "path": "/malicious"})
        self.bridge.call.assert_not_called()
        self.assertIn("no longer available", self.bridge.emit.call_args.kwargs["error"])

    def test_busy_operation_rejected(self):
        self.bridge.busy = True
        self.bridge.dispatch({"action": "pair", "path": "/device"})
        self.bridge.call.assert_not_called()
        self.assertIn("Wait", self.bridge.emit.call_args.kwargs["error"])

    def test_pair_authentication_failure_is_not_success(self):
        self.bridge.objects = {"/device": {bridge_module.DEVICE: {}}}
        self.bridge.call.side_effect = bridge_module.GLib.Error("AuthenticationFailed")
        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        with patch.object(bridge_module.threading, "Thread", ImmediateThread), patch.object(bridge_module.GLib, "idle_add"):
            self.bridge.dispatch({"action": "pair", "path": "/device"})
        calls = self.bridge.emit.call_args_list
        self.assertTrue(any("AuthenticationFailed" in str(call.kwargs.get("error", "")) for call in calls))
        self.assertFalse(any("message" in call.kwargs for call in calls))
        self.assertFalse(self.bridge.busy)
        self.assertEqual(self.bridge.call.call_args_list[0].kwargs["timeout"], 65000)

    def test_pairing_requires_matching_confirmation(self):
        invocation = Mock()
        self.bridge.pending = (4, invocation, "confirm")
        self.bridge.respond({"id": 3, "accept": True})
        invocation.return_value.assert_not_called()
        self.bridge.respond({"id": 4, "accept": True})
        invocation.return_value.assert_called_once_with(None)
        self.assertIsNone(self.bridge.pending)

    def test_reject_invalid_passkey(self):
        invocation = Mock()
        self.bridge.pending = (4, invocation, "passkey")
        self.bridge.respond({"id": 4, "accept": True, "value": "1000000"})
        invocation.return_dbus_error.assert_called_once()
        invocation.return_value.assert_not_called()

    def test_pin_preserves_leading_zeroes(self):
        invocation = Mock()
        self.bridge.pending = (4, invocation, "pin")
        self.bridge.respond({"id": 4, "accept": True, "value": "0042"})
        self.assertEqual(invocation.return_value.call_args.args[0].unpack(), ("0042",))

    def test_service_loss_clears_stale_devices_and_prompts(self):
        invocation = Mock()
        self.bridge.pending = (4, invocation, "confirm")
        self.bridge.objects = {"/device": {bridge_module.DEVICE: {}}}
        self.bridge.vanished()
        self.assertEqual(self.bridge.objects, {})
        self.assertIsNone(self.bridge.pending)
        self.assertFalse(self.bridge.emit.call_args.kwargs["available"])
        invocation.return_dbus_error.assert_called_once()

    def test_stop_scan_is_bounded_and_idempotent(self):
        self.bridge.scan_path = "/adapter"
        self.bridge.stop_scan()
        self.bridge.stop_scan()
        self.bridge.bus.call.assert_called_once()
        self.assertIn(5000, self.bridge.bus.call.call_args.args)


if __name__ == "__main__":
    unittest.main()
