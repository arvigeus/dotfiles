"""Temporary port boundaries, UI and lazy public-IP lookups; no host mutations."""
import copy
import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop'
HELPER = REPO / 'modules/system/security/ufw/files/usr/local/libexec/desktop-ports'
loader = importlib.machinery.SourceFileLoader('desktop_ports', str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
ports = importlib.util.module_from_spec(spec)
# This executable must not generate bytecode in the installed helper directory.
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
loader.exec_module(ports)
sys.dont_write_bytecode = _bytecode_disabled
QS = shutil.which('qs')
NETWORK = {'interface': 'wlan0', 'connection': '/active/1', 'address': '192.168.1.10', 'subnet': '192.168.1.0/24'}


class Kernel:
    def __init__(self):
        self.rules = [['-A', ports.CHAIN, '-p', 'tcp', '--dport', '22', '-j', 'ACCEPT']]
        self.calls = []
        self.fail_delete = False

    def __call__(self, *args):
        self.calls.append(args)
        if args[:1] == ('-S',):
            return Mock(returncode=0, stdout='\n'.join(shlex.join(rule) for rule in self.rules))
        if args[:1] == ('-I',):
            values = list(args[3:])
            # Match iptables -S canonicalization, which differs from the input.
            destination = values.index('-d') + 1
            values[destination] += '/32'
            values[0:4] = values[2:4] + values[0:2]
            self.rules.insert(0, ['-A', ports.CHAIN, *values])
            return Mock(returncode=0)
        if args[:1] == ('-D',):
            rule = ['-A', *args[1:]]
            if self.fail_delete:
                return Mock(returncode=1)
            self.rules.remove(rule)
            return Mock(returncode=0)
        raise AssertionError(args)


class PortBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Kernel()
        self.network = Mock(return_value=copy.deepcopy(NETWORK))
        self.service = ports.Ports(self.network)
        self.patcher = patch.object(ports, 'command', side_effect=self.kernel)
        self.patcher.start()
        config = patch.object(ports.Path, 'read_text', return_value='ENABLED=yes\n')
        config.start()
        self.addCleanup(config.stop)
        self.addCleanup(self.patcher.stop)

    def request(self, op='open', uid=1000, **values):
        return self.service.handle(dict(op=op, interface='wlan0', port=5173, **values), uid, lambda: True)

    def test_open_is_interface_source_and_destination_scoped_and_close_preserves_baseline(self):
        baseline = copy.deepcopy(self.kernel.rules)
        result = self.request()
        self.assertEqual(result, [{'interface': 'wlan0', 'port': 5173, 'address': NETWORK['address']}])
        rule = self.kernel.rules[0]
        for value in ('wlan0', '192.168.1.0/24', '192.168.1.10/32', 'tcp', '5173'):
            self.assertIn(value, rule)
        self.assertTrue(ports.own_rule(rule))
        self.assertEqual(self.request('close'), [])
        self.assertEqual(self.kernel.rules, baseline)

    def test_status_has_no_writes_and_other_users_cannot_close_or_see_rules(self):
        self.request()
        self.kernel.calls.clear()
        self.assertEqual(self.request('status', uid=1001), [])
        self.assertTrue(all(call[0] == '-S' for call in self.kernel.calls))
        self.assertEqual(self.request('close', uid=1001), [])
        self.assertEqual(len(self.service.entries), 1)

    def test_duplicate_rejected_without_another_insert(self):
        self.request()
        with self.assertRaisesRegex(ValueError, 'already open'):
            self.request()
        self.assertEqual(sum(c[0] == '-I' for c in self.kernel.calls), 1)

    def test_invalid_ports_interfaces_payloads_and_denied_actions_never_write(self):
        requests = [{'op': 'open', 'interface': 'wlan0', 'port': value} for value in (0, 65536, True, '5173', 1.5, None)]
        requests += [{'op': 'open', 'interface': value, 'port': 5173} for value in ('../x', 'wlan0;evil', '', None)]
        requests += [{'op': 'open', 'interface': 'wlan0', 'port': 5173, 'source': '0.0.0.0/0'}, [], {'op': 'disable'}]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.service.handle(request, 1000, lambda: True)
        with self.assertRaisesRegex(ValueError, 'administrator'):
            self.service.handle({'op': 'open', 'interface': 'wlan0', 'port': 5173}, 1000, lambda: False)
        self.assertFalse(any(c[0] in ('-I', '-D') for c in self.kernel.calls))

    def test_disconnect_reconnect_and_address_changes_revoke_without_reopening(self):
        for change in ({'connection': '/active/2'}, {'address': '192.168.1.11'}, {'subnet': '10.0.0.0/24'}):
            self.network.return_value = copy.deepcopy(NETWORK)
            self.request()
            self.network.return_value.update(change)
            self.service.reconcile()
            self.assertEqual(self.service.entries, [])
            self.assertEqual(len(self.kernel.rules), 1)
        self.network.return_value = copy.deepcopy(NETWORK)
        self.request()
        self.network.side_effect = ValueError('Disconnected')
        self.service.reconcile()
        self.assertEqual(len(self.kernel.rules), 1)

    def test_external_reload_clears_records_without_readding_and_restart_removes_orphans(self):
        self.request()
        self.kernel.rules.pop(0)
        self.service.reconcile()
        self.assertEqual(self.service.entries, [])
        self.request()
        restarted = ports.Ports(self.network)
        restarted.close_all()
        self.assertEqual(len(self.kernel.rules), 1)
        self.assertIn('22', self.kernel.rules[0])

    def test_failed_close_retains_ownership_for_retry(self):
        self.request()
        self.kernel.fail_delete = True
        with self.assertRaisesRegex(ValueError, 'Could not close'):
            self.request('close')
        self.assertEqual(len(self.service.entries), 1)
        self.kernel.fail_delete = False
        self.request('close')
        self.assertEqual(self.service.entries, [])

    def test_network_change_during_open_is_rolled_back(self):
        self.network.side_effect = [copy.deepcopy(NETWORK), {**NETWORK, 'connection':'/active/2'}]
        with self.assertRaisesRegex(ValueError, 'network changed'):
            self.request()
        self.assertEqual(self.service.entries, [])
        self.assertEqual(len(self.kernel.rules), 1)

    def test_disabled_firewall_never_claims_a_port_is_open(self):
        with patch.object(ports.Path, 'read_text', return_value='ENABLED=no\n'), \
                self.assertRaisesRegex(ValueError, 'UFW is not active'):
            self.request()
        self.assertFalse(any(c[0] == '-I' for c in self.kernel.calls))

    def test_failed_or_timed_out_open_rolls_back_even_if_kernel_already_added_it(self):
        original = self.kernel.__call__
        def uncertain(*args):
            result = original(*args)
            if args[0] == '-I':
                raise ValueError('Timed out')
            return result
        with patch.object(ports, 'command', side_effect=uncertain), \
                self.assertRaisesRegex(ValueError, 'Timed out'):
            self.request()
        self.assertEqual(self.service.entries, [])
        self.assertEqual(len(self.kernel.rules), 1)

    def test_network_scope_only_comes_from_connected_physical_device(self):
        NM = Mock()
        NM.DeviceType.WIFI, NM.DeviceType.ETHERNET = 1, 2
        NM.DeviceState.ACTIVATED = 100
        client = Mock()
        device = client.get_device_by_iface.return_value
        device.get_device_type.return_value = 1
        device.get_state.return_value = 100
        device.get_active_connection.return_value.get_path.return_value = '/active/1'
        address = Mock(get_address=lambda: '192.168.1.10', get_prefix=lambda: 24)
        device.get_ip4_config.return_value.get_addresses.return_value = [address]
        self.assertEqual(ports.network_for(client, 'wlan0', NM), NETWORK)
        device.get_device_type.return_value = 99
        with self.assertRaises(ValueError): ports.network_for(client, 'wg0', NM)
        device.get_device_type.return_value = 1
        device.get_state.return_value = 30
        with self.assertRaises(ValueError): ports.network_for(client, 'wlan0', NM)
        device.get_state.return_value = 100
        address.get_prefix = lambda: 0
        with self.assertRaises(ValueError): ports.network_for(client, 'wlan0', NM)

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_policy_only_allows_active_local_wheel_and_the_exact_action(self):
        policy = REPO / 'modules/system/security/ufw/files/etc/polkit-1/rules.d/50-desktop-ports.rules'
        script = '''const fs=require('fs'),vm=require('vm');let rule;
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{polkit:{addRule:f=>rule=f,Result:{YES:'yes'}}});
function allow(local=true,active=true,wheel=true,id='org.dotfiles.ports.manage'){
 return rule({id},{local,active,isInGroup:group=>group==='wheel'&&wheel})==='yes';}
if(!allow()||allow(false)||allow(true,false)||allow(true,true,false)||allow(true,true,true,'org.freedesktop.policykit.exec'))process.exit(1);
'''
        subprocess.run(['node', '-e', script, str(policy)], check=True)


@unittest.skipUnless(QS, 'Quickshell is required')
class NetworkFeatureQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('ui', 'icons', 'drawers'):
                shutil.copytree(DESKTOP / name, root / name)
            (root / 'runtime').mkdir(mode=0o700)
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            if setup: setup(root)
            (root / 'shell.qml').write_text(body)
            env = {**os.environ, 'QT_QPA_PLATFORM':'offscreen', 'XDG_RUNTIME_DIR':str(root / 'runtime'),
                   'XDG_CONFIG_HOME':str(root / 'config')}
            for key in ('WAYLAND_DISPLAY','HYPRLAND_INSTANCE_SIGNATURE'): env.pop(key,None)
            result = subprocess.run([QS,'--no-color','-p',str(root / 'shell.qml')],env=env,text=True,capture_output=True,timeout=12,check=False)
            log = result.stdout + result.stderr
            self.assertEqual(result.returncode,0,log)
            self.assertIn('FEATURE_PASS',log)
            for value in ('FEATURE_FAIL','TypeError','ReferenceError','Binding loop','Unable to assign','polish() loop','Polish loop'):
                self.assertNotIn(value,log)
            return root, log

    def test_cards_presets_numeric_entry_popup_escape_and_lifecycle(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import "drawers/network"
import "ui"
FloatingWindow {
 id:window; implicitWidth:480;implicitHeight:800;visible:true;color:Theme.background
 QtObject {
  id:fake; property bool observing:false;property bool available:true;property bool busy:false;property string error:""
  property var ports: [{interface:"wlan0",port:3000,address:"192.0.2.1"}]
  property var calls:[]
  signal completed(string operation,bool success)
  function run(op,values){calls=calls.concat([{op,values}]);if(op==="open")ports=ports.concat([{interface:values.interface,port:values.port}]);else if(op==="close")ports=ports.filter(p=>p.port!==values.port);completed(op,true);}
 }
 ColumnLayout {x:16;y:16;width:448;PortsControls{id:controls;Layout.fillWidth:true;active:true;connected:true;interfaceName:"wlan0";service:fake}}
 TestCase{id:input;when:false;parent:window.contentItem}
 function check(value,message){if(!value)throw Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const result=find(child,name);if(result)return result;}return null;}
 property int stage:0
 Timer{interval:160;running:true;repeat:true;onTriggered:{try{
  if(stage===0){check(fake.observing,"not observing");check(find(controls,"portCard:3000"),"port is not a card");input.mouseClick(find(controls,"portAdd"),80,17);}
  else if(stage===1){
   check(controls.popupOpen,"popover missing");const popup=find(controls,"portAdd").data.find(item=>item.objectName==="portPopup");
   check(Math.abs(popup.width-find(controls,"portAdd").width)<1,"popover width");
   check(!find(popup.contentItem,"portPreset:3000").enabled,"already open preset");
   input.mouseClick(find(popup.contentItem,"portPreset:5173"),30,17);
   check(find(popup.contentItem,"portNumber").number===5173,"preset did not fill numeric input");
   check(fake.calls.length===0,"preset opened the port");input.keyClick(Qt.Key_Return);
  }else if(stage===2){check(!controls.popupOpen&&fake.calls[0].values.port===5173,"numeric Enter did not open");check(find(controls,"portCard:5173"),"new card missing");input.mouseClick(find(controls,"portClose:5173"),17,17);}
  else if(stage===3){check(!find(controls,"portCard:5173"),"close left card");input.mouseClick(find(controls,"portAdd"),80,17);}
  else if(stage===4){input.keyClick(Qt.Key_Escape);check(!controls.popupOpen,"Escape did not close popover");check(find(controls,"portAdd").activeFocus,"focus not restored");input.mouseClick(find(controls,"portAdd"),80,17);}
  else if(stage===5){controls.active=false;check(!controls.popupOpen&&!fake.observing,"dismissal left popover or observation");check(fake.ports.length===1,"dismissal closed port");controls.active=true;controls.width=260;input.mouseClick(find(controls,"portAdd"),80,17);}
  else if(stage===6){check(controls.popupOpen,"narrow popover missing");controls.interfaceName="eth0";check(!controls.popupOpen,"adapter change left popover");console.log("FEATURE_PASS");Qt.quit();return;}
  stage++;
 }catch(e){console.error("FEATURE_FAIL",stage,e.message);Qt.quit();}}}
}
''')

    def test_port_actions_queue_behind_reads_and_finish_after_dismissal(self):
        def setup(root):
            (root / 'port-worker.py').write_text(
                'import json,sys,time\n'
                'request=json.loads(sys.stdin.readline());time.sleep(.12)\n'
                'rows=[dict(interface="wlan0",port=request["port"])] if request["op"]=="open" else []\n'
                'print(json.dumps(dict(ok=True,ports=rows,error="")),flush=True)\n')
            path = root / 'drawers/network/PortsService.qml'
            source = path.read_text()
            source = source.replace('command: ["/usr/local/libexec/desktop-ports"]',
                                    'command: ["python3", ' + json.dumps(str(root / 'port-worker.py')) + ']')
            path.write_text(source)
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/network"
ShellRoot {
 property int stage:0
 function check(value,message){if(!value)throw Error(message);}
 Timer{interval:180;running:true;repeat:true;onTriggered:{try{
  if(stage===0){PortsService.observing=true;}
  else if(stage===1&&PortsService.operation!=="")return;
  else if(stage===1){
   check(PortsService.loaded&&PortsService.available,"status failed");
   PortsService.refresh();check(!PortsService.busy,"read disabled controls");
   PortsService.run("open",{interface:"wlan0",port:5173});
   check(PortsService.queuedAction&&PortsService.busy,"action lost behind read");
   PortsService.observing=false;
  }
  else if(stage===2&&PortsService.operation!=="")return;
  else if(stage===2){
   check(!PortsService.observing&&PortsService.ports[0]?.port===5173,"dismissal lost opening");
   check(!PortsService.busy&&!PortsService.queuedAction,"finished operation retained busy state");
   console.log("FEATURE_PASS");Qt.quit();return;
  }
  stage++;
 }catch(e){console.error("FEATURE_FAIL",stage,e.message);Qt.quit();}}}
}
''', setup)

    def test_missing_helper_recovers_when_it_becomes_available(self):
        def setup(root):
            (root / 'available-port-helper.py').write_text(
                'import json,sys\njson.loads(sys.stdin.readline())\n'
                'print(json.dumps(dict(ok=True,ports=[],error="")),flush=True)\n')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/network"
