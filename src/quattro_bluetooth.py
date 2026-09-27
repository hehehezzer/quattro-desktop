"""Single event-driven BlueZ bridge and interactive Agent1 for the shell.

Requires python-gobject. Only enumerated adapter/device paths are actionable.
All system calls have deadlines; authentication requests require a UI response.
"""
from __future__ import annotations

import ctypes
import json
import os
import signal
import sys
import threading

from gi.repository import Gio, GLib

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
SCAN_SECONDS = 60
PROPS = "org.freedesktop.DBus.Properties"
AGENT_PATH = "/org/quattro/desktop/agent"
AGENT_XML = """<node><interface name="org.bluez.Agent1">
<method name="Release"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="Cancel"/>
</interface></node>"""


def operation_error(action, error):
    detail = str(error)
    lower = detail.lower()
    if "timeout" in lower or "timed out" in lower:
        if action == "pair":
            return "Pairing timed out. Keep the device nearby and try again."
        if action == "connect":
            return "Connection timed out. Check the device and try again."
        return "Bluetooth did not respond. Try again."
    if action == "pair" and "authenticationfailed" in lower:
        return "Pairing was rejected. Check the code on both devices and try again."
    if isinstance(error, GLib.Error):
        return "Bluetooth could not complete this action. Try again."
    return detail[:400]


