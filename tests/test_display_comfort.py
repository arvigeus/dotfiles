"""Monitor-scoped idle policy and native night light; no host mutations."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

SOURCE = support.DESKTOP / 'drawers/displays/comfort.py'
SPEC = importlib.util.spec_from_file_location('display_comfort', SOURCE)
comfort = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SOURCE.parent))
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    SPEC.loader.exec_module(comfort)
finally:
    sys.path.pop(0)
    sys.dont_write_bytecode = _bytecode_disabled


class ComfortTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, XDG_RUNTIME_DIR=self.directory.name, HYPRLAND_INSTANCE_SIGNATURE='test')
        self.env.start(); self.addCleanup(self.env.stop)
        self.rows = [support.display(), support.display('DP-1')]
        self.inventory = patch.object(comfort.backend, 'snapshot', side_effect=lambda: dict(displays=self.rows))
        self.inventory.start(); self.addCleanup(self.inventory.stop)
        self.binary = patch.object(comfort.shutil, 'which', return_value='/usr/bin/hyprsunset')
        self.binary.start(); self.addCleanup(self.binary.stop)
        self.unit = patch.object(comfort, 'systemctl', return_value='inactive')
        self.systemctl = self.unit.start(); self.addCleanup(self.unit.stop)
        self.controller = comfort.Controller()
        self.addCleanup(self.controller.close)

    def awake(self, row=None, enabled=True):
        row = row or self.rows[0]
        self.controller.action(dict(op='awake', name=row['name'], identity=row['identity'], enabled=enabled))

    def test_lease_is_per_monitor_indefinite_and_released(self):
        self.awake()
        self.assertEqual(comfort.protected(self.rows), {'eDP-1'})
        self.assertEqual(self.controller.snapshot()['awake'], {'eDP-1': self.rows[0]['identity']})
        self.awake(self.rows[1])
        self.assertEqual(comfort.protected(self.rows), {'eDP-1', 'DP-1'})
        self.awake(enabled=False)
        self.assertEqual(comfort.protected(self.rows), {'DP-1'})
        self.controller.close()
        self.assertEqual(comfort.protected(self.rows), set())
        self.assertEqual(list(comfort.session_directory().iterdir()), [])

    def test_crashed_lease_and_stale_identity_do_not_inhibit(self):
        self.awake()
        replaced = [support.display(identity=['eDP-1', 'replacement'])]
        self.assertEqual(comfort.protected(replaced), set())
        self.assertEqual(comfort.protected([support.display(enabled=False)]), set())
        # Simulate process death leaving runtime files behind.
        os.close(self.controller.lease.fd)
        self.controller.lease.fd = None
        self.assertEqual(comfort.protected(self.rows), set())

    def test_hotplug_disable_and_replacement_prune_checkmarks(self):
        for replacement in ([], [support.display(enabled=False)], [support.display(identity=['replacement'])]):
            self.rows = [support.display()]
            self.awake()
            self.rows = replacement
            self.controller.tick()
            self.assertEqual(self.controller.awake, {})
            self.assertIsNone(self.controller.lease.fd)

    def test_stale_actions_and_invalid_switches_do_not_publish(self):
        for values in [dict(name='missing', identity=[], enabled=True), dict(name='eDP-1', identity=['old'], enabled=True), dict(name='eDP-1', identity=self.rows[0]['identity'], enabled='yes')]:
            with self.assertRaises(ValueError):
                self.controller.action(dict(op='awake', **values))
        self.assertEqual(self.controller.awake, {})
        self.assertIsNone(self.controller.lease.fd)

    def test_blanking_targets_only_unprotected_outputs_and_session_guards_retry(self):
        self.awake()
        with patch.object(comfort.backend, 'command') as command:
            self.assertEqual(comfort.idle_action('blank'), 0)
        command.assert_called_once_with('dispatch', 'hl.dsp.dpms({action="off",monitor=' + comfort.backend.lua_string('DP-1') + '})')
        self.assertEqual(comfort.cli('allow-lock'), 1)
        self.awake(enabled=False)
        self.assertEqual(comfort.cli('allow-lock'), 0)
        self.assertEqual(comfort.cli('allow-session-idle'), comfort.HELPER_ERROR)
        # Guarded rules retry after unchecking, rather than losing their timeout.
        config = Path(__file__).resolve().parents[1] / 'modules/desktop/hyprland/files/home/.config/hypr/hypridle.conf'
        self.assertEqual(config.read_text().count('condition_retry = 10'), 2)
        self.assertNotIn('ignore_inhibit', config.read_text())

    def test_helper_errors_are_distinct_from_denial(self):
        # desktop-idle fails open on 2 (helper error); 1 always means "deny".
        with patch.object(comfort.backend, 'snapshot', side_effect=RuntimeError('Hyprland is unavailable.')):
            for op in ('allow-lock', 'allow-sleep', 'blank'):
                with self.subTest(op=op):
                    self.assertEqual(comfort.cli(op), comfort.HELPER_ERROR)
        self.controller.action(dict(op='pause-locking', enabled=True))
        self.assertEqual(comfort.cli('allow-lock'), 1)
        self.assertEqual(comfort.cli('allow-sleep'), 0)

    def test_status_reads_do_not_clear_action_errors(self):
        with self.assertRaises(ValueError):
            self.controller.action(dict(op='night', enabled=1))
        self.controller.error = 'Invalid night light switch.'
        self.controller.action(dict(op='status'))
        self.assertEqual(self.controller.error, 'Invalid night light switch.')

    def test_waking_a_dark_monitor_is_targeted_and_quoted(self):
        self.rows = [support.display('DP-"quoted', dpms=False)]
        with patch.object(comfort.backend, 'command') as command:
            self.awake()
        command.assert_called_once_with('dispatch', 'hl.dsp.dpms({action="on",monitor=' + comfort.backend.lua_string('DP-"quoted') + '})')

    def test_idle_wake_notifies_the_existing_display_policy_after_dpms(self):
        with patch.object(comfort.backend, 'command') as command:
            self.assertEqual(comfort.idle_action('wake'), 0)
        self.assertEqual(command.call_args_list, [
            unittest.mock.call('dispatch', 'hl.dsp.dpms({action="on"})'),
            unittest.mock.call('dispatch', 'hl.dsp.event("desktop-displays-changed")')])

    def test_night_toggle_uses_packaged_service_and_reads_external_state(self):
        self.systemctl.return_value = 'active'
        self.controller.action(dict(op='night', enabled=True))
        self.assertIn(unittest.mock.call('enable', '--now', 'hyprsunset.service'), self.systemctl.call_args_list)
        self.assertTrue(self.controller.snapshot()['nightEnabled'])
        self.systemctl.return_value = 'inactive'
        self.controller.action(dict(op='night', enabled=False))
        self.assertIn(unittest.mock.call('disable', '--now', 'hyprsunset.service'), self.systemctl.call_args_list)
        self.assertFalse(self.controller.snapshot()['nightEnabled'])
        self.systemctl.return_value = 'active'
        self.controller.tick()
        self.assertTrue(self.controller.snapshot()['nightEnabled'])
        with patch.object(comfort.shutil, 'which', return_value=None), self.assertRaises(RuntimeError):
            self.controller.action(dict(op='night', enabled=True))
        with self.assertRaises(ValueError):
            self.controller.action(dict(op='night', enabled=1))

    def test_publish_failure_keeps_previous_selection(self):
        self.awake()
        with patch.object(comfort.os, 'replace', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.awake(self.rows[1])
        self.assertEqual(comfort.protected(self.rows), {'eDP-1'})
        self.assertEqual(set(self.controller.awake), {'eDP-1'})

    def test_session_pauses_are_independent_and_leave_blanking_alone(self):
        self.controller.action(dict(op='pause-sleep', enabled=True))
        self.assertTrue(self.controller.snapshot()['sleepPaused'])
        self.assertEqual(comfort.idle_action('allow-sleep'), 1)
        self.assertEqual(comfort.idle_action('allow-lock'), 0)
        with patch.object(comfort.backend, 'command') as command:
            self.assertEqual(comfort.idle_action('blank'), 0)
        self.assertEqual(command.call_count, 2)
        self.controller.action(dict(op='pause-locking', enabled=True))
        self.assertEqual(comfort.idle_action('allow-lock'), 1)
        self.controller.action(dict(op='pause-sleep', enabled=False))
        self.assertEqual(comfort.idle_action('allow-sleep'), 0)
        self.assertEqual(comfort.idle_action('allow-lock'), 1)
        self.controller.close()
        self.assertEqual(comfort.idle_action('allow-lock'), 0)
        self.assertEqual(list(comfort.session_directory('desktop-session-pauses').iterdir()), [])

    def test_session_pauses_fail_closed_after_crash_and_validate_values(self):
        for enabled in (1, 'yes', None):
            with self.assertRaises(ValueError):
                self.controller.action(dict(op='pause-locking', enabled=enabled))
        self.controller.action(dict(op='pause-locking', enabled=True))
        self.controller.action(dict(op='pause-sleep', enabled=True))
        self.assertTrue(comfort.paused('locking'))
        os.close(self.controller.pause_lease.fd)
        self.controller.pause_lease.fd = None
        self.assertFalse(comfort.paused('locking'))
        self.assertFalse(comfort.paused('sleep'))
        fresh = comfort.Controller()
        self.addCleanup(fresh.close)
        self.assertFalse(fresh.snapshot()['sleepPaused'])
        self.assertFalse(fresh.snapshot()['lockingPaused'])

    def test_worker_eof_releases_monitor_lease(self):
        root = Path(self.directory.name)
        script = root / 'worker.py'
        script.write_text(f'''import sys,importlib.util
sys.path.insert(0,{str(SOURCE.parent)!r})
spec=importlib.util.spec_from_file_location('comfort',{str(SOURCE)!r})
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
c.backend.snapshot=lambda:dict(displays={self.rows!r})
c.systemctl=lambda *args:'inactive'
c.main()
''')
        request = dict(op='awake', name=self.rows[0]['name'], identity=self.rows[0]['identity'], enabled=True)
        requests = [request, dict(op='pause-sleep', enabled=True), dict(op='pause-locking', enabled=True)]
        result = subprocess.run([sys.executable, '-u', str(script)], input=''.join(json.dumps(value)+'\n' for value in requests), text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout.splitlines()[-1])['state']['awake'])
        self.assertTrue(json.loads(result.stdout.splitlines()[-1])['state']['sleepPaused'])
        self.assertTrue(json.loads(result.stdout.splitlines()[-1])['state']['lockingPaused'])
        self.assertEqual(comfort.protected(self.rows), set())
        self.assertFalse(comfort.paused('sleep'))
        self.assertFalse(comfort.paused('locking'))
        self.assertEqual(list(comfort.session_directory().iterdir()), [])


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ComfortQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            shutil.copytree(support.DESKTOP / 'bar', root / 'bar')
            if setup: setup(root)
        return support.run_qml(self, body, prepare)

    def test_simple_toggle_cog_checkmark_and_per_screen_indicator(self):
        rows = json.dumps([support.display(), support.display('DP-1')])
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "drawers"
import "bar"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:comfort
  property bool loaded:true
  property bool busy:false
  property string error:""
  property var state:({nightEnabled:false,nightAvailable:true,awake:{}})
  property int calls:0
  property var owners:[]
  function observe(owner,active){owners=owners.filter(item=>item!==owner).concat(active?[owner]:[]);}
  function awakeFor(name){return !!state.awake[name];}
  function setAwake(record,enabled){const awake=Object.assign({},state.awake);if(enabled)awake[record.name]=record.identity;else delete awake[record.name];state=Object.assign({},state,{awake});calls++;}
  function run(op,values){state=Object.assign({},state,{nightEnabled:values.enabled});calls++;}
 }
 QtObject {
  id:mock
  property var state:({available:true,displays:ROWS,token:"initial"})
  property bool loaded:true
  property bool busy:false
  property string error:""
  function observe(owner,active){}
  function refresh(){}
  function brightnessFor(name){return {available:false,value:0,reason:"Unavailable"};}
  function setBrightness(name,value){}
  function change(record,values){}
 }
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:900;visible:true;color:Theme.background
  DisplaysDrawer {id:drawer;x:16;y:16;width:448;height:650;active:true;service:mock;comfortService:comfort}
  StatusIslands {id:status;y:700;outputName:"eDP-1";displayComfort:comfort}
 }
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function choose(name){const button=find(drawer,"displayOptions:"+name);button.clicked();button.menu.activate(drawer.optionsFor(drawer.displays.find(row=>row.name===name)).find(entry=>entry.key==="awake"));check(!button.menu.visible,"cog stayed open");}
 property int stage:0
 Timer {interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   check(!find(drawer,"nightLightWarmth")&&!find(drawer,"nightLightStart")&&!find(drawer,"displayKeepAwake"),"extra controls remain");
   const toggle=find(drawer,"nightLightEnabled");input.mouseClick(toggle,toggle.width/2,toggle.height/2);
   check(comfort.state.nightEnabled,"night light toggle");
   choose("DP-1");
  }else if(stage===1){
   check(drawer.optionsFor(drawer.displays[1])[0].marked,"cog checkmark missing");
   check(!drawer.optionsFor(drawer.displays[0])[0].marked,"wrong display checked");
   check(String(find(status,"displaysButton").entry.iconColor)===String(Theme.text),"other display colored this bar");
   choose("eDP-1");
  }else if(stage===2){
   check(String(find(status,"displaysButton").entry.iconColor)===String(Theme.accent),"own display not red");
   drawer.active=false;check(comfort.awakeFor("eDP-1"),"dismissal cleared keep awake");
   drawer.active=true;choose("eDP-1");
  }else if(stage===3){
   check(!comfort.awakeFor("eDP-1")&&comfort.awakeFor("DP-1"),"unchecking changed another display");
   status.outputName="DP-1";drawer.width=268;
  }else if(stage===4){
   check(String(find(status,"displaysButton").entry.iconColor)===String(Theme.accent),"external display bar missing red indicator");
   const directory=Quickshell.env("DISPLAY_PREVIEW_DIR");if(directory)drawer.grabToImage(result=>result.saveToFile(directory+"/display-comfort-simple.png"));
  }else if(stage===5){console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
'''.replace('ROWS', rows))

    def test_service_finishes_requests_after_dismissal_and_polls_only_while_observed(self):
        def setup(root):
            (root / 'drawers/displays/comfort.py').write_text('''import json,sys,time
state=dict(nightEnabled=False,nightAvailable=True,awake={},error="",polls=0)
print(json.dumps(dict(reply=False,state=state)),flush=True)
for line in sys.stdin:
 r=json.loads(line);time.sleep(.1)
 if r['op']=='status':state['polls']+=1
 if r['op']=='night':state['nightEnabled']=r['enabled']
 if r['op']=='awake':state['awake'][r['name']]=r['identity']
 print(json.dumps(dict(reply=True,state=state)),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/displays"
ShellRoot {
 property int stage:0
 property int baseline:0
 property int ticks:0
 property var owner:({})
 Timer {interval:80;repeat:true;running:true;onTriggered:{try{
  if(stage===0){ComfortService.start();stage++;}
  else if(stage===1&&ComfortService.ready){
   ComfortService.run("night",{enabled:true});
   ComfortService.setAwake({name:"panel",identity:["panel"]},true);stage++;
  }else if(stage===2&&!ComfortService.busy){
   if(!ComfortService.state.nightEnabled||!ComfortService.awakeFor("panel")||!ComfortService.worker.running)throw new Error("state did not survive dismissal");
   if(ComfortService.state.polls!==0)throw new Error("helper polled without an observer");
   ComfortService.observe(owner,true);
   if(ComfortService.busy)throw new Error("background read disabled the switches");
   stage++;
  }else if(stage===3&&ComfortService.state.polls>=2&&!ComfortService.request){
   ComfortService.observe(owner,false);
   ComfortService.prune();stage++;
  }else if(stage===4&&!ComfortService.request){
   if(ComfortService.state.polls!==3)throw new Error("Keep awake prune did not read state");
   baseline=ComfortService.state.polls;stage++;
  }else if(stage===5){
   if(ComfortService.state.polls!==baseline||ComfortService.request)throw new Error("helper polled after dismissal");
   // Longer than the three-second observation interval.
   if(++ticks>=44){console.log("DISPLAY_PASS");Qt.quit();}
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout stage "+stage);Qt.quit();}}
}
''', setup)

if __name__ == '__main__':
    unittest.main()
