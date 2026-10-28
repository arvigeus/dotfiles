"""Spaces registry, fullscreen host and session actions without changing the host session."""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import support


SPEC = importlib.util.spec_from_file_location(
    'desktop_session', support.DESKTOP / 'drawers/spaces/backend.py'
)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
SESSION_MODE = (
    support.REPO / 'modules/desktop/hyprland/files/usr/local/bin/session-mode'
)


class SessionBackendTests(unittest.TestCase):
    def test_actions_and_shutdown_delay_validation(self):
        with (
            patch.object(backend, 'snapshot', return_value={}),
            patch.object(backend, 'run') as run,
        ):
            for action in ('suspend', 'reboot', 'poweroff'):
                backend.handle(dict(action=action))
                run.assert_called_with(['systemctl', action])
            for minutes in backend.DELAYS:
                backend.handle(dict(action='schedule-poweroff', minutes=minutes))
                run.assert_called_with(
                    ['systemctl', 'poweroff', f'--when=+{minutes}min']
                )
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
        with (
            patch.object(backend, 'snapshot', return_value={}),
            patch.object(backend, 'run') as run,
        ):
            backend.handle(dict(action='gaming'))
            run.assert_called_with(['session-mode', 'gaming'])
            backend.handle(dict(action='reload'))
            run.assert_called_with(['session-mode', 'desktop'])

    def test_capabilities_shutdown_status_and_command_errors(self):
        with patch.object(backend, 'run') as run:
            for answer, expected in [
                ('yes', True),
                ('challenge', True),
                ('no', False),
                ('na', False),
            ]:
                run.return_value = subprocess.CompletedProcess(
                    [], 0, f's "{answer}"', ''
                )
                self.assertEqual(backend.can('CanSuspend'), expected)
            run.side_effect = OSError('No bus')
            self.assertFalse(backend.can('CanSuspend'))
        with (
            patch.object(backend, 'can', return_value=True),
            patch.object(backend, 'session_status', return_value={}),
            patch.object(backend, 'run') as run,
        ):
            for data, expected in [
                (
                    ['poweroff', 1761750000123456],
                    dict(action='poweroff', at=1761750000123),
                ),
                (['reboot', 1761750000000000], dict(action='reboot', at=1761750000000)),
                (['', 2**64 - 1], None),
                (['poweroff', 0], None),
                (['poweroff', True], None),
                ('poweroff', None),
            ]:
                with self.subTest(data=data):
                    run.return_value = subprocess.CompletedProcess(
                        [], 0, json.dumps(dict(type='(st)', data=data)), ''
                    )
                    self.assertEqual(backend.snapshot()['scheduledShutdown'], expected)
            run.assert_called_with(
                [
                    'busctl',
                    '--system',
                    '--json=short',
                    'get-property',
                    *backend.LOGIN1,
                    'ScheduledShutdown',
                ]
            )
            self.assertFalse(backend.snapshot()['capabilities']['gaming'])
            run.return_value = subprocess.CompletedProcess([], 0, 'not json', '')
            self.assertIsNone(backend.snapshot()['scheduledShutdown'])
            run.side_effect = ValueError('Access denied')
            self.assertIsNone(backend.snapshot()['scheduledShutdown'])
        with patch.object(
            backend.subprocess,
            'run',
            return_value=subprocess.CompletedProcess([], 1, '', 'Access denied'),
        ):
            with self.assertRaisesRegex(ValueError, 'Access denied'):
                backend.run(['systemctl', 'suspend'])

    def test_session_capabilities_follow_the_real_session_mode_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir, runtime = root / 'bin', root / 'runtime'
            bin_dir.mkdir()
            runtime.mkdir(mode=0o700)
            (bin_dir / 'session-mode').symlink_to(SESSION_MODE)
            (bin_dir / 'python3').symlink_to(sys.executable)
            environment = dict(PATH=str(bin_dir), XDG_RUNTIME_DIR=str(runtime))
            with patch.dict(os.environ, environment):
                self.assertEqual(
                    backend.session_status(), dict(available=False, gaming=False)
                )
                state = runtime / 'session-mode'
                state.mkdir()
                current = state / 'current'
                current.write_text(json.dumps(dict(mode='desktop', pid=os.getpid())))
                for name in ('gaming-session', 'gamescope', 'steam'):
                    (bin_dir / name).symlink_to('/bin/true')
                with current.open() as owner:
                    fcntl.flock(owner, fcntl.LOCK_EX)
                    self.assertEqual(
                        backend.session_status(), dict(available=True, gaming=True)
                    )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SpacesDrawerTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_entries_hold_confirmation_popover_and_dismissal(self):
        self.run_qml("""import QtQuick
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
  id:fakeHost
  property var outputs:[]
  property int dismissals:0
  function openOn(output){outputs.push(output);}
  function deliver(id,payload){}
  function dismiss(){dismissals++;}
 }
 QtObject {
  id:mock
  property var state:({capabilities:{gaming:true,reload:true,suspend:true,reboot:true,poweroff:true},scheduledShutdown:{action:"poweroff",at:Date.UTC(2030,0,2,3,4)}})
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
  const names=["movies","series","music","streaming","radio","television","pictures","games","books"];
  check(!find(drawer,"space:desktop"),"Desktop remains in Spaces");
  const output=Quickshell.screens[0];
  SpaceState.host=fakeHost;drawer.screen=output;
  let last=-1;
  for(const name of names){
   const entry=find(drawer,"space:"+name);check(entry&&entry.enabled,"missing space "+name);
   check(!find(drawer,"closeSpace:"+name).visible&&entry.Accessible.description==="Open "+entry.text,"idle entry looks running "+name);
   const y=entry.mapToItem(drawer,0,0).y;check(y>last,"space order changed");last=y;entry.clicked();
   check(SpaceState.currentId===name&&fakeHost.outputs[fakeHost.outputs.length-1]===output,"entry did not open on the drawer output "+name);
   check(find(drawer,"closeSpace:"+name).visible&&entry.Accessible.description==="Running","running entry not marked "+name);
   check(find(entry,entry.objectName+"Icon").status===Image.Ready,"missing space icon "+name);
  }
  check(SpaceState.runningIds.join()===names.join()&&fakeHost.outputs.length===names.length,"running Spaces not tracked");
  click(find(drawer,"closeSpace:movies"));
  check(!SpaceState.runningIds.includes("movies")&&SpaceState.currentId==="books"&&!fakeHost.dismissals,"closing a background Space hid the current one");
  click(find(drawer,"closeSpace:books"));
  check(SpaceState.currentId===""&&fakeHost.dismissals===1&&!find(drawer,"closeSpace:books").visible,"closing the current Space did not hide it");
  for(const name of names)SpaceState.close(name);
  SpaceState.host=null;
  check(!calls.length&&!closes,"Spaces entry ran a session action or closed the drawer itself");
  const sleep=find(drawer,"session-action-suspend");
  check(sleep.holdDuration===2000,"two-second hold missing");
  check(sleep.contentItem.children.length===1,"action retained labels");
  check(find(drawer,"session-action-gaming").text==="Switch to gaming mode","gaming action not named correctly");
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
  const schedule=find(popup.contentItem,"sessionScheduledShutdown"),cancel=find(popup.contentItem,"sessionCancelShutdown");
  const scheduled=mock.state,at=scheduled.scheduledShutdown.at;
  check(schedule.visible&&cancel.visible&&schedule.text==="Shutdown scheduled for "+new Date(at).toLocaleString(Qt.locale(),Locale.ShortFormat),"scheduled shutdown time missing");
  mock.state=Object.assign({},scheduled,{scheduledShutdown:{action:"reboot",at}});
  check(schedule.text.startsWith("Restart scheduled for "),"scheduled restart labelled as shutdown");
  mock.state=Object.assign({},scheduled,{scheduledShutdown:null});
  check(!schedule.visible&&!cancel.visible,"cancel offered without a scheduled shutdown");
  mock.state=scheduled;
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
}""")

    def test_submitted_command_survives_page_destruction_and_reports_failure(self):
        def setup(root):
            (root / 'drawers/spaces/backend.py').write_text("""import json,sys,time
request=json.loads(sys.argv[1])
assert request==dict(action="schedule-poweroff",minutes=30),request
time.sleep(.4)
print(json.dumps(dict(ok=False,error="Fixture denied")))
""")

        self.run_qml(
            """import QtQuick
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
}""",
            setup,
        )

    def test_real_pause_service_survives_drawer_and_resets_with_worker(self):
        def setup(root):
            path = root / 'drawers/displays/comfort.py'
            source = path.read_text()
            source = source.replace(
                "if __name__ == '__main__':",
                """if __name__ == '__main__':
    os.environ['HYPRLAND_INSTANCE_SIGNATURE'] = 'fixture'
    backend.snapshot = lambda: dict(displays=[])
    systemctl = lambda *args: 'inactive'
""",
            )
            path.write_text(source)

        self.run_qml(
            """import QtQuick
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
}""",
            setup,
        )


