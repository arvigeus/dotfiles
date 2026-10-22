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

REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop'
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


class WireguardImportTests(unittest.TestCase):
    def test_picker_cancel_does_not_launch_editor(self):
        with patch.object(backend.subprocess, 'run', return_value=Mock(returncode=1, stdout='')) as run:
            backend.import_wireguard()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][:2], ['zenity', '--file-selection'])

    def test_selected_filename_is_one_argument_and_contents_are_not_read(self):
        filename = '/tmp/WireGuard configs/iPhone #% ✓ $(touch unexpected).conf'
        with patch.object(backend.subprocess, 'run', side_effect=[
                Mock(returncode=0, stdout=filename + '\n'), Mock(returncode=0)]) as run:
            backend.import_wireguard()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0],
                         ['nm-connection-editor', '--type', 'wireguard', '--import', filename])

    def test_editor_failure_shows_generic_error_without_diagnostics(self):
        with patch.object(backend.subprocess, 'run', side_effect=[
                Mock(returncode=0, stdout='/tmp/test.conf\n'),
                Mock(returncode=1, stderr='private-key'), Mock(returncode=0)]) as run:
            backend.import_wireguard()
        self.assertEqual(run.call_args.args[0][:2], ['zenity', '--error'])
        self.assertNotIn('private-key', str(run.call_args))


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
    def test_warp_policy_only_allows_local_active_wheel_start_stop(self):
        policy = REPO / 'modules/internet/cloudflare/files/etc/polkit-1/rules.d/50-desktop-warp.rules'
        script = '''const fs = require('fs'), vm = require('vm');
let rule;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
 polkit: {addRule: callback => rule = callback, Result: {YES: 'yes'}}
});
function allowed(unit, verb, local = true, active = true, id = 'org.freedesktop.systemd1.manage-units', wheel = true) {
 return rule({id, lookup: key => ({unit, verb})[key]}, {local, active, isInGroup: group => wheel && group === 'wheel'}) === 'yes';
}
if (!allowed('warp-svc.service', 'start') || !allowed('warp-svc.service', 'stop')
 || allowed('sshd.service', 'start') || allowed('warp-svc.service', 'restart')
 || allowed('warp-svc.service', 'start', false) || allowed('warp-svc.service', 'start', true, false)
 || allowed('warp-svc.service', 'start', true, true, 'org.freedesktop.systemd1.manage-unit-files')
 || allowed('warp-svc.service', 'start', true, true, 'org.freedesktop.systemd1.manage-units', false)) process.exit(1);
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
        device = Mock(get_device_type=lambda: NM.DeviceType.WIFI)
        n.client = Mock(get_active_connections=lambda: [], get_device_by_iface=Mock(return_value=device))
        n.call = Mock(return_value=Mock())
        n.wait_active = Mock()
        return n

    def test_new_network_profile_is_user_scoped_and_uses_dbus(self):
        n = self.network()
        secret = 'test-private-password'
        ssid = '  cafe:back\\slash  '
        with patch.object(backend, 'command') as command:
            n.join({'ssid': ssid, 'security': 'wpa-psk', 'password': secret, 'interface': 'wlan0'})
        self.assertEqual(n.call.call_args.args[1], 'add_and_activate_connection_async')
        connection = n.call.call_args.args[2]
        self.assertEqual(bytes(connection.get_setting_wireless().get_ssid().get_data()).decode(), ssid)
        self.assertTrue(connection.get_setting_connection().get_autoconnect())
        self.assertEqual(connection.get_setting_connection().get_num_permissions(), 1)
        self.assertEqual(connection.get_setting_wireless_security().get_psk(), secret)
        command.assert_not_called()

    def test_validation_does_not_create_profiles(self):
        for request in [{'ssid': 'x' * 33}, {'ssid': 'cafe', 'security': 'wpa-psk', 'password': 'short'},
                        {'ssid': 'cafe', 'security': 'enterprise'}]:
            n = self.network()
            with self.assertRaises(ValueError):
                n.join(dict(request, interface='wlan0'))
            n.call.assert_not_called()

    def test_profile_activation_is_limited_to_vpn_profiles(self):
        n = self.network()
        n.client.get_connection_by_uuid = lambda _: Mock(get_connection_type=lambda: '802-11-wireless')
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            n.activate('saved')
        n.call.assert_not_called()
        vpn = Mock(get_connection_type=lambda: 'wireguard')
        n.client.get_connection_by_uuid = lambda _: vpn
        n.activate('vpn')
        self.assertEqual(n.call.call_args.args, (n.client, 'activate_connection_async', vpn, None, None))
        n.wait_active.assert_called_once()

    def test_snapshot_lists_vpn_profiles_active_ids_and_details(self):
        n = self.network()
        active = Mock(get_uuid=lambda: 'vpn', get_state=lambda: NM.ActiveConnectionState.ACTIVATED)
        n.client.get_active_connections = lambda: [active]
        n.client.get_connections = lambda: [
            Mock(get_connection_type=lambda: 'wireguard', get_uuid=lambda: 'vpn', get_id=lambda: 'Work'),
            Mock(get_connection_type=lambda: '802-11-wireless', get_uuid=lambda: 'home', get_id=lambda: 'Home')]
        address = Mock(get_address=lambda: '192.0.2.2', get_prefix=lambda: 24)
        config = Mock(get_addresses=lambda: [address], get_gateway=lambda: '192.0.2.1', get_nameservers=lambda: ['192.0.2.1'])
        n.client.get_devices = lambda: [Mock(get_device_type=lambda: NM.DeviceType.WIFI, get_iface=lambda: 'wlan0',
                                             get_active_connection=lambda: Mock(get_id=lambda: 'Home'),
                                             get_ip4_config=lambda: config, get_ip6_config=lambda: None)]
        snapshot = n.snapshot()
        self.assertEqual(snapshot['active'], ['vpn'])
        self.assertEqual([p['uuid'] for p in snapshot['profiles']], ['vpn'])
        self.assertEqual(snapshot['profiles'][0]['state'], 'activated')
        self.assertEqual(snapshot['details']['wlan0'], {'connection': 'Home', 'ipv4': ['192.0.2.2/24'],
                         'ipv4Gateway': '192.0.2.1', 'ipv4Dns': ['192.0.2.1'], 'ipv6': [], 'ipv6Gateway': '', 'ipv6Dns': []})

    def test_unknown_operations_are_rejected_before_networkmanager(self):
        with patch.object(backend, 'Network') as network:
            for op in ('forget', 'autoconnect', 'check', 'import', 'radio', 'scan'):
                with self.assertRaisesRegex(ValueError, 'Unknown'):
                    backend.handle({'op': op})
        network.assert_not_called()


@unittest.skipUnless(QS, 'Quickshell is required')
class WifiDrawerTests(unittest.TestCase):
    def test_controls_errors_and_lifecycle(self):
        state = dict(profiles=[dict(uuid='vpn', name='Work', kind='wireguard', active=False, state='disconnected')],
                     active=['home'], details=dict(wlan0=dict(connection='Home', ipv4=['192.0.2.2/24'], ipv4Gateway='192.0.2.1',
                                                             ipv4Dns=['192.0.2.1'], ipv6=[], ipv6Gateway='', ipv6Dns=[])),
                     warp=dict(available=True, connected=False, running=False, state='Off · daemon stopped', mode=''))
        qml = '''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import Quickshell.Networking
