"""Directional controller keys use real shell focus and native QML controls."""

import unittest

import support


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ControllerNavigationTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_music_tabs_focus_the_catalogue_without_a_pointer_selection(self):
        from test_music_space import setup

        self.run_qml(
            """import QtQuick
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 property int stage:0
 InteractionState{id:interactions}
 SpaceHost{id:host;interactionState:interactions}
 TestCase{id:input;when:false;parent:host.contentItem}
 function check(value,message){if(!value)throw Error(message);}
 Timer{interval:80;repeat:true;running:true;onTriggered:{try{
  if(stage===0){SpaceState.open("music",Quickshell.screens[0]);stage++;return;}
  const page=host.currentPage;if(!page||!page.initialized||page.loading||!page.rows.length)return;
  if(stage===1){
   check(page.navigationTabs.length===2,"Music tabs not exposed");
   const tab=page.navigationTabs[1];input.mouseClick(tab,tab.width/2,tab.height/2);
   check(page.section==="discover","pointer did not switch Music section");
   stage++;return;
  }
  if(stage===2){
   check(page.catalogueFocus.activeFocus,"Music tab kept focus after loading");
   input.keyClick(Qt.Key_Down);check(page.catalogueFocus.activeFocus,"Music arrows left the list");
   input.keyClick(Qt.Key_PageUp,Qt.ControlModifier);
   check(page.section==="library","keyboard did not return to Music library");
   stage++;return;
  }
  check(page.catalogueFocus.activeFocus,"restored Music library did not get focus");
  SpaceState.close("music");console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
 Timer{interval:7000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.stage);Qt.quit();}}
}""",
            setup=setup,
        )

    def test_tabs_focus_async_catalogues_and_bumpers_follow_the_active_surface(self):
        def setup(root):
            support.floating_window(root / 'ui/InteractionWindow.qml', 800, 600)
            (root / 'spaces/games/Main.qml').write_text("""import QtQuick
import QtQuick.Controls
Item {
 id:page
 property bool active:false
 property var host
 property var toolbarTarget:null
 property var backdropTarget:null
 property real toolbarHeight:46
 property Item initialFocus:catalogue
 property Item catalogueFocus:catalogue
 property list<Item> navigationTabs:[library,browse,disabled]
 property alias view:catalogue
 property alias libraryButton:library
 property alias browseButton:browse
 property alias searchField:search
 property string mode:"library"
 property bool loading:false
 function dismissTransient(){return false;}
 function select(value){mode=value;loading=true;load.restart();}
 Timer{id:load;interval:150;onTriggered:page.loading=false}
 Row {
  parent:page.toolbarTarget||page
  Button{id:library;text:"Library";highlighted:page.mode==="library";onClicked:page.select("library")}
  Button{id:browse;text:"Discover";highlighted:page.mode==="discover";onClicked:page.select("discover")}
  Button{id:disabled;text:"Disabled";enabled:false}
 }
 TextField{id:search;y:60;width:240;text:"query"}
 ListView {
  id:catalogue;y:120;width:300;height:200;model:5;currentIndex:0
  visible:!page.loading;activeFocusOnTab:true
  delegate:Item{required property int index;width:300;height:40;Text{text:index}}
 }
}""")

        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 property int stage:0
 property var desktopCalls:[]
 InteractionState{id:interactions}
 SpaceHost {
  id:host;interactionState:interactions
  navigateDesktop: direction=>root.desktopCalls.push(direction)
 }
 InteractionWindow {
  id:drawer;interactionState:interactions;initialFocus:first
  Column{Button{id:first;text:"First"}Button{id:second;text:"Second"}}
 }
 TestCase{id:input;when:false;parent:host.contentItem}
 function check(value,message){if(!value)throw Error(message);}
 function click(item){input.mouseClick(item,item.width/2,item.height/2);}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  const page=host.currentPage;
  if(stage===0){
   host.handleBumper(-1);check(desktopCalls.join()==="-1","desktop bumper lost window fallback");
   SpaceState.open("games",Quickshell.screens[0]);stage++;return;
  }
  if(!page)return;
  if(stage===1){
   if(!page.view.activeFocus)return;
   click(page.browseButton);check(page.mode==="discover"&&page.loading,"pointer tab did not switch");
  }else if(stage===2){
   if(page.loading)return;
   check(page.view.activeFocus,"pointer tab did not focus catalogue after async results");
   input.keyClick(Qt.Key_Down);check(page.view.currentIndex===1,"stick did not navigate immediately");
   host.handleBumper(1);check(page.mode==="library","bumper did not wrap through enabled tabs");
  }else if(stage===3){
   if(page.loading)return;
   check(page.view.activeFocus,"bumper tab did not focus catalogue");
   input.keyClick(Qt.Key_PageDown,Qt.ControlModifier);
   check(page.mode==="discover","keyboard tab shortcut did not switch");
  }else if(stage===4){
   if(page.loading)return;
   check(page.view.activeFocus,"keyboard tab did not focus catalogue");
   click(page.libraryButton);page.searchField.forceActiveFocus();
  }else if(stage===5){
   if(page.loading)return;
   check(page.searchField.activeFocus,"late results stole focus from search");
   drawer.openOn(Quickshell.screens[0]);
  }else if(stage===6){
   if(!first.activeFocus)return;
   host.handleBumper(1);check(second.activeFocus,"drawer bumper did not step controls");
   check(desktopCalls.join()==="-1","shell bumper moved a desktop window");
   drawer.dismiss();host.handleBumper(1);
   check(desktopCalls.join()==="-1,1","desktop fallback did not return after dismissal");
   SpaceState.close("games");console.log("DISPLAY_PASS");Qt.quit();return;
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
 Timer{interval:7000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",root.stage);Qt.quit();}}
}""",
            setup=setup,
        )

    def test_spaces_open_on_first_entry_arrows_select_and_enter_opens(self):
        def setup(root):
            support.floating_window(root / 'ui/InteractionWindow.qml', 480, 540)

        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
import "drawers"
ShellRoot {
 id:root
 InteractionState{id:interactions}
 QtObject {
  id:mock
  property var state:({capabilities:{},scheduledShutdown:null})
  property bool busy:false
  property string error:""
  property bool pausesAvailable:false
  property bool sleepPaused:false
  property bool lockingPaused:false
  function refresh(){}
  function execute(action,minutes){throw Error("unexpected session action");}
  function setSleepPaused(value){}
  function setLockingPaused(value){}
 }
 QtObject {
  id:target
  property int opens:0
  function openOn(output){opens++;}
  function deliver(id,payload){}
  function dismiss(){}
 }
 InteractionWindow {
  id:window;interactionState:interactions;initialFocus:drawer.initialFocus
  SpacesDrawer{id:drawer;anchors.fill:parent;active:window.opened;service:mock;screen:Quickshell.screens[0]}
 }
 TestCase{id:input;when:false;parent:window.contentItem}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw Error(message);}
 Component.onCompleted:{SpaceState.host=target;window.openOn(Quickshell.screens[0]);}
 Timer{interval:300;running:true;onTriggered:{try{
  const names=SpaceState.entries.map(entry=>entry.id);
  check(find(drawer,"space:"+names[0]).activeFocus,"first Space did not get opening focus");
  for(let i=1;i<names.length;i++){
   input.keyClick(Qt.Key_Down);
   check(find(drawer,"space:"+names[i]).activeFocus,"Down skipped a Space at "+i);
  }
  input.wait(150);
  const last=find(drawer,"space:"+names[names.length-1]);
  const y=last.mapToItem(drawer,0,0).y;
  check(y>=0&&y+last.height<=drawer.height,"selected Space did not scroll into view");
  input.keyClick(Qt.Key_Return);
  check(target.opens===1&&SpaceState.currentId===names[names.length-1],"A did not open selected Space");
  input.keyClick(Qt.Key_Right);
  check(find(drawer,"closeSpace:"+names[names.length-1]).activeFocus,"Right did not select running Space close action");
  input.keyClick(Qt.Key_Left);
  check(last.activeFocus,"Left did not restore the Space entry");
  input.keyClick(Qt.Key_Up);
  check(find(drawer,"space:"+names[names.length-2]).activeFocus,"Up did not select previous entry");
  input.keyClick(Qt.Key_Escape);
  check(!window.opened,"B did not dismiss the drawer");
  SpaceState.host=null;console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup=setup,
        )

    def test_focus_shortcuts_skip_hidden_controls_and_leave_native_arrows_alone(self):
        def setup(root):
            support.floating_window(root / 'ui/InteractionWindow.qml', 700, 540)

        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui"
ShellRoot {
 id:root
 InteractionState{id:interactions}
 InteractionWindow {
  id:window;interactionState:interactions;initialFocus:first
  DrawerPage {
   id:page;anchors.fill:parent;active:window.opened
   Column {
    anchors.fill:parent
    ShellButton{id:first;text:"First";width:200}
    ShellButton{text:"Hidden";visible:false;width:200}
    ShellButton{text:"Disabled";enabled:false;width:200}
    TextField{id:field;text:"abcd";width:200}
    ListView {
     id:list;width:200;height:120;model:4;currentIndex:0;activeFocusOnTab:false
     delegate:Button{required property int index;width:200;height:30;text:index}
    }
    ShellButton{id:last;text:"Last";width:200}
   }
  }
 }
 TestCase{id:input;when:false;parent:window.contentItem}
 function check(value,message){if(!value)throw Error(message);}
 Component.onCompleted:window.openOn(Quickshell.screens[0])
 Timer{interval:250;running:true;onTriggered:{try{
  check(first.activeFocus,"opening focus missing");
  input.keyClick(Qt.Key_Down);
  check(field.activeFocus,"unhandled arrow did not move to next usable control");
  field.cursorPosition=3;input.keyClick(Qt.Key_Left);
  check(field.activeFocus&&field.cursorPosition===2,"fallback stole text editing arrow");
  input.keyClick(Qt.Key_F10,Qt.MetaModifier);
  check(list.activeFocus,"Y+Right did not reach native catalogue");
  input.keyClick(Qt.Key_Down);
  check(list.activeFocus&&list.currentIndex===1,"fallback stole catalogue arrow");
  for(let i=0;i<4;i++)input.keyClick(Qt.Key_Down);
  check(list.activeFocus&&list.currentIndex===3,"holding at the catalogue edge moved focus into detail controls");
  input.keyClick(Qt.Key_F10,Qt.MetaModifier);
  check(last.activeFocus,"Y+Right did not leave the catalogue for detail controls");
  input.keyClick(Qt.Key_F9,Qt.MetaModifier);
  check(list.activeFocus,"Y+Left did not restore catalogue focus");
  input.keyClick(Qt.Key_F9,Qt.MetaModifier);
  check(field.activeFocus,"Y+Left did not restore text field");
  input.keyClick(Qt.Key_F9,Qt.MetaModifier);
  check(first.activeFocus,"hidden or disabled control received focus");
  input.keyClick(Qt.Key_Escape);check(!window.opened,"B did not close surface");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup=setup,
        )
