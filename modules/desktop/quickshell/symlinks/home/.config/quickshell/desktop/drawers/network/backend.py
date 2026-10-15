#!/usr/bin/env python3
"""One JSON request on stdin, one JSON reply. NetworkManager owns connection lifetime.

Secrets travel over stdin and D-Bus, never argv, logs, or status snapshots. No
discovery happens here unless explicitly requested by the visible drawer.
"""

import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time
import uuid


def command(argv, timeout=20):
    try:
        return subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError:
        raise ValueError(f"{argv[0]} is not installed.") from None
    except subprocess.TimeoutExpired:
        raise ValueError("The operation timed out. Refresh to check its current state.") from None


def checked(argv, timeout=20):
    result = command(argv, timeout)
    if result.returncode:
        # CLI diagnostics can echo credentials/configuration. Never forward them.
        raise ValueError("The action failed. Check service availability and desktop authorization.")
    return result.stdout.strip()


WARP_MODES = ("warp+doh", "warp+dot", "warp", "doh", "dot", "tunnel_only", "proxy")


def warp_mode(value):
    return {"WarpWithDnsOverHttps": "warp+doh", "WarpWithDnsOverTls": "warp+dot",
            "DnsOverHttps": "doh", "DnsOverTls": "dot", "Warp": "warp",
            "TunnelOnly": "tunnel_only", "WarpProxy": "proxy"}.get(value, value)


def warp_status():
    if not shutil.which("warp-cli"):
        return {"available": False, "state": "Not installed", "connected": False, "running": False, "mode": ""}
    service = command(["systemctl", "show", "warp-svc.service", "--property=ActiveState", "--value"])
    state = service.stdout.strip()
    if state not in ("active", "activating", "reloading"):
        return {"available": True, "state": "Off · daemon stopped", "connected": False, "running": False, "mode": ""}
    result = command(["warp-cli", "--no-ansi", "status"])
    match = re.search(r"^Status update:\s*(\w+)", result.stdout, re.M)
    status = match.group(1) if match else "Unavailable · check WARP registration"
    mode = command(["warp-cli", "--no-ansi", "settings"])
    mode_match = re.search(r"(?:WarpMode|WARP mode|Mode):\s*(\S+)", mode.stdout, re.I)
    return {"available": True, "state": status, "running": True, "connected": status.lower() == "connected",
            "mode": warp_mode(mode_match.group(1)) if mode_match else ""}


def warp_control(request):
    action = request.get("action")
    if action == "disconnect":
        # Even a broken/missing registration must not prevent stopping the daemon.
        command(["warp-cli", "--accept-tos", "disconnect"])
        checked(["systemctl", "--no-ask-password", "stop", "warp-svc.service"], 45)
        return
    if action not in ("connect", "mode"):
        raise ValueError("Unknown WARP action.")
    mode = request.get("mode", "warp+doh")
    if mode not in WARP_MODES:
        raise ValueError("Choose a supported WARP mode.")
    if action == "mode":
        checked(["warp-cli", "--accept-tos", "mode", mode])
        return
    try:
        checked(["systemctl", "--no-ask-password", "start", "warp-svc.service"], 45)
        # systemd's start reply can precede readiness of the daemon's IPC socket.
        for attempt in range(30):
            probe = command(["warp-cli", "--accept-tos", "--json", "status"])
            try:
                code = json.loads(probe.stdout or probe.stderr).get("code")
            except (ValueError, AttributeError):
                code = None
            if code != "FailedToConnectToDaemon":
                break
            time.sleep(0.2)
        else:
            raise ValueError("WARP daemon did not become ready. Check warp-svc.service.")
        # Registration is explicit in the UI, never inferred from an arbitrary failure.
        if request.get("register"):
            checked(["warp-cli", "--accept-tos", "registration", "new"])
        elif code == "MissingRegistration":
            raise ValueError("WARP needs registration. Enable Register on new connect in settings, then connect again.")
        checked(["warp-cli", "--accept-tos", "mode", mode])
        checked(["warp-cli", "--accept-tos", "connect"])
    except ValueError:
        # A failed start/registration/connect must not leave an idle daemon behind.
        checked(["systemctl", "--no-ask-password", "stop", "warp-svc.service"], 45)
        raise