import "drawers"
import "ui" as UI
FloatingWindow {
 id: window
 implicitWidth: 480; implicitHeight: 900; color: UI.Theme.background
 Rectangle { anchors.fill: parent; color: UI.Theme.background }
 property var log: []
 component FakeNetwork: QtObject {
  property string name
  property real signalStrength: 0.5
  property int security: WifiSecurityType.Wpa2Psk
  property bool known: false
  property bool connected: false
  property int state: connected ? ConnectionState.Connected : ConnectionState.Disconnected
  property var device: wifi
  signal connectionFailed(int reason)
  function connect() { window.log = window.log.concat([["connect", name]]); }
  function connectWithPsk(psk) { window.log = window.log.concat([["psk", name, psk]]); }
  function disconnect() { window.log = window.log.concat([["disconnect", name]]); }
  function forget() { window.log = window.log.concat([["forget", name]]); }
 }
 FakeNetwork { id: newNetwork; name: "<Cafe & guests>"; signalStrength: 0.85 }
 FakeNetwork { id: home; name: "Home"; signalStrength: 0.82; known: true; connected: true }
 FakeNetwork { id: office; name: "Office"; signalStrength: 0.45; known: true }
 FakeNetwork { id: guest; name: "Guest network"; signalStrength: 0.42; security: WifiSecurityType.Open }
 FakeNetwork { id: away; name: "Away"; signalStrength: 0; known: true }
 QtObject { id: wifiNetworks; property var values: [newNetwork, home, office, guest, away] }
 QtObject { id: wifi; property int type: DeviceType.Wifi; property string name: "wlan0"; property string address: "00:11:22:33:44:55"
  property bool connected: true; property bool scannerEnabled: false; property var networks: wifiNetworks }
 QtObject { id: wired; property int type: DeviceType.Wired; property string name: "eth0"; property bool hasLink: false
  property bool connected: false; property int linkSpeed: 0; property var network: null; property int state: ConnectionState.Disconnected }
 QtObject { id: devicesModel; property var values: [wifi, wired] }
 QtObject { id: fakeNetworking; property int backend: NetworkBackendType.NetworkManager; property bool wifiEnabled: true
  property bool wifiHardwareEnabled: true; property int connectivity: NetworkConnectivity.Portal; property var devices: devicesModel }
 QtObject {
  id: fake
  property bool observing: false
  property bool loaded: true
  property bool busy: false
  property string interfaceName: ""
  property string error: ""
  property string pending: ""
  property string pendingKey: ""
  property var state: STATE
  property var calls: []
  property string warpMode: "warp+doh"
  property bool warpRegisterNext: false
  property int importRequests: 0
  function chooseWireguardConfig() { importRequests++; }
  function selectWarpMode(mode) { warpMode = mode; }
  function setWarpRegistration(value) { warpRegisterNext = value; }
  function dismissError() { error = ""; }
  signal completed(string operation, bool success)
  function run(op, values = {}, key = "") { pendingKey = key; calls = calls.concat([{op, values, key}]); }
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
   WifiDrawer { service: fake; networking: fakeNetworking; speedTest: speed; active: true; trafficRoot: Quickshell.env("WIFI_TRAFFIC_ROOT")
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
 function last() { return window.log[window.log.length - 1] ?? []; }
 function capture(item, name) {
  const output = Quickshell.env("WIFI_PREVIEW_DIR");
  if (output) item.grabToImage(result => console.log("PREVIEW_SAVED", name, result.saveToFile(output + "/" + name)));
 }
 property var savedRow: null
 property var savedVpnRow: null
 property int stage: 0
 Timer { interval: 150; running: drawerLoader.status === Loader.Ready; repeat: true; onTriggered: {
  try {
   let password = drawer.passwordField;
   const scroll = find(drawer, "networkScroll");
   if (window.stage === 0) {
    check(find(drawer, "wirelessSection").flat && find(drawer, "vpnSection").flat, "unexpected section background");
    check(!find(drawer, "ethernetSection").visible, "unplugged Ethernet is visible");
    const addVpn = find(drawer, "vpnAdd");
    check(addVpn && addVpn.iconName === "plus", "VPN import is not discoverable beside the heading");
    addVpn.clicked();
    check(addVpn.menu.visible && drawer.vpnImportMenu === addVpn.menu, "VPN import menu did not open");
    check(addVpn.menu.itemAt(0).text === "Import WireGuard…", "WireGuard import action is missing");
    addVpn.menu.itemAt(0).triggered();
    check(fake.importRequests === 1 && fake.calls.length === 0, "import should open a picker without changing networking");
    addVpn.menu.close();
    check(!find(window.contentItem, "wifiScan") && find(window.contentItem, "networkEdit") && !find(drawer, "networkEdit"), "header actions");
    check(find(preview, "wifiInfo").iconName === "info", "connection information is not discoverable in header");
    check(find(window.contentItem, "wifiToggle") && !find(drawer, "wifiToggle"), "power did not move to header");
    check(wifi.scannerEnabled && fake.observing, "open drawer did not scan/observe");
    check(drawer.networks.length === 4 && !find(drawer, "wifiNetwork:Away"), "out-of-range saved network listed");
    check(drawer.networks[0] === home && drawer.networks[1] === office, "connected and saved networks are not first");
    const row = find(drawer, "wifiNetwork:Home");
    check(row.hint.includes("82%") && row.hint.includes("WPA/WPA2 Personal") && !row.hint.includes("192.0.2"), "network tooltip");
    check(find(drawer, "wifiForget:Home").visible && !find(drawer, "wifiForget:Guest network").visible, "forget offered for unsaved network");
    check(row.foreground.toString() === UI.Theme.text.toString(), "connected row should use normal text");
    input.mouseMove(row, 8, row.height / 2);
    check(row.highlighted && row.foreground.toString() === UI.Theme.accent.toString(), "row hover did not cover icon and name");
    input.mouseMove(drawer, 0, drawer.height - 1);
    check(find(window.contentItem, "wifiToggle").checked && fake.calls.length === 0 && window.log.length === 0, "initial read issued a mutation");
    drawer.trafficSample = {received: 0, sent: 0, time: Date.now() - 1000};
    drawer.sampleTraffic();
    check(Math.abs(drawer.rates.down - 2048) < 300 && find(drawer, "downloadRate").text.endsWith("KiB/s"), "transfer statistics");
    capture(preview, "wifi-drawer-compact.png");
   } else if (window.stage === 1) {
    input.mouseClick(find(drawer, "wifiNetwork:<Cafe & guests>"), 80, 20);
    password = drawer.passwordField;
    password.forceActiveFocus(); input.keyClick(Qt.Key_A);
    check(drawer.passwordText === "a", "password edit did not reach the model");
    drawer.passwordText = "retry-password";
    input.mouseClick(find(drawer, "wifiSubmit"), 16, 16);
    const call = fake.calls[0];
    check(call.op === "join" && call.values.password === "retry-password" && call.values.security === "wpa-psk"
        && call.values.interface === "wlan0" && call.values.ssid === "<Cafe & guests>", "new network did not use helper");
    fake.error = "Incorrect password"; fake.completed("join", false);
    check(password.text === "retry-password" && find(drawer, "networkError").text === "Incorrect password", "failure discarded password");
    fake.busy = true;
    check(!find(drawer, "wifiSubmit").enabled, "duplicate action allowed");
    drawer.active = false; check(!fake.observing && !wifi.scannerEnabled, "observation survived dismissal");
    fake.completed("join", true); check(password.text === "", "success retained password");
    drawer.active = true; fake.busy = false; fake.error = "";
    check(wifi.scannerEnabled, "scanner did not resume");
    drawer.choose(newNetwork); drawer.passwordRequired = true;
    fake.selectWarpMode("tunnel_only");
    window.savedVpnRow = find(drawer, "networkProfile:vpn");
   } else if (window.stage === 2) {
    password = drawer.passwordField; drawer.passwordText = "keep-this-password"; password.forceActiveFocus();
    const networkRow = find(drawer, "wifiNetwork:<Cafe & guests>");
    const body = scroll.contentChildren[0];
    const auth = find(drawer, "wifiAuthentication");
    check(auth.visible && auth.mapToItem(body, 0, 0).y >= networkRow.mapToItem(body, 0, networkRow.height).y, "password form is not under the selected network");
    check(auth.mapToItem(body, 0, 0).x > networkRow.mapToItem(body, 0, 0).x, "password form lacks extra indentation");
    const offset = scroll.contentItem.contentY;
    newNetwork.signalStrength = 0.9; office.signalStrength = 0.5;
    fake.state = Object.assign({}, fake.state, {profiles: fake.state.profiles.map(p => Object.assign({}, p))});
    check(find(drawer, "wifiNetwork:<Cafe & guests>") === networkRow && find(drawer, "networkProfile:vpn") === window.savedVpnRow, "updates recreated delegates");
    check(fake.warpMode === "tunnel_only", "refresh reset WARP preference");
    check(password.activeFocus && password.text === "keep-this-password", "update lost form focus/text");
    check(scroll.contentItem.contentY === offset, "update moved scroll position");
    capture(preview, "wifi-drawer-password.png");
    fakeNetworking.wifiHardwareEnabled = false;
    check(!find(window.contentItem, "wifiToggle").enabled && drawer.networks.length === 0, "hardware block ignored");
    fakeNetworking.wifiHardwareEnabled = true;
    drawer.clearSelection();
   } else if (window.stage === 3) {
    input.mouseClick(find(drawer, "wifiNetwork:Guest network"), 100, 20);
    check(fake.calls[fake.calls.length - 1].op === "join" && fake.calls[fake.calls.length - 1].values.security === "open", "open network did not connect");
    input.mouseClick(find(drawer, "wifiNetwork:Office"), 100, 20);
    check(last()[0] === "connect" && last()[1] === "Office", "saved network did not connect natively");
    office.connectionFailed(ConnectionFailReason.NoSecrets);
    check(find(drawer, "wifiAuthentication")?.visible && drawer.selected === office, "missing secrets did not ask for a password");
    drawer.passwordText = "office-password";
    input.mouseClick(find(drawer, "wifiSubmit"), 16, 16);
    check(last()[0] === "psk" && last()[2] === "office-password", "saved network password did not use native PSK");
    office.connected = true;
    check(drawer.selected === null && drawer.passwordText === "", "connection retained password");
    office.connected = false;
    input.mouseClick(find(drawer, "wifiNetwork:Home"), 100, 20);
    check(last()[0] === "disconnect" && last()[1] === "Home", "connected row did not disconnect");
    find(drawer, "wifiForget:Office").confirmed();
    check(last()[0] === "forget" && last()[1] === "Office", "hold-to-forget did not forget natively");
    const vpn = find(drawer, "networkProfile:vpn");
    input.mouseClick(vpn, 8, vpn.height / 2);
    check(fake.calls[fake.calls.length - 1].values.uuid === "vpn", "VPN click did not connect");
    const toggle = find(window.contentItem, "wifiToggle");
    input.mouseClick(toggle, toggle.width / 2, toggle.height / 2);
    check(!fakeNetworking.wifiEnabled && !toggle.checked, "header switch did not toggle Wi-Fi");
    fakeNetworking.wifiEnabled = true;
    check(toggle.checked, "external power update broke switch binding");
    input.mouseClick(find(drawer, "warpToggle"), 10, 20);
    check(fake.calls[fake.calls.length - 1].op === "warp" && fake.calls[fake.calls.length - 1].values.mode === "tunnel_only", "Cloudflare row click lost mode");
    wired.hasLink = true;
    check(find(drawer, "ethernetSection").visible, "plugged Ethernet hidden");
    fake.busy = true;
    capture(scroll.contentChildren[0], "wifi-drawer-full.png");
   } else if (window.stage === 4) {
    check(find(drawer, "networkActivity").visible, "busy helper not shown");
    capture(preview, "wifi-drawer-loading.png");
   } else if (window.stage === 5) {
    fake.busy = false;
    scroll.contentItem.contentY = 0; UI.Theme.setMode("light");
   } else if (window.stage === 6) {
    capture(preview, "wifi-drawer-light.png");
   } else if (window.stage === 7) {
    UI.Theme.setMode("dark");
    input.mouseClick(find(drawer, "warpSettings"), 16, 16);
   } else if (window.stage === 8) {
    const menu = find(drawer, "warpSettings").menu;
    const ordered = ["warp+doh", "warp+dot", "warp", "doh", "dot", "tunnel_only", "proxy"];
    for (let i = 0; i < ordered.length; i++) check(menu.itemAt(i).objectName === "warpMode:" + ordered[i], "async incubation changed menu order");
    check(menu.count === 9 && menu.itemAt(7).objectName === "warpModeSeparator" && menu.itemAt(8).objectName === "warpRegistration", "registration is not separate below the separator");
    check(menu.itemAt(5).checked && menu.visible, "menu did not check the default mode");
    capture(menu.contentItem.parent, "wifi-drawer-menu.png");
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
    drawerLoader.active = false;
    check(!wifi.scannerEnabled, "destroyed drawer left scanning on");
    console.log("WIFI_DRAWER_PASS"); Qt.quit();
   }
   window.stage++;
  } catch (e) { console.error("WIFI_DRAWER_FAIL", window.stage, e.message); Qt.quit(); }
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
            statistics = root / 'net/wlan0/statistics'
            statistics.mkdir(parents=True)
            (statistics / 'rx_bytes').write_text('2048\n')
            (statistics / 'tx_bytes').write_text('1024\n')
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            platform = os.environ.get('WIFI_PREVIEW_PLATFORM', 'offscreen')
            env = {**os.environ, 'QT_QPA_PLATFORM': platform, 'XDG_CONFIG_HOME': str(root / 'config'),
                   'WIFI_TRAFFIC_ROOT': str(root / 'net'),
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
 QtObject { id: device; property int type: DeviceType.Wifi; property bool scannerEnabled: false; property var networks: networksModel }
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
            shutil.copytree(DESKTOP / 'drawers/network', root / 'drawers/network')
            shutil.copytree(DESKTOP / 'ui', root / 'ui')
            (root / 'ui/Apps.qml').write_text('''pragma Singleton
import Quickshell
Singleton {
 property var lastLaunch: []
 function launch(argv) { lastLaunch = argv; }
}
''')
            (root / 'drawers/network/backend.py').write_text("""import json,sys,time
from pathlib import Path
r=json.loads(sys.stdin.readline())
with (Path(__file__).parent/'operations').open('a') as f: f.write(r['op']+'\\n')
time.sleep(0.5 if r['op']=='connect' else 0.3)
print(json.dumps({'ok':True,'data':{'profiles':[{'uuid':'vpn','name':'Work','kind':'wireguard','active':False,'state':'disconnected'}],'active':[],'details':{}}}))
""")
            (root / 'shell.qml').write_text('''import QtQuick
import QtCore
import Quickshell
import "drawers/network"
import "ui" as UI
ShellRoot {
 Settings { id: saved; location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/quickshell/desktop/network.ini"; category: "Network" }
 property int stage: 0
 property int stateChanges: 0
 Connections { target: NetworkService; function onStateChanged() { stateChanges++; } }
 function check(value, message) { if (!value) throw new Error(message); }
 Timer { interval: 100; running: true; repeat: true; onTriggered: {
  try {
   if (stage === 0) {
    NetworkService.chooseWireguardConfig();
    check(JSON.stringify(UI.Apps.lastLaunch) === JSON.stringify([
     "python3", Quickshell.shellPath("drawers/network/backend.py"), "--import-wireguard"
    ]), "import did not launch the independent picker application");
    check(!NetworkService.working && !NetworkService.observing, "import changed networking or started observation");
    NetworkService.observing = true; stage++;
   }
   else if (stage === 1 && NetworkService.loaded && !NetworkService.working) {
    check(NetworkService.error === "", "status protocol failed: " + NetworkService.error);
    NetworkService.refresh();
    check(NetworkService.working && !NetworkService.busy, "background read appeared as a user action");
    NetworkService.run("connect", {uuid: "vpn", password: "private-test-password"}, "vpn");
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
    NetworkService.error = "Old VPN failure";
    NetworkService.failure = {operation: "connect", uuid: "vpn"};
    NetworkService.applySnapshot({profiles: [{uuid: "other", active: true, state: "activated"}]});
    check(NetworkService.error === "Old VPN failure", "unrelated profile cleared a VPN failure");
    NetworkService.applySnapshot({profiles: [{uuid: "vpn", active: true, state: "activated"}]});
    check(NetworkService.error === "", "successful reconnection left a stale error");
    check(NetworkService.queuedAction === null && NetworkService.request === null, "finished request retained credentials");
    NetworkService.selectWarpMode("proxy");
    NetworkService.setWarpRegistration(true);
    saved.sync();
    check(saved.value("warpMode") === "proxy" && String(saved.value("warpRegisterNext")) === "true", "WARP preferences were not saved");
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
            operations = (root / 'drawers/network/operations').read_text().splitlines()
        log = result.stdout + result.stderr
        self.assertIn('NETWORK_SERVICE_PASS', log)
        self.assertNotIn('NETWORK_SERVICE_FAIL', log)
        self.assertEqual(operations, ['status', 'status', 'connect'])


if __name__ == '__main__':
    unittest.main()
