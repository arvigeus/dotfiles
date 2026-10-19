"""Network boundaries and the production Wi-Fi drawer, without changing host networking."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

DESKTOP = (Path(__file__).resolve().parents[1] / 'modules/desktop/quickshell'
           / 'symlinks/home/.config/quickshell/desktop')
SPEC = importlib.util.spec_from_file_location('desktop_network', DESKTOP / 'drawers/network/backend.py')
backend = importlib.util.module_from_spec(SPEC)
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
SPEC.loader.exec_module(backend)
sys.dont_write_bytecode = _bytecode_disabled
QS = shutil.which('qs')
try:
    import gi
    gi.require_version('NM', '1.0')
    from gi.repository import NM
except (ImportError, ValueError):
    NM = None


class WarpTests(unittest.TestCase):
    def test_start_waits_for_daemon_and_never_registers_implicitly(self):
        replies = [Mock(stdout='{"code":"FailedToConnectToDaemon"}', stderr=''),
                   Mock(stdout='{"code":"MissingRegistration"}', stderr='')]
        with patch.object(backend, 'checked') as checked, patch.object(backend, 'command', side_effect=replies), patch.object(backend.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'needs registration'):
                backend.warp_control({'action': 'connect', 'mode': 'doh'})
        self.assertEqual(checked.call_args_list[0].args[0], ['systemctl', '--no-ask-password', 'start', 'warp-svc.service'])
        self.assertFalse(any('new' in call.args[0] for call in checked.call_args_list))

    def test_explicit_registration_mode_and_stop(self):
        with patch.object(backend, 'checked') as checked, patch.object(backend, 'command', return_value=Mock(stdout='{}', stderr='')):
            backend.warp_control({'action': 'connect', 'mode': 'tunnel_only', 'register': True})
            calls = [c.args[0] for c in checked.call_args_list]
            self.assertIn(['warp-cli', '--accept-tos', 'registration', 'new'], calls)
            self.assertIn(['warp-cli', '--accept-tos', 'mode', 'tunnel_only'], calls)
            checked.reset_mock()
            backend.warp_control({'action': 'disconnect'})
            self.assertEqual(checked.call_args_list[-1].args[0], ['systemctl', '--no-ask-password', 'stop', 'warp-svc.service'])

    def test_failed_connection_stops_daemon(self):
        def fail_connect(argv, timeout=20):
            if argv == ['warp-cli', '--accept-tos', 'connect']:
                raise ValueError('Connection failed')
            return ''
        with patch.object(backend, 'checked', side_effect=fail_connect) as checked, \
                patch.object(backend, 'command', return_value=Mock(stdout='{}', stderr='')):
            with self.assertRaisesRegex(ValueError, 'Connection failed'):
                backend.warp_control({'action': 'connect', 'mode': 'warp+doh'})
            self.assertEqual(checked.call_args_list[-1].args[0],
                             ['systemctl', '--no-ask-password', 'stop', 'warp-svc.service'])

    def test_mode_changes_do_not_start_or_register_daemon(self):
        with patch.object(backend, 'checked') as checked:
            for mode in backend.WARP_MODES:
                backend.warp_control({'action': 'mode', 'mode': mode})
            self.assertEqual(len(checked.call_args_list), 7)
            self.assertTrue(all(c.args[0][:3] == ['warp-cli', '--accept-tos', 'mode'] for c in checked.call_args_list))
            with self.assertRaisesRegex(ValueError, 'supported WARP mode'):
                backend.warp_control({'action': 'mode', 'mode': 'invalid'})
        self.assertEqual(backend.warp_mode('WarpWithDnsOverHttps'), 'warp+doh')
        self.assertEqual(backend.warp_mode('WarpWithDnsOverTls'), 'warp+dot')

    @unittest.skipUnless(shutil.which('node'), 'Node is required to evaluate the polkit rule')
    def test_warp_policy_only_allows_local_active_start_stop(self):
        policy = DESKTOP.parents[4] / 'files/etc/polkit-1/rules.d/50-desktop-warp.rules'
        script = '''const fs = require('fs'), vm = require('vm');
let rule;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
 polkit: {addRule: callback => rule = callback, Result: {YES: 'yes'}}
});
function allowed(unit, verb, local = true, active = true, id = 'org.freedesktop.systemd1.manage-units') {
 return rule({id, lookup: key => ({unit, verb})[key]}, {local, active}) === 'yes';
}
if (!allowed('warp-svc.service', 'start') || !allowed('warp-svc.service', 'stop')
 || allowed('sshd.service', 'start') || allowed('warp-svc.service', 'restart')
 || allowed('warp-svc.service', 'start', false) || allowed('warp-svc.service', 'start', true, false)
 || allowed('warp-svc.service', 'start', true, true, 'org.freedesktop.systemd1.manage-unit-files')) process.exit(1);
'''
        result = subprocess.run(['node', '-e', script, str(policy)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_errors_never_expose_output(self):
        with patch.object(backend, 'command', return_value=Mock(returncode=1, stderr='private-key-and-password', stdout='')):
            with self.assertRaises(ValueError) as error:
                backend.checked(['nmcli'])
        self.assertNotIn('private-key', str(error.exception))


@unittest.skipUnless(NM, 'libnm introspection is required')
class NetworkTests(unittest.TestCase):
    def network(self):
        n = backend.Network.__new__(backend.Network)
        from gi.repository import GLib, Gio
        n.NM, n.GLib, n.Gio = NM, GLib, Gio
        n.client = Mock(get_active_connections=lambda: [])
        n.device = Mock(return_value=Mock(get_device_type=lambda: NM.DeviceType.WIFI))
        n.call = Mock(return_value=Mock())
        n.wait_active = Mock()
        return n

    def test_hidden_password_uses_dbus_and_preserves_ssid(self):
        n = self.network()
        secret = 'test-private-password'
        ssid = '  cafe:back\\slash  '
        with patch.object(backend, 'command') as command:
            n.connect({'ssid': ssid, 'security': 'wpa-psk', 'password': secret,
                       'interface': 'wlan0', 'hidden': True, 'autoconnect': False})
        connection = n.call.call_args.args[2]
        self.assertEqual(backend.ssid_text(connection.get_setting_wireless().get_ssid()), ssid)
        self.assertTrue(connection.get_setting_wireless().get_hidden())
        self.assertFalse(connection.get_setting_connection().get_autoconnect())
        self.assertEqual(connection.get_setting_connection().get_num_permissions(), 1)
        self.assertEqual(connection.get_setting_wireless_security().get_psk(), secret)
        command.assert_not_called()

    def test_validation_does_not_create_profiles(self):
        for request in [{'ssid': 'x' * 33}, {'ssid': 'cafe', 'security': 'wpa-psk', 'password': 'short'},
                        {'ssid': 'cafe', 'security': 'enterprise'}]:
            n = self.network()
            with self.assertRaises(ValueError):
                n.connect(request)
            n.call.assert_not_called()

    def test_wired_activation_uses_device_without_wifi_settings(self):
        n = self.network()
        device = Mock(get_device_type=lambda: NM.DeviceType.ETHERNET)
        n.device.return_value = device
        n.connect({'interface': 'eth0'})
        self.assertEqual(n.call.call_args.args, (n.client, 'activate_connection_async', None, device, None))

    def test_import_rejects_hooks_without_touching_networkmanager(self):
        n = self.network()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.conf'
            path.write_text('[Interface]\nPostUp=echo secret\n[Peer]\n')
            with self.assertRaisesRegex(ValueError, 'wg-quick'):
                n.control({'op': 'import', 'path': str(path)})
        n.call.assert_not_called()

    def test_scans_skip_radio_transitions(self):
        n = self.network()
        n.device.return_value.get_state.return_value = NM.DeviceState.CONFIG
        n.control({'op': 'scan', 'interface': 'wlan0'})
        n.call.assert_not_called()

    def test_scan_not_allowed_is_not_authentication_failure(self):
        n = self.network()
        owner = Mock()
        def finish(_response):
            raise n.GLib.Error.new_literal(NM.DeviceError.quark(), 'Scanning not allowed', NM.DeviceError.NOTALLOWED)
        owner.request_scan_finish = finish
        def start(cancel, callback, data):
            n.GLib.idle_add(lambda: callback(owner, None))
        owner.request_scan_async = start
        self.assertFalse(backend.Network.call(n, owner, 'request_scan_async'))

    def test_connect_reuses_an_already_active_profile(self):
        n = self.network()
        active = Mock(get_uuid=lambda: 'saved', get_state=lambda: NM.ActiveConnectionState.ACTIVATED)
        n.client.get_active_connections = lambda: [active]
        n.profile = Mock()
        n.connect({'uuid': 'saved'})
        n.wait_active.assert_called_once_with(active)
        n.call.assert_not_called()

    def test_security_keeps_open_and_protected_networks_separate(self):
        flags = getattr(NM, '80211ApSecurityFlags')
        ap = Mock(get_flags=lambda: 0, get_wpa_flags=lambda: 0, get_rsn_flags=lambda: 0)
        self.assertEqual(backend.security(ap, NM), 'open')
        ap.get_rsn_flags = lambda: flags.KEY_MGMT_SAE | flags.KEY_MGMT_PSK
        self.assertEqual(backend.security(ap, NM), 'sae')
        ap.get_rsn_flags = lambda: flags.KEY_MGMT_802_1X
        self.assertEqual(backend.security(ap, NM), 'enterprise')


@unittest.skipUnless(QS, 'Quickshell is required')
class WifiDrawerTests(unittest.TestCase):
    def test_controls_errors_and_lifecycle(self):
        state = dict(available=True, wifiEnabled=True, hardwareEnabled=True, connectivity='portal',
                     adapters=[dict(interface='wlan0', state='activated', connected=True, connection='Home', details='IPv4: 192.0.2.2/24\nIPv4 gateway: 192.0.2.1\nIPv4 DNS: 192.0.2.1', mac='00:11:22:33:44:55', uuid='saved', speed=433)],
                     networks=[dict(key='new', ssid='<Cafe & guests>', interface='wlan0', security='wpa-psk', strength=85, frequency=5180, bssid='00:11:22:33:44:66', connected=False, uuid=''),
                               dict(key='home', ssid='Home', interface='wlan0', security='wpa-psk', strength=82, frequency=2412, bssid='00:11:22:33:44:77', connected=True, uuid='saved'),
                               dict(key='guest', ssid='Guest network', interface='wlan0', security='open', strength=42, frequency=2412, bssid='00:11:22:33:44:88', connected=False, uuid='')],
                     profiles=[dict(uuid='saved', name='Home', ssid='Home', kind='802-11-wireless', active=True, state='activated', autoconnect=True),
                               dict(uuid='vpn', name='Work', kind='wireguard', active=False, state='disconnected', autoconnect=False)],
                     wired=[dict(interface='eth0', state='unavailable', connected=False, carrier=False, speed=0, uuid='', connection='', details='')],
                     warp=dict(available=True, connected=False, running=False, state='Off · daemon stopped', mode=''))
        qml = '''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import "drawers"
import "ui" as UI
FloatingWindow {
 id: window
 implicitWidth: 480; implicitHeight: 900; color: UI.Theme.background
 Rectangle { anchors.fill: parent; color: UI.Theme.background }
 QtObject {
  id: fake
  property bool observing: false
  property bool loaded: true
  property bool busy: false
  property string interfaceName: "wlan0"
  property string error: ""
  property var traffic: ({wlan0: {down: 2048, up: 1024}})
  property string pending: ""
  property string pendingKey: ""
  property var state: STATE
  property var calls: []
  property string warpMode: "warp+doh"
  property bool warpRegisterNext: false
  function selectWarpMode(mode) { warpMode = mode; }
  function setWarpRegistration(value) { warpRegisterNext = value; }
  signal completed(string operation, bool success)
  function run(op, values = {}, key = "") { pendingKey = key; calls = calls.concat([{op, values, key}]); }
  function refresh() { run("status"); }
  function scan() { run("scan"); }
 }
 QtObject {
  id: speed
  property bool running: false
  property var result: null
  property string error: ""
  property int starts: 0
  function start() { starts++; running = true; }
  function cancel() { running = false; }
 }
 property var drawer: drawerLoader.item
 Item { id: preview; width: 480; height: 900
 Rectangle { anchors.fill: parent; color: UI.Theme.background }
 RowLayout {
  id: header
  x: 16; y: 16; width: 448; spacing: 12
  ColumnLayout {
   Layout.fillWidth: true; spacing: 2
   UI.ShellText { text: "Wi-Fi"; font.pixelSize: UI.Theme.titleFontSize; Layout.fillWidth: true; elide: Text.ElideRight }
  }
  Loader { sourceComponent: drawer?.headerActions ?? null }
  UI.ShellButton { text: "×"; Layout.preferredWidth: 34 }
 }
 Rectangle { x: 16; y: header.y + header.height + 16; width: 448; height: 1; color: UI.Theme.border }
 Loader {
  id: drawerLoader
  width: 448; height: 900 - y - 16; x: 16; y: header.y + header.height + 33
  asynchronous: true
  sourceComponent: Component {
   WifiDrawer { service: fake; speedTest: speed; active: true
    Rectangle { anchors.fill: parent; color: UI.Theme.background; z: -1 }
   }
  }
 }
 }
 TestCase { id: input; when: false; parent: window.contentItem }
 function find(item, name) {
  if (item.objectName === name) return item;
  for (const child of item.children || []) { const result = find(child, name); if (result) return result; }
  return null;
 }
 function check(value, message) { if (!value) throw new Error(message); }
 function capture(item, name) {
  const output = Quickshell.env("WIFI_PREVIEW_DIR") || "/tmp";
  const requested = item.grabToImage(result => console.log("PREVIEW_SAVED", name, result.saveToFile(output + "/" + name)));
  check(requested, "capture request failed: " + name);
 }
 property var savedNetworkRow: null
 property var savedVpnRow: null
 property real savedOffset: 0
 property int stage: 0
 Timer { interval: 150; running: drawerLoader.status === Loader.Ready; repeat: true; onTriggered: {
  try {
   let password = drawer.passwordField;
   const scroll = find(drawer, "networkScroll");
   if (window.stage === 0) {
    check(find(drawer, "wirelessSection").flat && find(drawer, "vpnSection").flat, "unexpected section background");
    check(!find(drawer, "savedNetworksSection") && !find(drawer, "hiddenNetworkSection"), "old management forms remain");
    check(!find(drawer, "ethernetSection").visible, "unplugged Ethernet is visible");
    check(drawer.headerActions !== null && !find(drawer, "networkEdit") && !find(drawer, "vpnEdit") && !find(drawer, "addVpn"), "management action is not confined to the header");
    check(!find(drawer, "connectionDetails") && !find(drawer, "connectionInfo"), "info controls remain");
    const row = find(drawer, "wifiNetwork:home");
    check(row.leftPadding >= 0 && !row.hint.includes("192.0.2.1") && row.hint.includes("82%"), "network tooltip lost signal or duplicated connection information");
    check(find(preview, "wifiInfo").iconName === "info", "connection information is not discoverable in header");
    check(find(drawer,"wirelessSection").hint === "", "Wireless heading retains hidden information");
    for (const name of ["wirelessSection", "ethernetSection", "vpnSection"])
     check(find(drawer, name).iconName === "" && find(drawer, name).leading === null, "section still has an icon");
    check(find(window.contentItem, "wifiScan") && !find(drawer, "wifiScan") && !find(drawer, "wifiToggle"), "power/scan did not move to header");
    check(row.foreground.toString() === UI.Theme.text.toString(), "connected row should use normal text");
    input.mouseMove(row, 8, row.height / 2);
    check(row.highlighted && row.foreground.toString() === UI.Theme.accent.toString(), "row hover did not cover icon and name");
    input.mouseMove(drawer, 0, drawer.height - 1);
    check(find(window.contentItem, "wifiToggle").checked && fake.calls.length === 0, "initial power read issued a mutation");
    const scan = find(window.contentItem, "wifiScan");
    input.mouseClick(scan, scan.width / 2, scan.height / 2);
    check(fake.calls.length === 1 && fake.calls[0].op === "scan", "header refresh did not request a scan");
    fake.calls = [];
    check(find(drawer, "downloadRate").text === "2.0 KiB/s", "compact transfer statistics missing");
    check(find(drawer, "networkActivity").foreground.toString() === UI.Theme.text.toString(), "spinner does not follow theme");
    capture(preview, "wifi-drawer-compact.png");
   } else if (window.stage === 1) {
    check(fake.observing && drawer.networks.length === 3, "activation/network list");
    const newNetwork = find(drawer, "wifiNetwork:new");
    input.mouseClick(newNetwork, 80, 20);
    password = drawer.passwordField;
    password.forceActiveFocus(); input.keyClick(Qt.Key_A);
    check(drawer.passwordText === "a", "password edit did not reach the model");
    drawer.passwordText = "retry-password";
    input.mouseClick(find(drawer, "wifiSubmit"), 16, 16);
    check(fake.calls[0].op === "connect" && fake.calls[0].values.password === "retry-password", "password dispatch");
    fake.error = "Incorrect password"; fake.completed("connect", false);
    check(password.text === "retry-password", "failure discarded password");
    fake.busy = true;
    check(!find(window.contentItem, "wifiToggle").enabled, "duplicate action allowed");
    drawer.active = false; check(!fake.observing, "observation survived dismissal");
    fake.completed("connect", true); check(password.text === "", "success retained password");
    drawer.active = true; fake.busy = false; fake.error = "";
    drawer.choose(fake.state.networks[0]);
    fake.selectWarpMode("tunnel_only");
    password = drawer.passwordField; drawer.passwordText = "keep-this-password"; password.forceActiveFocus();
   } else if (window.stage === 2) {
    const networkRow = find(drawer, "wifiNetwork:new");
    const body = scroll.contentChildren[0];
    const auth = find(drawer, "wifiAuthentication");
    const next = find(drawer, "wifiNetwork:guest");
    check(auth.visible && auth.mapToItem(body, 0, 0).y >= networkRow.mapToItem(body, 0, networkRow.height).y
        && auth.mapToItem(body, 0, auth.height).y < next.mapToItem(body, 0, 0).y, "password form is not under the selected network");
    check(auth.mapToItem(body, 0, 0).x > networkRow.mapToItem(body, 0, 0).x, "password form lacks extra indentation");
    const vpnRow = find(drawer, "networkProfile:vpn");
    const offset = scroll.contentItem.contentY;
    fake.pending = "status";
    check(find(window.contentItem, "wifiToggle").enabled, "background read disabled controls");
    fake.state = Object.assign({}, fake.state, {networks: fake.state.networks.map(n => Object.assign({}, n, {strength: 25})).reverse()});
    check(find(drawer, "wifiNetwork:new") === networkRow && find(drawer, "networkProfile:vpn") === vpnRow, "refresh recreated delegates");
    check(fake.warpMode === "tunnel_only", "refresh reset WARP preference");
    capture(preview, "wifi-drawer-password.png");
    check(password.activeFocus && password.text === "keep-this-password", "refresh lost form focus/text");
    check(scroll.contentItem.contentY === offset, "refresh moved scroll position");
    fake.pending = "";
    fake.state = Object.assign({}, fake.state, {hardwareEnabled: false});
    check(!find(window.contentItem, "wifiToggle").enabled, "hardware block ignored");
    fake.state = Object.assign({}, fake.state, {hardwareEnabled: true});
   } else if (window.stage === 3) {
    const row = find(drawer, "wifiNetwork:guest");
    input.mouseClick(row, row.width / 2, row.height / 2);
    check(fake.calls[fake.calls.length - 1].key === "guest", "row click did not connect");
    const vpn = find(drawer, "networkProfile:vpn");
    input.mouseClick(vpn, 8, vpn.height / 2);
    check(fake.calls[fake.calls.length - 1].values.uuid === "vpn", "VPN icon click did not connect");
    const toggle = find(window.contentItem, "wifiToggle");
    input.mouseClick(toggle, toggle.width / 2, toggle.height / 2);
    check(fake.calls[fake.calls.length - 1].op === "radio", "header switch did not toggle Wi-Fi");
    fake.state = Object.assign({}, fake.state, {wifiEnabled: false});
    check(!toggle.checked && !find(window.contentItem, "wifiScan").enabled, "power/scan state ignored readback");
    check(fake.calls.filter(c => c.op === "radio").length === 1 && fake.calls[fake.calls.length - 1].values.enabled === false, "readback issued extra radio requests");
    fake.state = Object.assign({}, fake.state, {wifiEnabled: true});
    check(toggle.checked, "external power update broke switch binding");
    input.mouseClick(find(drawer, "warpToggle"), 10, 20);
    check(fake.calls[fake.calls.length - 1].op === "warp" && fake.calls[fake.calls.length - 1].values.mode === "tunnel_only", "Cloudflare row click lost mode");
    fake.busy = true;
    capture(scroll.contentChildren[0], "wifi-drawer-full.png");
   } else if (window.stage === 4) {
    capture(preview, "wifi-drawer-loading.png");
   } else if (window.stage === 5) {
    fake.busy = false;
    drawer.selected = null;
    scroll.contentItem.contentY = 0; UI.Theme.setMode("light");
   } else if (window.stage === 6) {
    check(find(drawer, "networkActivity").foreground.toString() === UI.Theme.text.toString(), "spinner missed theme change");
    capture(preview, "wifi-drawer-light.png");
   } else if (window.stage === 7) {
    UI.Theme.setMode("dark");
    input.mouseClick(find(drawer, "warpSettings"), 16, 16);
   } else if (window.stage === 8) {
    const menu = find(drawer, "warpSettings").menu;
    const ordered = ["warp+doh", "warp+dot", "warp", "doh", "dot", "tunnel_only", "proxy"];
    for (let i = 0; i < ordered.length; i++) check(menu.itemAt(i).objectName === "warpMode:" + ordered[i], "async incubation changed menu order");
    check(menu.count === 9 && menu.itemAt(7).objectName === "warpModeSeparator" && menu.itemAt(8).objectName === "warpRegistration", "registration is not separate below the separator");
    const mode = menu.itemAt(5);
    check(mode && mode.checked && find(drawer, "warpSettings").menu.visible, "menu did not check the default mode");
    capture(find(drawer, "warpSettings").menu.contentItem.parent, "wifi-drawer-menu.png");
   } else if (window.stage === 9) {
    input.mouseClick(find(drawer, "warpSettings").menu.itemAt(3), 80, 18);
    check(fake.warpMode === "doh", "menu did not change the default mode");
    input.mouseClick(find(drawer, "warpSettings"), 16, 16);
   } else if (window.stage === 10) {
    check(find(drawer, "warpSettings").menu.itemAt(3).checked && !find(drawer, "warpSettings").menu.itemAt(5).checked, "mode checkmarks did not follow selection");
    input.mouseClick(find(drawer, "warpSettings").menu.itemAt(8), 80, 18);
    check(fake.warpRegisterNext, "registration menu item did not toggle");
    input.mouseClick(find(drawer, "warpSettings"), 16, 16);
   } else if (window.stage === 11) {
    const current = find(drawer, "warpSettings").menu.itemAt(3);
    input.mouseClick(current, 80, 18);
    check(current.checked, "clicking the current mode cleared its checkmark");
    input.mouseClick(find(drawer, "warpSettings"), 16, 16);
   } else if (window.stage === 12) {
    check(find(drawer, "warpSettings").menu.itemAt(8).checked, "registration checkmark did not persist");
    fake.state = Object.assign({}, fake.state, {warp: {available: true, running: true, connected: true, state: "Connected", mode: "warp+dot"}});
    check(find(drawer, "warpSettings").menu.itemAt(1).checked && !find(drawer, "warpSettings").menu.itemAt(3).checked, "menu did not reflect active mode");
   } else if (window.stage === 13) {
    find(drawer, "warpSettings").menu.close();
    const button = find(drawer, "speedTestButton");
    const label = find(drawer, "speedTestLabel");
    check(button.width === drawer.width, "speed test button does not fill drawer width");
    check(Math.abs(label.mapToItem(button, 0, label.height / 2).y - button.height / 2) < 1, "speed test label is not vertically centered");
    check(speed.starts === 0, "speed test ran automatically");
    input.mouseClick(button, 16, 16);
    check(speed.running && speed.starts === 1, "speed test button did not start");
    input.mouseClick(button, 16, 16);
    check(!speed.running, "speed test button did not cancel");
    speed.start(); drawer.active = false;
    check(!speed.running, "dismissal left speed test running");
   } else if (window.stage === 14) {
    drawer.active = true;
    speed.result = {download: 7.6, upload: 15.6, ping: 232, jitter: 5, server: "Test server", timestamp: "2026-10-15"};
   } else if (window.stage === 15) {
    check(find(drawer, "speedTestResult").visible && find(drawer, "speedTestButton").height === 64, "speed result is not inside expanded button");
    check(find(drawer, "speedTestResult").text === "↓ 7.6 Mb/s   ↑ 15.6 Mb/s · 232 ms", "speed result is missing a unit");
    capture(preview, "wifi-speed-result.png");
   } else if (window.stage === 16) {
    speed.start();
   } else if (window.stage === 17) {
    capture(preview, "wifi-speed-running.png");
   } else if (window.stage >= 18 && window.stage <= 22) {
    speed.cancel();
    speed.error = "The speed-test server returned no usable result. Check the connection and try again.";
    drawerLoader.width = [0, 1, 80, 200, 448][window.stage - 18];
   } else if (window.stage === 23) {
    speed.error = "";
    speed.result = {download: 12345.67, upload: 98765.43, ping: 9999, jitter: 12, server: "Test", timestamp: "2026-10-15"};
    const button = find(drawer, "speedTestButton");
    check(button.width === 448 && button.height === 64, "resize or result left stale button geometry");
   } else {
    console.log("WIFI_DRAWER_PASS"); Qt.quit();
   }
   window.stage++;
  } catch (e) { console.error("WIFI_DRAWER_FAIL", e.message); Qt.quit(); }
 } }
}
'''.replace('STATE', json.dumps(state))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('ui', 'icons', 'drawers'):
                shutil.copytree(DESKTOP / name, root / name)
            (root / 'shell.qml').write_text(qml)
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            platform = os.environ.get('WIFI_PREVIEW_PLATFORM', 'offscreen')
            env = {**os.environ, 'QT_QPA_PLATFORM': platform, 'XDG_CONFIG_HOME': str(root / 'config'),
                   'XDG_RUNTIME_DIR': str(runtime) if platform == 'offscreen' else os.environ['XDG_RUNTIME_DIR']}
            for key in (('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE') if platform == 'offscreen' else ('HYPRLAND_INSTANCE_SIGNATURE',)):
                env.pop(key, None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')], env=env, text=True, capture_output=True, timeout=20)
        log = result.stdout + result.stderr
        if os.environ.get("WIFI_PREVIEW_PLATFORM"):
            print(log)
        self.assertEqual(result.returncode, 0, log)
        self.assertIn('WIFI_DRAWER_PASS', log)
        for error in ('WIFI_DRAWER_FAIL', 'TypeError', 'ReferenceError', 'Binding loop', 'Unable to assign', 'polish() loop', 'Polish loop'):
            self.assertNotIn(error, log)


    def test_speed_test_process_results_failure_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DESKTOP / 'drawers/network', root / 'network')
            (root / 'fake.py').write_text("""import json,sys,time