def security(ap, NM):
    flags_type = getattr(NM, "80211ApSecurityFlags")
    flags = int(ap.get_wpa_flags()) | int(ap.get_rsn_flags())
    if flags & int(flags_type.KEY_MGMT_SAE):
        return "sae"
    if flags & int(flags_type.KEY_MGMT_802_1X):
        return "enterprise"
    if flags & int(flags_type.KEY_MGMT_PSK):
        return "wpa-psk"
    if flags & int(flags_type.KEY_MGMT_OWE | flags_type.KEY_MGMT_OWE_TM):
        return "owe"
    return "wep" if int(ap.get_flags()) & int(getattr(NM, "80211ApFlags").PRIVACY) else "open"


def ssid_text(value):
    return bytes(value.get_data()).decode("utf-8", errors="replace") if value else ""


def ip_details(device):
    lines = []
    for label, config in (("IPv4", device.get_ip4_config()), ("IPv6", device.get_ip6_config())):
        if not config:
            continue
        addresses = [f"{a.get_address()}/{a.get_prefix()}" for a in config.get_addresses()]
        if addresses:
            lines.append(f"{label}: {', '.join(addresses)}")
        if config.get_gateway():
            lines.append(f"{label} gateway: {config.get_gateway()}")
        if config.get_nameservers():
            lines.append(f"{label} DNS: {', '.join(config.get_nameservers())}")
    return "\n".join(lines)


def traffic_counters(interface):
    """Local interface counters only; never perform a speed test or send traffic."""
    if not re.fullmatch(r"[\w.:-]{1,15}", interface) or interface in (".", ".."):
        return {}
    directory = Path("/sys/class/net") / interface / "statistics"
    try:
        return {"received": int((directory / "rx_bytes").read_text()),
                "sent": int((directory / "tx_bytes").read_text())}
    except (OSError, ValueError):
        return {}


