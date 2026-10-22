"""Spaces navigation placeholders and session actions without changing the host session."""
import importlib.util
import os
import subprocess
import unittest
from unittest.mock import patch

import support


SPEC = importlib.util.spec_from_file_location('desktop_session', support.DESKTOP / 'drawers/spaces/backend.py')
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class SessionBackendTests(unittest.TestCase):
    def test_actions_and_shutdown_delay_validation(self):
        with patch.object(backend, 'snapshot', return_value={}), patch.object(backend, 'run') as run:
            for action in ('suspend', 'reboot', 'poweroff'):
                backend.handle(dict(action=action))
                run.assert_called_with(['systemctl', action])
            for minutes in backend.DELAYS:
                backend.handle(dict(action='schedule-poweroff', minutes=minutes))
                run.assert_called_with(['systemctl', 'poweroff', f'--when=+{minutes}min'])
            backend.handle(dict(action='cancel-poweroff'))
            run.assert_called_with(['systemctl', 'poweroff', '--when=cancel'])
            run.reset_mock()
            for minutes in (True, '15', 0, -1, 16, None):
                with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                    backend.handle(dict(action='schedule-poweroff', minutes=minutes))
            with self.assertRaises(ValueError):
                backend.handle(dict(action='unknown'))
            run.assert_not_called()

    def test_gaming_switch_and_reload_use_one_shot_session_requests(self):
        with patch.object(backend, 'snapshot', return_value={}), patch.object(backend, 'run') as run:
            backend.handle(dict(action='gaming'))
            run.assert_called_with(['session-mode', 'gaming'])
            backend.handle(dict(action='reload'))
            run.assert_called_with(['session-mode', 'desktop'])

    def test_capabilities_shutdown_status_and_command_errors(self):
        with patch.object(backend, 'run') as run:
            for answer, expected in [('yes', True), ('challenge', True), ('no', False), ('na', False)]:
                run.return_value = subprocess.CompletedProcess([], 0, f's "{answer}"', '')
                self.assertEqual(backend.can('CanSuspend'), expected)
            run.side_effect = OSError('No bus')
            self.assertFalse(backend.can('CanSuspend'))
        with patch.object(backend, 'can', return_value=True), \
                patch.object(backend, 'session_status', return_value={}), patch.object(backend, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '', 'Shutdown scheduled for tomorrow.')
            self.assertEqual(backend.snapshot()['scheduledShutdown'], 'Shutdown scheduled for tomorrow.')
            self.assertFalse(backend.snapshot()['capabilities']['gaming'])
            run.return_value = subprocess.CompletedProcess([], 0, 'No scheduled shutdown.', '')
            self.assertEqual(backend.snapshot()['scheduledShutdown'], '')
        with patch.object(backend.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'Access denied')):
            with self.assertRaisesRegex(ValueError, 'Access denied'):
                backend.run(['systemctl', 'suspend'])


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SpacesDrawerTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_placeholders_hold_confirmation_popover_and_dismissal(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id:root
 property var calls:[]
 property int closes:0
 QtObject {
  id:mock
  property var state:({capabilities:{gaming:true,reload:true,suspend:true,reboot:true,poweroff:true},scheduledShutdown:"Shutdown scheduled for tomorrow."})
  property bool busy:false
  property string error:""
  property bool pausesAvailable:true
  property bool sleepPaused:false
  property bool lockingPaused:false
  function refresh(){}
  function execute(action,minutes){root.calls.push({action,minutes});}
  function setSleepPaused(value){sleepPaused=value;}
  function setLockingPaused(value){lockingPaused=value;}
 }
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:900;visible:true;color:Theme.background
  SpacesDrawer{id:drawer;x:16;y:16;width:448;height:868;active:true;service:mock;onCloseRequested:root.closes++}
 }
 TestCase {id:input;when:false;parent:window.contentItem}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function click(item){input.mouseClick(item,item.width/2,item.height/2);}
 Timer {interval:200;running:true;onTriggered:{try{
  const names=["apps","files","terminal","projects","movies","series","music","radio","pictures","games","books"];
  let last=-1;
  for(const name of names){
   const entry=find(drawer,"space:"+name);check(entry&&entry.enabled,"missing space "+name);
   check(entry.y>last,"space order changed");last=entry.y;entry.clicked();
   check(find(entry,entry.objectName+"Icon").status===Image.Ready,"missing space icon "+name);
  }
  check(!calls.length&&!closes,"placeholder navigated or closed drawer");
  const sleep=find(drawer,"session-action-suspend");
  check(sleep.holdDuration===2000,"two-second hold missing");
  check(sleep.contentItem.children.length===1,"action retained labels");
  check(find(drawer,"session-action-gaming").text==="Go to gaming mode","gaming action not named correctly");
  check(sleep.data.some(value=>value.target===sleep&&value.text?.includes("Sleep")),"action tooltip missing");
  click(sleep);check(!calls.length,"click executed session action");
  input.mousePress(sleep,sleep.width/2,sleep.height/2);input.wait(200);input.mouseRelease(sleep,sleep.width/2,sleep.height/2);
  check(!calls.length,"early release executed session action");
  input.mousePress(sleep,sleep.width/2,sleep.height/2);input.wait(2100);input.mouseRelease(sleep,sleep.width/2,sleep.height/2);
  check(calls.length===1&&calls[0].action==="suspend","held Sleep did not execute exactly once");
  for(const action of ["gaming","reboot","poweroff"]){
   const button=find(drawer,"session-action-"+action);button.holdDuration=80;
   input.mousePress(button,button.width/2,button.height/2);input.wait(120);input.mouseRelease(button,button.width/2,button.height/2);
   check(calls[calls.length-1].action===action,"wrong action "+action);
  }
  const actions=find(drawer,"session-actions");
  click(find(drawer,"sessionSleepOptions"));input.wait(150);
  check(actions.sleepPopup.visible,"sleep options did not open");
  click(find(actions.sleepPopup.contentItem,"sessionPauseSleep"));input.wait(150);
  check(mock.sleepPaused&&sleep.iconName==="coffee","sleep pause not reflected in icon");
  check(find(sleep,"session-action-suspendIcon").status===Image.Ready,"coffee icon missing");
  click(sleep);check(!mock.sleepPaused&&calls.length===4,"coffee click did not restore without suspending");
  click(find(drawer,"sessionSleepOptions"));input.wait(150);
  click(find(drawer,"sessionLockOptions"));input.wait(150);
  check(actions.lockingPopup.visible&&!actions.sleepPopup.visible,"session popovers overlap");
  click(find(actions.lockingPopup.contentItem,"sessionPauseLocking"));input.wait(150);
  const gaming=find(drawer,"session-action-gaming");
  check(mock.lockingPaused&&gaming.iconName==="lock-open","locking pause not reflected in icon");
  check(gaming.data.some(value=>value.target===gaming&&value.text==="Enable automatic locking"),"restore tooltip describes wrong action");
  check(find(gaming,"session-action-gamingIcon").status===Image.Ready,"lock-open icon missing");
  mock.sleepPaused=true;drawer.active=false;input.wait(50);drawer.active=true;
  check(mock.sleepPaused&&mock.lockingPaused,"drawer dismissal cleared temporary pauses");
  click(gaming);click(sleep);
  check(!mock.lockingPaused&&!mock.sleepPaused&&calls.length===4,"restore icons executed destructive actions");
  click(find(drawer,"sessionRestartOptions"));input.wait(150);
  const reload=find(actions.restartPopup.contentItem,"sessionReload");reload.holdDuration=80;
  input.mousePress(reload,reload.width/2,reload.height/2);input.wait(120);input.mouseRelease(window.contentItem,1,1);
  check(calls[calls.length-1].action==="reload","Reload did not request a desktop restart");input.wait(150);
  const options=find(drawer,"sessionShutdownOptions");click(options);input.wait(150);
  const popup=find(drawer,"session-actions").shutdownPopup;
  check(popup.visible,"shutdown options did not open");
  for(const minutes of [15,30,60,90,120,180,240,300]){
   const label=find(popup.contentItem,"sessionDelay:"+minutes+"Label");
   check(label&&!label.truncated&&label.contentWidth<=label.width+1,"shutdown label clipped: "+minutes);
  }
  check(drawer.escapeHandler&&drawer.escapeHandler(),"popup did not consume Escape");input.wait(150);
  check(!popup.visible&&!closes,"Escape dismissed drawer instead of popup");
  click(options);input.wait(150);
  const delay=find(popup.contentItem,"sessionDelay:30");delay.holdDuration=80;
  input.mousePress(delay,delay.width/2,delay.height/2);input.wait(120);input.mouseRelease(window.contentItem,1,1);
  check(calls[calls.length-1].action==="schedule-poweroff"&&calls[calls.length-1].minutes===30,"shutdown delay not forwarded");
  input.wait(150);click(options);input.wait(150);click(find(popup.contentItem,"sessionCancelShutdown"));
  check(calls[calls.length-1].action==="cancel-poweroff","scheduled shutdown could not be cancelled");
  input.wait(150);click(options);input.wait(150);drawer.active=false;input.wait(150);
  check(!popup.visible&&!sleep.enabled,"dismissed drawer retained controls");
  drawer.active=true;mock.busy=true;check(!sleep.enabled,"busy session permits duplicate action");mock.busy=false;
  mock.state={capabilities:{gaming:false,suspend:true,reboot:true,poweroff:true},scheduledShutdown:""};
  check(!find(drawer,"session-action-gaming").enabled,"unsupported gaming enabled");
  mock.error="Access denied";check(find(drawer,"sessionError").text==="Access denied","command error hidden");
  drawer.width=288;drawer.height=380;input.wait(150);
  check(options.mapToItem(drawer,options.width,0).x<=drawer.width+1,"narrow power controls overflow");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''')

    def test_submitted_command_survives_page_destruction_and_reports_failure(self):
        def setup(root):
            (root / 'drawers/spaces/backend.py').write_text('''import json,sys,time
request=json.loads(sys.argv[1])
assert request==dict(action="schedule-poweroff",minutes=30),request
time.sleep(.4)
print(json.dumps(dict(ok=False,error="Fixture denied")))
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/spaces"
ShellRoot {
 id:root
 property int stage:0
 Component{id:page;SessionActions{active:true}}
 property var temporary:null
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0){temporary=page.createObject(root);SessionService.execute("schedule-poweroff",30);temporary.destroy();}
  else if(stage===1){if(!SessionService.busy)throw new Error("command ended with page");SessionService.execute("poweroff");}
  else if(stage>5){
   if(SessionService.busy||SessionService.error!=="Fixture denied")throw new Error("submitted command or failure lost");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''', setup)

    def test_real_pause_service_survives_drawer_and_resets_with_worker(self):
        def setup(root):
            path = root / 'drawers/displays/comfort.py'
            source = path.read_text()
            source = source.replace("if __name__ == '__main__':", """if __name__ == '__main__':
    os.environ['HYPRLAND_INSTANCE_SIGNATURE'] = 'fixture'
    backend.snapshot = lambda: dict(displays=[])
    systemctl = lambda *args: 'inactive'
""")
            path.write_text(source)
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/spaces"
import "drawers/displays"
ShellRoot {
 id:root
 property int stage:0
 property var temporary:null
 Component{id:page;SessionActions{active:true}}
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(SessionService.busy)return;
  if(stage===0){SessionService.setSleepPaused(true);}
  else if(stage===1){
   check(SessionService.sleepPaused,"real sleep pause failed: "+SessionService.error);
   temporary=page.createObject(root);temporary.destroy();SessionService.setLockingPaused(true);
  }else if(stage===2){
   check(SessionService.sleepPaused&&SessionService.lockingPaused,"page destruction lost pause");
   SessionService.setSleepPaused(false);
  }else if(stage===3){
   check(!SessionService.sleepPaused&&SessionService.lockingPaused,"restoring sleep changed locking");
   ComfortService.worker.running=false;
  }else if(stage===4){
   check(!SessionService.sleepPaused&&!SessionService.lockingPaused,"worker exit retained pause icons");
   ComfortService.run("status");
  }else if(stage===5){
   check(SessionService.pausesAvailable&&!SessionService.sleepPaused&&!SessionService.lockingPaused,"worker restart persisted pauses");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup)


if __name__ == '__main__':
    unittest.main()
