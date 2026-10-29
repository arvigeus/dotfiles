"""BlueZ pairing helper and native drawer interactions without host mutations."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import support

SOURCE = support.DESKTOP / 'drawers/bluetooth/backend.py'
backend = support.load('desktop_bluetooth', SOURCE)
FIXTURE = Path(__file__).parent / 'fixtures/bluez_service.py'
D = '/org/bluez/hci0/dev_AA'


class PairingHelperTests(unittest.TestCase):
    def setUp(self):
        self.events, self.calls, self.quit = [], [], Mock()
        self.bus = Mock()
        self.props = dict(Address='AA:BB', Paired=False)
        self.bus.call_sync.side_effect = lambda service, path, interface, method, *a: (
            Mock(
                unpack=Mock(
                    return_value=(self.props,) if method == 'GetAll' else (':bluez',)
                )
            )
        )
        self.p = backend.Pairing(self.bus, D, 'AA:BB', self.events.append, self.quit)
        self.p.call = (
            lambda path, interface, method, args=None, done=None, timeout=30000: (
                self.calls.append(dict(path=path, method=method, args=args, done=done))
            )
        )
        for name in ('timeout_add_seconds', 'source_remove'):
            item = patch.object(backend.GLib, name, return_value=7)
            item.start()
            self.addCleanup(item.stop)

    def complete(self, method, error=''):
        next(c for c in reversed(self.calls) if c['method'] == method)['done'](error)

    def methods(self):
        return [c['method'] for c in self.calls]

    def prompt(self, kind='RequestConfirmation', args=None, sender=':bluez'):
        invocation = Mock()
        self.p.agent(
            self.bus,
            sender,
            backend.AGENT_PATH,
            'org.bluez.Agent1',
            kind,
            backend.GLib.Variant('(ou)', (D, 42)) if args is None else args,
            invocation,
        )
        return invocation

    def start(self):
        self.p.start()
        self.complete('RegisterAgent')

    def test_errors_are_readable(self):
        error = backend.Gio.dbus_error_new_for_dbus_error(
            'org.bluez.Error.AuthenticationRejected', 'Rejected'
        )
        self.assertEqual(
            backend.error_text(error), 'Pairing was rejected by the device.'
        )

    def test_stale_or_paired_device_never_registers_agent(self):
        for props in (dict(Address='other'), dict(Address='AA:BB', Paired=True)):
            self.props, self.p.done = props, False
            self.p.start()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.events[-1]['error'])
        self.quit.assert_called()

    def test_confirmed_pairing_trusts_then_connects_and_exits(self):
        self.start()
        self.assertEqual(
            self.calls[0]['args'].unpack(), (backend.AGENT_PATH, 'KeyboardDisplay')
        )
        invocation = self.prompt()
        self.assertEqual(self.p.prompt['code'], '000042')
        self.p.respond(dict(id=self.p.prompt['id'], accept=True))
        invocation.return_value.assert_called_once_with(None)
        self.complete('Pair')
        self.assertEqual(self.events[-1], dict(type='connecting'))
        self.assertEqual(
            self.calls[-1]['args'].unpack(), (backend.DEVICE, 'Trusted', True)
        )
        self.p.cancel()  # Dismissal after pairing must not interrupt the connection.
        self.complete('Set')
        self.complete('Connect')
        self.assertEqual(self.methods(), ['RegisterAgent', 'Pair', 'Set', 'Connect'])
        self.assertEqual(self.events[-1], dict(type='done', error=''))
        self.quit.assert_called_once()

    def test_pin_and_passkey_validation(self):
        self.start()
        invocation = self.prompt('RequestPasskey', backend.GLib.Variant('(o)', (D,)))
        for value in ('', '1234567', '12ab', '１２'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.p.respond(dict(id=self.p.prompt['id'], accept=True, value=value))
        self.p.respond(dict(id=self.p.prompt['id'], accept=True, value='000042'))
        self.assertEqual(invocation.return_value.call_args.args[0].unpack(), (42,))
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.p.respond(dict(id=1, accept=True))
        invocation = self.prompt('RequestPinCode', backend.GLib.Variant('(o)', (D,)))
        self.p.respond(dict(id=self.p.prompt['id'], accept=True, value='aB12'))
        self.assertEqual(invocation.return_value.call_args.args[0].unpack(), ('aB12',))

    def test_rejection_cancels_without_trust(self):
        self.start()
        invocation = self.prompt(
            'RequestAuthorization', backend.GLib.Variant('(o)', (D,))
        )
        self.p.respond(dict(id=self.p.prompt['id'], accept=False))
        invocation.return_dbus_error.assert_called_once()
        self.assertEqual(self.methods()[-1], 'CancelPairing')
        # BlueZ blames the device for the agent's rejection; the user rejected.
        self.complete('Pair', 'Pairing was rejected by the device.')
        self.assertNotIn('Set', self.methods())
        self.assertEqual(self.events[-1]['error'], 'Pairing canceled.')

    def test_expiry_withdraws_the_prompt_and_says_it_timed_out(self):
        self.start()
        invocation = self.prompt()
        self.p.expire()
        invocation.return_dbus_error.assert_called_once()
        self.assertIsNone(self.p.prompt)
        self.assertEqual(self.methods()[-1], 'CancelPairing')
        self.complete('Pair', 'Pairing canceled.')
        self.assertEqual(self.events[-1], dict(type='done', error='Pairing timed out.'))

    def test_pairing_completed_before_a_late_cancel_still_connects(self):
        self.start()
        self.p.cancel()
        self.complete('Pair')
        self.assertEqual(self.methods()[-2:], ['CancelPairing', 'Set'])
        self.complete('Set')
        self.complete('Connect')
        self.assertEqual(self.events[-1], dict(type='done', error=''))

    def test_foreign_sender_and_other_device_cannot_prompt(self):
        self.start()
        self.prompt(sender=':other').return_dbus_error.assert_called_once()
        self.prompt(
            args=backend.GLib.Variant('(ou)', ('/other', 1))
        ).return_dbus_error.assert_called_once()
        self.assertIsNone(self.p.prompt)

    def test_cancel_before_pair_and_trust_failure(self):
        self.p.start()
        self.p.cancel()
        self.complete('RegisterAgent')
        self.assertNotIn('Pair', self.methods())
        self.assertEqual(self.events[-1]['error'], 'Pairing canceled.')
        self.setUp()
        self.start()
        self.complete('Pair')
        self.complete('Set', 'Permission denied')
        self.assertNotIn('Connect', self.methods())
        self.assertTrue(self.events[-1]['error'].startswith('Paired, but'))


QML = """import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import Quickshell.Bluetooth
import "drawers"
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:window.contentItem }
 Component { id:deviceType; QtObject {
  property string dbusPath; property string name; property string address; property string icon
  property bool connected; property bool paired; property bool trusted; property bool blocked
  property bool batteryAvailable; property real battery; property int state
 } }
 QtObject { id:adapter; property string name:"Laptop"; property string adapterId:"hci0"; property bool enabled:true
  property bool discovering:false; property int state:BluetoothAdapterState.Enabled; property var devices:({values:[]}) }
 QtObject { id:bt; property var adapters:({values:[adapter]}); property var defaultAdapter:adapter }
 QtObject {
  id:mock
  property QtObject pairingDevice:null
  property bool pairingConnects:false
  property var prompt:null
  property string error:""
  property string errorKey:""
  property string last:""
  property string response:""
  property QtObject scanAdapter:null
  property bool scanning:false
  function startScan(a){scanAdapter=a;scanning=true;a.discovering=true;}
  function stopScan(){if(scanning)scanAdapter.discovering=false;scanning=false;scanAdapter=null;}
  function connect(d){last="connect:"+d.dbusPath;}
  function disconnect(d){last="disconnect:"+d.dbusPath;}
  function forget(d){last="forget:"+d.dbusPath;}
  function pair(d){stopScan();last="pair:"+d.dbusPath;pairingDevice=d;}
  function cancel(){last="cancel";pairingDevice=null;prompt=null;}
  function respond(accept,value){response=accept+":"+value;prompt=null;}
 }
 FloatingWindow { id:window; visible:true; implicitWidth:480; implicitHeight:760; color:Theme.background
  ColumnLayout { id:preview; x:16; y:16; width:window.implicitWidth-32; height:window.implicitHeight-32
   Loader { sourceComponent:drawer.headerActions }
   BluetoothDrawer { id:drawer; Layout.fillWidth:true; Layout.fillHeight:true; active:true; service:mock; bluetooth:bt }
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const value=find(child,name);if(value)return value;}return null;}
 function check(value,message){if(!value)throw Error(message);}
 function click(name){const item=find(preview,name);check(item&&item.enabled,"unavailable "+name);input.mouseClick(item,item.width/2,item.height/2);}
 property var c; property var p; property var n
 Component.onCompleted:{
  c=deviceType.createObject(adapter,{dbusPath:"c",name:"Desk headphones",address:"c",icon:"audio-headphones",connected:true,paired:true,batteryAvailable:true,battery:0,state:BluetoothDeviceState.Connected});
  p=deviceType.createObject(adapter,{dbusPath:"p",name:"Travel headphones with a very long device name",address:"p",icon:"audio-headset",paired:true});
  n=deviceType.createObject(adapter,{dbusPath:"n",name:"Keyboard",address:"n",icon:"input-keyboard",batteryAvailable:true,battery:.75});
  adapter.devices={values:[n,p,c]};
 }
 property int stage:0
 Timer { id:steps; interval:120; running:true; repeat:true; onTriggered:{try{
  if(stage===1){
   check(find(drawer,"bluetoothName:c").mapToItem(drawer,0,0).y<find(drawer,"bluetoothName:p").mapToItem(drawer,0,0).y,"connected not first");
   check(find(drawer,"bluetoothBattery:c").description==="Battery: 0%"&&find(drawer,"bluetoothBatteryTrack:c").visible,"zero battery hidden");
   check(!find(drawer,"bluetoothBatteryTrack:p").visible,"unknown battery shown");
   check(find(drawer,"bluetoothBatteryFill:n").height===15,"battery level");
   check(find(drawer,"bluetoothName:p").truncated,"long name not elided");
   click("bluetoothAction:c");check(mock.last==="disconnect:c","disconnect");
   click("bluetoothAction:p");check(mock.last==="connect:p","connect");
   click("bluetoothPower");check(!adapter.enabled,"power write");
  }else if(stage===2){
   check(!find(drawer,"bluetoothAction:p").enabled&&!find(preview,"bluetoothScan").enabled,"off adapter controls stale");
   adapter.enabled=true;
   adapter.discovering=true;
   const scan=find(preview,"bluetoothScan");
   check(scan.checked&&!scan.enabled,"another client's discovery offered as stoppable");
   adapter.discovering=false;
  }else if(stage===3){
   const label=find(drawer,"bluetoothAction:cLabel"),width=find(drawer,"bluetoothAction:c").width;
   c.state=BluetoothDeviceState.Disconnecting;
   check(label.text==="Disconnecting…"&&!label.truncated&&find(drawer,"bluetoothAction:c").width===width,"progress clipped or resized");
   c.state=BluetoothDeviceState.Connected;
   click("bluetoothScan");check(adapter.discovering&&mock.scanAdapter===adapter,"search");
   click("bluetoothScan");check(!adapter.discovering&&!mock.scanning,"stop search");
   click("bluetoothScan");click("bluetoothAction:n");check(mock.last==="pair:n"&&!adapter.discovering,"pair did not stop search");
   mock.prompt={kind:"RequestConfirmation",code:"000042",id:1,entered:0};
  }else if(stage===4){
   check(find(drawer,"bluetoothAction:n").text==="Pairing…","pairing progress");
   check(find(drawer,"bluetoothPasskey:n").text==="000042"&&!find(preview,"bluetoothScan").enabled,"confirmation");
   click("bluetoothSubmit:n");check(mock.response==="true:","confirm");
   mock.prompt={kind:"RequestPasskey",code:"",id:2,entered:0};
  }else if(stage===5){
   const field=find(drawer,"bluetoothPin:n");check(field.visible&&!find(drawer,"bluetoothSubmit:n").enabled,"passkey field");
   field.forceActiveFocus();for(const key of [Qt.Key_4,Qt.Key_2])input.keyClick(key);
   input.keyClick(Qt.Key_Return);check(mock.response==="true:42","typed passkey lost");
   check(typeof drawer.escapeHandler==="function","escape does not cancel pairing");
   click("bluetoothCancel:n");check(mock.last==="cancel","cancel");
   click("bluetoothForget:p");check(mock.last==="cancel","short click forgot device");
   mock.error="Could not connect.";mock.errorKey="p";
  }else if(stage===6){
   check(!find(drawer,"bluetoothError").visible,"device error shown globally");
   p.blocked=true;check(find(drawer,"bluetoothState:p").visible&&!find(drawer,"bluetoothAction:p").enabled,"blocked device");
   window.implicitWidth=300;
  }else if(stage===7){
   check(find(drawer,"bluetoothAction:c").mapToItem(drawer,0,0).y>find(drawer,"bluetoothName:c").mapToItem(drawer,0,0).y+20,"narrow actions did not wrap");
   adapter.state=BluetoothAdapterState.Blocked;
   check(!find(preview,"bluetoothPower").enabled&&find(drawer,"bluetoothAdapterState").text.includes("blocked"),"blocked adapter");
   click("bluetoothScan");mock.pairingDevice=n;drawer.active=false;
   check(!adapter.discovering&&mock.last==="cancel","dismissal kept search or pairing");
   bt.adapters={values:[]};bt.defaultAdapter=null;
  }else if(stage===8){
   check(drawer.adapter===null&&!find(drawer,"bluetoothAction:c"),"removed adapter retained");
   console.log("DISPLAY_PASS");Qt.quit();
  }stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);steps.stop();Qt.callLater(Qt.quit);}} }
 Timer { interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();} }
}
"""


@unittest.skipUnless(support.QS, 'Quickshell is required')
class BluetoothQmlTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_native_devices_pairing_prompts_and_dismissal(self):
        self.run_qml(QML)

    def test_service_pair_helper_and_native_failure_messages(self):
        def setup(root):
            (root / 'drawers/bluetooth/backend.py').write_text("""import json,sys