class Network:
    def __init__(self):
        import gi
        gi.require_version("NM", "1.0")
        from gi.repository import GLib, Gio, NM
        self.NM, self.GLib, self.Gio = NM, GLib, Gio
        self.client = NM.Client.new(None)
        if not self.client.get_nm_running():
            raise ValueError("NetworkManager is not running.")

    def call(self, owner, method, *args):
        loop = self.GLib.MainLoop()
        result = {}
        cancel = self.Gio.Cancellable()

        def finished(source, response, *_):
            try:
                result["value"] = getattr(source, method.removesuffix("_async") + "_finish")(response)
            except self.GLib.Error as error:
                # Scans are routinely refused during radio transitions, while
                # associating, or within the driver's scan rate limit. Cached
                # access points remain valid; this is not an authentication error.
                not_allowed = (error.matches(self.NM.DeviceError.quark(), self.NM.DeviceError.NOTALLOWED)
                               or (self.Gio.DBusError.is_remote_error(error) and self.Gio.DBusError.get_remote_error(error)
                                   == "org.freedesktop.NetworkManager.Device.NotAllowed"))
                if method == "request_scan_async" and not_allowed:
                    result["value"] = False
                else:
                    result["error"] = error
            loop.quit()

        def timeout():
            result["error"] = True
            cancel.cancel()
            loop.quit()
            return False

        timer = self.GLib.timeout_add_seconds(45, timeout)
        getattr(owner, method)(*args, cancel, finished, None)
        loop.run()
        if not cancel.is_cancelled():
            self.GLib.source_remove(timer)
        if result.get("error"):
            error = result["error"]
            if isinstance(error, self.GLib.Error) and error.matches(self.NM.ManagerError.quark(), self.NM.ManagerError.PERMISSIONDENIED):
                raise ValueError("NetworkManager denied permission. Check desktop authorization.")
            if method == "request_scan_async":
                raise ValueError("Could not scan for networks. Try again shortly.")
            raise ValueError("NetworkManager could not finish this action. Retry or open the connection editor.")
        return result.get("value")

    def profile(self, identity):
        if not isinstance(identity, str):
            raise ValueError("Select a saved profile.")
        profile = self.client.get_connection_by_uuid(identity)
        if not profile or profile.get_connection_type() not in ("802-11-wireless", "802-3-ethernet", "vpn", "wireguard"):
            raise ValueError("This profile is no longer available. Refresh and try again.")
        return profile

    def device(self, interface):
        device = self.client.get_device_by_iface(interface or "")
        if not device:
            raise ValueError("This adapter is no longer available.")
        return device

    def snapshot(self):
        NM = self.NM
        active = {a.get_uuid(): a for a in self.client.get_active_connections()}
        profiles = []
        for c in self.client.get_connections():
            kind = c.get_connection_type()
            if kind not in ("802-11-wireless", "802-3-ethernet", "vpn", "wireguard"):
                continue
            wifi = c.get_setting_wireless()
            a = active.get(c.get_uuid())
            profiles.append({"uuid": c.get_uuid(), "name": c.get_id(), "kind": kind,
                             "ssid": ssid_text(wifi.get_ssid()) if wifi else "",
                             "autoconnect": c.get_setting_connection().get_autoconnect(),
                             "active": bool(a), "state": a.get_state().value_nick if a else "disconnected"})
        adapters, wired, networks = [], [], []
        for d in self.client.get_devices():
            kind = d.get_device_type()
            if kind not in (NM.DeviceType.WIFI, NM.DeviceType.ETHERNET):
                continue
            a = d.get_active_connection()
            entry = {"interface": d.get_iface(), "name": d.get_description() or d.get_iface(),
                     "state": d.get_state().value_nick, "connected": d.get_state() == NM.DeviceState.ACTIVATED,
                     "uuid": a.get_uuid() if a else "", "connection": a.get_id() if a else "",
                     "details": ip_details(d), "mac": d.get_hw_address() or "",
                     "traffic": traffic_counters(d.get_iface()) if d.get_state() == NM.DeviceState.ACTIVATED else {}}
            if kind == NM.DeviceType.ETHERNET:
                entry.update(carrier=d.get_carrier(), speed=d.get_speed())
                wired.append(entry)
                continue
            entry["speed"] = round(d.get_bitrate() / 1000, 1)
            adapters.append(entry)
            current = d.get_active_access_point()
            grouped = {}
            for ap in d.get_access_points():
                raw = ap.get_ssid()
                if not raw:
                    continue
                sec = security(ap, NM)
                identity = bytes(raw.get_data()).hex() + ":" + sec
                previous = grouped.get(identity)
                if previous is None or ap == current or (previous != current and ap.get_strength() > previous.get_strength()):
                    grouped[identity] = ap
            for identity, ap in grouped.items():
                matches = [c for c in self.client.get_connections() if ap.connection_valid(c)]
                matches.sort(key=lambda c: (c.get_uuid() not in active, c.get_id().casefold()))
                c = matches[0] if matches else None
                networks.append({"key": d.get_iface() + ":" + identity, "ssid": ssid_text(ap.get_ssid()),
                                 "ap": ap.get_path(), "interface": d.get_iface(), "security": security(ap, NM),
                                 "strength": ap.get_strength(), "frequency": ap.get_frequency(),
                                 "bssid": ap.get_bssid(), "connected": ap == current and entry["connected"],
                                 "uuid": c.get_uuid() if c else ""})
        networks.sort(key=lambda n: (not n["connected"], not bool(n["uuid"]), -n["strength"], n["ssid"].casefold()))
        return {"available": True, "wifiEnabled": self.client.wireless_get_enabled(),
                "hardwareEnabled": self.client.wireless_hardware_get_enabled(),
                "connectivity": self.client.get_connectivity().value_nick,
                "adapters": adapters, "wired": wired, "networks": networks, "profiles": profiles,
                "sampleTime": time.monotonic()}

    def wait_active(self, active):
        NM = self.NM
        if active.get_state() == NM.ActiveConnectionState.ACTIVATED:
            return
        loop = self.GLib.MainLoop()
        timed_out = []

        def changed(*_):
            if active.get_state() in (NM.ActiveConnectionState.ACTIVATED, NM.ActiveConnectionState.DEACTIVATED):
                loop.quit()

        def timeout():
            timed_out.append(True)
            loop.quit()
            return False

        handler = active.connect("state-changed", changed)
        timer = self.GLib.timeout_add_seconds(50, timeout)
        if active.get_state() not in (NM.ActiveConnectionState.ACTIVATED, NM.ActiveConnectionState.DEACTIVATED):
            loop.run()
        active.disconnect(handler)
        if not timed_out:
            self.GLib.source_remove(timer)
        if active.get_state() != NM.ActiveConnectionState.ACTIVATED:
            raise ValueError("Could not connect. Check the password and signal, or edit this connection.")

    def connect(self, request):
        NM, GLib = self.NM, self.GLib
        device = self.device(request["interface"]) if request.get("interface") else None
        if request.get("uuid"):
            connection = self.profile(request["uuid"])
            existing = next((a for a in self.client.get_active_connections()
                             if a.get_uuid() == request["uuid"] and (not device or device in a.get_devices()) and a.get_state() in
                             (NM.ActiveConnectionState.ACTIVATED, NM.ActiveConnectionState.ACTIVATING)), None)
            if existing and not request.get("password"):
                self.wait_active(existing)
                return
            if request.get("password"):
                sec = connection.get_setting_wireless_security()
                if not sec or sec.get_key_mgmt() not in ("wpa-psk", "sae"):
                    raise ValueError("Use the connection editor to change these credentials.")
                sec.set_property("psk", request["password"])
                sec.set_secret_flags("psk", NM.SettingSecretFlags.NONE)
                self.call(connection, "commit_changes_async", True)
            active = self.call(self.client, "activate_connection_async", connection, device, None)
        elif device and device.get_device_type() == NM.DeviceType.ETHERNET:
            method = "activate_connection_async" if device.get_available_connections() else "add_and_activate_connection_async"
            active = self.call(self.client, method, None, device, None)
        else:
            ssid = request.get("ssid", "")
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or "\x00" in ssid:
                raise ValueError("The network name must contain 1–32 bytes.")
            sec = request.get("security", "open")
            if sec not in ("open", "owe", "wpa-psk", "sae"):
                raise ValueError("Use the connection editor for enterprise or WEP authentication.")
            password = request.get("password", "")
            if sec == "wpa-psk" and not (8 <= len(password) <= 63 or re.fullmatch(r"[0-9a-fA-F]{64}", password)):
                raise ValueError("WPA passwords need 8–63 characters or a 64-digit hexadecimal key.")
            if sec == "sae" and not 1 <= len(password) <= 63:
                raise ValueError("Enter a WPA3 password of 1–63 characters.")
            connection = NM.SimpleConnection.new()
            setting = NM.SettingConnection.new()
            setting.set_property("id", ssid)
            setting.set_property("uuid", str(uuid.uuid4()))
            setting.set_property("type", "802-11-wireless")
            setting.set_property("autoconnect", bool(request.get("autoconnect", True)))
            setting.add_permission("user", pwd.getpwuid(os.getuid()).pw_name, None)
            connection.add_setting(setting)
            wifi = NM.SettingWireless.new()
            wifi.set_property("ssid", GLib.Bytes.new(ssid.encode()))
            wifi.set_property("mode", "infrastructure")
            wifi.set_property("hidden", bool(request.get("hidden")))
            connection.add_setting(wifi)
            if sec != "open":
                auth = NM.SettingWirelessSecurity.new()
                auth.set_property("key-mgmt", sec)
                if sec in ("wpa-psk", "sae"):
                    auth.set_property("psk", password)
                connection.add_setting(auth)
            connection.normalize()
            active = self.call(self.client, "add_and_activate_connection_async", connection, device, request.get("ap"))
        self.wait_active(active)

    def control(self, request):
        op = request["op"]
        if op == "connect":
            self.connect(request)
        elif op == "disconnect":
            matches = [a for a in self.client.get_active_connections() if a.get_uuid() == request.get("uuid")]
            for a in matches:
                self.call(self.client, "deactivate_connection_async", a)
        elif op == "forget":
            profile = self.profile(request.get("uuid"))
            if profile.get_connection_type() != "802-11-wireless":
                raise ValueError("Only saved Wi-Fi profiles can be forgotten here.")
            self.call(profile, "delete_async")
        elif op == "autoconnect":
            profile = self.profile(request.get("uuid"))
            profile.get_setting_connection().set_property("autoconnect", bool(request.get("enabled")))
            self.call(profile, "commit_changes_async", True)
        elif op == "radio":
            # nmcli waits for the D-Bus reply and reports denied permission.
            checked(["nmcli", "radio", "wifi", "on" if request.get("enabled") else "off"])
        elif op == "scan":
            device = self.device(request.get("interface"))
            if (self.client.wireless_get_enabled() and self.client.wireless_hardware_get_enabled()
                    and device.get_state() in (self.NM.DeviceState.DISCONNECTED, self.NM.DeviceState.ACTIVATED)):
                self.call(device, "request_scan_async")
        elif op == "check":
            self.call(self.client, "check_connectivity_async")
        elif op == "import":
            path = Path(request.get("path", "")).expanduser()
            if not path.is_file() or path.suffix != ".conf" or path.stat().st_size > 262144:
                raise ValueError("Choose a WireGuard .conf file smaller than 256 KiB.")
            text = path.read_text()
            if re.search(r"^\s*(PreUp|PostUp|PreDown|PostDown|Table|SaveConfig)\s*=", text, re.M | re.I):
                raise ValueError("This file needs wg-quick hooks or routing options. Import a NetworkManager-compatible config.")
            connection = self.NM.conn_wireguard_import(str(path))
            setting = connection.get_setting_connection()
            setting.set_property("autoconnect", False)
            setting.add_permission("user", pwd.getpwuid(os.getuid()).pw_name, None)
            self.call(self.client, "add_connection_async", connection, True)
        elif op != "status":
            raise ValueError("Unknown network operation.")


def handle(request):
    if request.get("op") == "warp":
        warp_control(request)
    network = Network()
    if request.get("op") != "warp":
        network.control(request)
    # The radio CLI may have changed D-Bus state while the GLib context was
    # blocked. Recreate its client to read a coherent final snapshot.
    if request.get("op") == "radio":
        network = Network()
    snapshot = network.snapshot()
    try:
        snapshot["warp"] = warp_status()
    except ValueError:
        snapshot["warp"] = {"available": bool(shutil.which("warp-cli")), "running": False,
                            "connected": False, "state": "WARP status unavailable", "mode": ""}
    return snapshot


def main():
    try:
        request = json.loads(sys.stdin.readline(65536))
        result = {"ok": True, "data": handle(request)}
    except ValueError as error:
        result = {"ok": False, "error": str(error)}
    except ImportError:
        result = {"ok": False, "error": "Install python-gobject and NetworkManager to use network controls."}
    except Exception:
        # libnm exceptions may contain configuration values. Keep the boundary quiet.
        result = {"ok": False, "error": "Network control failed. Check NetworkManager, WARP and desktop authorization."}
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