ShellRoot {
 Component.onCompleted:{PortsService.process.command=["/tmp/nonexistent-desktop-port-helper"];PortsService.observing=true;}
 property int stage:0
 Timer{interval:250;running:true;repeat:true;onTriggered:{try{
  if(stage===0){
   if(PortsService.operation!==""||!PortsService.loaded||PortsService.available||!PortsService.error)throw Error("missing helper retained pending state");
   PortsService.process.command=["python3",decodeURIComponent(Qt.resolvedUrl("available-port-helper.py").toString().slice(7))];
   PortsService.refresh();
  }else if(stage===1){
   if(PortsService.operation!==""||!PortsService.available||PortsService.error)throw Error("new helper did not recover");
   console.log("FEATURE_PASS");Qt.quit();return;
  }
  stage++;
 }catch(e){console.error("FEATURE_FAIL",stage,e.message);Qt.quit();}}}
}
''',setup)

    def test_public_lookup_is_lazy_cached_bounded_and_invalidated_by_route(self):
        def setup(root):
            (root / 'lookup.py').write_text('import time\ntime.sleep(0.12)\nprint("203.0.113.25")\n')
            path = root / 'drawers/network/PublicIpService.qml'
            source = path.read_text()
            start = source.index('        command: [')
            end = source.index('\n',start)
            path.write_text(source[:start] + '        command: ["python3", ' + json.dumps(str(root / 'lookup.py')) + ']' + source[end:])
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/network"
ShellRoot {
 property int stage:0
 function check(value,message){if(!value)throw Error(message);}
 Timer{interval:180;running:true;repeat:true;onTriggered:{try{
  if(stage===0){PublicIpService.context="route-a";check(!PublicIpService.busy&&!PublicIpService.checkedAt,"eager request");PublicIpService.lookup();check(PublicIpService.busy,"lookup did not start");}
  else if(stage===1&&PublicIpService.busy)return;
  else if(stage===1){check(PublicIpService.address==="203.0.113.25","invalid result");PublicIpService.lookup();check(!PublicIpService.busy,"cache ignored");PublicIpService.context="route-b";check(PublicIpService.address==="","route retained stale IP");PublicIpService.lookup();}
  else if(stage===2&&PublicIpService.busy)return;
  else if(stage===2){check(PublicIpService.address==="203.0.113.25","new route failed");PublicIpService.checkedAt=Date.now()-600001;PublicIpService.lookup();check(PublicIpService.busy,"TTL not enforced");PublicIpService.context="route-c";}
  else if(stage===3){check(PublicIpService.address==="","cancelled old-route result leaked");console.log("FEATURE_PASS");Qt.quit();return;}
  stage++;
 }catch(e){console.error("FEATURE_FAIL",stage,e.message);Qt.quit();}}}
}
''', setup)