mode=sys.argv[1]
if mode=='hang': time.sleep(60)
time.sleep(0.15)
if mode=='invalid': print('not json')
else: print(json.dumps([{'download':123.45,'upload':67.89,'ping':12.5,'jitter':0.7,
 'server':{'name':'Test server'},'timestamp':'2026-10-15T05:00:00Z', 'client':{'ip':'private-client-ip'}}]))
""")
            (root / 'shell.qml').write_text(r'''import QtQuick
import Quickshell
import "network"
ShellRoot {
 property int stage: 0
 function check(value, message) { if (!value) throw new Error(message); }
 function run(mode) {
  SpeedTestService.command = ["python3", decodeURIComponent(Qt.resolvedUrl("fake.py").toString().replace(/^file:\/\//, "")), mode];
  SpeedTestService.start();
 }
 Timer { interval: 100; running: true; repeat: true; onTriggered: {
  try {
   if (stage === 0) {
    check(!SpeedTestService.running, "test ran without a click");
    run("success"); stage++;
   } else if (stage === 1 && !SpeedTestService.running) {
    check(SpeedTestService.result.download === 123.45 && SpeedTestService.result.upload === 67.89
        && SpeedTestService.result.ping === 12.5 && SpeedTestService.result.jitter === 0.7, "wrong result units or values");
    check(!JSON.stringify(SpeedTestService.result).includes("private-client-ip") && SpeedTestService.response === "", "retained private client data");
    run("invalid"); stage++;
   } else if (stage === 2 && !SpeedTestService.running) {
    check(SpeedTestService.error !== "" && SpeedTestService.result === null, "malformed results looked successful");
    SpeedTestService.command = ["env", "desktop-test-nonexistent-speedtest"];
    SpeedTestService.start(); stage++;
   } else if (stage === 3 && !SpeedTestService.running) {
    check(SpeedTestService.error.includes("Install librespeed-cli-bin"), "missing package has no actionable error");
    run("hang"); stage++;
   } else if (stage === 4) {
    check(SpeedTestService.running, "test failed to start");
    SpeedTestService.cancel(); stage++;
   } else if (stage === 5 && !SpeedTestService.running) {
    check(SpeedTestService.error === "" && SpeedTestService.result === null, "cancellation reported failure or stale results");
    SpeedTestService.deadline.interval = 50;
    run("hang"); stage++;
   } else if (stage === 6 && !SpeedTestService.running) {
    check(SpeedTestService.timedOut && SpeedTestService.error.includes("timed out"), "timeout did not terminate the test");
    console.log("SPEED_TEST_PASS"); Qt.quit();
   }
  } catch (e) { console.error("SPEED_TEST_FAIL", e.message); Qt.quit(); }
 } }
}
''')
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'XDG_RUNTIME_DIR': str(runtime)}
            env.pop('WAYLAND_DISPLAY', None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')], env=env,
                                    text=True, capture_output=True, timeout=10)
        log = result.stdout + result.stderr
        self.assertIn('SPEED_TEST_PASS', log)
        for error in ('SPEED_TEST_FAIL', 'TypeError', 'ReferenceError', 'Binding loop', 'Unable to assign'):
            self.assertNotIn(error, log)


    def test_bar_signal_and_radio_updates_without_drawer(self):
        qml = """import QtQuick
