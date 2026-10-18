"""Production language switching and drawer interactions without host changes."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_display_drawer as fixtures

SOURCE = fixtures.DESKTOP / 'drawers/keyboard/backend.py'
SPEC = importlib.util.spec_from_file_location('keyboard_backend', SOURCE)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


class KeyboardBackendTests(unittest.TestCase):
    def test_provider_uses_argument_array_and_reads_do_not_start_services(self):
        state = dict(available=True, language='en', secondary='vi', running=True)
        with patch.object(backend, 'provider', return_value=['controller', 'argument with spaces']), patch.object(backend, 'command', return_value=json.dumps(state)) as command:
            self.assertEqual(backend.request('status', 'laptop'), state)
            command.assert_called_once_with(['controller', 'argument with spaces', 'status', 'laptop'])
            self.assertEqual(backend.request('select', 'vi'), state)
            self.assertEqual(command.call_args.args[0], ['controller', 'argument with spaces', 'select', 'vi'])

    def test_bad_provider_and_invalid_requests_preserve_confirmed_state(self):
        for state in ({}, dict(error='Input unavailable'), dict(available='yes', language='en', secondary='bg'), []):
            with self.subTest(state=state), patch.object(backend, 'provider', return_value=['controller']), patch.object(backend, 'command', return_value=json.dumps(state)), self.assertRaises(ValueError):
                backend.request('status')
        with patch.object(backend, 'command') as command:
            for action, code in [('delete', ''), ('select', 'xx')]:
                with self.assertRaises(ValueError): backend.request(action, code)
            command.assert_not_called()

    def test_fallback_follows_event_keyboard_and_validates_layout(self):
        devices = dict(keyboards=[dict(name='usb', main=True, layout='us,bg', active_layout_index=0),
                                  dict(name='laptop', layout='us,bg', active_layout_index=1)])
        with patch.object(backend, 'provider', return_value=None), patch.object(backend, 'command', return_value=json.dumps(devices)) as command:
            self.assertEqual(backend.request('status', 'laptop')['language'], 'bg')
            self.assertEqual(backend.request('status')['language'], 'en')
            self.assertFalse(backend.request('status')['available'])
            with self.assertRaisesRegex(ValueError, 'Vietnamese'): backend.request('select', 'vi')
            backend.request('select', 'bg')
            self.assertIn(unittest.mock.call(['hyprctl', 'switchxkblayout', 'all', '1']), command.call_args_list)
            devices['keyboards'][0]['layout'] = 'us'
            command.return_value = json.dumps(devices)
            with self.assertRaisesRegex(ValueError, 'not configured'): backend.request('select', 'bg')


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class KeyboardQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            shutil.copytree(fixtures.DESKTOP / 'bar', root / 'bar')
            if setup: setup(root)
        return fixtures.DisplayQmlTests.run_qml(self, body, prepare)

    def test_languages_secondary_checkmarks_reference_typing_and_bar(self):
        self.run_qml('''import QtQuick
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
  KeyboardDrawer{id:drawer;x:16;y:16;width:448;height:700;active:true;service:mock;backlightService:light}
  StatusIslands{id:status;y:740;inputLanguage:mock}
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
   check(find(status,"keyboardButton").entry.label==="VI","bar did not update");
   check(field.activeFocus,"test input did not gain fresh focus");
   for (const key of [Qt.Key_T,Qt.Key_Y,Qt.Key_P,Qt.Key_I,Qt.Key_N,Qt.Key_G]) input.keyClick(key);check(field.text==="typing","test typing");
   capture("vietnamese",()=>choose("en"));
  }else if(stage===2){
   check(mock.secondary==="vi"&&find(drawer,"language-secondary-vi").visible,"English lost secondary");
   check(find(drawer,"language-en").current&&!find(drawer,"language-secondary-en").visible,"English presentation");
   check(field.text==="typing","language switch discarded text");
   mock.language="bg";mock.secondary="bg";
   check(find(status,"keyboardButton").entry.label==="BG","external change missing from bar");
   check(find(drawer,"language-bg").current,"external change missing from drawer");
   find(drawer,"keyboardHelp").clicked();
  }else if(stage===3){
   check(drawer.referencePopup.visible&&drawer.escapeHandler,"reference did not open");
   const telex=find(drawer.referencePopup.contentItem,"keyboardTelexTab");
   const shortcuts=find(drawer.referencePopup.contentItem,"keyboardShortcutsTab");
   check(shortcuts.x>=telex.x+telex.width+7,"tabs overlap");
   check(Math.abs(telex.width-shortcuts.width)<1,"tab widths differ");
   const phonetic=find(drawer.referencePopup.contentItem,"keyboardPhoneticTab");
   capture("telex",()=>{input.mouseClick(phonetic,phonetic.width/2,phonetic.height/2);check(drawer.referencePopup.currentTab===1,"phonetic tab did not switch");});
  }else if(stage===4){
   check(find(drawer.referencePopup.contentItem,"phonetic:в").keys==="W"&&find(drawer.referencePopup.contentItem,"phonetic:й").keys==="J","wrong phonetic variant");
   check(find(drawer.referencePopup.contentItem,"phonetic:ъ").keys==="Y"&&find(drawer.referencePopup.contentItem,"phonetic:я").keys==="Q","special phonetic keys");
   const shortcuts=find(drawer.referencePopup.contentItem,"keyboardShortcutsTab");
   capture("phonetic",()=>{input.mouseClick(shortcuts,shortcuts.width/2,shortcuts.height/2);check(drawer.referencePopup.currentTab===2,"shortcut tab did not switch");});
  }else if(stage===5){capture("shortcuts");
  }else if(stage===6){drawer.escapeHandler();
   check(!drawer.referencePopup.visible&&drawer.active,"help Escape dismissed drawer");
   field.forceActiveFocus();input.keyClick(Qt.Key_A,Qt.ControlModifier);input.keyClick(Qt.Key_Backspace);check(field.text==="","clear test text");
   mock.available=false;check(!find(drawer,"language-vi").enabled&&find(drawer,"language-en").enabled,"missing IME disabled working choices");
   drawer.width=268;capture("narrow");
  }else if(stage===7){
   Theme.setMode("light");field.text="temporary";drawer.active=false;check(field.text==="","dismissal kept test text");drawer.active=true;
   drawer.referencePopup.currentTab=1;find(drawer,"keyboardHelp").clicked();
  }else if(stage===8){capture("phonetic-narrow");
  }else if(stage===9){
   const help=find(drawer,"keyboardHelp");input.mouseClick(help,help.width/2,help.height/2);
   check(!drawer.referencePopup.visible,"second help click reopened the popup");capture("light");
  }else if(stage===10){
   light.values=[];check(!find(drawer,"keyboardBacklightSlider:test::kbd_backlight"),"unsupported keyboard retained a slider");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''')

    def test_serial_requests_survive_dismissal_and_track_layout_events(self):
        def setup(root):
            (root / 'drawers/keyboard/backend.py').write_text('''import sys,json,time
from pathlib import Path
p=Path(__file__).with_name('state.json')
s=json.loads(p.read_text()) if p.exists() else dict(available=True,language='en',secondary='bg')
a,c=sys.argv[1:];time.sleep(.12)
if a=='select':
 s['language']=c
 if c!='en':s['secondary']=c
 p.write_text(json.dumps(s))
print(json.dumps(s))
''')
        self.run_qml('''import QtQuick
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
   InputLanguage.select("vi");drawer.active=false;stage++;
  }else if(stage===2&&!InputLanguage.busy){
   if(InputLanguage.language!=="vi"||InputLanguage.secondary!=="vi")throw new Error("Vietnamese did not finish");
   InputLanguage.select("en");stage++;
  }else if(stage===3&&!InputLanguage.busy){
   if(InputLanguage.language!=="en"||InputLanguage.secondary!=="vi")throw new Error("English discarded pair");
   InputLanguage.handleLayoutEvent("activelayout","laptop,English (US)");stage++;
  }else if(stage===4&&!InputLanguage.busy){
   if(InputLanguage.keyboard!=="laptop")throw new Error("event keyboard lost");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''', setup)

    def test_failed_selection_keeps_confirmed_state_and_error_after_refresh(self):
        def setup(root):
            (root / 'drawers/keyboard/backend.py').write_text("""import sys,json,time
