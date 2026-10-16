"""Display identification and visual tests; no monitor configuration writes."""
import os
import unittest

import test_display_drawer as fixtures


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class DisplayToolTests(unittest.TestCase):
    run_qml = fixtures.DisplayQmlTests.run_qml

    def test_controller_selection_hotplug_and_identification_timeout(self):
        def setup(root):
            (root / 'drawers/displays/FakeTestWindow.qml').write_text('''import QtQml
QtObject {
 property var target:null
 property var controller:null
 onControllerChanged: if(controller) console.log("TEST_WINDOW_READY",target.record.name,controller.mode)
 Component.onCompleted: console.log("TEST_WINDOW_CREATED")
 Component.onDestruction: console.log("TEST_WINDOW_DESTROYED")
}
''')
        log = self.run_qml('''import QtQuick
import Quickshell
import "drawers/displays"
ShellRoot {
 id:root
 property int stage:0
 property real started:0
 property var record:null
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:120;repeat:true;running:true;onTriggered:{
  try{
   if(stage===0){
    check(!DisplayTestService.running&&DisplayTestService.targets.length===0,"eager test windows");
    const screen=Quickshell.screens[0];check(screen,"no native screen");
    root.record={name:screen.name,label:"Test panel",enabled:true,mode:"1920x1080@60Hz"};
    DisplayTestService.windowSource=Qt.resolvedUrl("drawers/displays/FakeTestWindow.qml");
    const records=[record,Object.assign({},record,{enabled:false}),Object.assign({},record,{name:"missing"})];
    check(DisplayTestService.identify(records),"identify failed");
    check(DisplayTestService.targets.length===1&&DisplayTestService.targets[0].screen===screen,"disabled/missing output identified");
    check(DisplayTestService.mode==="identify","identify mode missing");stage++;
   }else if(stage===1){
    check(DisplayTestService.start("patterns",record),"patterns did not start");
    check(DisplayTestService.targets.length===1&&DisplayTestService.targets[0].record===record,"test not targeted");stage++;
   }else if(stage===2){
    check(DisplayTestService.start("motion",record)&&DisplayTestService.mode==="motion","motion did not replace patterns");stage++;
   }else if(stage===3){
    DisplayTestService.reconcile([]);
    check(!DisplayTestService.running&&!DisplayTestService.targets.length,"hotplug retained test window");
    check(!DisplayTestService.start("patterns",Object.assign({},record,{enabled:false})),"disabled output tested");
    check(!DisplayTestService.start("invalid",record),"invalid mode accepted");
    check(DisplayTestService.identify([record]),"identify did not restart");started=Date.now();stage++;
   }else if(stage===4&&!DisplayTestService.running){
    check(Date.now()-started>=4800&&DisplayTestService.targets.length===0,"identify timeout incorrect");
    console.log("DISPLAY_PASS");Qt.quit();
   }
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}
 }}
 Timer{interval:9000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''', setup)
        self.assertEqual(log.count('TEST_WINDOW_CREATED'), 4, log)
        self.assertEqual(log.count('TEST_WINDOW_READY'), 4, log)
        self.assertEqual(log.count('TEST_WINDOW_DESTROYED'), 4, log)

    def test_patterns_motion_and_click_dismissal(self):
        self.run_qml('''import QtQuick
import QtTest
import Quickshell
import "drawers/displays"
ShellRoot {
 TestCase{id:input;when:false;parent:displayWindow.contentItem}
 property int closed:0
 property int stage:0
 property real stoppedDistance:0
 FloatingWindow{
  id:displayWindow;implicitWidth:800;implicitHeight:600;visible:true
  DisplayTestView{
   id:view;width:800;height:600
   record:({name:"DP-1",label:"Example <panel> & display",mode:"2560x1440@120Hz"})
   onCloseRequested:closed++
  }
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){
  if(item.objectName===name)return item;
  for(let child of item.children??[]){const found=find(child,name);if(found)return found;}
  return null;
 }
 Timer{interval:180;repeat:true;running:true;onTriggered:{
  try{
   const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(stage===0){
    check(find(view,"displayIdentityLabel").visible,"identity label missing");
    if(destination)view.grabToImage(result=>result.saveToFile(destination+"/display-identify.png"));
   }else if(stage===1){
    view.mode="patterns";
    const color=find(view,"displayPatternColor");
    for(let i=0;i<5;i++){view.pattern=i;check(color.visible&&String(color.color)===view.colors[i],"solid pattern incorrect");}
    view.advance(-5);check(view.pattern===6,"backwards wrap incorrect");
    view.advance(1);check(view.pattern===0,"forward wrap incorrect");
    view.pattern=5;
   }else if(stage===2){
    check(find(view,"displayPatternGradient").visible,"gradient missing");
    if(destination)view.grabToImage(result=>result.saveToFile(destination+"/display-gradient.png"));
   }else if(stage===3){view.pattern=6;
   }else if(stage===4){
    check(find(view,"displayPatternCheckerboard").visible,"checkerboard missing");
    if(destination)view.grabToImage(result=>result.saveToFile(destination+"/display-checkerboard.png"));
   }else if(stage===5){view.mode="motion";
   }else if(stage===6){
    check(view.distance>0,"motion did not advance");
    const target=find(view,"displayMotionTarget:0");
    check(target.x===view.distance-100,"motion target not animated");
    if(destination)view.grabToImage(result=>result.saveToFile(destination+"/display-motion.png"));
   }else if(stage===7){view.controlsVisible=false;view.visible=false;stoppedDistance=view.distance;
   }else if(stage===8){
    check(view.distance===stoppedDistance,"hidden motion still animates");
    view.visible=true;view.mode="patterns";
    input.mouseClick(find(view,"displayTestDismiss"),20,20);
    check(closed===1,"click did not dismiss");console.log("DISPLAY_PASS");Qt.quit();
   }
   stage++;
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}
 }}
 Timer{interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''')

    @unittest.skipUnless(os.environ.get('DISPLAY_PREVIEW_PLATFORM') == 'wayland', 'Wayland panels require a native backend')
    def test_native_panel_input_masks_keyboard_and_dismissal(self):
        self.run_qml('''import QtQuick
import QtTest
import Quickshell
import Quickshell.Wayland
ShellRoot {
 id:root
 property var overlay:null
 property int stage:0
 TestCase{id:input;when:false;parent:root.overlay?.contentItem??null}
 QtObject{
  id:controller
  property string mode:"identify"
  property bool running:true
  property int stops:0
  function stop(){running=false;stops++;}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){
  if(item.objectName===name)return item;
  for(let child of item.children??[]){const found=find(child,name);if(found)return found;}
  return null;
 }
 function open(){
  const component=Qt.createComponent("drawers/displays/DisplayTestWindow.qml");
  check(component.status===Component.Ready,component.errorString());
  overlay=component.createObject(root,{target:{screen:Quickshell.screens[0],record:{name:Quickshell.screens[0].name,label:"Native test",mode:"1920x1080@60Hz"},number:1},controller:controller});
  check(overlay,"native window creation failed");
 }
 Timer{interval:220;repeat:true;running:true;onTriggered:{
  try{
   if(stage===0){open();
   }else if(stage===1){
    check(overlay.visible&&overlay.mask!==null,"identify accepts pointer input");
    check(overlay.WlrLayershell.keyboardFocus===WlrKeyboardFocus.None,"identify took keyboard");
    controller.mode="patterns";
   }else if(stage===2){
    check(overlay.mask===null&&overlay.WlrLayershell.keyboardFocus===WlrKeyboardFocus.Exclusive,"test cannot accept input");
    const view=find(overlay.contentItem,"displayTestView");check(view,"test view missing");
    view.forceActiveFocus();input.keyClick(Qt.Key_Space);check(view.pattern===1,"Space did not change pattern");
    input.keyClick(Qt.Key_Left);check(view.pattern===0,"Left did not change pattern");
    input.keyClick(Qt.Key_H);check(!view.controlsVisible,"H did not hide controls");
    input.keyClick(Qt.Key_Escape);check(controller.stops===1&&!overlay.visible,"Escape did not release test");
    overlay.destroy();overlay=null;
   }else if(stage===3){controller.running=true;controller.mode="motion";open();
   }else if(stage===4){
    const view=find(overlay.contentItem,"displayTestView");check(view.distance>0,"native motion not animating");
    input.mouseClick(view,20,20);check(controller.stops===2&&!overlay.visible,"click did not release test");
    overlay.destroy();overlay=null;console.log("DISPLAY_PASS");Qt.quit();
   }
   stage++;
  }catch(e){console.error("DISPLAY_FAIL",e);if(overlay)overlay.visible=false;Qt.quit();}
 }}
 Timer{interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''')


if __name__ == '__main__':
    unittest.main()