def emit(v): print(json.dumps(v),flush=True)
assert sys.argv[1:]==['/dev/x','AA']
emit(dict(type='prompt',prompt=dict(id=1,kind='RequestPasskey',code='')))
for line in sys.stdin:
 r=json.loads(line)
 if r['op']=='respond' and r['value']=='bad': emit(dict(type='error',error='Invalid passkey'))
 elif r['op']=='respond':
  emit(dict(type='prompt',prompt=None));emit(dict(type='connecting'));emit(dict(type='done',error=''));break
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Bluetooth
import "drawers/bluetooth"
ShellRoot {
 component Device: QtObject { property string dbusPath; property string address:"AA"; property bool trusted:false
  property bool connected:false; property int state:BluetoothDeviceState.Disconnected
  function connect(){state=BluetoothDeviceState.Connecting;} }
 Device { id:device; dbusPath:"/dev/x" }
 Device { id:other; dbusPath:"/dev/y" }
 property int stage:0
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:150;running:true;repeat:true;onTriggered:{try{
  const s=BluetoothService;
  if(stage===0){s.connect(device);s.connect(other);check(device.trusted&&other.trusted&&s.error==="","connect did not trust");
   device.state=BluetoothDeviceState.Disconnected;check(s.errorKey==="/dev/x"&&s.error.includes("Could not connect"),"earlier failed connect silent");
   other.connected=true;other.state=BluetoothDeviceState.Connected;check(s.errorKey==="/dev/x","successful connect reported");s.error="";}
  else if(stage===1){device.state=BluetoothDeviceState.Connected;check(s.error==="","settled connect still watched");s.pair(device);}
  else if(stage===3){check(s.prompt&&s.pairingDevice===device,"missing prompt");s.respond(true,"bad");}
  else if(stage===4){check(s.error==="Invalid passkey"&&s.prompt,"input error ended pairing");s.respond(true,"42");}
  else if(stage===6){check(!s.pairingDevice&&!s.prompt&&s.error==="","pairing completion");console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup,
        )

    def test_helper_crash_reaches_the_shell_log(self):
        def setup(root):
            (root / 'drawers/bluetooth/backend.py').write_text(
                "import sys; sys.exit('helper crashed in fixture')\n"
            )

        log = self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/bluetooth"
ShellRoot {
 QtObject { id:device; property string dbusPath:"/dev/x"; property string address:"AA" }
 Component.onCompleted: BluetoothService.pair(device)
 Timer {interval:50;running:true;repeat:true;onTriggered:{
  const s=BluetoothService;
  if(!s.pairingDevice&&s.error==="Bluetooth pairing helper stopped."){console.log("DISPLAY_PASS");Qt.quit();}
 }}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL pairing stuck");Qt.quit();}}
}""",
            setup,
        )
        self.assertIn('Bluetooth pairing helper: helper crashed in fixture', log)

    def test_helper_that_cannot_start_releases_pairing(self):
        with tempfile.TemporaryDirectory() as empty, patch.dict(os.environ, PATH=empty):
            self.run_qml("""import QtQuick
import Quickshell
import "drawers/bluetooth"
ShellRoot {
 QtObject { id:device; property string dbusPath:"/dev/x"; property string address:"AA" }
 Component.onCompleted: BluetoothService.pair(device)
 Timer {interval:50;running:true;repeat:true;onTriggered:{
  const s=BluetoothService;
  if(!s.pairingDevice&&s.error==="Bluetooth pairing helper stopped."){console.log("DISPLAY_PASS");Qt.quit();}
 }}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL pairing stuck");Qt.quit();}}
}""")


ADDRESSES = [f'AA:00:00:00:00:0{n}' for n in range(1, 5)]
BLUEZ_QML = """import QtQuick
import QtQuick.Layouts
import QtTest
import Quickshell
import Quickshell.Bluetooth
import "drawers"
import "drawers/bluetooth"
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:window.contentItem }
 FloatingWindow { id:window; visible:true; implicitWidth:480; implicitHeight:760; color:Theme.background
  ColumnLayout { id:preview; x:16; y:16; width:window.implicitWidth-32; height:window.implicitHeight-32
   Loader { sourceComponent:page.item?.headerActions ?? null }
   Loader { id:page; active:false; Layout.fillWidth:true; Layout.fillHeight:true
    sourceComponent: Component { BluetoothDrawer { active:true } } }
  }
 }
 readonly property var s: BluetoothService
 readonly property var adapter: Bluetooth.defaultAdapter
 function device(n){return adapter?.devices.values.find(d=>d.address==="AA:00:00:00:00:0"+n)??null;}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const value=find(child,name);if(value)return value;}return null;}
 function check(value,message){if(!value)throw Error(message);}
 function shown(name,n){const item=find(preview,n?name+":"+device(n).dbusPath:name);return item&&item.visible&&item.enabled?item:null;}
 function click(name,n){const item=shown(name,n);check(item,"unavailable "+name+" "+(n??""));input.mouseClick(item,item.width/2,item.height/2);}
 // Like DrawerHost: dismissal clears active, then the page is destroyed.
 function dismiss(destroy){page.item.active=false;if(destroy)page.active=false;}
 readonly property var steps:[
  ["BlueZ objects",()=>device(4),()=>{page.active=true;}],
  ["drawer",()=>shown("bluetoothScan"),()=>{
   click("bluetoothScan");check(s.scanning&&!adapter.discovering,"discovery start not pending");dismiss(true);}],
  // The service lets go of the adapter only after stopping reported discovery.
  ["stop applied once reported",()=>!s.scanAdapter&&!adapter.discovering,()=>{page.active=true;}],
  ["drawer reopened",()=>shown("bluetoothScan"),()=>{click("bluetoothScan");}],
  ["discovery",()=>adapter.discovering,()=>{
   click("bluetoothAction",1);check(s.pairingDevice===device(1)&&!s.scanning,"pairing kept discovery");}],
  ["passkey prompt",()=>shown("bluetoothPin",1),()=>{
   shown("bluetoothPin",1).forceActiveFocus();for(const key of [Qt.Key_4,Qt.Key_2,Qt.Key_Return])input.keyClick(key);}],
  ["paired and connected",()=>!s.pairingDevice&&device(1).connected,()=>{
   check(device(1).paired&&device(1).trusted&&s.error===""&&!adapter.discovering,"pairing result");click("bluetoothAction",2);}],
  ["confirmation",()=>shown("bluetoothPasskey",2)?.text==="123456",()=>{click("bluetoothCancel",2);}],
  ["rejected",()=>!s.pairingDevice,()=>{
   check(!device(2).paired&&!device(2).trusted&&s.errorKey===device(2).dbusPath&&s.error==="Pairing canceled.","rejection: "+s.error);
   click("bluetoothAction",2);}],
  ["confirmation again",()=>shown("bluetoothPasskey",2),()=>{dismiss(false);}],
  ["dismissal canceled",()=>!s.pairingDevice,()=>{
   check(!device(2).paired&&s.error==="Pairing canceled.","dismissal: "+s.error);page.item.active=true;
   click("bluetoothAction",3);check(device(3).trusted,"connect did not trust");}],
  ["native connect failure",()=>s.errorKey===device(3).dbusPath,()=>{
   check(s.error.includes("Could not connect")&&shown("bluetoothAction",3).text==="Connect","connect failure");click("bluetoothAction",4);}],
  ["vanished device",()=>!s.pairingDevice&&!device(4),()=>{check(shown("bluetoothError")&&s.error!=="","vanished device error hidden");}],
 ]
 property int stage:0
 Timer { interval:50; running:true; repeat:true; onTriggered:{try{
  if(stage===steps.length){console.log("DISPLAY_PASS");stop();Qt.quit();}
  else if(steps[stage][1]()){steps[stage][2]();stage++;}
 }catch(e){console.error("DISPLAY_FAIL",steps[stage][0],e);stop();Qt.quit();}} }
 Timer { interval:12000; running:true; onTriggered:{console.error("DISPLAY_FAIL timeout:",steps[stage][0]);Qt.quit();} }
}
"""


def device_path(address):
    return '/org/bluez/hci0/dev_' + address.replace(':', '_')


def history(calls, address):
    """A device's calls as (method, *args, outcome)."""
    return [
        (c['method'], *c['args'], c['outcome'])
        for c in calls
        if c['path'] == device_path(address)
    ]


