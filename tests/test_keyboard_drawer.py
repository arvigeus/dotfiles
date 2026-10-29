"""Input-language controller calls, shortcut formatting and drawer interactions
without host changes."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import support

shortcuts = support.load(
    'keyboard_shortcuts', support.DESKTOP / 'drawers/keyboard/shortcuts.py'
)


def run_qml(test, body, setup=None):
    """Run on a private bus: the bar's tray must never join the user's session."""

    def prepare(root):
        shutil.copytree(support.DESKTOP / 'bar', root / 'bar')
        # The production helper would read this machine's keyboard LEDs.
        (root / 'drawers/keyboard/backlight.py').write_text(
            'import json,sys\n'
            'for line in sys.stdin:print(json.dumps(dict(ok=True,values=[],error="")),flush=True)\n'
        )
        if setup:
            setup(root)

    return support.run_qml(test, body, prepare, isolate_bus=True)


# A stand-in for the input-method controller. It records its arguments in the
# directory named by its first argument and keeps state there.
CONTROLLER = """import json, sys, time
from pathlib import Path
here = Path(sys.argv[1])
with open(here / 'calls.log', 'a') as log:
    log.write(json.dumps(sys.argv[2:]) + '\\n')
path = here / 'state.json'
state = json.loads(path.read_text()) if path.exists() else dict(
    available=True, language='en', secondary='bg', running=False)
action, *rest = sys.argv[2:]
if (here / 'hang').exists():
    time.sleep(30)
time.sleep(.1)
if action == 'select':
    code = rest[0]
    if (here / ('fail-' + code)).exists():
        print(json.dumps(dict(state, language=code, secondary=code)))
        print('IME failed to start', file=sys.stderr)
        print('Input method failed: return 1', file=sys.stderr)
        sys.exit(1)
    state['language'] = code
    if code != 'en':
        state['secondary'] = code
    path.write_text(json.dumps(state))
if (here / 'garbage').exists():
    print('not json')
    sys.exit(0)
