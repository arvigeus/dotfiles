"""BlueZ lifecycle and production drawer interactions without host mutations."""
import copy
import importlib.util
import json
import os
import unittest
from unittest.mock import Mock, patch

import test_display_drawer as fixtures

SOURCE = fixtures.DESKTOP / 'drawers/bluetooth/backend.py'
SPEC = importlib.util.spec_from_file_location('desktop_bluetooth', SOURCE)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
A = '/org/bluez/hci0'
D = A + '/dev_AA'


def objects():
    return {A: {backend.ADAPTER: dict(Alias='Laptop', Address='00:11', Powered=True)},
            D: {backend.DEVICE: dict(Adapter=A, Alias='Headphones', Address='AA:BB', Paired=False, Connected=False)}}


class BluetoothBackendTests(unittest.TestCase):
    def setUp(self):
        self.events, self.calls = [], []
        self.bus = Mock()
        self.bus.call_sync.return_value.unpack.return_value = (':bluez',)
        self.controller = backend.Controller(self.bus, self.events.append)
        self.c = self.controller
        self.raw = objects()
        self.c.read = Mock(side_effect=lambda: copy.deepcopy(self.raw))
        self.c.call = self.call
        self.c.active = True
        self.timers = patch.object(backend.GLib, 'timeout_add_seconds', return_value=123)
        self.timer_mock = self.timers.start(); self.addCleanup(self.timers.stop)
        self.remove = patch.object(backend.GLib, 'source_remove')
        self.remove.start(); self.addCleanup(self.remove.stop)

    def call(self, path, interface, method, args=None, done=None, timeout=30000):
        self.calls.append(dict(path=path, interface=interface, method=method, args=args, done=done))

    def complete(self, method, error='', apply=True):
        call = next(call for call in reversed(self.calls) if call['method'] == method)
        if not error and apply:
            if method == 'Pair':
                self.raw[call['path']][backend.DEVICE]['Paired'] = True
            elif method == 'Set' and call['path'] in self.raw:
                interface, name, value = call['args'].unpack()
                self.raw[call['path']][interface][name] = value
        call['done'](error)

    def request(self, op, **fields):
        self.c.handle(dict(op=op, key=D, address='AA:BB', **fields))

    def prompt(self, kind='RequestConfirmation', args=None):
        invocation = Mock()
        self.c.agent(self.bus, ':bluez', backend.AGENT_PATH, 'org.bluez.Agent1', kind,
                     backend.GLib.Variant('(ou)', (D, 42)) if args is None else args, invocation)
        return invocation

    def test_inventory_preserves_zero_battery_alias_and_unknown(self):
        self.raw[D]['org.bluez.Battery1'] = dict(Percentage=0)
        row = backend.inventory(self.raw)['devices'][0]
        self.assertEqual((row['name'], row['battery']), ('Headphones', 0))
        del self.raw[D]['org.bluez.Battery1']
        del self.raw[D][backend.DEVICE]['Alias']
        row = backend.inventory(self.raw)['devices'][0]
        self.assertEqual((row['name'], row['battery']), ('AA:BB', -1))

    def test_dbus_errors_are_readable_without_transport_details(self):
        error = backend.Gio.dbus_error_new_for_dbus_error('org.bluez.Error.AuthenticationRejected', 'Rejected')
        self.assertEqual(backend.error_text(error), 'Pairing was rejected by the device.')

    def test_pin_reply_and_agent_cancel_expire_the_prompt(self):
        self.request('pair'); self.complete('RegisterAgent')
        invocation = self.prompt('RequestPinCode', backend.GLib.Variant('(o)', (D,)))
        self.c.respond(dict(id=self.c.prompt['id'], accept=True, value='aB12'))
        self.assertEqual(invocation.return_value.call_args.args[0].unpack(), ('aB12',))
        invocation = self.prompt('RequestAuthorization', backend.GLib.Variant('(o)', (D,)))
        canceled = self.prompt('Cancel', backend.GLib.Variant('()', ()))
        invocation.return_dbus_error.assert_called_once()
        canceled.return_value.assert_called_once_with(None)
        self.assertIsNone(self.c.prompt)

    def test_stale_blocked_off_and_unsupported_actions_never_write(self):
        for changes, request in [({}, dict(op='delete')), ({}, dict(op='connect')),
                                 ({}, dict(op='pair', address='replacement')),
                                 ({'Blocked': True}, dict(op='pair'))]:
            self.raw[D][backend.DEVICE].update(changes)
            with self.assertRaises(ValueError):
                self.c.handle(dict(dict(key=D, address='AA:BB'), **request))
        self.raw[A][backend.ADAPTER]['Powered'] = False
        with self.assertRaises(ValueError): self.request('pair')
        self.assertEqual(self.calls, [])

    def test_opening_only_reads_and_discovery_is_owned_bounded_and_stopped(self):
        self.c.handle(dict(op='observe', active=True))
        self.assertEqual(self.calls, [])
        self.c.handle(dict(op='scan', key=A))
        self.complete('StartDiscovery')
        self.assertEqual(self.c.scan, A)
        self.timer_mock.assert_called_with(30, self.c.stop_scan)
        self.c.handle(dict(op='observe', active=False))
        self.assertEqual(self.c.scan, '')
        self.assertEqual([c['method'] for c in self.calls], ['StartDiscovery', 'StopDiscovery'])
        self.c.stop_scan()
        self.assertEqual(len(self.calls), 2)

    def test_scan_started_after_dismissal_is_immediately_released(self):
        self.c.handle(dict(op='scan', key=A))
        self.c.handle(dict(op='observe', active=False))
        self.complete('StartDiscovery')
        self.assertEqual(self.c.scan, '')
        self.assertEqual(self.calls[-1]['method'], 'StopDiscovery')

    def test_pair_confirms_code_then_trusts_only_paired_device_before_connecting(self):
        self.request('pair')
        self.assertEqual(self.calls[-1]['args'].unpack(), (backend.AGENT_PATH, 'KeyboardDisplay'))
        self.complete('RegisterAgent')
        invocation = self.prompt()
        self.assertEqual(self.c.prompt['code'], '000042')
        invocation.return_value.assert_not_called()
        self.c.respond(dict(id=self.c.prompt['id'], accept=True))
        invocation.return_value.assert_called_once_with(None)
        self.complete('Pair')
        self.assertEqual(self.c.pending['op'], 'connect')
        self.assertEqual(self.calls[-1]['method'], 'Set')
        self.assertEqual(self.calls[-1]['args'].unpack(), (backend.DEVICE, 'Trusted', True))
        self.assertNotIn('Connect', [c['method'] for c in self.calls])
        self.complete('Set')
        self.assertEqual(self.calls[-1]['method'], 'Connect')
        self.complete('Connect')
        self.assertIsNone(self.c.pending)
        self.assertNotIn('RequestDefaultAgent', [c['method'] for c in self.calls])
        self.assertTrue(self.raw[D][backend.DEVICE]['Trusted'])
        self.assertEqual([c['path'] for c in self.calls if c['method'] == 'Set'], [D])

    def test_passkey_input_validation_and_expired_response(self):
        self.request('pair'); self.complete('RegisterAgent')
        invocation = self.prompt('RequestPasskey', backend.GLib.Variant('(o)', (D,)))
        for value in ('', '-1', '1234567', '12ab', '１２'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.c.respond(dict(id=self.c.prompt['id'], accept=True, value=value))
        invocation.return_value.assert_not_called()
        self.c.respond(dict(id=self.c.prompt['id'], accept=True, value='000042'))
        self.assertEqual(invocation.return_value.call_args.args[0].unpack(), (42,))
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.c.respond(dict(id=1, accept=True))

    def test_display_progress_is_acknowledged_and_rejection_stops_pairing(self):
        self.request('pair'); self.complete('RegisterAgent')
        invocation = self.prompt('DisplayPasskey', backend.GLib.Variant('(ouq)', (D, 42, 3)))
        invocation.return_value.assert_called_once_with(None)
        self.assertEqual((self.c.prompt['code'], self.c.prompt['entered']), ('000042', 3))
        invocation = self.prompt('RequestAuthorization', backend.GLib.Variant('(o)', (D,)))
        self.c.respond(dict(id=self.c.prompt['id'], accept=False))
        invocation.return_dbus_error.assert_called_once()
        self.assertEqual(self.calls[-1]['method'], 'CancelPairing')
        self.complete('Pair', 'AuthenticationRejected')
        self.assertIsNone(self.c.pending)
        self.assertIn('AuthenticationRejected', self.events[-2]['error'])
        self.assertNotIn('Set', [c['method'] for c in self.calls])

    def test_foreign_sender_or_unrequested_device_cannot_prompt(self):
        invocation = self.prompt()
        invocation.return_dbus_error.assert_called_once()
        self.request('pair'); self.complete('RegisterAgent')
        self.bus.call_sync.return_value.unpack.return_value = (':other',)
        invocation = self.prompt()
        invocation.return_dbus_error.assert_called_once()
        self.assertIsNone(self.c.prompt)

    def test_dismissal_and_adapter_loss_cancel_pairing_without_connecting(self):
        self.request('pair'); self.complete('RegisterAgent')
        invocation = self.prompt()
        self.raw[A][backend.ADAPTER]['Powered'] = False
        self.c.refresh()
        invocation.return_dbus_error.assert_called_once()
        self.assertTrue(self.c.pending['canceled'])
        self.complete('Pair')
        self.assertNotIn('Connect', [c['method'] for c in self.calls])
        self.assertNotIn('Set', [c['method'] for c in self.calls])
        self.raw[D][backend.DEVICE]['Paired'] = False
        self.c.active = True; self.raw[A][backend.ADAPTER]['Powered'] = True
        self.request('pair')
        self.c.handle(dict(op='observe', active=False))
        self.assertTrue(self.c.pending['canceled'])

    def test_connect_survives_dismissal_and_forget_targets_current_adapter(self):
        self.raw[D][backend.DEVICE]['Paired'] = True
        self.request('connect')
        self.c.handle(dict(op='observe', active=False))
        self.assertEqual([c['method'] for c in self.calls], ['Set'])
        self.complete('Set')
        self.assertEqual(self.calls[-1]['method'], 'Connect')
        self.complete('Connect', 'NotSupported')
        self.assertIsNone(self.c.pending)
        self.assertEqual(self.events[-1]['error'], 'NotSupported')
        self.assertTrue(self.raw[D][backend.DEVICE]['Trusted'])
        self.c.active = True
        self.request('forget')
        self.assertEqual((self.calls[-1]['path'], self.calls[-1]['args'].unpack()), (A, (D,)))

    def test_already_trusted_connection_does_not_rewrite_trust(self):
        self.raw[D][backend.DEVICE].update(Paired=True, Trusted=True)
        self.request('connect')
        self.assertEqual([c['method'] for c in self.calls], ['Connect'])

    def test_trust_write_failure_stops_connection_and_reports_error(self):
        self.raw[D][backend.DEVICE]['Paired'] = True
        self.request('connect')
        self.complete('Set', 'Permission denied')
        self.assertNotIn('Connect', [c['method'] for c in self.calls])
        self.assertIsNone(self.c.pending)
        self.assertIn('authorize automatic reconnections', self.events[-2]['error'])

    def test_pair_success_trust_failure_preserves_pairing_and_reports_partial_success(self):
        self.request('pair'); self.complete('RegisterAgent'); self.complete('Pair')
        self.complete('Set', 'Permission denied')
        self.assertTrue(self.raw[D][backend.DEVICE]['Paired'])
        self.assertFalse(self.raw[D][backend.DEVICE].get('Trusted', False))
        self.assertNotIn('Connect', [c['method'] for c in self.calls])
        self.assertTrue(self.events[-2]['error'].startswith('Paired, but'))

    def test_unconfirmed_trust_write_does_not_connect(self):
        self.raw[D][backend.DEVICE]['Paired'] = True
        self.request('connect')
        self.complete('Set', apply=False)
        self.assertNotIn('Connect', [c['method'] for c in self.calls])
        self.assertIn('confirm authorization', self.events[-2]['error'])

    def test_device_loss_during_trust_write_does_not_connect(self):
        self.raw[D][backend.DEVICE]['Paired'] = True
        self.request('connect')
        del self.raw[D]
        self.complete('Set')
        self.assertNotIn('Connect', [c['method'] for c in self.calls])
        self.assertIsNone(self.c.pending)

    def test_connection_rechecks_address_pairing_block_and_adapter_after_trust(self):
        for change in ('address', 'pairing', 'blocked', 'power'):
            with self.subTest(change=change):
                self.raw = objects()
                self.raw[D][backend.DEVICE]['Paired'] = True
                self.calls.clear()
                self.request('connect')
                if change == 'address': self.raw[D][backend.DEVICE]['Address'] = 'replacement'
                elif change == 'pairing': self.raw[D][backend.DEVICE]['Paired'] = False
                elif change == 'blocked': self.raw[D][backend.DEVICE]['Blocked'] = True
                else: self.raw[A][backend.ADAPTER]['Powered'] = False
                self.complete('Set')
                self.assertNotIn('Connect', [c['method'] for c in self.calls])
                self.assertIsNone(self.c.pending)

    def test_completed_pair_connection_survives_dismissal(self):
        self.request('pair'); self.complete('RegisterAgent'); self.complete('Pair')
        self.c.handle(dict(op='observe', active=False))
        self.assertNotIn('CancelPairing', [c['method'] for c in self.calls])
        self.complete('Set'); self.complete('Connect')
        self.assertIsNone(self.c.pending)

    def test_disconnect_and_forget_never_grant_trust(self):
        self.raw[D][backend.DEVICE]['Paired'] = True
        self.request('disconnect'); self.complete('Disconnect')
        self.request('forget'); self.complete('RemoveDevice')
        self.assertEqual([c['method'] for c in self.calls], ['Disconnect', 'RemoveDevice'])


QML = '''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import Quickshell.Wayland
import "drawers"
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:window.contentItem }
 QtObject {
  id:mock
  property var state: ({available:true,adapters:[{key:"a",name:"Laptop",address:"00",powered:true},{key:"b",name:"USB",address:"11",powered:true}],devices:ROWS})
  property bool loaded:true
  property string error:""
  property string errorKey:""
  property string pending:""
  property string pendingKey:""
  property string scanning:""
  property var prompt:null
  readonly property bool busy:pending!==""
  property var owners:[]
  property string lastOp:""
  property var lastFields: ({})
  property string response:""
  property int stopped:0
  property int calls:0
  function observe(owner,active){owners=owners.filter(o=>o!==owner).concat(active?[owner]:[]);}
  function run(op,record,fields){lastOp=op;lastFields=fields;calls++;}
  function stopScan(){scanning="";stopped++;}
  function cancel(){pending="";pendingKey="";prompt=null;lastOp="cancel";}
  function respond(accept,value){response=String(accept)+":"+value;prompt=null;}
 }
 PanelWindow { id:window; visible:true; implicitWidth:480; implicitHeight:760; color:Theme.background
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
  Item { id:preview; width:window.implicitWidth; height:parent.height
   Rectangle { anchors.fill:parent; color:Theme.background }
   ColumnLayout { anchors.fill:parent; anchors.margins:16; spacing:16
    RowLayout {
     Layout.fillWidth:true;spacing:12
     ColumnLayout {
      Layout.fillWidth:true;spacing:2
      ShellText { text:"Bluetooth";font.pixelSize:Theme.titleFontSize;Layout.fillWidth:true;elide:Text.ElideRight }
     }
     Loader { sourceComponent:drawer.headerActions }
     ShellButton { text:"×";Layout.preferredWidth:34 }
    }
    Rectangle { Layout.fillWidth:true;implicitHeight:1;color:Theme.border }
    BluetoothDrawer { id:drawer; Layout.fillWidth:true;Layout.fillHeight:true; active:true; service:mock }
   }
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children||[]){const value=find(child,name);if(value)return value;}return null;}
 function check(value,message){if(!value)throw Error(message);}
 function click(name){const item=find(preview,name);check(item&&item.enabled,"unavailable "+name);input.mouseClick(item,item.width/2,item.height/2);}
 property bool capturing:false
 function capture(name,after){
  const path=Quickshell.env("DISPLAY_PREVIEW_DIR");
  if(!path){if(after)after();return;}
  capturing=true;
  preview.grabToImage(r=>{try{check(r.saveToFile(path+"/bluetooth-"+name+".png"),"capture failed");if(after)after();capturing=false;}
   catch(e){console.error("DISPLAY_FAIL",e);Qt.callLater(Qt.quit);}});
 }
 property int stage:-5
 property var actionPosition:null
 property var forgetPosition:null
 property var namePosition:null
 property var nextPosition:null
 function rememberPositions(){
  actionPosition=find(drawer,"bluetoothAction:c").mapToItem(drawer,0,0);forgetPosition=find(drawer,"bluetoothForget:c").mapToItem(drawer,0,0);
  namePosition=find(drawer,"bluetoothName:c").mapToItem(drawer,0,0);nextPosition=find(drawer,"bluetoothName:p").mapToItem(drawer,0,0);
 }
 function checkPositions(busy=true){
  const action=find(drawer,"bluetoothAction:c"),forget=find(drawer,"bluetoothForget:c");
  if(busy){
   const label=find(action,"bluetoothAction:cLabel");
   check(action.visible&&!action.enabled&&action.text===drawer.progress(mock.pending),"pending action lacks progress text");
   check(label.visible&&label.text===action.text&&!label.truncated,"progress text is blank or clipped: "+JSON.stringify({stage,text:label.text,width:label.width,implicitWidth:label.implicitWidth,truncated:label.truncated,visible:label.visible,buttonWidth:action.width}));
  }
  check(Math.abs(action.mapToItem(drawer,0,0).x-actionPosition.x)<1&&Math.abs(action.mapToItem(drawer,0,0).y-actionPosition.y)<1,"pending action moved");
  check(Math.abs(forget.mapToItem(drawer,0,0).x-forgetPosition.x)<1&&Math.abs(forget.mapToItem(drawer,0,0).y-forgetPosition.y)<1,"forget moved during action");
  check(Math.abs(find(drawer,"bluetoothName:c").mapToItem(drawer,0,0).y-namePosition.y)<1,"battery availability shifted the name");
  check(Math.abs(find(drawer,"bluetoothName:p").mapToItem(drawer,0,0).y-nextPosition.y)<1,"battery availability changed the card height");
 }
 function setBattery(value){mock.state=Object.assign({},mock.state,{devices:mock.state.devices.map(d=>d.key==="c"?Object.assign({},d,{battery:value}):d)});}
 property bool stepping:false
 Timer { id:steps; interval:160; running:true; repeat:true; onTriggered:{if(capturing||stepping)return;stepping=true;try{
  if(stage===-5){rememberPositions();setBattery(-1);
  }else if(stage===-4){checkPositions(false);check(!find(drawer,"bluetoothBattery:c").available&&!find(drawer,"bluetoothBatteryTrack:c").visible,"unavailable battery shown");setBattery(0);
  }else if(stage===-3){checkPositions(false);rememberPositions();mock.pending="disconnect";mock.pendingKey="c";
  }else if(stage===-2){checkPositions();capture("busy",()=>{mock.pending="connect";});
  }else if(stage===-1){checkPositions();mock.pending="";mock.pendingKey="";
  }else if(stage===0){
   check(mock.owners.length===1,"not observing");
   check(find(preview,"bluetoothInfo").iconName==="info"&&!find(drawer,"bluetoothPower")&&find(preview,"bluetoothPower").checked,"power/alias missing in header");
   check(mock.calls===0,"power read triggered a mutation");
   click("bluetoothPower");
   check(mock.lastOp==="power"&&mock.lastFields.enabled===false&&find(preview,"bluetoothPower").checked,"power request did not preserve readback binding");
   mock.calls=0;
   check(find(preview,"bluetoothScan").iconName==="refresh-cw"&&!find(drawer,"bluetoothScan"),"discovery is not a header refresh");
   check(find(preview,"bluetoothEdit").iconName==="pencil","Bluetooth editor missing");
   check(find(drawer,"bluetoothBattery:c").description==="Battery: 0%"&&find(drawer,"bluetoothBatteryTrack:c").visible,"zero battery hidden");
   check(!find(drawer,"bluetoothBatteryTrack:p").visible,"unknown battery shown");
   check(find(drawer,"bluetoothBattery:c").width===find(drawer,"bluetoothBattery:p").width,"battery slot not reserved");
   check(find(drawer,"bluetoothAction:c").text==="Disconnect","connected action");
   check(find(drawer,"bluetoothBatteryFill:c").height===1&&find(drawer,"bluetoothBatteryFill:n").height===15,"battery bar levels");
   check(find(drawer,"bluetoothName:p").truncated&&find(drawer,"bluetoothName:p").width>=100,"long name did not retain useful space");
   check(Math.abs(find(drawer,"bluetoothName:c").mapToItem(drawer,0,0).y-find(drawer,"bluetoothAction:c").mapToItem(drawer,0,0).y)<12,"normal layout is not one row");
   for(const key of ["c","p"]){
    const name=find(drawer,"bluetoothName:"+key),action=find(drawer,"bluetoothAction:"+key);
    check(Math.abs(name.mapToItem(drawer,0,name.height/2).y-action.mapToItem(drawer,0,action.height/2).y)<1,"name is not vertically centered");
   }
   for(const key of ["c","p","n"]){
    check(!find(drawer,"bluetoothState:"+key).visible,"default state repeats section");
   }
   click("bluetoothAction:c");check(mock.lastOp==="disconnect","disconnect");
   click("bluetoothAction:p");check(mock.lastOp==="connect","connect");capture("devices");
  }else if(stage===1){
   click("bluetoothAction:n");check(mock.lastOp==="pair","pair");
   mock.pending="pair";mock.pendingKey="n";mock.prompt={key:"n",kind:"RequestConfirmation",code:"000042",id:1,entered:0};
   check(find(drawer,"bluetoothAction:n").text==="Pairing…"&&!find(drawer,"bluetoothState:n").visible,"pairing lacks button progress");
  }else if(stage===2){
   check(find(drawer,"bluetoothPasskey:n").text==="000042","confirmation code");
   check(!find(preview,"bluetoothScan").enabled,"scan available while pairing");
   capture("confirmation",()=>{click("bluetoothSubmit:n");check(mock.response==="true:","confirm");
    mock.prompt={key:"n",kind:"RequestPasskey",code:"",id:2,entered:0};});
  }else if(stage===3){
   const field=find(drawer,"bluetoothPin:n");check(field.visible,"missing passkey field");
   check(!find(drawer,"bluetoothSubmit:n").enabled,"empty input accepted");
   field.forceActiveFocus();for(const key of [Qt.Key_0,Qt.Key_0,Qt.Key_0,Qt.Key_0,Qt.Key_4,Qt.Key_2])input.keyClick(key);
   input.keyClick(Qt.Key_Return);check(mock.response==="true:000042","typed passkey lost");
   mock.prompt={key:"n",kind:"DisplayPasskey",code:"000042",id:3,entered:3};
  }else if(stage===4){
   check(!find(drawer,"bluetoothSubmit:n").visible,"display prompt offers confirmation");
   check(find(drawer,"bluetoothAction:n").visible&&!find(drawer,"bluetoothAction:n").enabled,"pair action did not stay in place");
   capture("keyboard",()=>{click("bluetoothCancel:n");check(mock.lastOp==="cancel","cancel");
    click("bluetoothForget:p");check(mock.lastOp==="cancel"&&!drawer.escapeHandler,"short click forgot device or opened confirmation");});
  }else if(stage===5){
   check(find(drawer,"bluetoothForget:p").holdDuration===1300,"forget hold duration");
  }else if(stage===6){
   mock.scanning="a";check(find(preview,"bluetoothScan").checked,"discovery not highlighted");
   click("bluetoothScan");check(mock.stopped===1,"stop search");
   click("bluetoothScan");check(mock.lastOp==="scan","search");
   window.implicitWidth=300;
  }else if(stage===7){
   check(drawer.width<=300,"narrow width did not apply");
   check(find(drawer,"bluetoothAction:c").mapToItem(drawer,0,0).y>find(drawer,"bluetoothName:c").mapToItem(drawer,0,0).y+20,"narrow actions did not wrap");
   rememberPositions();mock.pending="disconnect";mock.pendingKey="c";
   capture("narrow");
  }else if(stage===8){
   checkPositions();mock.pending="";mock.pendingKey="";
   mock.state={available:true,adapters:[{key:"a",name:"Laptop",powered:false}],devices:mock.state.devices};
   check(!find(drawer,"bluetoothAction:c").enabled&&!find(preview,"bluetoothScan").enabled,"off adapter controls stale");
   check(!find(preview,"bluetoothPower").checked,"power switch missed external change");
   Theme.setMode("light");
  }else if(stage===9){capture("off-light");
  }else if(stage===10){
   mock.state={available:true,adapters:mock.state.adapters,devices:mock.state.devices.map(d=>Object.assign({},d,{blocked:d.key==="n"}))};
   check(find(drawer,"bluetoothState:n").visible&&find(drawer,"bluetoothState:n").text.includes("Blocked"),"blocked explanation hidden");
   mock.state={available:true,adapters:[],devices:[]};
   check(drawer.adapter===null&&!find(drawer,"bluetoothAction:c"),"removed device retained");
   check(!find(preview,"bluetoothPower").enabled,"missing adapter toggle active");
   drawer.active=false;check(mock.owners.length===0,"dismissal retained observer");
   console.log("DISPLAY_PASS");Qt.quit();
  }stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);steps.stop();Qt.callLater(Qt.quit);}finally{stepping=false;}} }
 Timer { interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.callLater(Qt.quit);} }
}
'''


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class BluetoothQmlTests(unittest.TestCase):
    run_qml = fixtures.DisplayQmlTests.run_qml
    def run_drawer(self, body, rows):
        body = body.replace('ROWS', json.dumps(rows))
        if os.environ.get('DISPLAY_PREVIEW_PLATFORM', 'offscreen') == 'offscreen':
            body = body.replace('PanelWindow {', 'FloatingWindow {')
            body = body.replace('  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive\n', '')
        self.run_qml(body)

    def test_devices_pairing_forget_removal_and_narrow_layout(self):
        rows = [dict(key=key, adapter='a', address=key, name=name, icon=icon, paired=paired,
                     connected=connected, blocked=False, battery=battery)
                for key, name, icon, paired, connected, battery in
                [('c', 'Desk headphones', 'audio-headphones', True, True, 0),
                 ('p', 'Travel headphones with a very long device name', 'audio-headset', True, False, -1),
                 ('n', 'Keyboard', 'input-keyboard', False, False, 75)]]
        self.run_drawer(QML, rows)

    def test_forget_requires_hold_and_cancels_on_dismissal_or_removal(self):
        rows = backend.inventory(objects())['devices']
        rows[0].update(key='c', adapter='a', paired=True)
        body = QML.split(' property int stage:-5')[0] + '''
 property int stage:0
 property bool stepping:false
 property var button:null
 Timer { id:steps;interval:100;running:true;repeat:true;onTriggered:{if(stepping)return;stepping=true;try{
  if(stage===0){
   button=find(drawer,"bluetoothForget:c");check(button.holdDuration===1300,"wrong production hold duration");
   check(button.width===34&&button.contentItem.width===18,"forget icon sizing changed");button.holdDuration=350;
   click("bluetoothForget:c");check(mock.calls===0,"short click forgot device");
   input.mousePress(button,button.width/2,button.height/2);
  }else if(stage===1){
   input.mouseRelease(button,button.width/2,button.height/2);check(mock.calls===0&&button.progress===0,"early release did not cancel");
   button.forceActiveFocus();input.keyPress(Qt.Key_Space);
  }else if(stage===2){drawer.active=false;input.keyRelease(Qt.Key_Space);
  }else if(stage===4){check(mock.calls===0&&button.progress===0,"dismissal confirmed hold");drawer.active=true;
  }else if(stage===5){input.mousePress(button,button.width/2,button.height/2);
  }else if(stage===10){
   check(mock.calls===1&&mock.lastOp==="forget","pointer hold did not confirm exactly once");input.mouseRelease(button,button.width/2,button.height/2);
   button.forceActiveFocus();input.keyPress(Qt.Key_Space);
  }else if(stage===15){
   check(mock.calls===2,"keyboard hold did not confirm exactly once");input.keyRelease(Qt.Key_Space);
   input.mousePress(button,button.width/2,button.height/2);
   mock.state=Object.assign({},mock.state,{devices:[]});
  }else if(stage===20){
   check(mock.calls===2&&!find(drawer,"bluetoothForget:c"),"removed device confirmed hold");
   input.mouseRelease(window.contentItem,1,1);console.log("DISPLAY_PASS");Qt.callLater(Qt.quit);
  }stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);steps.stop();Qt.callLater(Qt.quit);}finally{stepping=false;}} }
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.callLater(Qt.quit);}}
}
'''
        self.run_drawer(body, rows)


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class BluetoothServiceTests(unittest.TestCase):
    run_qml = fixtures.DisplayQmlTests.run_qml

    def test_worker_protocol_dismissal_pending_operation_and_reopening(self):
        def setup(root):
            (root / 'drawers/bluetooth/backend.py').write_text('''import json,sys,threading
lock=threading.Lock()
def emit(value):
 with lock: print(json.dumps(value),flush=True)
def finish(): emit(dict(type='done',error=''))
for line in sys.stdin:
 r=json.loads(line);op=r['op']
 if op=='observe':
  if r['active']: emit(dict(type='state',available=True,adapters=[],devices=[]))
  else:
   emit(dict(type='scan',key=''));emit(dict(type='prompt',prompt=None))
 elif op=='connect':
  emit(dict(type='pending',op=op,key=r['key']));threading.Timer(.5,finish).start()
 elif op=='pair':
  emit(dict(type='pending',op=op,key=r['key']))
  emit(dict(type='prompt',prompt=dict(id=1,key=r['key'],kind='RequestPasskey',code='')))
 elif op=='respond':
  if r['value']=='bad':emit(dict(type='error',error='Invalid passkey',busy=True))
  else:
   emit(dict(type='prompt',prompt=None));finish()
 elif op=='cancel':
  emit(dict(type='prompt',prompt=None));finish()
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/bluetooth"
ShellRoot {
 id:root
 property int stage:0
 function check(value,message){if(!value)throw Error(message);}
 Component.onCompleted:BluetoothService.observe(root,true)
 Timer {interval:180;running:true;repeat:true;onTriggered:{try{
  const s=BluetoothService;
  if(root.stage===0){check(s.loaded,"did not load");s.run("connect",{key:"device",address:"AA"});}
  else if(root.stage===1){s.observe(root,false);check(s.busy,"pending action lost on dismissal");}
  else if(root.stage===4){check(!s.busy&&s.error==="","dismissal interrupted connection");s.observe(root,true);}
  else if(root.stage===5){check(s.loaded,"reopen failed");s.run("pair",{key:"device",address:"AA"});}
  else if(root.stage===6){check(s.prompt&&s.busy,"missing prompt");s.respond(true,"bad");}
  else if(root.stage===7){check(s.error==="Invalid passkey"&&s.busy&&s.prompt,"input error cleared pairing");s.respond(true,"42");}
  else if(root.stage===8){check(!s.busy&&!s.prompt&&s.error==="","pairing completion");s.observe(root,false);s.observe(root,true);}
  else if(root.stage===10){check(s.loaded&&s.error==="","quick reopen failed");s.observe(root,false);console.log("DISPLAY_PASS");Qt.quit();}
  root.stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup)


if __name__ == '__main__':
    unittest.main()