@contextlib.contextmanager
def bluez_service(root, state):
    """Point both buses at a private bus where only a fake BlueZ runs; yield its calls."""
    (root / 'state.json').write_text(json.dumps(state))
    log = root / 'calls.jsonl'
    log.touch()
    service = subprocess.Popen(
        [
            *support.private_bus(root),
            sys.executable,
            '-B',
            FIXTURE,
            root / 'state.json',
            log,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        address = service.stdout.readline().strip()
        if not address:
            raise AssertionError('The fake BlueZ did not start.')
        with patch.dict(
            os.environ,
            DBUS_SYSTEM_BUS_ADDRESS=address,
            DBUS_SESSION_BUS_ADDRESS=address,
        ):
            yield lambda: [json.loads(line) for line in log.read_text().splitlines()]
    finally:
        service.stdin.close()
        service.wait(timeout=10)
        service.stdout.close()


@unittest.skipUnless(
    support.QS and shutil.which('dbus-run-session'),
    'Quickshell and dbus-run-session are required',
)
class BluezDrawerTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_discovery_ownership_and_pairing_against_bluez(self):
        devices = [
            dict(Address=ADDRESSES[0], Alias='Keyboard', Icon='input-keyboard',
                 script=dict(agent='RequestPasskey', reply=[42])),
            dict(Address=ADDRESSES[1], Alias='Phone', Icon='phone',
                 script=dict(agent='RequestConfirmation')),
            dict(Address=ADDRESSES[2], Alias='Headphones', Icon='audio-headphones',
                 Paired=True, Bonded=True, script=dict(connect='fail')),
            dict(Address=ADDRESSES[3], Alias='Gone', script=dict(remove=True)),
        ]  # fmt: skip
        with (
            tempfile.TemporaryDirectory() as directory,
            bluez_service(
                Path(directory), dict(start_delay=400, devices=devices)
            ) as calls,
        ):
            self.run_qml(BLUEZ_QML)
            calls = calls()

        discovery = [c for c in calls if c['method'].endswith('Discovery')]
        # The stop requested while the first start was in flight still reached BlueZ.
        self.assertEqual(
            [(c['method'], c['outcome']) for c in discovery],
            [('StartDiscovery', 'ok'), ('StopDiscovery', 'ok')] * 2,
        )
        self.assertEqual(len({c['sender'] for c in discovery}), 1)
        self.assertEqual(
            [c['args'] for c in calls if c['method'] == 'RegisterAgent'],
            [[backend.AGENT_PATH, 'KeyboardDisplay']] * 4,
        )

        self.assertEqual(
            history(calls, ADDRESSES[0]),
            [
                ('RequestPasskey', [42]),
                ('Pair', 'ok'),
                ('Set', 'Trusted', True, 'ok'),
                ('Connect', 'ok'),
            ],
        )
        self.assertEqual(
            history(calls, ADDRESSES[1]),
            [
                ('RequestConfirmation', 'org.bluez.Error.Rejected'),
                ('Pair', 'AuthenticationRejected'),
                ('CancelPairing', 'DoesNotExist'),
                ('RequestConfirmation', 'org.bluez.Error.Canceled'),
                ('Pair', 'AuthenticationCanceled'),
                ('CancelPairing', 'DoesNotExist'),
            ],
        )
        self.assertEqual(
            history(calls, ADDRESSES[2]),
            [('Set', 'Trusted', True, 'ok'), ('Connect', 'Failed')],
        )
        self.assertEqual(
            history(calls, ADDRESSES[3]), [('Pair', 'AuthenticationCanceled')]
        )


@unittest.skipUnless(shutil.which('dbus-run-session'), 'dbus-run-session is required')
class PairingHelperBusTests(unittest.TestCase):
    def test_shell_reload_cancels_prompts_but_not_a_completed_pairing(self):
        devices = [
            dict(Address=ADDRESSES[0], Alias='Keyboard',
                 script=dict(agent='RequestConfirmation', trust_delay=300)),
            dict(Address=ADDRESSES[1], Alias='Phone',
                 script=dict(agent='RequestConfirmation')),
        ]  # fmt: skip
        with (
            tempfile.TemporaryDirectory() as directory,
            bluez_service(Path(directory), dict(devices=devices)) as calls,
        ):
            # A private copy identifies this test's helper processes.
            source = Path(directory) / 'backend.py'
            shutil.copy(SOURCE, source)

            def reload_at(address, wanted):
                helper = subprocess.Popen(
                    [sys.executable, '-B', source, device_path(address), address],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                )
                for line in helper.stdout:
                    event = json.loads(line)
                    if event['type'] == wanted and event.get('prompt', True):
                        break
                    if event['type'] == 'prompt' and event['prompt']:
                        reply = dict(
                            op='respond', id=event['prompt']['id'], accept=True
                        )
                        helper.stdin.write(json.dumps(reply) + '\n')
                        helper.stdin.flush()
                # Destroying a Quickshell Process SIGKILLs it and closes its pipes.
                helper.kill()
                helper.wait()
                helper.stdin.close()
                helper.stdout.close()

            def settled(address, last):
                deadline = time.monotonic() + 5
                while history(calls(), address)[-1:] != [last]:
                    if time.monotonic() > deadline:
                        self.fail(f'{address}: {history(calls(), address)}')
                    time.sleep(0.05)

            reload_at(ADDRESSES[0], 'connecting')
            settled(ADDRESSES[0], ('Connect', 'ok'))
            reload_at(ADDRESSES[1], 'prompt')
            settled(ADDRESSES[1], ('CancelPairing', 'DoesNotExist'))
            deadline = time.monotonic() + 5
            while subprocess.run(['pgrep', '-f', source], capture_output=True).stdout:
                self.assertLess(
                    time.monotonic(), deadline, 'pairing helper left running'
                )
                time.sleep(0.05)
            calls = calls()
        self.assertEqual(
            history(calls, ADDRESSES[0]),
            [
                ('RequestConfirmation', []),
                ('Pair', 'ok'),
                ('Set', 'Trusted', True, 'ok'),
                ('Connect', 'ok'),
            ],
        )
        # The closed pipe still cancels an unfinished pairing.
        self.assertEqual(
            history(calls, ADDRESSES[1]),
            [
                ('RequestConfirmation', 'org.bluez.Error.Canceled'),
                ('Pair', 'AuthenticationCanceled'),
                ('CancelPairing', 'DoesNotExist'),
            ],
        )


if __name__ == '__main__':
    unittest.main()