class Bridge:
    def __init__(self):
        # Quickshell can exit without closing inherited pipe writers. Tie this
        # child to its creator so a shell restart cannot strand a default agent.
        parent = os.getppid()
        if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise OSError("Could not establish Bluetooth bridge lifetime")
        if os.getppid() != parent or parent == 1:
            raise OSError("Bluetooth bridge requires a live owner")
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.loop = GLib.MainLoop()
        self.objects = {}
        self.busy = False
        self.scan_path = None
        self.scan_timer = 0
        self.refresh_timer = 0
        self.pending = None
        self.request_id = 0
        self.write_lock = threading.Lock()
        info = Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0]
        self.bus.register_object(AGENT_PATH, info, self.agent, None, None)
        for interface, member in [(PROPS, "PropertiesChanged"),
                                  ("org.freedesktop.DBus.ObjectManager", "InterfacesAdded"),
                                  ("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved")]:
            self.bus.signal_subscribe(BLUEZ, interface, member, None, None,
                                      Gio.DBusSignalFlags.NONE, self.changed)
        Gio.bus_watch_name_on_connection(self.bus, BLUEZ, Gio.BusNameWatcherFlags.NONE,
                                         self.appeared, self.vanished)

    def emit(self, **data):
        with self.write_lock:
            print(json.dumps(data), flush=True)

    def call(self, path, interface, method, args=None, timeout=5000):
        return self.bus.call_sync(BLUEZ, path, interface, method, args, None,
                                  Gio.DBusCallFlags.NONE, timeout, None)

    def appeared(self, *_):
        def register():
            try:
                self.call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                          GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")))
                self.call("/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent",
                          GLib.Variant("(o)", (AGENT_PATH,)))
                self.emit(agentReady=True)
            except GLib.Error as error:
                self.emit(error="Pairing agent unavailable: " + error.message)
            GLib.idle_add(self.refresh)
        threading.Thread(target=register, daemon=True).start()

    def vanished(self, *_):
        self.objects = {}
        self.scan_path = None
        self.cancel_scan_timer()
        self.cancel_prompt()
        self.emit(available=False, adapters=[], devices=[], error="Bluetooth service unavailable")

    def changed(self, *_):
        if not self.refresh_timer:
            self.refresh_timer = GLib.timeout_add(150, self.refresh)

    def refresh(self):
        self.refresh_timer = 0
        self.bus.call(BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                      None, None, Gio.DBusCallFlags.NONE, 5000, None, self.snapshot)
        return False

    def snapshot(self, bus, result):
        try:
            self.objects = bus.call_finish(result).unpack()[0]
            adapters, devices = [], []
            for path, interfaces in self.objects.items():
                if ADAPTER in interfaces:
                    p = interfaces[ADAPTER]
                    adapters.append({"path": path, "name": p.get("Alias", "Bluetooth"),
                                     "powered": p.get("Powered", False), "scanning": p.get("Discovering", False)})
                if DEVICE in interfaces:
                    p = interfaces[DEVICE]
                    devices.append({"path": path, "name": p.get("Alias", p.get("Address", "Unknown device")),
                                    "address": p.get("Address", ""), "icon": p.get("Icon", "bluetooth"),
                                    "paired": p.get("Paired", False), "connected": p.get("Connected", False),
                                    "trusted": p.get("Trusted", False), "rssi": p.get("RSSI"),
                                    "adapter": p.get("Adapter", "")})
            devices.sort(key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))
            self.emit(available=True, adapters=adapters, devices=devices)
        except GLib.Error as error:
            self.emit(available=False, adapters=[], devices=[], error=error.message[:300])

    def cancel_prompt(self):
        if self.pending:
            _, invocation, _ = self.pending
            self.pending = None
            invocation.return_dbus_error("org.bluez.Error.Canceled", "Pairing cancelled")
        self.emit(prompt=None)

    def agent(self, connection, sender, path, interface, method, params, invocation):
        if method in {"Release", "Cancel"}:
            self.cancel_prompt()
            invocation.return_value(None)
            return
        values = params.unpack()
        device = self.objects.get(values[0], {}).get(DEVICE, {})
        name = device.get("Alias", "Bluetooth device")
        if method.startswith("Display"):
            self.emit(prompt={"id": 0, "kind": "display", "name": name,
                              "message": str(values[1]).zfill(6) if method == "DisplayPasskey" else values[1]})
            invocation.return_value(None)
            return
        self.cancel_prompt()
        self.request_id += 1
        kind = "pin" if method == "RequestPinCode" else "passkey" if method == "RequestPasskey" else "confirm"
        self.pending = (self.request_id, invocation, kind)
        detail = str(values[1]).zfill(6) if method == "RequestConfirmation" else "Allow Bluetooth authentication?"
        self.emit(prompt={"id": self.request_id, "kind": kind, "name": name, "message": detail})
        request_id = self.request_id
        def expire():
            if self.pending and self.pending[0] == request_id:
                self.cancel_prompt()
            return False
        GLib.timeout_add_seconds(60, expire)

    def respond(self, request):
        if not self.pending or request.get("id") != self.pending[0]:
            return
        _, invocation, kind = self.pending
        self.pending = None
        value = str(request.get("value", ""))
        if not request.get("accept"):
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Rejected by user")
        elif kind == "pin" and 1 <= len(value) <= 16 and value.isascii():
            invocation.return_value(GLib.Variant("(s)", (value,)))
        elif kind == "passkey" and value.isascii() and value.isdigit() and len(value) <= 6:
            invocation.return_value(GLib.Variant("(u)", (int(value),)))
        elif kind == "confirm":
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.bluez.Error.Rejected", "Invalid PIN or passkey")
            self.emit(error="Invalid PIN or passkey")
        self.emit(prompt=None)

    def dispatch(self, request):
        action = request.get("action")
        if action == "respond":
            self.respond(request)
            return False
        if action == "refresh":
            self.refresh()
            return False
        if self.busy:
            self.emit(error="Wait for the current Bluetooth operation")
            return False
        path = request.get("path", "")
        adapter_action = action in {"power", "scan", "stop"}
        interface = ADAPTER if adapter_action else DEVICE
        if interface not in self.objects.get(path, {}):
            self.emit(error="Adapter or device is no longer available")
            return False
        props = self.objects[path][interface]
        self.busy = True
        self.emit(busy=True, action=action, pendingPath=path, error="")
        def worker():
            try:
                if action in {"power", "trust"}:
                    if not isinstance(request.get("value"), bool):
                        raise ValueError("Expected on/off value")
                    self.call(path, PROPS, "Set", GLib.Variant("(ssv)",
                              (interface, "Powered" if action == "power" else "Trusted",
                               GLib.Variant("b", request["value"]))))
                elif action == "scan":
                    self.call(path, ADAPTER, "StartDiscovery")
                    self.scan_path = path
                    GLib.idle_add(self.arm_scan_timer)
                elif action == "stop":
                    if self.scan_path == path:
                        self.call(path, ADAPTER, "StopDiscovery")
                    self.scan_path = None
                    GLib.idle_add(self.cancel_scan_timer)
                elif action == "remove":
                    self.call(props["Adapter"], ADAPTER, "RemoveDevice", GLib.Variant("(o)", (path,)))
                elif action in {"pair", "connect", "disconnect", "cancel"}:
                    method = {"pair": "Pair", "connect": "Connect", "disconnect": "Disconnect", "cancel": "CancelPairing"}[action]
                    try:
                        self.call(path, DEVICE, method, timeout=65000 if action == "pair" else 20000)
                    except GLib.Error:
                        if action == "pair":
                            try:
                                self.call(path, DEVICE, "CancelPairing")
                            except GLib.Error:
                                pass
                        raise
                else:
                    raise ValueError("Unsupported Bluetooth operation")
                self.emit(message="Bluetooth operation completed", error="")
            except (GLib.Error, ValueError, KeyError) as error:
                self.emit(error=operation_error(action, error))
            finally:
                self.busy = False
                self.emit(busy=False, pendingPath="")
                if action == "pair":
                    GLib.idle_add(self.cancel_prompt)
                GLib.idle_add(self.refresh)
        threading.Thread(target=worker, daemon=True).start()
        return False

    def cancel_scan_timer(self):
        if self.scan_timer:
            GLib.source_remove(self.scan_timer)
            self.scan_timer = 0
        return False

    def arm_scan_timer(self):
        self.cancel_scan_timer()
        self.scan_timer = GLib.timeout_add_seconds(SCAN_SECONDS, self.scan_expired)
        return False

    def scan_expired(self):
        self.scan_timer = 0
        return self.stop_scan()

    def stop_scan(self):
        self.cancel_scan_timer()
        if self.scan_path:
            path, self.scan_path = self.scan_path, None
            self.bus.call(BLUEZ, path, ADAPTER, "StopDiscovery", None, None,
                          Gio.DBusCallFlags.NONE, 5000, None, None)
        return False

    def read_input(self):
        while True:
            line = sys.stdin.readline(8193)
            if not line:
                GLib.idle_add(self.shutdown)
                return
            try:
                if len(line) > 8192:
                    raise ValueError("Request too large")
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Invalid request")
                GLib.idle_add(self.dispatch, request)
            except ValueError as error:
                self.emit(error=str(error))

    def shutdown(self):
        self.stop_scan()
        self.cancel_prompt()
        self.loop.quit()
        return False

    def run(self):
        threading.Thread(target=self.read_input, daemon=True).start()
        self.loop.run()


if __name__ == "__main__":
    try:
        Bridge().run()
    except (GLib.Error, OSError) as error:
        print(json.dumps({"available": False, "error": str(error)[:300]}), flush=True)
        sys.exit(1)