FIXTURE_SPACE = """import QtQuick
Item {
 property var host
 property bool active: false
 property Item backdropTarget: null
 property Item toolbarTarget: null
 property var payloads: []
 property bool popupOpen: false
 function handleOpen(payload){payloads=payloads.concat([payload]);}
 function dismissTransient(){const open=popupOpen;popupOpen=false;return open;}
}
"""


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SpaceHostTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_routing_retention_escape_late_callbacks_and_failures(self):
        def setup(root):
            support.floating_window(root / 'ui/InteractionWindow.qml', 800, 600)
            for path in ('music/Main.qml', 'radio/Main.qml', 'series/Main.qml'):
                (root / 'spaces' / path).write_text(FIXTURE_SPACE)
            (root / 'spaces/books/Main.qml').write_text('import QtQuick\nItem {\n')

        self.run_qml(
            """import QtQuick
import Quickshell
import "ui"
ShellRoot {
 id:root
 property int step:0
 property var music:null
 property var radio:null
 InteractionState{id:interactions}
 SpaceHost{id:host;interactionState:interactions}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:50;repeat:true;running:true;onTriggered:{try{
  const screen=Quickshell.screens[0];
  if(step===0){
   check(SpaceState.entries.map(entry=>entry.id).join()==="movies,series,music,streaming,radio,television,pictures,games,books","registry order changed");
   check(!SpaceState.open("unknown",screen)&&!SpaceState.open("music",null)&&!SpaceState.runningIds.length&&!interactions.activeSurface,"invalid open accepted");
   check(SpaceState.open("music",screen,{track:"first"}),"music did not open");
  }else if(step===1){
   if(!host.currentPage)return;
   music=host.currentPage;
   check(host.opened&&music.active&&music.toolbarTarget&&music.backdropTarget,"page not presented");
   check(music.payloads.length===1&&music.payloads[0].track==="first","payload lost while loading");
   music.popupOpen=true;host.escapeHandler();
   check(host.opened&&!music.popupOpen,"Escape skipped page transients");
   host.escapeHandler();
   check(!host.opened&&!music.active&&host.currentPage===music&&SpaceState.runningIds.includes("music"),"Escape did not hide and retain music");
   check(!music.host.openModule("radio",{station:"late"})&&!interactions.activeSurface&&!SpaceState.runningIds.includes("radio"),"hidden Space reopened the host");
   check(SpaceState.open("radio",screen),"radio did not open");
  }else if(step===2){
   if(!host.currentPage)return;
   radio=host.currentPage;
   check(!music.host.openModule("series",{title:"late"})&&SpaceState.currentId==="radio"&&!SpaceState.runningIds.includes("series"),"background Space navigated");
   music.host.hide();check(host.opened&&radio.active,"background Space hid the presented one");
   check(radio.host.openModule("music",{track:"second"})&&host.currentPage===music&&music.active&&!radio.active,"presented Space could not navigate");
   check(music.payloads.length===2&&music.payloads[1].track==="second","navigation payload lost");
   SpaceState.open("series",screen,{title:"stale"});
   check(!host.currentPage,"fixture loaded synchronously");
   SpaceState.close("series");
   check(!host.opened&&SpaceState.currentId===""&&SpaceState.runningIds.join()==="music,radio","closing the current Space disturbed others");
  }else if(step===3){
   SpaceState.open("series",screen);
  }else if(step===4){
   if(!host.currentPage)return;
   check(!host.currentPage.payloads.length,"closed Space received a stale payload");
   SpaceState.close("series");SpaceState.open("books",screen,{id:"OL1W"});
  }else if(step===5){
   const close=find(host.contentItem,"closeFailedSpace:books");
   if(!close?.visible)return;
   check(!host.currentPage,"failed page presented");
   host.escapeHandler();check(!host.opened&&SpaceState.runningIds.includes("books"),"Escape did not hide a failed Space");
   SpaceState.open("books",screen);close.clicked();
   check(!host.opened&&!SpaceState.runningIds.includes("books"),"failed Space could not be closed");
   check(music.host.openModule&&!("close" in music.host),"unused page close hook returned");
   SpaceState.close("music");SpaceState.close("radio");
   check(!SpaceState.runningIds.length&&!host.currentPage,"close left instances running");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  step++;
 }catch(e){console.error("DISPLAY_FAIL",step,e);Qt.quit();}}}
 Timer{interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.step);Qt.quit();}}
}""",
            setup,
        )


if __name__ == '__main__':
    unittest.main()
