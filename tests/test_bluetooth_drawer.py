"""BlueZ pairing helper and native drawer interactions without host mutations."""
import importlib.util
import json
import os
import unittest
from unittest.mock import Mock, patch

import support

SOURCE = support.DESKTOP / 'drawers/bluetooth/backend.py'
SPEC = importlib.util.spec_from_file_location('desktop_bluetooth', SOURCE)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
D = '/org/bluez/hci0/dev_AA'


class PairingHelperTests(unittest.TestCase):
    def setUp(self):
        self.events, self.calls, self.quit = [], [], Mock()
        self.bus = Mock()
        self.props = dict(Address='AA:BB', Paired=False)
        self.bus.call_sync.side_effect = lambda service, path, interface, method, *a: Mock(
            unpack=Mock(return_value=(self.props,) if method == 'GetAll' else (':bluez',)))
        self.p = backend.Pairing(self.bus, D, 'AA:BB', self.events.append, self.quit)
        self.p.call = lambda path, interface, method, args=None, done=None, timeout=30000: self.calls.append(
            dict(path=path, method=method, args=args, done=done))
        for name in ('timeout_add_seconds', 'source_remove'):
            item = patch.object(backend.GLib, name, return_value=7); item.start(); self.addCleanup(item.stop)

    def complete(self, method, error=''):
        next(c for c in reversed(self.calls) if c['method'] == method)['done'](error)

    def methods(self):
        return [c['method'] for c in self.calls]

    def prompt(self, kind='RequestConfirmation', args=None, sender=':bluez'):
        invocation = Mock()
        self.p.agent(self.bus, sender, backend.AGENT_PATH, 'org.bluez.Agent1', kind,
                     backend.GLib.Variant('(ou)', (D, 42)) if args is None else args, invocation)
        return invocation

    def start(self):
        self.p.start(); self.complete('RegisterAgent')

    def test_errors_are_readable(self):
        error = backend.Gio.dbus_error_new_for_dbus_error('org.bluez.Error.AuthenticationRejected', 'Rejected')
        self.assertEqual(backend.error_text(error), 'Pairing was rejected by the device.')

    def test_stale_or_paired_device_never_registers_agent(self):
        for props in (dict(Address='other'), dict(Address='AA:BB', Paired=True)):
            self.props, self.p.done = props, False
            self.p.start()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.events[-1]['error'])
        self.quit.assert_called()

    def test_confirmed_pairing_trusts_then_connects_and_exits(self):
        self.start()
        self.assertEqual(self.calls[0]['args'].unpack(), (backend.AGENT_PATH, 'KeyboardDisplay'))
        invocation = self.prompt()
        self.assertEqual(self.p.prompt['code'], '000042')
        self.p.respond(dict(id=self.p.prompt['id'], accept=True))
        invocation.return_value.assert_called_once_with(None)
        self.complete('Pair')
        self.assertEqual(self.events[-1], dict(type='connecting'))
        self.assertEqual(self.calls[-1]['args'].unpack(), (backend.DEVICE, 'Trusted', True))
        self.p.cancel()  # Dismissal after pairing must not interrupt the connection.
        self.complete('Set'); self.complete('Connect')
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
        invocation = self.prompt('RequestAuthorization', backend.GLib.Variant('(o)', (D,)))
        self.p.respond(dict(id=self.p.prompt['id'], accept=False))
        invocation.return_dbus_error.assert_called_once()
        self.assertEqual(self.methods()[-1], 'CancelPairing')
        self.complete('Pair', 'Pairing was rejected by the device.')
        self.assertNotIn('Set', self.methods())
        self.assertEqual(self.events[-1]['error'], 'Pairing was rejected by the device.')

    def test_foreign_sender_and_other_device_cannot_prompt(self):
        self.start()
        self.prompt(sender=':other').return_dbus_error.assert_called_once()
        self.prompt(args=backend.GLib.Variant('(ou)', ('/other', 1))).return_dbus_error.assert_called_once()
        self.assertIsNone(self.p.prompt)

    def test_cancel_before_pair_and_trust_failure(self):
        self.p.start(); self.p.cancel(); self.complete('RegisterAgent')
        self.assertNotIn('Pair', self.methods())
        self.assertEqual(self.events[-1]['error'], 'Pairing canceled.')
        self.setUp(); self.start(); self.complete('Pair'); self.complete('Set', 'Permission denied')
        self.assertNotIn('Connect', self.methods())
        self.assertTrue(self.events[-1]['error'].startswith('Paired, but'))


QML = '''import QtQuick
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
  function connect(d){last="connect:"+d.dbusPath;}
  function disconnect(d){last="disconnect:"+d.dbusPath;}
  function forget(d){last="forget:"+d.dbusPath;}
  function pair(d){last="pair:"+d.dbusPath;pairingDevice=d;}
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
  }else if(stage===3){
   const label=find(drawer,"bluetoothAction:cLabel"),width=find(drawer,"bluetoothAction:c").width;
   c.state=BluetoothDeviceState.Disconnecting;
   check(label.text==="Disconnecting…"&&!label.truncated&&find(drawer,"bluetoothAction:c").width===width,"progress clipped or resized");
   c.state=BluetoothDeviceState.Connected;
   click("bluetoothScan");check(adapter.discovering&&drawer.scanAdapter===adapter,"search");
   click("bluetoothAction:n");check(mock.last==="pair:n"&&!adapter.discovering,"pair did not stop search");
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
'''


@unittest.skipUnless(support.QS, 'Quickshell is required')
class BluetoothQmlTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_native_devices_pairing_prompts_and_dismissal(self):
        self.run_qml(QML)

    def test_service_pair_helper_and_native_failure_messages(self):
        def setup(root):
            (root / 'drawers/bluetooth/backend.py').write_text('''import json,sys
def emit(v): print(json.dumps(v),flush=True)
assert sys.argv[1:]==['/dev/x','AA']
emit(dict(type='prompt',prompt=dict(id=1,kind='RequestPasskey',code='')))
for line in sys.stdin:
 r=json.loads(line)
 if r['op']=='respond' and r['value']=='bad': emit(dict(type='error',error='Invalid passkey'))
 elif r['op']=='respond':
  emit(dict(type='prompt',prompt=None));emit(dict(type='connecting'));emit(dict(type='done',error=''));break
''')
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Bluetooth
import "drawers/bluetooth"
ShellRoot {
 QtObject { id:device; property string dbusPath:"/dev/x"; property string address:"AA"; property bool trusted:false
  property bool connected:false; property int state:BluetoothDeviceState.Disconnected
  function connect(){state=BluetoothDeviceState.Connecting;} }
 property int stage:0
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:150;running:true;repeat:true;onTriggered:{try{
  const s=BluetoothService;
  if(stage===0){s.connect(device);check(device.trusted&&s.error==="","connect did not trust");device.state=BluetoothDeviceState.Disconnected;
   check(s.errorKey==="/dev/x"&&s.error.includes("Could not connect"),"failed connect silent");s.pair(device);}
  else if(stage===2){check(s.prompt&&s.pairingDevice===device,"missing prompt");s.respond(true,"bad");}
  else if(stage===3){check(s.error==="Invalid passkey"&&s.prompt,"input error ended pairing");s.respond(true,"42");}
  else if(stage===5){check(!s.pairingDevice&&!s.prompt&&s.error==="","pairing completion");console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup)


if __name__ == '__main__':
    unittest.main()