print('diagnostic noise on success', file=sys.stderr)
print(json.dumps(state))
"""


def install_controller(root, directory, command=None):
    """Declare a controller in the private config, as input-method does."""
    script = Path(directory) / 'controller.py'
    script.write_text(CONTROLLER)
    path = root / 'config/quickshell/input-language.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(command=command or [sys.executable, '-B', str(script), directory])
        )
    )


def calls(directory):
    log = Path(directory) / 'calls.log'
    return [json.loads(line) for line in log.read_text().splitlines()]


class ShortcutTests(unittest.TestCase):
    def test_lua_binds_never_expose_opaque_dispatch_handles(self):
        # Hyprland 0.57 reports Lua binds this way in `hyprctl -j binds`.
        cases = [
            (dict(dispatcher='HL.Dispatcher(exec_cmd)', arg='12'), 'Run command'),
            (dict(dispatcher='HL.Dispatcher(close)', arg='21'), 'Close'),
            (dict(dispatcher='HL.Dispatcher(move_focus)', arg='3'), 'Move focus'),
            (dict(dispatcher='function: 0x5640cddfd890', arg='104'), 'Custom action'),
            (
                dict(dispatcher='HL.Dispatcher(close)', arg='21', description='Quit'),
                'Quit',
            ),
            (dict(dispatcher='unknown', arg='x' * 300), 'unknown: ' + 'x' * 168 + '…'),
        ]
        for bind, label in cases:
            with self.subTest(bind=bind):
                self.assertEqual(shortcuts.action_label(bind), label)

    def test_key_labels_name_modifiers_submaps_codes_and_punctuation(self):
        cases = [
            (dict(modmask=4 | 8 | 1 | 64, key='Delete'), 'Ctrl+Alt+Shift+Win+Delete'),
            (dict(modmask=64, key='bracketleft'), 'Win+['),
            (dict(modmask=64, key='period'), 'Win+.'),
            (dict(modmask=0, key='PRINT'), 'Print'),
            (dict(modmask=64, key='code:10', submap='resize'), 'resize · Win+Code 10'),
            (dict(modmask=256, key='', keycode=36), 'Mod8+Code 36'),
            (dict(modmask='bad', key='XF86AudioMute'), 'XF86AudioMute'),
            (dict(key='', keycode=0), ''),
        ]
        for bind, label in cases:
            with self.subTest(bind=bind):
                self.assertEqual(shortcuts.key_label(bind), label)

    def test_mouse_buttons_wheel_steps_and_catch_all_binds_are_omitted(self):
        def bind(key, **values):
            return dict(
                dict(modmask=64, key=key, keycode=0, description=key, mouse=False),
                **values,
            )

        binds = [
            bind('T'),
            bind('mouse:272', mouse=True),
            bind('mouse:273', modmask=0, release=True, non_consuming=True),
            bind('mouse_down'),
            bind('mouse_up'),
            bind('', catch_all=True),
            bind('A', modmask=0),
            'not a bind',
        ]
        result = subprocess.CompletedProcess([], 0, json.dumps(binds), '')
        with patch.object(shortcuts.subprocess, 'run', return_value=result) as run:
            self.assertEqual(
                shortcuts.bindings(),
                [
                    dict(keys='A', description='A'),
                    dict(keys='Win+T', description='T'),
                ],
            )
        self.assertEqual(run.call_args.args[0], ['hyprctl', '-j', 'binds'])
        self.assertTrue(run.call_args.kwargs['timeout'])

    def test_failures_are_reported_in_the_json_reply(self):
        cases = [
            (FileNotFoundError(), 'hyprctl is unavailable.'),
            (subprocess.TimeoutExpired('hyprctl', 3), 'Hyprland did not respond.'),
            (
                subprocess.CalledProcessError(1, 'hyprctl', '', 'Hyprland is gone'),
                'Hyprland is gone',
            ),
            (subprocess.CompletedProcess([], 0, '{}', ''), 'Could not read'),
            (subprocess.CompletedProcess([], 0, 'not json', ''), 'Could not read'),
        ]
        for outcome, error in cases:
            with (
                self.subTest(outcome=outcome),
                patch.object(shortcuts.subprocess, 'run') as run,
                patch.object(shortcuts.sys, 'stdout', io.StringIO()) as stdout,
            ):
                if isinstance(outcome, Exception):
                    run.side_effect = outcome
                else:
                    run.return_value = outcome
                shortcuts.main()
                reply = json.loads(stdout.getvalue())
                self.assertEqual(reply['shortcuts'], [])
                self.assertIn(error, reply['error'])


@unittest.skipUnless(support.QS, 'Quickshell is required')
class KeyboardQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        return run_qml(self, body, setup)

    def test_languages_secondary_checkmarks_reference_typing_and_bar(self):
        self.run_qml("""import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "bar"
