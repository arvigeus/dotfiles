"""Cleanup targeting and hold interactions. All mutations use temporary files or mocks."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

import test_display_drawer as fixtures

SPEC = importlib.util.spec_from_file_location('desktop_cleanup', fixtures.DESKTOP / 'drawers/disks/cleanup.py')
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def test_paths_follow_dotfiles_environment_and_never_cover_whole_cache(self):
        with patch.dict(os.environ, {'HOME': '/tmp/cleanup-home', 'XDG_CACHE_HOME': '/tmp/cleanup-home/.local/cache',
                                     'CARGO_HOME': '/tmp/cargo', 'MISE_DATA_DIR': '/tmp/mise',
                                     'npm_config_cache': '/tmp/npm', 'PIP_CACHE_DIR': '/tmp/pip'}, clear=True):
            rows = {row['id']: row for row in cleanup.catalog()}
        self.assertEqual(rows['cargo']['paths'], [Path('/tmp/cargo/registry/cache')])
        self.assertEqual(rows['npm']['paths'][0], Path('/tmp/npm/_cacache'))
        self.assertIn(Path('/tmp/mise/downloads'), rows['mise-cache']['paths'])
        self.assertEqual(rows['pip']['paths'], [Path('/tmp/pip')])
        for row in rows.values():
            for path in row.get('paths', []):
                self.assertNotEqual(path, Path('/tmp/cleanup-home/.local/cache'))
        self.assertFalse(any('system' in row.get('command', []) and 'prune' in row['command'] for row in rows.values()))

    def test_inventory_only_checks_presence_and_does_not_execute_commands(self):
        with patch.object(cleanup, 'run') as run, patch.object(cleanup.shutil, 'which', return_value=None):
            rows = cleanup.inventory()
        self.assertFalse(next(row for row in rows if row['id'] == 'podman')['available'])
        run.assert_not_called()

    def test_cache_clear_keeps_root_and_does_not_follow_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'; cache.mkdir()
            outside = root / 'personal'; outside.mkdir()
            (outside / 'keep').write_text('important')
            (cache / 'nested').mkdir(); (cache / 'nested/file').write_text('download')
            (cache / 'link').symlink_to(outside, target_is_directory=True)
            cleanup.clear_path(cache)
            self.assertEqual(list(cache.iterdir()), [])
            self.assertEqual((outside / 'keep').read_text(), 'important')
            (root / 'redirect').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                cleanup.clear_path(root / 'redirect/keep')
            self.assertTrue((outside / 'keep').exists())
            cleanup.clear_path(root / 'missing')

    def test_rejects_home_data_and_config_ancestors(self):
        for path in [Path('/'), Path.home(), Path.home() / '.cache/..', Path.home().parent, Path.home() / '.config', Path.home() / '.local/share']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                cleanup.clear_path(path)

    def test_aur_only_removes_package_archives_preserving_worktrees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'clone/pkg').mkdir(parents=True)
            for name in ['PKGBUILD', 'patch.diff', 'source.tar.gz', 'thing.pkg.tar.zst', 'thing.pkg.tar.zst.sig']:
                (root / 'clone/pkg' / name).write_text('data')
            cleanup.clear_path(root, archives=True)
            self.assertEqual(sorted(p.name for p in (root / 'clone/pkg').iterdir()), ['PKGBUILD', 'patch.diff', 'source.tar.gz'])

    def test_validates_entire_request_before_mutating(self):
        with patch.object(cleanup, 'run') as run, patch.object(cleanup, 'clear_path') as clear:
            for selected in [None, [], 'npm', ['npm', 'invalid'], ['npm', 'npm'], [{}]]:
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    cleanup.clean(selected, lambda _: None)
            run.assert_not_called(); clear.assert_not_called()

    def test_partial_failure_continues_and_reports_each_category(self):
        with patch.object(cleanup, 'run', side_effect=[RuntimeError('permission denied'), 'done']) as run:
            result = cleanup.clean(['pnpm', 'uv'], lambda _: None)
        self.assertFalse(result['ok'])
        self.assertEqual([row['ok'] for row in result['results']], [False, True])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(result['results'][0]['error'], 'Some cached files could not be removed because you do not have permission.')

    def test_errors_are_readable_without_terminal_diagnostics(self):
        cases = [
            (RuntimeError('Error executing command as another user: Not authorized\nThis incident has been reported.'), 'Administrator approval was not granted.'),
            (PermissionError(13, 'Permission denied', 'pkg'), 'Some cached files could not be removed'),
            (subprocess.TimeoutExpired(['pnpm'], 600), 'Cleanup took too long.'),
            (RuntimeError('a terminal diagnostic'), 'Cleanup could not finish.'),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                message = cleanup.failure_message(error)
                self.assertTrue(message.startswith(expected), message)
                self.assertNotIn('Errno', message)
                self.assertNotIn('incident', message)

    def test_all_mise_selection_supersedes_pruning(self):
        with patch.object(cleanup, 'run') as run:
            cleanup.clean(['mise-unused', 'mise-tools'], lambda _: None)
        run.assert_called_once_with('mise', 'uninstall', '--all', '--yes')

    def test_tool_removal_runs_after_package_manager_cleanup(self):
        with patch.object(cleanup, 'run') as run:
            cleanup.clean(['mise-tools', 'pnpm'], lambda _: None)
        self.assertEqual([call.args[0] for call in run.call_args_list], ['pnpm', 'mise'])

    def test_dotfiles_defaults_clean_configured_paths_and_leave_legacy_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            configured = ['.local/cache/thumbnails', '.local/cache/mesa_shader_cache',
                          '.local/cache/npm/_cacache', '.local/cache/pip', '.local/cache/mise',
                          '.local/share/mise/downloads', '.local/share/cargo/registry/cache']
            preserved = ['.cache/thumbnails', '.cargo/registry/cache', '.npm/_cacache',
                         '.local/share/cargo/git/checkouts', '.local/share/cargo/registry/src',
                         '.local/share/cargo/bin']
            for name in configured + preserved:
                path = home / name; path.mkdir(parents=True)
                (path / 'fixture').write_text('keep or download')
            with patch.dict(os.environ, {'HOME': str(home)}, clear=True):
                available = {row['id']: row['available'] for row in cleanup.inventory()}
                selected = ['thumbnails', 'npm', 'pip', 'mise-cache', 'cargo']
                self.assertTrue(all(available[key] for key in selected))
                result = cleanup.clean(selected, lambda _: None)
            self.assertTrue(result['ok'], result)
            self.assertTrue(all((home / name).is_dir() and not list((home / name).iterdir()) for name in configured))
            self.assertTrue(all((home / name / 'fixture').exists() for name in preserved))

    def test_podman_preserves_local_builds_and_stopped_container_images(self):
        local, used, unused = 'a'*64, 'b'*64, 'c'*64
        def run(*args):
            if args[1] == 'images': return json.dumps([{'Id': key} for key in [local, used, unused]])
            if args[1:3] == ('image', 'inspect'):
                return json.dumps([{'RepoDigests': [] if args[-1] == local else ['registry.test/repo@sha256:digest']}])
            if args[1] == 'ps': return 'stopped-container' if args[-1].endswith(used) else ''
            return ''
        with patch.object(cleanup, 'run', side_effect=run) as command:
            cleanup.podman_images()
        removals = [call.args for call in command.call_args_list if call.args[1] == 'rmi']
        self.assertEqual(removals, [('podman', 'rmi', unused)])
        self.assertTrue(all('--all' in call.args for call in command.call_args_list if call.args[1] == 'ps'))


class CleanupQmlTests(unittest.TestCase):
    run_qml = fixtures.DisplayQmlTests.run_qml

    def test_select_all_partial_selection_clear_and_admin_hint(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers/disks"
import "ui"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:mock
  property var entries:[
   {id:"npm",title:"npm cache",detail:"",group:"Caches",available:true},
   {id:"pacman",title:"System packages",detail:"Offline rollback copies.",group:"Caches",available:true,admin:true},
   {id:"absent",title:"Missing cache",detail:"",group:"Caches",available:false},
   {id:"mise-unused",title:"Unused Mise versions",detail:"",group:"Tools",available:true},
   {id:"mise-tools",title:"All Mise tools",detail:"Run mise install to restore tools.",group:"Tools",available:true}]
  property bool busy:false
  property bool cleaning:false
  property string progress:""
  function scan(){}
 }
 FloatingWindow {id:window;implicitWidth:320;implicitHeight:760;visible:true;color:Theme.background
  CleanupControl {id:control;x:16;y:700;width:270;active:true;service:mock}
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 property var all:null
 property int stage:0
 Timer {interval:200;running:true;repeat:true;onTriggered:{try{
  if(stage===0)control.popup.open();
  else if(stage===1){
   all=find(control.popup.contentItem,"cleanupSelectAll");input.mouseClick(all,10,12);
   const admin=find(control.popup.contentItem,"cleanupAdmin:pacman");
   check(admin.visible&&admin.iconName==="shield-lock"&&admin.hint==="May require administrator approval","admin icon/tooltip missing");
   check(!find(control.popup.contentItem,"cleanupAdmin:npm").visible,"unneeded admin icon");
  }else if(stage===2){
   check(control.allSelected&&control.selected.length===3,"Select all did not select available choices");
   check(!control.selected.includes("absent")&&!control.selected.includes("mise-unused")&&control.selected.includes("mise-tools"),"invalid bulk targets");
   input.mouseClick(find(control.popup.contentItem,"cleanup:npm"),10,12);
  }else if(stage===3){
   check(all.checkState===Qt.PartiallyChecked,"partial selection missing");input.mouseClick(all,10,12);
  }else if(stage===4){check(control.allSelected,"partial selection did not select all");all.forceActiveFocus();input.keyClick(Qt.Key_Space);}
  else if(stage===5){check(!control.selected.length&&all.checkState===Qt.Unchecked,"Select all did not clear");mock.busy=true;}
  else {check(!all.enabled,"Select all enabled while busy");console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}''')

    def test_shared_button_content_is_centered_and_fits_at_both_widths(self):
        self.run_qml('''import QtQuick
import QtQuick.Layouts
import Quickshell
import "ui"
import "drawers/disks"
import "drawers/network"
ShellRoot {
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:300;visible:true;color:Theme.background
  ColumnLayout {x:16;y:16;width:448
   CleanupControl {id:cleanup;Layout.fillWidth:true;active:true}
   HoldButton {id:hold;objectName:"hold";Layout.fillWidth:true;text:"Hold to clean"}
   NetworkButton {id:network;objectName:"network";Layout.fillWidth:true;text:"Connect"}
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function checkButtons(){
  for(const button of [cleanup,hold,network]){
   const label=find(button,button.objectName+"Label");
   if(Math.abs(label.mapToItem(button,0,0).y+label.height/2-button.height/2)>.5)throw new Error("label not centered: "+button.objectName);
   if(label.height<label.implicitHeight)throw new Error("label clipped: "+button.objectName);
   if(Math.abs(label.mapToItem(button,0,0).x+label.width/2-button.width/2)>.5)throw new Error("label horizontally offset");
  }
  const icon=find(cleanup,"systemCleanupIcon");
  if(Math.abs(icon.mapToItem(cleanup,0,0).y+icon.height/2-cleanup.height/2)>.5)throw new Error("icon not centered");
 }
 property int stage:0
 Timer {interval:250;running:true;repeat:true;onTriggered:{try{
  checkButtons();
  const path=Quickshell.env("DISPLAY_PREVIEW_DIR");
  if(path)cleanup.grabToImage(r=>r.saveToFile(path+"/cleanup-button-"+stage+".png"));
  if(stage===0){cleanup.parent.width=270;Theme.setMode("light");}
  else if(stage===1){find(hold,"holdLabel").font.pixelSize=40;}
  else {console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}''')

    def test_pointer_hold_fires_once_and_leaving_cancels(self):
        self.run_qml('''import QtQuick
import QtTest
import Quickshell
import "ui"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 property int calls:0
 FloatingWindow {id:window;implicitWidth:400;implicitHeight:200;visible:true
  HoldButton {id:hold;x:20;y:20;width:300;holdDuration:400;text:"Hold to clean";onConfirmed:calls++}
 }
 property int stage:0
 Timer {interval:150;running:true;repeat:true;onTriggered:{try{
  if(stage===0)input.mousePress(hold,100,15);
  else if(stage===1||stage===2||stage===3||stage===4){}
  else if(stage===5){if(calls!==1)throw new Error("pointer hold did not fire once");input.mouseRelease(hold,100,15);}
  else if(stage===6)input.mousePress(hold,100,15);
  else if(stage===7)input.mouseMove(hold,-10,-10);
  else if(stage===8||stage===9||stage===10){}
  else if(stage===11){input.mouseRelease(window.contentItem,1,1);if(calls!==1||hold.progress!==0)throw new Error("leaving failed to cancel");}
  else {console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}''')

    def test_full_catalog_scroll_and_visual_layout(self):
        rows = cleanup.inventory()
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers/disks"
import "ui"
ShellRoot {
 QtObject {
  id:mock
  property var entries: ROWS
  property var results:[]
  property bool busy:false
  property bool cleaning:false
  property string progress:""
  property string error:""
  property string message:""
  function scan(){}
 }
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:780;visible:true;color:Theme.background
  CleanupControl {id:control;x:16;y:720;width:448;active:true;service:mock}
 }
 function capture(name){
  const path=Quickshell.env("DISPLAY_PREVIEW_DIR");
  if(path)control.popup.contentItem.parent.grabToImage(r=>{if(!r.saveToFile(path+"/cleanup-"+name+".png"))console.error("DISPLAY_FAIL capture failed");});
 }
 property int stage:0
 Timer {interval:350;repeat:true;running:true;onTriggered:{try{
  if(stage===0)control.popup.open();
  else if(stage===1)capture("catalog-dark");
  else if(stage===2){control.width=270;Theme.setMode("light");}
  else if(stage===3)capture("catalog-narrow-light");
  else if(stage===4){const scroll=control.popup.contentItem.children.find(c=>c.objectName==="cleanupChoices");scroll.contentItem.contentY=scroll.contentItem.contentHeight-scroll.contentItem.height;}
  else if(stage===5)capture("catalog-tools");
  else {console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}'''.replace('ROWS', json.dumps(rows)))

    def test_popup_selection_hold_cancel_keyboard_narrow_layout_and_dismissal(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers/disks"
import "ui"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:mock
  property var entries:[{id:"npm",title:"npm download cache",detail:"Downloads return when needed.",group:"Caches and downloads",available:true},
   {id:"mise-tools",title:"All Mise tool versions",detail:"Reinstall tools with mise install.",group:"Installed tools",available:true},
   {id:"missing",title:"Unavailable cache",detail:"No cache.",group:"Installed tools",available:false}]
  property var results:[]
  property bool busy:false
  property bool cleaning:false
  property string progress:""
  property string error:""
  property string message:""
  property int calls:0
  property int scans:0
  property var chosen:[]
  function scan(){scans++;}
  function clean(values){calls++;chosen=values;}
 }
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:780;visible:true;color:Theme.background
  CleanupControl {id:control;x:16;y:720;width:448;active:true;service:mock}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){let found=find(child,name);if(found)return found;}return null;}
 function capture(name){const path=Quickshell.env("DISPLAY_PREVIEW_DIR");if(path)control.popup.contentItem.parent.grabToImage(r=>r.saveToFile(path+"/cleanup-"+name+".png"));}
 property int stage:0
 property var hold:null
 Timer {interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){input.mouseClick(control);}
  else if(stage===1){
   check(control.popupOpen,"popup did not open");check(mock.scans===1,"no discovery");
   check(control.popup.width===control.width,"popup width");
   hold=find(control.popup.contentItem,"cleanupConfirm");hold.holdDuration=500;
   check(!hold.enabled,"empty selection enabled");
   const box=find(control.popup.contentItem,"cleanup:npm");input.mouseClick(box,10,box.height/2);
   check(control.selected.length===1,"checkbox selection");check(hold.enabled,"selection did not enable hold");
   check(!find(control.popup.contentItem,"cleanup:missing").enabled,"unavailable choice enabled");capture("dark");
   input.mousePress(hold,hold.width/2,hold.height/2);
  }
  else if(stage===2){input.mouseRelease(hold,hold.width/2,hold.height/2);check(mock.calls===0,"short press cleaned");}
  else if(stage===3){check(hold.progress===0,"progress not reset");hold.forceActiveFocus();input.keyPress(Qt.Key_Space);}
  else if(stage===4||stage===5){}
  else if(stage===6){input.keyRelease(Qt.Key_Space);check(mock.calls===1,"keyboard hold did not confirm exactly once");check(mock.chosen[0]==="npm","wrong targets");check(control.selected.length===0,"selection retained");}
  else if(stage===7){control.select("mise-tools",true);input.mousePress(hold,hold.width/2,hold.height/2);}
  else if(stage===8){control.closePopup();}
  else if(stage===9||stage===10){}
  else if(stage===11){input.mouseRelease(window.contentItem,1,1);check(mock.calls===1,"dismissal confirmed hold");input.mouseClick(control);}
  else if(stage===12){check(!hold.enabled,"reopening retained selection");control.width=270;Theme.setMode("light");}
  else if(stage===13){check(control.popup.width===270,"narrow popup overflow");check(control.popup.height<=window.height-32,"popup exceeds window");capture("narrow-light");input.keyClick(Qt.Key_Escape);}
  else if(stage===14){check(!control.popupOpen,"Escape did not close popup");control.popup.open();}
  else if(stage===15){control.select("npm",true);input.mousePress(hold,hold.width/2,hold.height/2);control.active=false;}
  else if(stage===16||stage===17){}
  else {check(!control.popupOpen,"drawer dismissal left popup open");check(mock.calls===1,"deactivation confirmed hold");console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}''')

    def test_cleanup_service_survives_owner_dismissal_and_notifies_once(self):
        def setup(root):
            (root / 'drawers/disks/cleanup.py').write_text('''import json,sys,time
request=json.loads(sys.stdin.readline())
if request['op']=='scan': print(json.dumps(dict(ok=True,entries=[])),flush=True)
else:
 print(json.dumps(dict(progress='Mock cache')),flush=True)
 time.sleep(.7)
 print(json.dumps(dict(ok=False,results=[dict(id='npm',title='npm',ok=True),dict(id='uv',title='uv',ok=False,error='denied')])),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/disks"
ShellRoot {
 property var owner:null
 property var notices:[]
 Component {id:factory;CleanupControl {active:true}}
 Component.onCompleted:{CleanupService.deliver=(title,body)=>notices=notices.concat([{title,body}]);owner=factory.createObject(this);CleanupService.clean(["npm","uv"]);owner.destroy();}
 property int ticks:0
 Timer {interval:150;repeat:true;running:true;onTriggered:{try{
  ticks++;if(ticks<3){if(!CleanupService.busy)throw new Error("cleanup ended on dismissal");return;}
  if(CleanupService.busy)return;
  if(CleanupService.results.length!==2||CleanupService.results[1].error!=="denied")throw new Error("partial results lost");
  if(notices.length!==1||notices[0].title!=="Cleanup needs attention"||!notices[0].body.includes("Cleaned 1 of 2 selected items.")||!notices[0].body.includes("uv: denied"))throw new Error("notification missing");
  if(ticks<10){CleanupService.scan();return;}
  if(notices.length!==1)throw new Error("discovery repeated cleanup notification");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}''', setup=setup)

    def test_success_and_worker_exit_each_send_one_readable_notification(self):
        def setup(root):
            (root / 'drawers/disks/cleanup.py').write_text('''import json,sys
request=json.loads(sys.stdin.readline())
if request['selected']==['success']:
 print(json.dumps(dict(ok=True,results=[dict(id='success',title='Download cache',ok=True)])),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/disks"
ShellRoot {
 property var notices:[]
 property int stage:0
 Component.onCompleted:{CleanupService.deliver=(title,body)=>notices=notices.concat([{title,body}]);CleanupService.clean(["success"]);}
 Timer {interval:150;running:true;repeat:true;onTriggered:{try{
  if(CleanupService.busy)return;
  if(stage===0){
   if(notices.length!==1||notices[0].title!=="Cleanup complete"||notices[0].body!=="Finished cleaning the selected items.")throw new Error("success notification missing");
   stage++;CleanupService.clean(["empty"]);
  }else{
   if(notices.length!==2||notices[1].title!=="Cleanup needs attention"||notices[1].body!=="The cleanup helper stopped. Try again.")throw new Error("helper exit notification missing");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e.stack);Qt.quit();}}}
}''', setup=setup)


if __name__ == '__main__':
    unittest.main()
