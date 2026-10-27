"""Temporary firewalld ports, UI and lazy public-IP lookups; no host mutations."""

import copy
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop'
FIREWALL = REPO / 'modules/system/security/firewall'
HELPER = FIREWALL / 'files/usr/local/libexec/firewall-ports'
loader = importlib.machinery.SourceFileLoader('firewall_ports', str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
ports = importlib.util.module_from_spec(spec)
# This executable must not generate bytecode in the installed helper directory.
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
loader.exec_module(ports)
sys.dont_write_bytecode = _bytecode_disabled
QS = shutil.which('qs')
OPENED = (
    'rule family="ipv4" source address="192.168.1.0/24" destination address="192.168.1.10" '
    'port port="5173" protocol="tcp" accept'
)
OTHER_RULE = 'rule family="ipv4" source address="10.0.0.0/8" service name="ssh" accept'


class Host:
    """Fake firewall-cmd and ip; records every argv."""

    def __init__(self):
        self.zones = {
            'public': {'interfaces': ['wlan0', 'eth0'], 'rules': [OTHER_RULE]},
            'libvirt': {'interfaces': ['virbr0'], 'rules': []},
            'home': {'interfaces': [], 'rules': []},
        }
        self.links = [
            {'ifname': 'lo', 'addr_info': [{'local': '127.0.0.1', 'prefixlen': 8}]},
            {
                'ifname': 'wlan0',
                'addr_info': [{'local': '192.168.1.10', 'prefixlen': 24}],
            },
            {'ifname': 'eth0', 'addr_info': []},
            {
                'ifname': 'virbr0',
                'addr_info': [{'local': '192.168.122.1', 'prefixlen': 24}],
            },
        ]
        self.calls = []
        self.status = {}

    def __call__(self, argv, **_):
        self.calls.append(argv)
        if argv[0] == ports.IP:
            return Mock(returncode=0, stdout=json.dumps(self.links))
        option = argv[-1].split('=', 1)[0]
        if option in self.status:
            return Mock(returncode=self.status[option], stdout='')
        if argv[1:] == ['--get-active-zones']:
            lines = []
            for name, zone in self.zones.items():
                if zone['interfaces']:
                    lines += [
                        name + (' (default)' if name == 'public' else ''),
                        '  interfaces: ' + ' '.join(zone['interfaces']),
                    ]
            return Mock(returncode=0, stdout='\n'.join(lines) + '\n')
        zone = self.zones[argv[1].removeprefix('--zone=')]
        if argv[2] == '--list-rich-rules':
            return Mock(returncode=0, stdout='\n'.join(zone['rules']) + '\n')
        value = argv[2].split('=', 1)[1]
        if option == '--add-rich-rule':
            zone['rules'].append(value)
        elif option == '--remove-rich-rule':
            zone['rules'].remove(value)
        else:
            raise AssertionError(argv)
        return Mock(returncode=0, stdout='success\n')

    def writes(self):
        return [
            call
            for call in self.calls
            if any(arg.startswith(('--add', '--remove')) for arg in call)
        ]


class FirewallPortTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        patcher = patch.object(ports.subprocess, 'run', side_effect=self.host)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, op='open', **values):
        return ports.handle({'op': op, 'interface': 'wlan0', 'port': 5173, **values})

    def test_open_adds_one_runtime_rule_in_the_interface_zone_and_close_restores_baseline(
        self,
    ):
        baseline = copy.deepcopy(self.host.zones)
        row = {
            'interface': 'wlan0',
            'port': 5173,
            'address': '192.168.1.10',
            'zone': 'public',
        }
        self.assertEqual(self.request(), [row])
        self.assertEqual(
            self.host.writes(),
            [[ports.FIREWALL_CMD, '--zone=public', '--add-rich-rule=' + OPENED]],
        )
        self.assertEqual(self.request('status'), [row])
        self.assertEqual(self.request('close'), [])
        self.assertEqual(self.host.zones, baseline)
        self.assertFalse(any('--permanent' in call for call in self.host.calls))

    def test_status_is_read_only_and_only_reports_rules_for_current_addresses(self):
        stale = OPENED.replace('192.168.1.10', '192.168.1.99')
        self.host.zones['public']['rules'] += [
            OPENED,
            stale,
            OPENED.replace('5173', '8080/tcp'),
        ]
        self.assertEqual([row['port'] for row in self.request('status')], [5173])
        self.assertEqual(self.host.writes(), [])
        listed = [call[1] for call in self.host.calls if '--list-rich-rules' in call]
        self.assertEqual(listed, ['--zone=public', '--zone=libvirt'])
        self.request('close')
        self.assertEqual(
            self.host.zones['public']['rules'],
            [OTHER_RULE, stale, OPENED.replace('5173', '8080/tcp')],
        )

    def test_duplicate_is_rejected_without_another_write(self):
        self.request()
        with self.assertRaisesRegex(ports.PortError, 'already open'):
            self.request()
        self.assertEqual(len(self.host.writes()), 1)

    def test_invalid_requests_never_reach_the_host(self):
        requests = [
            {'op': 'open', 'interface': 'wlan0', 'port': value}
            for value in (0, 65536, True, '5173', 1.5, None)
        ]
        requests += [
            {'op': 'close', 'interface': value, 'port': 5173}
            for value in (
                '-x',
                '--permanent',
                '../x',
                'wlan0;evil',
                'wlan 0',
                '',
                'a' * 16,
                None,
            )
        ]
        requests += [
            {'op': 'open', 'interface': 'wlan0', 'port': 5173, 'zone': 'trusted'},
            [],
            None,
            {'op': 'reload'},
        ]
        for request in requests:
            with self.subTest(request=request), self.assertRaises(ports.PortError):
                ports.handle(request)
        self.assertEqual(self.host.calls, [])

    def test_network_without_usable_address_or_zone_is_rejected(self):
        with self.assertRaisesRegex(ports.PortError, 'no usable'):
            self.request(interface='eth0')
        self.host.links.append(
            {'ifname': 'enp1s0', 'addr_info': [{'local': '10.0.0.5', 'prefixlen': 24}]}
        )
        with self.assertRaisesRegex(ports.PortError, 'no firewall zone'):
            self.request(interface='enp1s0')
        self.host.links[1]['addr_info'] = [
            {'local': '192.168.1.10', 'prefixlen': 32},
            {'local': '169.254.3.4', 'prefixlen': 16},
        ]
        self.assertEqual(self.request()[0]['address'], '169.254.3.4')
        self.assertIn('source address="169.254.0.0/16"', self.host.writes()[0][2])

    def test_firewall_failures_become_drawer_messages(self):
        for code, message in (
            (252, 'not running'),
            (253, 'administrator session'),
            (1, 'Could not open'),
        ):
            self.host.status = {'--add-rich-rule': code}
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(ports.PortError, message),
            ):
                self.request()
        self.host.status = {'--get-active-zones': 252}
        with self.assertRaisesRegex(ports.PortError, 'not running'):
            self.request('status')
        for error, message in (
            (FileNotFoundError(), 'not installed'),
            (subprocess.TimeoutExpired('firewall-cmd', 15), 'did not respond'),
        ):
            with (
                self.subTest(error=error),
                patch.object(ports.subprocess, 'run', side_effect=error),
                self.assertRaisesRegex(ports.PortError, message),
            ):
                ports.firewall('--get-active-zones', failure='unused')

    def test_main_speaks_one_json_line(self):
        for line, expected in (
            ('{"op":"status"}\n', {'ok': True, 'ports': [], 'error': ''}),
            ('not json\n', {'ok': False, 'error': 'Invalid port request.'}),
        ):
            output = io.StringIO()
            with (
                self.subTest(line=line),
                patch.object(sys, 'stdin', io.StringIO(line)),
                patch.object(sys, 'stdout', output),
            ):
                ports.main()
            self.assertEqual(json.loads(output.getvalue()), expected)


class FirewallAssetTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_policy_only_allows_zone_configuration_for_active_local_wheel(self):
        policy = FIREWALL / 'files/etc/polkit-1/rules.d/50-firewall.rules'
        script = """const fs=require('fs'),vm=require('vm');let rule;
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{polkit:{addRule:f=>rule=f,Result:{YES:'yes'}}});
function allow(id,local=true,active=true,wheel=true){
 return rule({id},{local,active,isInGroup:group=>group==='wheel'&&wheel})==='yes';}
const base='org.fedoraproject.FirewallD1';
if(!allow(base+'.config')||!allow(base+'.config.info'))process.exit(1);
if(allow(base+'.config',false)||allow(base+'.config',true,false)||allow(base+'.config',true,true,false))process.exit(2);
for(const id of [base+'.all',base+'.direct',base+'.policies','org.freedesktop.policykit.exec'])if(allow(id))process.exit(3);
"""
        subprocess.run(['node', '-e', script, str(policy)], check=True)

    def test_default_zone_denies_ssh_and_modules_own_their_policies(self):
        public = ET.parse(FIREWALL / 'files/etc/firewalld/zones/public.xml').getroot()
        self.assertEqual(
            [service.get('name') for service in public.iter('service')],
            ['dhcpv6-client'],
        )
        self.assertIsNone(public.get('target'))
        policies = {
            'ssh': REPO
            / 'modules/system/security/ssh/server/files/etc/firewalld/policies/ssh.xml',
            'kdeconnect': REPO
            / 'modules/communication/kdeconnect/files/etc/firewalld/policies/kdeconnect.xml',
        }
        for name, path in policies.items():
            root = ET.parse(path).getroot()
            self.assertEqual(
                (
                    root.find('ingress-zone').get('name'),
                    root.find('egress-zone').get('name'),
                ),
                ('ANY', 'HOST'),
            )
            self.assertEqual(root.get('target'), 'CONTINUE')
            self.assertEqual(
                {service.get('name') for service in root.iter('service')}, {name}
            )
        sources = [
            source.get('address')
            for source in ET.parse(policies['kdeconnect']).getroot().iter('source')
        ]
        self.assertEqual(
            sources,
            [
                '10.0.0.0/8',
                '172.16.0.0/12',
                '192.168.0.0/16',
                '169.254.0.0/16',
                'fc00::/7',
                'fe80::/10',
            ],
        )
        self.assertEqual(
            json.loads((FIREWALL / 'config.json').read_text())['app_config'],
            {'firewall_config': {'firewall': 'firewalld'}},
        )


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
            if setup:
                setup(root)
            (root / 'shell.qml').write_text(body)
            env = {
                **os.environ,
                'QT_QPA_PLATFORM': 'offscreen',
                'XDG_RUNTIME_DIR': str(root / 'runtime'),
                'XDG_CONFIG_HOME': str(root / 'config'),
            }
            for key in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
                env.pop(key, None)
            result = subprocess.run(
                [QS, '--no-color', '-p', str(root / 'shell.qml')],
                env=env,
                text=True,
                capture_output=True,
                timeout=12,
                check=False,
            )
            log = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, log)
            self.assertIn('FEATURE_PASS', log)
            for value in (
                'FEATURE_FAIL',
                'TypeError',
                'ReferenceError',
                'Binding loop',
                'Unable to assign',
                'polish() loop',
                'Polish loop',
            ):
                self.assertNotIn(value, log)
            return root, log

    def test_cards_presets_numeric_entry_popup_escape_and_lifecycle(self):
        self.run_qml("""import QtQuick
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
""")

    def test_port_actions_queue_behind_reads_and_finish_after_dismissal(self):
        def setup(root):
            (root / 'port-worker.py').write_text(
                'import json,sys,time\n'
                'request=json.loads(sys.stdin.readline());time.sleep(.12)\n'
                'rows=[dict(interface="wlan0",port=request["port"])] if request["op"]=="open" else []\n'
                'print(json.dumps(dict(ok=True,ports=rows,error="")),flush=True)\n'
            )
            path = root / 'drawers/network/PortsService.qml'
            source = path.read_text()
            source = source.replace(
                'command: ["/usr/local/libexec/firewall-ports"]',
                'command: ["python3", '
                + json.dumps(str(root / 'port-worker.py'))
                + ']',
            )
            path.write_text(source)

        self.run_qml(
            """import QtQuick
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
""",
            setup,
        )

    def test_missing_helper_recovers_when_it_becomes_available(self):
        def setup(root):
            (root / 'available-port-helper.py').write_text(
                'import json,sys\njson.loads(sys.stdin.readline())\n'
                'print(json.dumps(dict(ok=True,ports=[],error="")),flush=True)\n'
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/network"
ShellRoot {
 Component.onCompleted:{PortsService.process.command=["/tmp/nonexistent-firewall-port-helper"];PortsService.observing=true;}
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
""",
            setup,
        )

    def test_public_lookup_is_lazy_cached_bounded_and_invalidated_by_route(self):
        def setup(root):
            (root / 'lookup.py').write_text(
                'import time\ntime.sleep(0.12)\nprint("203.0.113.25")\n'
            )
            path = root / 'drawers/network/PublicIpService.qml'
            source = path.read_text()
            start = source.index('        command: [')
            end = source.index('\n', start)
            path.write_text(
                source[:start]
                + '        command: ["python3", '
                + json.dumps(str(root / 'lookup.py'))
                + ']'
                + source[end:]
            )

        self.run_qml(
            """import QtQuick
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
""",
            setup,
        )