import "ui"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:mock
  property string language:"en"
  property string secondary:"bg"
  property bool available:true
  property bool loaded:true
  property bool selecting:false
  property string selectingLanguage:""
  property string error:""
  readonly property string label:language.toUpperCase()
  readonly property string description:languageName(language)
  signal selectionFinished(string code,bool success)
  function refresh(){}
  function languageName(code){return ({en:"English",bg:"Български",vi:"Tiếng Việt"})[code];}
  function select(code){selectingLanguage=code;selecting=true;}
  function finishSelection(){const code=selectingLanguage;language=code;if(code!=="en")secondary=code;selecting=false;selectingLanguage="";selectionFinished(code,true);}
 }
 QtObject {
  id:light
  property var values:[{key:"test::kbd_backlight",identity:"test",maximum:3,value:1,available:true,reason:""}]
  property string error:""
  function observe(owner,active){}
  function setBrightness(row,value){values=[Object.assign({},row,{value})];}
 }
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:900;visible:true;color:Theme.background
  Item {id:canvas;anchors.fill:parent
  Rectangle {anchors.fill:parent;color:Theme.background}
  // Header actions sit above the page as in DrawerHost; popups open below them.
  Loader{id:header;x:464-width;y:12;sourceComponent:drawer.headerActions}
  KeyboardDrawer{id:drawer;x:16;y:60;width:448;height:700;active:true;service:mock;backlightService:light}
  StatusIslands{id:status;y:780;inputLanguage:mock}
  }
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function capture(name,done){
  const dir=Quickshell.env("DISPLAY_PREVIEW_DIR");
  const item=(name.startsWith("telex")||name.startsWith("phonetic")||name==="shortcuts")?drawer.referencePopup.contentItem:drawer;
  if(dir)item.grabToImage(result=>{result.saveToFile(dir+"/keyboard-"+name+".png");if(done)done();});
  else if(done)done();
 }
 function choose(code){
  const button=find(drawer,"language-"+code);
  input.mouseClick(button,button.width/2,button.height/2);
  check(find(drawer,"language-loading-"+code).visible&&find(drawer,"language-loading-"+code).running,"selected row has no spinner");
  check(!find(drawer,"language-secondary-"+code).visible,"checkmark overlaps spinner");
  check(["en","bg","vi"].every(other=>other===code||!find(drawer,"language-loading-"+other).visible),"another row is spinning");
  mock.finishSelection();
  check(!find(drawer,"language-loading-"+code).visible,"completed selection kept spinner");
 }
 property int stage:0
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  const field=find(drawer,"keyboardTestInput");
  if(stage===0){
   check(find(drawer,"language-en").current,"English not active");
   check(find(drawer,"keyboardPrimaryLabel").text==="Primary language","primary heading");
   check(field.height<=44,"test field is not a single line");
   const slider=find(drawer,"keyboardBacklightSlider:test::kbd_backlight");
   check(slider&&slider.from===0&&slider.to===3&&slider.stepSize===1,"native backlight range");
   slider.forceActiveFocus();input.keyClick(Qt.Key_Right);input.keyClick(Qt.Key_Right);check(light.values[0].value===3,"backlight maximum");
   input.keyClick(Qt.Key_Left);input.keyClick(Qt.Key_Left);input.keyClick(Qt.Key_Left);check(light.values[0].value===0,"backlight off");
   light.setBrightness(light.values[0],2);check(slider.value===2,"external brightness did not update");
   check(!find(drawer,"language-secondary-en").visible,"English got a checkmark");
   check(find(drawer,"language-secondary-bg").visible,"BG pair missing");
   check(find(drawer,"language-bg").text==="Български"&&find(drawer,"language-vi").text==="Tiếng Việt","native labels");
   capture("english",()=>choose("vi"));
  }else if(stage===1){
   check(mock.language==="vi"&&mock.secondary==="vi","VI selection");
   check(find(status,"keyboardButton").entry.badge==="VI","bar did not update");
   check(field.activeFocus,"test input did not gain fresh focus");
   for (const key of [Qt.Key_T,Qt.Key_Y,Qt.Key_P,Qt.Key_I,Qt.Key_N,Qt.Key_G]) input.keyClick(key);check(field.text==="typing","test typing");
   capture("vietnamese",()=>choose("en"));
  }else if(stage===2){
   check(mock.secondary==="vi"&&find(drawer,"language-secondary-vi").visible,"English lost secondary");
   check(find(drawer,"language-en").current&&!find(drawer,"language-secondary-en").visible,"English presentation");
   check(field.text==="typing","language switch discarded text");
   mock.language="bg";mock.secondary="bg";
   check(find(status,"keyboardButton").entry.badge==="BG","external change missing from bar");
   check(find(drawer,"language-bg").current,"external change missing from drawer");
   find(header,"keyboardHelp").clicked();
  }else if(stage===3){
   check(drawer.referencePopup.visible&&drawer.escapeHandler,"reference did not open");
   const telex=find(drawer.referencePopup.contentItem,"keyboardTelexTab");
   const shortcuts=find(drawer.referencePopup.contentItem,"keyboardShortcutsTab");
   const phonetic=find(drawer.referencePopup.contentItem,"keyboardPhoneticTab");
   check(telex.x>=shortcuts.x+shortcuts.width+7&&phonetic.x>=telex.x+telex.width+7,"tabs overlap or lost their order");
   check(Math.abs(telex.width-shortcuts.width)<1,"tab widths differ");
   capture("shortcuts",()=>{input.mouseClick(phonetic,phonetic.width/2,phonetic.height/2);check(phonetic.checked,"phonetic tab did not switch");});
  }else if(stage===4){
   check(find(drawer.referencePopup.contentItem,"phonetic:в").keys==="W"&&find(drawer.referencePopup.contentItem,"phonetic:й").keys==="J","wrong phonetic variant");
   check(find(drawer.referencePopup.contentItem,"phonetic:ъ").keys==="Y"&&find(drawer.referencePopup.contentItem,"phonetic:я").keys==="Q","special phonetic keys");
   const telex=find(drawer.referencePopup.contentItem,"keyboardTelexTab");
   capture("phonetic",()=>{input.mouseClick(telex,telex.width/2,telex.height/2);check(telex.checked,"telex tab did not switch");});
  }else if(stage===5){capture("telex");
  }else if(stage===6){drawer.escapeHandler();
   check(!drawer.referencePopup.visible&&drawer.active,"help Escape dismissed drawer");
   field.forceActiveFocus();input.keyClick(Qt.Key_A,Qt.ControlModifier);input.keyClick(Qt.Key_Backspace);check(field.text==="","clear test text");
   mock.available=false;check(!find(drawer,"language-vi").enabled&&find(drawer,"language-en").enabled,"missing IME disabled working choices");
   drawer.width=268;capture("narrow");
  }else if(stage===7){
   Theme.setMode("light");field.text="temporary";drawer.active=false;check(field.text==="","dismissal kept test text");drawer.active=true;
   find(header,"keyboardHelp").clicked();
  }else if(stage===8){
   check(find(drawer.referencePopup.contentItem,"keyboardShortcutsTab").checked,"reopened reference did not start on shortcuts");
   const phonetic=find(drawer.referencePopup.contentItem,"keyboardPhoneticTab");
   input.mouseClick(phonetic,phonetic.width/2,phonetic.height/2);capture("phonetic-narrow");
  }else if(stage===9){
   const help=find(header,"keyboardHelp");input.mouseClick(help,help.width/2,help.height/2);
   check(!drawer.referencePopup.visible,"second help click reopened the popup");capture("light");
  }else if(stage===10){
   light.values=[];check(!find(drawer,"keyboardBacklightSlider:test::kbd_backlight"),"unsupported keyboard retained a slider");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""")

    def test_serial_controller_calls_survive_dismissal_and_track_layout_events(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_qml(
                """import QtQuick
import Quickshell
import "drawers/keyboard"
import "drawers"
ShellRoot {
 FloatingWindow {visible:true;implicitWidth:480;implicitHeight:720;KeyboardDrawer{id:drawer;anchors.fill:parent;active:false}}
 property int stage:0
 Timer{interval:80;repeat:true;running:true;onTriggered:{try{
  if(stage===0){drawer.active=true;InputLanguage.refresh();InputLanguage.select("bg");InputLanguage.refresh();stage++;}
  else if(stage===1&&!InputLanguage.busy){
   if(InputLanguage.language!=="bg"||InputLanguage.secondary!=="bg")throw new Error("queued selection lost");
   if(InputLanguage.error)throw new Error("successful call reported diagnostics: "+InputLanguage.error);
   InputLanguage.select("vi");drawer.active=false;stage++;
  }else if(stage===2&&!InputLanguage.busy){
   if(InputLanguage.language!=="vi"||InputLanguage.secondary!=="vi")throw new Error("Vietnamese did not finish");
   InputLanguage.select("en");stage++;
  }else if(stage===3&&!InputLanguage.busy){
   if(InputLanguage.language!=="en"||InputLanguage.secondary!=="vi")throw new Error("English discarded pair");
   InputLanguage.handleLayoutEvent("activelayout","laptop,English (US)");stage++;
  }else if(stage===4)stage++; // Let the event debounce start its read.
  else if(stage===5&&!InputLanguage.busy){
   if(InputLanguage.keyboard!=="laptop")throw new Error("event keyboard lost");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
                lambda root: install_controller(root, directory),
            )
            made = calls(directory)
        # One process per request; the pending refresh collapses into one read.
        self.assertEqual(made[:3], [['status'], ['select', 'bg'], ['status']])
        self.assertIn(['select', 'vi'], made)
        self.assertEqual(made[-1], ['status', 'laptop'])

    def test_failed_selection_keeps_confirmed_state_and_shows_the_reason(self):
        def setup(root):
            install_controller(root, directory)
            (Path(directory) / 'fail-vi').touch()

        with tempfile.TemporaryDirectory() as directory:
            self.run_qml(
                """import QtQuick
import Quickshell
import "drawers/keyboard"
ShellRoot {
 property int stage:0
 property var finished:[]
 Connections{target:InputLanguage;function onSelectionFinished(code,success){finished.push(code+":"+success);}}
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0){InputLanguage.refresh();stage++;}
  else if(stage===1&&!InputLanguage.busy){InputLanguage.select("vi");stage++;}
  else if(stage===2&&!InputLanguage.busy&&!InputLanguage.refreshPending){
   if(InputLanguage.language!=="en"||InputLanguage.secondary!=="bg")throw new Error("failed action published state");
   if(InputLanguage.error!=="IME failed to start")throw new Error("reason was not the controller's message: "+InputLanguage.error);
   if(finished.join()!=="vi:false")throw new Error("selection result: "+finished.join());
   InputLanguage.select("bg");stage++;
  }else if(stage===3&&!InputLanguage.busy){
   if(InputLanguage.language!=="bg"||InputLanguage.error)throw new Error("explicit retry did not recover");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
                setup,
            )

    def test_missing_unstartable_hung_or_garbled_controller_releases_the_service(self):
        body = """import QtQuick
import Quickshell
import "drawers/keyboard"
ShellRoot {
 property int stage:0
 property var finished:[]
 Connections{target:InputLanguage;function onSelectionFinished(code,success){finished.push(code+":"+success);}}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  if(stage===0){InputLanguage.requestTimeout=400;InputLanguage.refresh();InputLanguage.select("bg");stage++;}
  else if(stage===1&&!InputLanguage.busy){
   if(!InputLanguage.error.includes("ERROR"))throw new Error("unexpected error: "+InputLanguage.error);
   if(InputLanguage.loaded||InputLanguage.label!=="…")throw new Error("an unconfirmed state was published");
   if(finished.join()!=="bg:false")throw new Error("selection result: "+finished.join());
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
"""
        cases = {
            'not installed': lambda root, directory: None,
            'Could not start': lambda root, directory: install_controller(
                root, directory, [str(Path(directory) / 'missing-controller')]
            ),
            'did not respond': lambda root, directory: (
                install_controller(root, directory),
                (Path(directory) / 'hang').touch(),
            ),
            'Could not read': lambda root, directory: (
                install_controller(root, directory),
                (Path(directory) / 'garbage').touch(),
            ),
        }
        for error, setup in cases.items():
            with (
                self.subTest(error=error),
                tempfile.TemporaryDirectory() as directory,
            ):
                self.run_qml(
                    body.replace('ERROR', error),
                    lambda root: setup(root, directory),
                )


if __name__ == '__main__':
    unittest.main()
