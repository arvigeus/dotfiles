"""Recoverable charge-once/recording actions and production drawer layouts."""
import copy
import json
import importlib.util
import os
import select
import subprocess
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys

import support
import test_power_drawers as fixtures

backend = fixtures.backend
with patch.dict(sys.modules, {'backend': backend}):
    session = fixtures.load('power_utilities', support.DESKTOP / 'drawers/power/session.py')


class UtilitiesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.row = copy.deepcopy(fixtures.snapshot()['hardware'][0])
        self.controller = Mock()
        self.controller.hardware.side_effect = lambda: ([copy.deepcopy(self.row)], [])
        self.controller.handle.side_effect = self.change
        self.utility = session.Session(self.root, self.controller)
        self.power(False)

    def power(self, value, target=None):
        (target or self.utility).handle(dict(op='power', onBattery=value))

    def change(self, request):
        self.assertEqual(request['op'], 'charge-limit')
        self.assertEqual(request['previous'], self.row['limit'])
        self.row['limit'] = request['value']

    def once(self):
        self.utility.handle(dict(op='charge-once', key=self.row['key'], identity=self.row['identity'], limit=self.row['limit']))

    def test_charge_once_survives_reload_and_restores_after_unplug(self):
        self.once()
        self.assertEqual(self.row['limit'], 100)
        reloaded = session.Session(self.root, self.controller)
        self.power(False, reloaded)
        self.assertEqual(self.row['limit'], 100)
        self.power(True, reloaded)
        self.assertEqual(self.row['limit'], 80)
        self.assertIsNone(reloaded.data['once'])
        self.assertIsNone(json.loads(reloaded.path.read_text())['once'])

    def test_intent_precedes_charge_mutation_and_reboot_restores_it(self):
        original = self.controller.handle.side_effect
        def checked(request):
            saved = json.loads(self.utility.path.read_text())
            self.assertEqual(saved['once']['previous'], 80)
            original(request)
        self.controller.handle.side_effect = checked
        self.once()
        self.controller.handle.side_effect = original
        self.utility.boot = 'another-boot'
        self.utility.reconcile()
        self.assertEqual(self.row['limit'], 80)

    def test_charge_restoration_retries_when_controller_returns(self):
        self.once()
        self.controller.hardware.side_effect = lambda: ([], [])
        with self.assertRaisesRegex(ValueError, 'pending restoration'):
            self.power(True)
        self.assertIsNotNone(self.utility.data['once'])
        self.controller.hardware.side_effect = lambda: ([copy.deepcopy(self.row)], [])
        self.utility.reconcile()
        self.assertEqual(self.row['limit'], 80)

    def test_pending_charge_can_be_restored_without_unplugging(self):
        self.once()
        self.utility.handle(dict(op='restore-charge'))
        self.assertEqual(self.row['limit'], 80)
        self.assertIsNone(self.utility.data['once'])

    def test_malformed_saved_actions_do_not_prevent_startup(self):
        self.utility.path.write_text(json.dumps(dict(once={'previous': 'invalid'}, recording={'running': True})))
        reloaded = session.Session(self.root, self.controller)
        self.power(False, reloaded)
        self.assertIsNone(reloaded.data['once'])
        self.assertIsNone(reloaded.data['recording'])
        self.controller.handle.assert_not_called()

    def test_invalid_recording_summary_is_not_published(self):
        (self.root / 'summary.json').write_text('[]')
        self.utility.path.write_text(json.dumps(dict(recording=dict(path=str(self.root), summary=['invalid']))))
        reloaded = session.Session(self.root, self.controller)
        self.assertIsNone(reloaded.data['recording']['summary'])
        self.assertIn('without a summary', reloaded.data['recording']['error'])

    def test_external_and_manual_limits_are_respected(self):
        self.once()
        self.row['limit'] = 65
        self.power(True)
        self.assertEqual(self.row['limit'], 65)
        self.assertIsNone(self.utility.data['once'])
        self.power(False)
        self.once()
        self.utility.handle(dict(op='charge-limit', previous=100, value=70))
        self.assertIsNone(self.utility.data['once'])
        self.power(True)
        self.assertEqual(self.row['limit'], 70)

    def test_stale_charge_once_and_unplugged_start_do_not_write(self):
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.utility.handle(dict(op='charge-once', key=self.row['key'], identity='stale', limit=80))
        self.power(None)
        with self.assertRaisesRegex(ValueError, 'Connect'):
            self.once()
        self.controller.handle.assert_not_called()

    def test_failed_charge_write_does_not_claim_full_charge(self):
        self.controller.handle.side_effect = ValueError('denied')
        with self.assertRaisesRegex(ValueError, 'denied'):
            self.once()
        self.assertIsNone(self.utility.data['once'])
        self.assertEqual(self.row['limit'], 80)

    def test_failed_readback_retains_restoration_if_hardware_did_change(self):
        def changed_but_unconfirmed(request):
            self.row['limit'] = 100
            raise ValueError('readback failed')
        self.controller.handle.side_effect = changed_but_unconfirmed
        with self.assertRaisesRegex(ValueError, 'readback'):
            self.once()
        self.assertEqual(self.utility.data['once']['previous'], 80)

    def test_battery_reports_without_pending_charge_do_not_touch_hardware(self):
        for value in (True, False, None, 'yes'):
            self.power(value)
        self.controller.handle.assert_not_called()
        self.controller.hardware.assert_not_called()
        self.assertFalse(self.utility.path.exists())
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            self.utility.handle(dict(op='profile', value='performance'))

    def test_removed_settings_are_pruned_without_changing_hardware(self):
        self.utility.path.write_text(json.dumps(dict(history=[dict(time=1000)], notification=dict(percentage=80),
            temporary=dict(target='performance'), once=None, recording=None)))
        reloaded = session.Session(self.root, self.controller)
        self.assertEqual(set(json.loads(reloaded.path.read_text())), {'once', 'recording'})
        self.controller.handle.assert_not_called()

    def test_recording_runs_until_stopped_and_excludes_gpu_sensors(self):
        self.utility.record_available = True
        child = Mock()
        child.poll.return_value = None
        with patch.object(session.subprocess, 'Popen', return_value=child) as launch:
            self.utility.handle(dict(op='record'))
        args = launch.call_args.args[0]
        self.assertNotIn('--gpu-telemetry', args)
        self.assertIn('--until-stopped', args)
        self.assertTrue(self.utility.state()['recording']['running'])
        self.utility.handle(dict(op='stop-recording'))
        child.terminate.assert_called_once()
        self.utility.log.close()
        self.utility.child = None

    def test_recording_recovers_summary_and_shutdown_stops_child(self):
        self.utility.record_available = True
        child = Mock()
        child.poll.return_value = None
        with patch.object(session.subprocess, 'Popen', return_value=child):
            self.utility.handle(dict(op='record'))
        output = Path(self.utility.data['recording']['path'])
        output.mkdir()
        (output / 'summary.json').write_text(json.dumps(dict(samples=12, measured_seconds=24)))
        child.poll.return_value = 0
        child.returncode = 0
        self.assertTrue(self.utility.poll_recording())
        self.assertFalse(self.utility.data['recording']['running'])
        reloaded = session.Session(self.root, self.controller)
        self.assertEqual(reloaded.data['recording']['summary']['samples'], 12)
        self.assertIsNone(self.utility.child)


