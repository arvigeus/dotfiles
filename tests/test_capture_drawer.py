"""Capture lifecycle and drawer layout without taking pictures or recording."""

import json
import os
import socket
import threading
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support


@unittest.skipUnless(support.QS, 'Quickshell is required')
class CaptureTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_countdown_freezes_request_survives_page_and_can_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / 'desktop-screenshot'
            command.write_text("""#!/usr/bin/env python3
import sys
assert sys.stdin.read() == ''
assert sys.argv[1:] == ['output', '--output', 'DP-2', '--report', '--save', '--edit'], sys.argv
print('/tmp/Last screenshot.png')
""")
            command.chmod(0o755)
            with patch.dict(os.environ, PATH=directory + ':' + os.environ['PATH']):
                self.run_qml("""import QtQuick
import Quickshell
import "drawers/capture"
ShellRoot {
 id:root
 property int hidden:0
 property int stage:0
 Connections { target:CaptureService; function onHideRequested(){root.hidden++;} }
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:80;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   CaptureService.delay=5;CaptureService.setEdit(true);
   check(!CaptureService.capture(""),"empty display accepted");
   check(CaptureService.capture("DP-2"),"capture rejected");
   check(!CaptureService.capture("other"),"duplicate capture accepted");
   const deadline=CaptureService.deadline;
   CaptureService.setEdit(false);CaptureService.output="other";
   check(CaptureService.pending.save,"save choice was not frozen");
   CaptureService.tick(deadline-1000);check(!hidden&&!CaptureService.capturing,"capture hid too early");
   CaptureService.tick(deadline-400);check(hidden===1&&CaptureService.waiting,"drawer did not dismiss before capture");
   CaptureService.cancel();CaptureService.tick(deadline+1000);
   check(!CaptureService.waiting&&!CaptureService.capturing,"cancelled capture started");
   CaptureService.delay=0;CaptureService.setEdit(true);CaptureService.capture("DP-2");CaptureService.setSave(false);
   CaptureService.tick(CaptureService.deadline+60000);
   check(CaptureService.waiting&&!CaptureService.capturing&&hidden===2,"late timer skipped drawer exit");
   CaptureService.tick(CaptureService.deadline);
   check(!CaptureService.waiting,"capture did not begin after settling");
   stage++;
  }else if(CaptureService.lastImage||CaptureService.error){
   check(!CaptureService.error&&CaptureService.lastImage==="/tmp/Last screenshot.png","reported image lost: "+CaptureService.error);
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_recording_start_waits_for_dismissal_and_survives_closed_page(self):
        seen = []

        def setup(root):
            # A fake service on the runtime control socket (systemd would own it).
            directory = root / 'runtime/desktop-capture'
            directory.mkdir(parents=True)
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(directory / 'control.sock'))
            server.listen()

            def serve():
                with server:
                    connection, _ = server.accept()
                    with connection, connection.makefile() as requests:
                        for line in requests:
                            seen.append(json.loads(line))
                            connection.sendall(
                                (
                                    json.dumps(
                                        dict(
                                            phase='recording'
                                            if seen[-1]['op'] == 'start'
                                            else 'idle',
                                            available=True,
                                            elapsed=0,
                                        )
                                    )
                                    + '\n'
                                ).encode()
                            )

            threading.Thread(target=serve, daemon=True).start()

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/capture"
ShellRoot {
 id:root
 property int stage:0
 property int hidden:0
 Connections{target:CaptureService;function onHideRequested(){root.hidden++;}}
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:150;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   CaptureService.recorder={available:true,phase:"idle"};
   check(CaptureService.record("DP-2"),"recording request rejected");
   check(CaptureService.recordingPending&&hidden===1,"recording did not dismiss drawer first");
   check(!CaptureService.record("DP-2"),"duplicate recording start accepted");
  }else if(stage===1){check(CaptureService.recordingPending,"recording started before drawer exit");
  }else if(stage>=4){
   check(!CaptureService.recordingPending&&hidden===2&&!CaptureService.error,"recording request did not finish after dismissal: "+CaptureService.error);
   check(CaptureService.sessionActive,"recording state was not received over the control socket");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""",
            setup,
        )
        self.assertEqual(seen, [dict(op='start', source='DP-2')])

    def test_region_shortcut_selection_cancellation_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / 'slurp'
            count = Path(directory) / 'count'
            selector.write_text(
                "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nassert sys.stdin.read() == ''\np=Path("
                + repr(str(count))
                + ")\nif p.exists():raise SystemExit(1)\np.touch()\nprint('640x360+6656+0')\n"
            )
            selector.chmod(0o755)
            with patch.dict(os.environ, PATH=directory + ':' + os.environ['PATH']):
                self.run_qml("""import QtQuick
import Quickshell
import "drawers/capture"
ShellRoot {
 id:root
 property int stage:0
 property var requests:[]
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:150;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   CaptureService.recorder={available:true,phase:"idle"};
   CaptureService.send=request=>{root.requests.push(request);return true;};
   CaptureService.recordRegion();CaptureService.recordRegion();
  }else if(stage===1){check(!requests.length,"region started before drawer dismissal");
  }else if(stage===8){
   check(requests.length===1&&requests[0].source==="640x360+6656+0","selected area was not recorded");
   CaptureService.recorder={available:true,phase:"recording"};
   CaptureService.recordRegion();
   check(requests.length===2&&requests[1].op==="stop","shortcut did not stop active recording");
   CaptureService.recorder={available:true,phase:"idle"};CaptureService.recordRegion();
  }else if(stage===16){
   check(requests.length===2,"cancelling region selection started a recording");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_split_button_timing_preference_and_recording_options(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers"
import "drawers/capture"
import "ui"
ShellRoot {
 id:root
 property int stage:0
 property int closes:0
 property var launches:[]
 FloatingWindow{id:window;implicitWidth:480;implicitHeight:900;visible:true;color:Theme.background
  CaptureDrawer{id:drawer;x:16;y:16;width:parent.width-32;height:parent.height-32;active:true
   outputs:[{name:"DP-2"}];webcams:[]
   onCloseRequested:root.closes++
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function popup(){return drawer.screenshotMenu;}
 function recordingPopup(){return drawer.recordingMenu;}
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   CaptureService.launch=command=>root.launches.push(command);
   CaptureService.recorder={available:true,phase:"idle",pictures:"/tmp",videos:"/tmp",options:{systemAudio:true,microphone:false,pointer:true}};
   CaptureService.send=request=>{root.launches.push(request);return true;};
   check(!find(drawer,"captureWebcamToggle")&&find(drawer,"webcamsEmpty").visible,"old webcam footer retained");
   check(drawer.visibleWebcams([{description:"USB camera"},{description:"USB IR camera"}]).length===1,"infrared companion duplicated webcam");
   find(drawer,"captureRecordingOptions").clicked();
   check(find(recordingPopup().contentItem,"recordSystemAudio").checked&&!find(recordingPopup().contentItem,"recordMicrophone").checked,"recording options not read back");
   find(drawer,"captureScreenshotOptions").clicked();
   check(popup().visible&&!recordingPopup().visible,"capture menus overlapped");
   const edit=find(popup().contentItem,"captureEdit");edit.checked=false;edit.toggled();
  }else if(stage===1){
   check(!CaptureService.edit,"global preference not saved");
   check(popup().visible&&drawer.escapeHandler,"timing menu did not open");
   check(!find(popup().contentItem,"captureDelay:0")&&!find(popup().contentItem,"captureDelay:0:output"),"immediate choice retained");
   check(find(popup().contentItem,"captureSave").checked,"saving did not default to on");
   check(drawer.escapeHandler()&&!popup().visible,"Escape did not close timing menu first");
   find(drawer,"captureScreenshotOptions").clicked();
   find(popup().contentItem,"captureDelay:5:output").clicked();
   check(CaptureService.waiting&&CaptureService.delay===5&&closes===1&&!popup().visible,"timed selection did not start capture and close drawer");
   find(drawer,"captureCancel").clicked();check(!CaptureService.waiting,"countdown did not cancel");
   find(drawer,"captureScreenshotAction").clicked();
   check(CaptureService.waiting&&CaptureService.delay===0&&closes===2,"main action inherited old delay");CaptureService.cancel();
   CaptureService.recorder=Object.assign({},CaptureService.recorder,{phase:"recording",elapsed:65});
   find(drawer,"captureRecordingAction").clicked();check(closes===2&&launches[0].op==="stop","active recording did not stop from main action");
   check(CaptureService.recordingTime==="1:05","recording duration is not readable");
   find(drawer,"capturePause").clicked();check(launches[1].op==="pause","pause control did not send command");
   find(drawer,"captureRecordingOptions").clicked();
   check(!find(recordingPopup().contentItem,"recordMicrophone").enabled&&find(drawer,"captureRecordingState").text.includes("Recording"),"session settings editable while recording");
   CaptureService.recorder=Object.assign({},CaptureService.recorder,{phase:"paused"});
   check(find(drawer,"capturePause").text.includes("Resume"),"paused session has no resume action");
   const save=find(popup().contentItem,"captureSave");save.checked=false;save.toggled();
   drawer.active=false;drawer.active=true;drawer.width=268;Theme.setMode("light");
  }else if(stage===2){
   check(!CaptureService.edit&&!find(popup().contentItem,"captureEdit").checked,"editor preference lost on reopen");
   check(!CaptureService.save&&!find(popup().contentItem,"captureSave").checked&&!find(popup().contentItem,"captureEdit").enabled,"clipboard-only preference did not persist/disable editing");
   check(find(drawer,"captureRecordingOptions").mapToItem(drawer,32,0).x<=drawer.width,"split button overflow");
   check(Math.abs(find(drawer,"captureScreenshot").width-find(drawer,"captureRecording").width)<2,"capture buttons have unequal widths");
   check(find(drawer,"captureScreenshot").height>=60,"capture action is not a large tile");
   find(drawer,"captureScreenshotOptions").clicked();
  }else if(stage===3){
   check(popup().width<=drawer.width+16,"narrow timing popup overflow");
   for(const seconds of [3,5,10])for(const mode of ["output","region"]){
    const name="captureDelay:"+seconds+":"+mode;
    const button=find(popup().contentItem,name),label=find(button,name+"Label");
    check(label.width>=label.implicitWidth-1,"timing text clipped: "+label.width+" / "+label.implicitWidth);
    check(label.horizontalAlignment===Text.AlignLeft&&find(button,name+"Icon").name==="alarm-clock","timing entry has no left icon/label");
   }
   drawer.escapeHandler();
   const folder=Quickshell.env("CAPTURE_PREVIEW_DIR");if(folder)drawer.grabToImage(result=>result.saveToFile(folder+"/capture-narrow.png"));
  }else if(stage===4){drawer.width=448;Theme.setMode("dark");CaptureService.setSave(true);
  }else if(stage===5){
   const folder=Quickshell.env("CAPTURE_PREVIEW_DIR");if(folder)drawer.grabToImage(result=>result.saveToFile(folder+"/capture-dark.png"));
  }else if(stage===6){console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_delayed_region_freezes_clipboard_choice_and_accepts_clipboard_result(self):
        with tempfile.TemporaryDirectory() as directory:
            command = Path(directory) / 'desktop-screenshot'
            command.write_text(
                "#!/usr/bin/env python3\nimport sys\nassert sys.stdin.read() == ''\nassert sys.argv[1:]==['region','--report','--no-save','--edit'],sys.argv\nprint('clipboard')\n"
            )
            command.chmod(0o755)
            with patch.dict(os.environ, PATH=directory + ':' + os.environ['PATH']):
                self.run_qml("""import QtQuick
import Quickshell
import "drawers/capture"
ShellRoot {
 property int stage:0
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0){CaptureService.setSave(false);CaptureService.setEdit(true);
  }else if(stage===1){
   check(!CaptureService.save,"save preference not written");
   CaptureService.delay=3;check(CaptureService.capture("","region"),"region incorrectly requires a display");
   const deadline=CaptureService.deadline;
   CaptureService.setSave(true);
   CaptureService.tick(deadline-500);check(CaptureService.waiting&&!CaptureService.capturing,"region selection began before countdown");
   CaptureService.tick(deadline-400);CaptureService.tick(CaptureService.deadline);
  }else if(stage===5){
   check(!CaptureService.error&&!CaptureService.capturing&&!CaptureService.lastImage,"clipboard result treated as file/error: "+CaptureService.error);
   CaptureService.setSave(false);
  }else if(stage===6){
   // Reusing the same Process must close its new stdin pipe too.
   check(CaptureService.capture("","region"),"repeat capture rejected");
   CaptureService.tick(CaptureService.deadline-400);CaptureService.tick(CaptureService.deadline);
  }else if(stage===10){
   check(!CaptureService.error&&!CaptureService.capturing,"repeat capture hung: "+CaptureService.error);
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")

    def test_menu_fits_rendered_labels_hover_and_checkbox_clicks(self):
        self.run_qml("""import QtQuick
import QtTest
import Quickshell
import "drawers"
import "drawers/capture"
ShellRoot {
 id:root
 property int stage:0
 property real initialWidth:0
 TestCase{id:input;when:false;parent:window.contentItem}
 FloatingWindow{id:window;implicitWidth:480;implicitHeight:780;visible:true
  CaptureDrawer{id:drawer;x:16;y:16;width:448;height:748;active:true;outputs:[{name:"DP-2"}];webcams:[]}
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function entry(name){return find(drawer.screenshotMenu.contentItem,name);}
 function recordEntry(name){return find(drawer.recordingMenu.contentItem,name);}
 function check(value,message){if(!value)throw new Error(message);}
 function fits(item){const label=find(item,item.objectName+"Label");check(!label.truncated&&label.lineCount===1&&label.width>=label.implicitWidth,"menu label does not fit: "+item.text);}
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   CaptureService.recorder={available:true,phase:"idle",pictures:"/tmp",videos:"/tmp",lastVideo:"/tmp/test.mp4",options:{systemAudio:true,microphone:false,pointer:true}};
   CaptureService.send=request=>{CaptureService.recorder=Object.assign({},CaptureService.recorder,{options:Object.assign({},CaptureService.recorder.options,{[request.key]:request.value})});return true;};
   find(drawer,"captureScreenshotOptions").clicked();
  }else if(stage===1){
   initialWidth=drawer.screenshotMenu.width;
   for(const seconds of [3,5,10])for(const mode of ["output","region"])fits(entry("captureDelay:"+seconds+":"+mode));
   fits(entry("captureFolder"));
   input.mouseMove(entry("captureDelay:3:output"),50,16);
  }else if(stage===2){
   const row=entry("captureDelay:3:output");
   check(row.hovered&&find(row,row.objectName+"Background").highlighted,"screenshot menu has no hover highlight");
   const folder=Quickshell.env("CAPTURE_PREVIEW_DIR");if(folder)drawer.screenshotMenu.contentItem.grabToImage(result=>result.saveToFile(folder+"/screenshot-menu-hover.png"));
   find(entry("captureDelay:10:output"),"captureDelay:10:outputLabel").font.pixelSize=19;
  }else if(stage===3){
   check(drawer.screenshotMenu.width>initialWidth,"menu width ignores rendered font size");fits(entry("captureDelay:10:output"));
   const checkbox=entry("captureSave");input.mouseClick(checkbox,50,16);
  }else if(stage===4){
   check(!CaptureService.save&&drawer.screenshotMenu.visible,"checkbox click failed or dismissed menu");
   find(drawer,"captureRecordingOptions").clicked();
  }else if(stage===5){
   fits(recordEntry("recordFolder"));fits(recordEntry("recordLastVideo"));
   input.mouseMove(recordEntry("recordSystemAudio"),50,16);
  }else if(stage===6){
   const row=recordEntry("recordSystemAudio");
   check(row.hovered&&find(row,row.objectName+"Background").highlighted,"recording menu has no hover highlight");
   const folder=Quickshell.env("CAPTURE_PREVIEW_DIR");if(folder)drawer.recordingMenu.contentItem.grabToImage(result=>result.saveToFile(folder+"/recording-menu-hover.png"));
   input.mouseClick(row,50,16);
  }else if(stage===7){
   check(!CaptureService.recorder.options.systemAudio&&drawer.recordingMenu.visible,"recording checkbox failed or dismissed menu");
   recordEntry("recordPointer").forceActiveFocus(Qt.TabFocusReason);
  }else if(stage===8){
   const row=recordEntry("recordPointer");check(row.visualFocus&&find(row,row.objectName+"Background").highlighted,"keyboard focus is invisible");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_combo_hover_uses_one_background_for_both_targets(self):
        self.run_qml("""import QtQuick
import QtTest
import Quickshell
import "drawers/capture"
ShellRoot {
 TestCase{id:input;when:false;parent:window.contentItem}
 FloatingWindow{id:window;implicitWidth:360;implicitHeight:200;visible:true
  CaptureButton{id:button;objectName:"combo";x:20;y:20;width:220;text:"Screenshot";iconName:"camera"}
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 property int stage:0
 Timer{interval:150;repeat:true;running:true;onTriggered:{try{
  const background=find(button,"comboBackground");
  if(stage===0){input.mouseMove(find(button,"comboAction"),20,20);
  }else if(stage===1){
   check(button.hovered&&background.highlighted&&background.width===button.width,"main action did not highlight whole tile");
   input.mouseMove(find(button,"comboOptions"),16,20);
  }else if(stage===2){
   check(button.hovered&&background.highlighted&&background.width===button.width,"chevron did not highlight whole tile");
   input.mouseMove(window.contentItem,340,180);
  }else if(stage===3){
   check(!button.hovered&&!background.highlighted,"hover did not clear");console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")

    def test_webcam_slider_drag_commits_new_value_and_keeps_readback(self):
        self.run_qml("""import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers/capture"
import "ui"
ShellRoot {
 id:root
 property var edits:[]
 TestCase{id:input;when:false;parent:window.contentItem}
 QtObject{id:mock;property bool active:true;property bool loaded:true;property string error:""
  property var state:({controls:[{key:"brightness",label:"Brightness",kind:"int",value:20,writable:true,minimum:0,maximum:100,step:1,choices:[]}]})
  function setControl(key,value){root.edits.push({key,value});state={controls:[Object.assign({},state.controls[0],{value})]};}
 }
 FloatingWindow{id:window;implicitWidth:480;implicitHeight:250;visible:true;color:Theme.background
  WebcamControls{id:controls;x:16;y:16;width:448;service:mock}
 }
 function slider(item){if(item instanceof Slider)return item;for(const child of item.children??[]){const found=slider(child);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 property int stage:0
 property real requested:0
 Timer{interval:150;repeat:true;running:true;onTriggered:{try{
  const control=slider(controls);
  if(stage===0){
   check(control&&control.enabled,"brightness slider unavailable");
   input.mousePress(control,control.leftPadding+control.visualPosition*control.availableWidth,control.height/2);
   input.mouseMove(control,control.leftPadding+control.availableWidth*.8,control.height/2,40);
   check(control.value>65,"drag did not move slider: "+control.value+" size="+control.width+"x"+control.height+" pressed="+control.pressed+" pos="+control.visualPosition+" edits="+JSON.stringify(edits));requested=Math.round(control.value);
   check(!edits.length,"drag committed before release");
   // A background read must not replace an in-progress edit.
   mock.state={controls:[Object.assign({},mock.state.controls[0],{value:25})]};
  }else if(stage===1){
   check(Math.round(control.value)===requested,"poll changed dragged value");
   input.mouseRelease(control,control.leftPadding+control.availableWidth*.8,control.height/2);
  }else if(stage===2){
   check(edits.length===1&&edits[0].value===requested,"release sent old value: "+JSON.stringify(edits)+" wanted "+requested);
   check(Math.round(control.value)===requested,"slider snapped back after release");
   control.forceActiveFocus();input.keyClick(Qt.Key_Left);
  }else if(stage===3){
   check(edits.length===2&&edits[1].value===requested-1,"keyboard edit failed");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_webcam_device_controls_privacy_and_preview_lifetime(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers/capture"
import "ui"
ShellRoot {
 id:root
 property int stage:0
 property var edits:[]
 QtObject{id:mock;property bool active:true;property bool loaded:true;property string error:""
  property var state:({token:"test",controls:[
   {key:"privacy",label:"Privacy",kind:"bool",value:0,writable:true,minimum:0,maximum:1,step:1,choices:[]},
   {key:"brightness",label:"Brightness",kind:"int",value:128,writable:true,minimum:0,maximum:255,step:1,choices:[]},
   {key:"focus_auto",label:"Autofocus",kind:"bool",value:1,writable:true,minimum:0,maximum:1,step:1,choices:[]}
  ]})
  function refresh(){}
  function setControl(key,value){root.edits.push({key,value});state=Object.assign({},state,{controls:state.controls.map(control=>control.key===key?Object.assign({},control,{value}):control)});}
 }
 FloatingWindow{implicitWidth:480;implicitHeight:700;visible:true;color:Theme.background
  WebcamCard{id:card;x:16;y:16;width:448;active:true;device:({id:"/dev/video9",description:"Test webcam"});service:mock
   previewComponent:Component{Rectangle{implicitHeight:180;color:"#222222"}}
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function popup(){return find(card,"webcamSettings").data.find(item=>item.objectName==="webcamSettingsPopup");}
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   check(!find(card,"webcamPreview").active,"camera started without Test");
   find(card,"webcamTest").clicked();check(card.previewing,"Test did not open preview");
  }else if(stage===1){
   check(find(card,"webcamPreview").item,"preview failed to load");
   find(card,"webcamSettings").clicked();
  }else if(stage===2){
   check(card.settingsOpen&&popup().visible,"camera controls did not open");
   const focus=find(popup().contentItem,"webcamControl:focus_auto");
   focus.checked=false;focus.toggled();
   check(edits.length===1&&edits[0].key==="focus_auto"&&edits[0].value===0,"autofocus mutation wrong");
   card.closeSettings();
   const privacy=find(card,"webcamEnabled");privacy.checked=false;privacy.toggled();
   check(card.blocked&&!card.previewing&&!find(card,"webcamTest").enabled,"hardware privacy did not stop preview");
   mock.setControl("privacy",0);find(card,"webcamTest").clicked();card.active=false;
   check(!card.previewing&&!find(card,"webcamPreview").active&&!card.settingsOpen,"camera survived dismissal");
   card.active=true;
   check(!card.previewing,"camera restarted on reopen");
   mock.state=Object.assign({},mock.state,{controls:mock.state.controls.filter(control=>control.key!=="privacy")});
   check(!find(card,"webcamEnabled").visible,"fake disable switch shown without hardware support");
   card.width=244;
  }else if(stage===3){
   check(find(card,"webcamTest").width>210,"narrow Test button squeezed");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")


if __name__ == '__main__':
    unittest.main()
