"""Production tray input, hot removal and layout; no real application actions."""
import os
import unittest
import support


@unittest.skipUnless(support.QS, 'Quickshell is required')
class TrayDrawerTests(unittest.TestCase):
    def test_blueman_menu_icons_with_native_theme(self):
        if os.environ.get('DISPLAY_PREVIEW_PLATFORM') != 'wayland':
            self.skipTest('System icon search paths require the native Wayland QPA')
        startup = '\n'.join(line for line in (support.DESKTOP / 'shell.qml').read_text().splitlines()
                            if line.startswith('//@ pragma ')) + '\n'
        support.run_qml(self, startup + '''import QtQuick
import Quickshell
ShellRoot {
 property var names:["bluetooth-disabled-symbolic","edit-find-symbolic","document-open-recent-symbolic","bluetooth-symbolic","document-properties-symbolic","application-x-addon-symbolic","help-about-symbolic","application-exit-symbolic"]
 FloatingWindow {implicitWidth:256;implicitHeight:48;visible:true;color:"#eeeeee"
  Row {id:icons;width:256;height:48;spacing:0
   Repeater {model:names;delegate:Item {
    required property string modelData
    width:32;height:48
    Image {anchors.centerIn:parent;width:16;height:16;source:Quickshell.iconPath(parent.modelData,true);sourceSize.width:16;sourceSize.height:16}
   }}
  }
 }
 Timer {interval:250;running:true;onTriggered:{try{
  for(const name of names)if(!Quickshell.iconPath(name,true))throw Error("Blueman menu icon missing: "+name);
  const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
  if(destination)icons.grabToImage(result=>{result.saveToFile(destination+"/tray-menu-icons.png");console.log("DISPLAY_PASS");Qt.quit();});
  else{console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''')

    def test_live_items_keyboard_mouse_scrolling_and_dismissal(self):
        support.run_qml(self, '''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import Quickshell.Services.SystemTray
import "ui"
import "drawers"
ShellRoot {
 id:root
 property int closed:0
 property var scrolls:[]
 QtObject {id:service;property var items:({values:[first,second,third]})}
 QtObject {id:first;property string id:"first";property string title:"Music player";property string tooltipTitle:"Music";property string tooltipDescription:"Playing a song";property string icon:"";property int status:Status.Active;property bool hasMenu:false;property bool onlyMenu:false;property var menu:null;property int activations:0;property int secondary:0
  function activate(){activations++;}function secondaryActivate(){secondary++;}function scroll(delta,horizontal){root.scrolls=root.scrolls.concat([{delta,horizontal}]);}}
 QtObject {id:second;property string id:"second";property string title:"";property string tooltipTitle:"Sync client";property string tooltipDescription:"";property string icon:"";property int status:Status.Passive;property bool hasMenu:false;property bool onlyMenu:false;property var menu:null;property int activations:0
  function activate(){activations++;}function secondaryActivate(){}function scroll(delta,horizontal){}}
 QtObject {id:third;property string id:"third";property string title:"Chat application with a long name";property string tooltipTitle:"";property string tooltipDescription:"Unread messages";property string icon:"";property int status:Status.NeedsAttention;property bool hasMenu:false;property bool onlyMenu:true;property var menu:null;property int activations:0
  function activate(){activations++;}function secondaryActivate(){}function scroll(delta,horizontal){}}
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:400;visible:true;color:Theme.background
  TrayDrawer {id:drawer;x:16;y:16;width:Math.min(448,window.width-32);height:Math.min(368,window.height-32);active:true;tray:service;onCloseRequested:root.closed++}
 }
 TestCase {id:input;when:false;parent:window.contentItem}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 property int stage:0
 Timer {interval:150;repeat:true;running:true;onTriggered:{try{
  const list=find(drawer,"trayScroll"),select=find(drawer,"trayActivate:first");
  if(stage===0){
   check(list.count===3&&!find(drawer,"trayEmpty").visible,"tray inventory not rendered");
   check(find(drawer,"trayActivate:second").text==="Sync client","tooltip title fallback missing");
   check(find(drawer,"trayStatus:second").text==="Idle"&&find(drawer,"trayStatus:third").text==="Needs attention","statuses wrong");
   check(!find(drawer,"trayMenu:first").enabled,"menu-less item exposes menu action");
   const card=find(drawer,"trayItem:first"),background=find(drawer,"trayBackground:first"),menuButton=find(drawer,"trayMenu:first");
   check(drawer.initialFocus===null,"opening the tray automatically focuses its first item");
   input.mouseMove(window.contentItem,1,1);input.wait(30);
   check(!card.highlighted&&!background.highlighted,"first item is highlighted without pointer or keyboard focus");
   check(background.width===card.width&&background.height===card.height,"highlight does not cover the whole row");
   first.hasMenu=true;
   input.mouseMove(select,select.width/2,select.height/2);input.wait(30);
   check(card.highlighted&&background.highlighted,"primary hover did not highlight row");
   input.mouseMove(menuButton,menuButton.width/2,menuButton.height/2);input.wait(30);
   check(card.highlighted&&background.highlighted,"menu-button hover did not highlight row");
   input.mouseMove(window.contentItem,1,1);menuButton.forceActiveFocus();
   check(card.highlighted,"menu keyboard focus did not highlight row");
   first.hasMenu=false;
   input.mouseClick(select,select.width/2,select.height/2);check(first.activations===1&&closed===1,"primary action lost");
   input.mouseClick(select,select.width/2,select.height/2,Qt.MiddleButton);check(first.secondary===1&&closed===2,"middle activation lost");
   input.mouseClick(select,select.width/2,select.height/2,Qt.RightButton);check(first.activations===1&&closed===2,"right click activated application");
   input.mouseWheel(select,select.width/2,select.height/2,0,120);
   input.mouseWheel(select,select.width/2,select.height/2,-120,0);
   check(scrolls.length===2&&scrolls[0].delta===120&&!scrolls[0].horizontal&&scrolls[1].delta===-120&&scrolls[1].horizontal,"wheel direction or delta changed");
   select.forceActiveFocus();input.keyClick(Qt.Key_Space);check(first.activations===2,"keyboard Space lost");
   list.forceActiveFocus();list.currentIndex=0;input.keyClick(Qt.Key_Down);input.keyClick(Qt.Key_Return);
   check(second.activations===1&&list.currentIndex===1,"list keyboard navigation lost");
   check(find(drawer,"trayItem:second").highlighted&&!card.highlighted,"keyboard highlight did not follow current item");
   input.keyClick(Qt.Key_Tab);check(window.activeFocusItem!==list,"Tab did not reach app controls");
   drawer.activate(third,select,false);check(third.activations===0,"menu-only item activated");
   first.status=Status.NeedsAttention;drawer.width=236;
  }else if(stage===1){
   check(find(drawer,"trayStatus:first").text==="Needs attention","live status stale");
   for(const id of ["first","second","third"]){
    const card=find(drawer,"trayItem:"+id),button=find(drawer,"trayMenu:"+id);
    check(card.width<=drawer.width&&button.mapToItem(card,button.width,0).x<=card.width,"narrow row overflow");
   }
   const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
   if(destination)drawer.grabToImage(result=>result.saveToFile(destination+"/tray-narrow.png"));
   service.items={values:[second,third]};
   drawer.activate(first,select,false);check(first.activations===2,"removed item was activated");
  }else if(stage===2){
   check(list.count===2&&!find(drawer,"trayActivate:first"),"removed item retained");
   drawer.active=false;
   drawer.activate(second,find(drawer,"trayActivate:second"),false);check(second.activations===1,"dismissed drawer activated item");
   check(!find(drawer,"trayActivate:second").enabled&&!drawer.escapeHandler,"dismissed controls remain active");
   service.items={values:[]};
  }else if(stage===3){
   check(!list.count&&find(drawer,"trayEmpty").visible,"empty tray guidance missing");
   check(!drawer.menuItem&&!drawer.menuButton,"stale menu target retained");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}''')

    def test_native_registration_menu_tree_actions_status_and_removal(self):
        import shutil
        import subprocess
        import sys
        from pathlib import Path
        from unittest.mock import patch
        if not shutil.which('dbus-run-session'):
            self.skipTest('Private D-Bus is required')
        try:
            import gi  # noqa: F401
        except ImportError:
            self.skipTest('Python GObject bindings are required')

        def setup(root):
            shutil.copyfile(Path(__file__).parent / 'fixtures/tray_service.py', root / 'tray_service.py')
        run = subprocess.run
        def isolated(command, **kwargs):
            if command[0] == support.QS:
                command = ['dbus-run-session', '--', *command]
                # QTest's synthetic input has no compositor seat serial for a
                # native grabbing menu. Test its actions/semantics offscreen;
                # icon rendering has a separate native Wayland check above.
                kwargs['env']['QT_QPA_PLATFORM'] = 'offscreen'
            try:
                return run(command, **kwargs)
            except subprocess.TimeoutExpired as error:
                self.fail((error.stdout or b'').decode() + (error.stderr or b'').decode())
        with patch.object(support.subprocess, 'run', side_effect=isolated):
            startup = '\n'.join(line for line in (support.DESKTOP / 'shell.qml').read_text().splitlines()
                                if line.startswith('//@ pragma ')) + '\n'
            support.run_qml(self, startup + '''import QtQuick
import QtTest
import Quickshell
import Quickshell.Io
import Quickshell.Services.SystemTray
import "ui"
import "drawers"
ShellRoot {
 id:root
 // Match the session root: the host must exist before the drawer is opened.
 readonly property var host:SystemTray
 property var messages:[]
 property int closed:0
 Process {id:app;command:["PYTHON","-B",Qt.resolvedUrl("tray_service.py").toString().replace("file://","")];running:true;stdinEnabled:true
  stdout:SplitParser {onRead:data=>{const message=JSON.parse(data);if(message.error)console.error("DISPLAY_FAIL",message.error);root.messages=root.messages.concat([message]);}}
  stderr:StdioCollector {onStreamFinished:if(text)console.error("DISPLAY_FAIL service",text)}
 }
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:500;visible:true;color:Theme.background
  TrayDrawer {id:drawer;x:16;y:16;width:window.width-32;height:window.height-32;active:false;onCloseRequested:root.closed++}
 }
 TestCase {id:input;when:false;parent:window.contentItem}
 QsMenuOpener {id:opener;menu:drawer.menuItem?.menu??null}
 QsMenuOpener {id:submenu;menu:opener.children.values[3]??null}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 function received(action){return messages.filter(message=>message.action===action);}
 property int stage:0
 property int attempts:0
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  check(++attempts<100,"native tray operation timed out at stage "+stage+" "+JSON.stringify(messages));
  if(stage===0){
   if(!drawer.items.length)return;
   check(!drawer.active&&host.items.values.length===1,"host not tracking while closed");
   drawer.active=true;
  }else if(stage===1){
   const button=find(drawer,"trayMenu:fixture-app");if(!button)return;
   check(button.enabled,"published menu unavailable");button.clicked();
  }else if(stage===2){
   if(opener.children.values.length!==5)return;
   check(drawer.data.find(item=>item.objectName==="trayNativeMenu").visible,"native menu did not open");
   const entries=opener.children.values;
   check(entries[1].checkState===Qt.Checked&&entries[2].isSeparator&&entries[3].hasChildren&&!entries[4].enabled,"native menu semantics lost");
   if(submenu.children.values.length!==1)return;
   check(submenu.children.values[0].text==="Nested action","submenu entries missing");
   check(entries[0].icon!=="","published menu icon was dropped");
   entries[0].triggered();
   drawer.closeMenu();
  }else if(stage===3){
   if(!received("menu").some(event=>event.identifier===1&&event.event==="clicked"))return;
   check(!drawer.menuItem&&!drawer.escapeHandler,"menu close left stale target");
   input.mouseClick(find(drawer,"trayActivate:fixture-app"),60,20);
  }else if(stage===4){
   if(!received("Activate").length)return;
   check(closed===1,"activation did not dismiss drawer");
   const button=find(drawer,"trayActivate:fixture-app");
   input.mouseClick(button,60,20,Qt.MiddleButton);
   input.mouseWheel(button,60,20,0,-120);
  }else if(stage===5){
   if(!received("SecondaryActivate").length||!received("Scroll").length)return;
   check(received("Scroll")[0].args[0]===-120&&received("Scroll")[0].args[1]==="vertical","SNI scroll transport wrong");
   app.write(JSON.stringify({op:"status",value:"NeedsAttention"})+"\\n");
  }else if(stage===6){
   if(find(drawer,"trayStatus:fixture-app").text!=="Needs attention")return;
   find(drawer,"trayMenu:fixture-app").clicked();
  }else if(stage===7){
   if(!drawer.menuItem)return;
   drawer.active=false;
   check(!drawer.menuItem&&!drawer.menuButton&&!drawer.escapeHandler,"dismissal retained app menu");
   drawer.active=true;
   find(drawer,"trayMenu:fixture-app").clicked();
   app.write(JSON.stringify({op:"exit"})+"\\n");
  }else if(stage===8){
   if(drawer.items.length)return;
   check(!drawer.menuItem&&!drawer.menuButton&&!drawer.escapeHandler,"app exit retained menu");
   check(find(drawer,"trayEmpty").visible,"empty state missing after app exit");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;attempts=0;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}'''.replace('PYTHON', sys.executable), setup)

    def test_bar_count_attention_notification_fallback_and_acknowledgement(self):
        import shutil
        def setup(root):
            shutil.copytree(support.DESKTOP / 'bar', root / 'bar')
        support.run_qml(self, '''import QtQuick
import Quickshell
import Quickshell.Services.SystemTray
import "ui"
import "bar"
import "drawers"
import "drawers/tray"
ShellRoot {
 id:root
 QtObject {id:tray;property var items:({values:[chat,viber,background]})}
 QtObject {id:chat;property string id:"zapzap";property string title:"ZapZap";property string tooltipTitle:"";property string tooltipDescription:"";property string icon:"";property int status:Status.Active;property bool hasMenu:false;property bool onlyMenu:false;property var menu:null;property int activations:0
  function activate(){activations++;}function secondaryActivate(){}function scroll(delta,horizontal){} }
 QtObject {id:viber;property string id:"viber";property string title:"Viber";property string tooltipTitle:"";property string tooltipDescription:"";property string icon:"";property int status:Status.Active;property bool hasMenu:false;property bool onlyMenu:false;property var menu:null
  function activate(){}function secondaryActivate(){}function scroll(delta,horizontal){} }
 QtObject {id:background;property string id:"background";property string title:"Background app";property string tooltipTitle:"";property string tooltipDescription:"";property string icon:"";property int status:Status.Passive;property bool hasMenu:false;property bool onlyMenu:false;property var menu:null
  function activate(){}function secondaryActivate(){}function scroll(delta,horizontal){} }
 QtObject {id:notices;property var state:({items:[],paused:false});property int unseenCount:0
  function markSeen(id){state={items:state.items.map(row=>row.id===id?Object.assign({},row,{seen:true}):row),paused:false};}
 }
 Component.onCompleted:{TrayService.tray=tray;TrayService.notifications=notices;}
 FloatingWindow {id:window;implicitWidth:1300;implicitHeight:600;visible:true;color:Theme.background
  StatusIslands {id:islands;x:8;y:8;trayStatus:TrayService;notificationCenter:notices}
  TrayDrawer {id:drawer;x:16;y:90;width:448;height:400;tray:tray;active:false}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(const child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 property int stage:0
 property real reservedWidth:0
 Timer {interval:150;repeat:true;running:true;onTriggered:{try{
  const button=find(islands,"trayButton"),badge=find(button,"trayBadge");
  if(stage===0){
   check(TrayService.count===3&&badge.text==="3","badge must count all tray apps, including passive ones");
   check(!button.entry.attention&&!button.selected&&!badge.highlighted,"idle tray is highlighted");
   reservedWidth=button.width;chat.status=Status.NeedsAttention;
  }else if(stage===1){
   check(button.entry.attention&&button.selected&&badge.highlighted,"native attention did not highlight whole tray button and badge");
   check(button.entry.description.includes("ZapZap")&&find(drawer,"trayItem:zapzap").attention,"attention app not identified");
   chat.status=Status.Active;
   notices.state={items:[{id:"z",app:"Chat profile",desktopEntry:"com.rtosta.zapzap.desktop",seen:false},{id:"v",app:"Viber",seen:false},{id:"other",app:"ZapZap Helper",seen:false}],paused:false};
  }else if(stage===2){
   check(TrayService.attentionItems.length===2&&TrayService.needsAttention(chat)&&TrayService.needsAttention(viber),"unseen notifications did not match desktop ID/display name");
   check(!TrayService.needsAttention(background),"unrelated notification marked another app");
   drawer.active=true;
   check(TrayService.attention,"opening the tray acknowledged notifications");
   drawer.activate(chat,find(drawer,"trayActivate:zapzap"),false);
   check(chat.activations===1&&!TrayService.needsAttention(chat)&&TrayService.needsAttention(viber),"opening app did not acknowledge only its notifications");
   viber.status=Status.NeedsAttention;TrayService.acknowledge(viber);
  }else if(stage===3){
   check(TrayService.needsAttention(viber),"acknowledgement erased app-owned native attention");
   check(!TrayService.needsAttention(chat),"substring sender produced false attention");
   viber.status=Status.Active;
   notices.state={items:[],paused:false};
  }else if(stage===4){
   check(!button.selected&&!badge.highlighted&&!button.entry.attention,"cleared attention stuck");
   tray.items={values:Array.from({length:105},(_,index)=>({id:"fixture-"+index,title:"Fixture app",status:Status.Passive,icon:"",hasMenu:false,tooltipTitle:"",tooltipDescription:""}))};
  }else if(stage===5){
   check(badge.text==="99+"&&button.width===reservedWidth,"large count overflowed or shifted tray button");
   tray.items={values:[]};
  }else if(stage===6){
   check(badge.text===""&&button.width===reservedWidth&&!button.selected,"empty tray count retained or shifted badge");
   check(TrayService.count===0&&!TrayService.attention,"removal retained tray state");
   // Release test-owned publishers before their QtObjects are destroyed.
   TrayService.tray=null;TrayService.notifications=null;
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
}''', setup)