@unittest.skipUnless(importlib.util.find_spec('gi'), 'PyGObject is required')
class ProcessLifecycleTests(unittest.TestCase):
    def test_qprocess_kill_still_stops_recording_and_saves_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            recorder = binary / 'power-study'
            recorder.write_text('''#!/usr/bin/python3
import json,signal,sys,time
from pathlib import Path
output=Path(sys.argv[sys.argv.index('--output')+1]);output.mkdir()
def stop(*_):
 (output/'summary.json').write_text(json.dumps(dict(samples=1,interrupted=True)))
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
(output/'ready').write_text('ready')
time.sleep(30)
''')
            recorder.chmod(0o755)
            # Real GLib main loop/stdio/supervisor and Session persistence; only
            # daemon data and the bounded recorder executable are substituted.
            runner = root / 'runner.py'
            runner.write_text('''import sys
from unittest.mock import Mock
sys.path.insert(0, SOURCE)
import session,backend
from gi.repository import Gio
controller=Mock()
original=session.Session
session.Session=lambda: original(controller=controller)
Gio.bus_get_sync=lambda *a: Mock()
raise SystemExit(session.supervise())
'''.replace('SOURCE', repr(str(support.DESKTOP / 'drawers/power'))))
            child = subprocess.Popen([sys.executable, '-B', '-u', str(runner)],
                env=dict(os.environ, XDG_STATE_HOME=str(root / 'state'), PATH=str(binary) + os.pathsep + os.environ['PATH']),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'helper startup timed out')
                self.assertFalse(json.loads(child.stdout.readline())['state']['error'])
                child.stdin.write('{"op":"record"}\n')
                child.stdin.flush()
                self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'record response timed out')
                response = json.loads(child.stdout.readline())
                self.assertTrue(response['state']['recording']['running'])
                output = Path(response['state']['recording']['path'])
                deadline = time.monotonic() + 3
                while not (output / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((output / 'ready').exists(), 'recorder startup timed out')
                child.kill()  # QProcess destroys its direct child with SIGKILL.
                child.stdin.close()
                child.stdin = None
                _, errors = child.communicate(timeout=5)
                self.assertNotIn('Traceback', errors)
                saved = json.loads((root / 'state/quickshell/power/session.json').read_text())
                self.assertEqual(set(saved), {'once', 'recording'})
                self.assertFalse(saved['recording']['running'])
                self.assertTrue(saved['recording']['summary']['interrupted'])
            finally:
                if child.poll() is None:
                    child.kill()
                if child.stdin:
                    child.stdin.close()
                    child.stdin = None
                child.communicate(timeout=5)


@unittest.skipUnless(support.QS, 'Quickshell is required')
class UtilitiesQmlTests(fixtures.PowerQmlTests):
    # Do not rerun the inherited fixture cases in this module.
    test_drawers_native_values_actions_missing_data_narrow_and_bar = None
    test_polling_follows_observers_and_stops_on_dismissal = None

    def test_session_transport_owns_mutations_after_drawer_dismissal(self):
        def setup(root):
            (root / 'drawers/power/backend.py').write_text('import json,sys\nstate=DATA\nfor line in sys.stdin:\n json.loads(line)\n print(json.dumps(dict(ok=True,data=state,error="")),flush=True)\n'.replace('DATA', repr(fixtures.snapshot())))
            (root / 'drawers/power/session.py').write_text('''import json,sys,time
state=dict(once=None,recording=None,recordAvailable=False,error="",lastOperation="",power="unset")
print(json.dumps(dict(state=state,reply=False)),flush=True)
for line in sys.stdin:
 request=json.loads(line)
 if request['op']=='power': state['power']=request['onBattery']
 else: time.sleep(.1); state['lastOperation']=request['op']
 print(json.dumps(dict(state=state,reply=request['op']!='power')),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/power"
ShellRoot {
 QtObject {id:owner}
 Component.onCompleted: {PowerSession.start();PowerService.observe(owner,true,false);}
 function check(v,m){if(!v)throw new Error(m);}
 property int stage:0
 Timer {interval:50;repeat:true;running:true;onTriggered:{try{
  if(stage===0&&PowerSession.ready&&PowerService.loaded&&!PowerService.reading&&PowerSession.state.power!=="unset"){
   check(PowerSession.state.power===PowerSession.batteryPower,"battery state not reported");
   PowerService.chargeLimit({key:"asus",identity:"test",limit:80},70);
   check(PowerSession.pending===1&&PowerService.changing,"charge action bypassed utility helper");
   PowerService.observe(owner,false,false);stage++;
  }else if(stage===1&&!PowerSession.busy&&!PowerService.running){
   check(PowerSession.state.lastOperation==="charge-limit","dismissal lost charge mutation");
   check(PowerSession.pending===0,"battery report counted as an action");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''', setup)

    def test_sections_device_cards_and_bottom_actions(self):
        data = fixtures.snapshot()
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import Quickshell.Services.UPower
import "drawers"
import "ui"
ShellRoot {
UPOWER
 QtObject {
  id:mock
  property var state: DATA
  property bool loaded:true
  property bool busy:false
  property bool changing:false
  property bool reading:false
  property string error:""
  function observe(owner,active,details){}
  function refresh(){}
  function chargeLimit(row,value){}
 }
 QtObject {
  id:utilities
  property bool ready:true
  property bool busy:false
  property string error:""
  property var sent:null
  property var state: ({once:null,recording:null,recordAvailable:true})
  function send(request){sent=request;}
 }
 TestCase {id:input;when:false;parent:window.contentItem}
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:1080;visible:true;color:Theme.background
  BatteryDrawer {id:battery;width:Math.min(448,window.width-32);height:window.height-32;x:16;y:16;active:true;service:mock;session:utilities;upower:up}
  PerformanceDrawer {id:performance;width:battery.width;height:battery.height;x:16;y:16;active:false;visible:false;service:mock;session:utilities}
 }
 function check(v,m){if(!v)throw new Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function click(item){item.forceActiveFocus();input.keyClick(Qt.Key_Space);}
 function update(fn){const s=JSON.parse(JSON.stringify(mock.state));fn(s);mock.state=s;}
 function utilityUpdate(fn){const s=JSON.parse(JSON.stringify(utilities.state));fn(s);utilities.state=s;}
 function typeNumber(control,value){control.focusEditor();input.keyClick(Qt.Key_A,Qt.ControlModifier);for(const c of value)input.keyClick(c.charCodeAt(0));}
 function capture(name,item){const dir=Quickshell.env("DISPLAY_PREVIEW_DIR");if(dir)item.grabToImage(result=>result.saveToFile(dir+"/power-utilities-"+name+".png"));}
 function bottom(item,drawer){return item.mapToItem(drawer,0,item.height).y;}
 function checkAction(button){
  const icon=find(button,button.objectName+"Icon"),label=find(button,button.objectName+"Label");
  check(icon.visible&&icon.status===Image.Ready,"footer icon failed to load");
  const left=icon.mapToItem(button,0,0).x,right=label.mapToItem(button,label.width,0).x;
  check(Math.abs((left+right)/2-button.width/2)<1,"footer group is not centered");
  check(Math.abs(label.mapToItem(button,0,0).x-left-icon.width-12)<1,"footer icon is not next to text");
  check(button.height===48&&label.height>=label.implicitHeight,"footer height or label clipping");
 }
 property int stage:0
 Timer {interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){setPower(u=>{u.onBattery=false;u.devices={values:u.devices.values.concat([
    device({type:UPowerDeviceType.Mouse,powerSupply:false,isLaptopBattery:false,nativePath:"mouse",model:"Mouse",percentage:.63}),
    device({type:UPowerDeviceType.Keyboard,powerSupply:false,isLaptopBattery:false,nativePath:"keyboard",model:"Keyboard",percentage:.82,state:UPowerDeviceState.Charging})])};});
   check(find(battery,"batteriesHeading").text==="Batteries","battery section missing");
   check(find(battery,"deviceBatteriesHeading").text==="Device batteries","device section missing");
   check(find(battery,"deviceBattery:mouse")&&find(battery,"deviceBattery:keyboard"),"individual device cards missing");
   check(!find(battery,"batteryHistoryGraph")&&!find(battery,"batteryNotify"),"removed battery features remain");
   const action=find(battery,"batteryChargeOnce");
   check(action.visible&&Math.abs(bottom(action,battery)-battery.height)<1,"charge action is not pinned to bottom");
   checkAction(action);
   click(action);check(utilities.sent.op==="charge-once","charge action");
   capture("battery",battery);
  }else if(stage===1){
   update(s=>s.hardware[0].limit=100);
  }else if(stage===2){
   check(!find(battery,"batteryChargeOnce").visible,"charge action shown at 100% limit");
   utilityUpdate(s=>s.once={key:"asus",previous:80});
   const action=find(battery,"batteryChargeOnce");
   check(action.visible&&action.enabled&&action.text==="Restore charge limit","pending charge cannot be restored");
   click(action);check(utilities.sent.op==="restore-charge","charge restoration action");
   utilityUpdate(s=>s.once=null);
   update(s=>s.hardware[0].limit=80);
   battery.active=false;battery.visible=false;performance.visible=true;performance.active=true;
  }else if(stage===3){
   check(find(performance,"performanceHeading").text==="Mode","mode section missing");
   check(!find(performance,"temporaryModeApply"),"temporary modes remain");
   const row=find(performance,"performanceRecordRow"),button=find(performance,"performanceRecord");
   check(Math.abs(bottom(row,performance)-performance.height)<1,"record row is not pinned to bottom");
   check(button.text==="Record performance"&&button.iconName==="circle-dot","record label/icon");
   checkAction(button);
   check(row.height===48,"recording row stretched vertically");
   click(button);check(utilities.sent.op==="record","start recording");
   const s=JSON.parse(JSON.stringify(mock.state));s.metrics.cpu.usage=42;mock.state=s;
   capture("performance",performance);
  }else if(stage===4){
   utilityUpdate(s=>s.recording={running:true,path:"/tmp/test-recording",summary:null,error:""});
  }else if(stage===5){
   check(find(performance,"performanceRecord").iconName==="square","recording has no stop icon");
   click(find(performance,"performanceRecord"));check(utilities.sent.op==="stop-recording","stop action");
   utilityUpdate(s=>s.recording={running:false,path:"/tmp/test-recording",error:"",summary:{samples:60,measured_seconds:118,cpu_usage:24,peak_memory_used:1073741824,observed_peak_temperatures_c:{cpu:60},batteries:{BAT0:{mean_w:8}}}});
   update(s=>s.metrics.cpu.usage=32);performance.width=268;battery.width=268;Theme.setMode("light");
  }else if(stage===6){
   const button=find(performance,"performanceRecord"),label=find(button,"performanceRecordLabel");
   checkAction(button);
   check(find(performance,"performanceRecordRow").height===48,"narrow recording row stretched vertically");
   check(label.width>=label.implicitWidth,"narrow record label clipped: "+label.width+"/"+label.implicitWidth);
   check(Math.abs(bottom(find(performance,"performanceRecordRow"),performance)-performance.height)<1,"narrow recording footer moved");
   check(find(performance,"performanceDevicesHeading").text==="Devices","devices section missing");
   check(!find(performance,"cpuTrend")&&!find(performance,"memoryTrend"),"time graphs remain");
   capture("performance-narrow-light",performance);
  }else if(stage===7){performance.visible=false;performance.active=false;battery.visible=true;battery.active=true;
  }else if(stage===8){check(Math.abs(bottom(find(battery,"batteryChargeOnce"),battery)-battery.height)<1,"narrow battery footer moved");checkAction(find(battery,"batteryChargeOnce"));capture("battery-narrow-light",battery);
  }else if(stage===9){console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
'''.replace('UPOWER', fixtures.UPOWER).replace('DATA', json.dumps(data)))


if __name__ == '__main__':
    unittest.main()