from pathlib import Path
p=Path(__file__).with_name('state.json')
s=json.loads(p.read_text()) if p.exists() else dict(available=True,language='en',secondary='bg')
a,c=sys.argv[1:];time.sleep(.08)
if a=='select':
 if c=='vi':
  print(json.dumps(dict(available=True,language='vi',secondary='vi')))
  print('IME failed to start',file=sys.stderr);sys.exit(1)
 s['language']=c
 p.write_text(json.dumps(s))
print(json.dumps(s))
""")
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/keyboard"
ShellRoot {
 property int stage:0
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0){InputLanguage.refresh();stage++;}
  else if(stage===1&&!InputLanguage.busy){InputLanguage.select("vi");stage++;}
  else if(stage===2&&!InputLanguage.busy&&!InputLanguage.refreshPending){
   if(InputLanguage.language!=="en"||InputLanguage.secondary!=="bg")throw new Error("failed action published state");
   if(!InputLanguage.error.includes("IME failed"))throw new Error("recovery hid the action error");
   InputLanguage.select("bg");stage++;
  }else if(stage===3&&!InputLanguage.busy){
   if(InputLanguage.language!=="bg"||InputLanguage.error)throw new Error("explicit retry did not recover");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''', setup)


if __name__ == '__main__':
    unittest.main()