import Quickshell
import Quickshell.Networking
import "bar"
ShellRoot {
 id: root
 QtObject { id: network; property bool connected: true; property real signalStrength: 0.85; property string name: "Home" }
 QtObject { id: networksModel; property var values: [network] }
 QtObject { id: device; property int type: DeviceType.Wifi; property bool scannerEnabled: true; property var networks: networksModel }
 QtObject { id: devicesModel; property var values: [device] }
 QtObject { id: fake; property bool wifiEnabled: true; property bool wifiHardwareEnabled: true; property var devices: devicesModel }
 NetworkStatus { id: status; provider: fake }
 function check(value, message) { if (!value) throw new Error(message); }
 Timer { interval: 100; running: true; onTriggered: {
  try {
   check(status.iconName === "wifi" && status.description.includes("85%"), "strong signal missing");
   check(!device.scannerEnabled, "bar started scanning");
   network.signalStrength = 0.5; check(status.iconName === "wifi-high", "medium signal not reactive");
   network.signalStrength = 0.25; check(status.iconName === "wifi-low", "low signal not reactive");
   network.signalStrength = 0.1; check(status.iconName === "wifi-zero", "weak signal missing");
   fake.wifiEnabled = false; check(status.iconName === "wifi-off", "radio state not reactive");
   fake.wifiEnabled = true; fake.wifiHardwareEnabled = false; check(status.iconName === "wifi-off", "hardware block missing");
   fake.wifiHardwareEnabled = true; network.connected = false;
   check(status.iconName === "wifi-zero" && status.description.includes("Not connected"), "disconnection missing");
   console.log("NETWORK_BAR_PASS"); Qt.quit();
  } catch (e) { console.error("NETWORK_BAR_FAIL", e.message); Qt.quit(); }
 } }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('bar', 'ui', 'icons'):
                shutil.copytree(DESKTOP / name, root / name)
            (root / 'shell.qml').write_text(qml)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'XDG_RUNTIME_DIR': str(runtime)}
            env.pop('WAYLAND_DISPLAY', None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')], env=env,
                                    text=True, capture_output=True, timeout=10)
        log = result.stdout + result.stderr
        self.assertIn('NETWORK_BAR_PASS', log)
        for error in ('NETWORK_BAR_FAIL', 'TypeError', 'ReferenceError', 'Binding loop', 'Unable to assign'):
            self.assertNotIn(error, log)


    def test_service_protocol_survives_dismissal(self):
        # Replace only the OS boundary, then exercise the actual singleton and
        # Process/stdin protocol. No NetworkManager or WARP calls leave this test.
        with tempfile.TemporaryDirectory(prefix='wifi service ') as directory:
            root = Path(directory)
            shutil.copytree(DESKTOP / 'drawers/network', root / 'network')
            (root / 'network/backend.py').write_text("""import json,sys,time
from pathlib import Path
r=json.loads(sys.stdin.readline())
with (Path(__file__).parent/'operations').open('a') as f: f.write(r['op']+'\\n')
time.sleep(0.5 if r['op']=='connect' else 0.3)
print(json.dumps({'ok':True,'data':{'available':True,'wifiEnabled':False,'adapters':[],'networks':[]}}))
""")
            (root / 'shell.qml').write_text('''import QtQuick
import Quickshell
import "network"
ShellRoot {
 property int stage: 0
 property int stateChanges: 0
 Connections { target: NetworkService; function onStateChanged() { stateChanges++; } }
 function check(value, message) { if (!value) throw new Error(message); }
 Timer { interval: 100; running: true; repeat: true; onTriggered: {
  try {
   if (stage === 0) { NetworkService.observing = true; stage++; }
   else if (stage === 1 && NetworkService.loaded && !NetworkService.working) {
    check(NetworkService.error === "", "status protocol failed: " + NetworkService.error);
    NetworkService.refresh();
    check(NetworkService.working && !NetworkService.busy, "background read appeared as a user action");
    NetworkService.run("connect", {password: "private-test-password"}, "profile");
    check(NetworkService.queuedAction !== null && NetworkService.busy, "action was lost behind a background read");
    NetworkService.observing = false;
    stage++;
   } else if (stage === 2) {
    check(NetworkService.busy, "dismissal cancelled the operation");
    check(NetworkService.request === null, "request retained a password after stdin write");
    stage++;
   } else if (stage === 3 && !NetworkService.busy) {
    check(NetworkService.error === "", "connect protocol failed: " + NetworkService.error);
    check(!NetworkService.observing, "operation restarted observation");
    check(stateChanges === 1, "identical snapshots notified the UI again");
    NetworkService.error = "Old reconnect failure";
    NetworkService.failure = {operation: "connect", uuid: "saved", key: "home"};
    NetworkService.applySnapshot({profiles: [{uuid: "saved", active: true, state: "activated"}], networks: []});
    check(NetworkService.error === "", "successful reconnection left a stale error");
    NetworkService.error = "Unrelated VPN failure";
    NetworkService.failure = {operation: "connect", uuid: "vpn", key: "vpn"};
    NetworkService.applySnapshot({profiles: [{uuid: "saved", active: true, state: "activated"}], networks: []});
    check(NetworkService.error === "Unrelated VPN failure", "unrelated Wi-Fi success cleared a VPN failure");
    NetworkService.sampleTraffic({sampleTime: 1, adapters: [{interface: "wlan0", connected: true, traffic: {received: 100, sent: 40}}]});
    NetworkService.sampleTraffic({sampleTime: 2, adapters: [{interface: "wlan0", connected: true, traffic: {received: 1124, sent: 552}}]});
    check(NetworkService.traffic.wlan0.down === 1024 && NetworkService.traffic.wlan0.up === 512, "interface rate calculation");
    check(NetworkService.queuedAction === null && NetworkService.request === null, "finished request retained credentials");
    NetworkService.selectWarpMode("proxy");
    NetworkService.setWarpRegistration(true);
    check(NetworkService.preferences.value("warpMode") === "proxy" && NetworkService.preferences.value("warpRegisterNext") === true, "WARP preferences were not saved");
    NetworkService.error = "Mode change failed";
    NetworkService.failure = {operation: "warp", action: "mode", mode: "doh"};
    NetworkService.applySnapshot({warp: {running: false, mode: ""}});
    check(NetworkService.error === "Mode change failed", "stopped daemon hid mode error");
    NetworkService.applySnapshot({warp: {running: true, mode: "doh"}});
    check(NetworkService.error === "", "confirmed mode did not clear its stale error");
    console.log("NETWORK_SERVICE_PASS"); Qt.quit();
   }
  } catch (e) { console.error("NETWORK_SERVICE_FAIL", e.message); Qt.quit(); }
 } }
}
''')
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'XDG_RUNTIME_DIR': str(runtime), 'XDG_CONFIG_HOME': str(root / 'config')}
            env.pop('WAYLAND_DISPLAY', None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')],
                                    env=env, text=True, capture_output=True, timeout=10)
            operations = (root / 'network/operations').read_text().splitlines()
        log = result.stdout + result.stderr
        self.assertIn('NETWORK_SERVICE_PASS', log)
        self.assertNotIn('NETWORK_SERVICE_FAIL', log)
        self.assertEqual(operations, ['status', 'status', 'connect'])


if __name__ == '__main__':
    unittest.main()
