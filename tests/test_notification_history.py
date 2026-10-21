"""Native notification lifecycle, private history, and production cards/drawer."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import test_display_drawer as fixtures

spec = importlib.util.spec_from_file_location('notification_history', fixtures.DESKTOP/'drawers/notifications/backend.py')
backend = importlib.util.module_from_spec(spec); spec.loader.exec_module(backend)


class HistoryTests(unittest.TestCase):
    def test_private_atomic_history_preserves_text_and_strips_dead_actions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_STATE_HOME=directory):
            self.assertEqual(backend.load(), dict(items=[], paused=False))
            state = dict(items=[dict(id='one',app='Mail',desktopEntry='org.example.Mail',summary='New mail',body='Literal $(command) & text',timestamp=10,
                                    appIcon='https://example.test/icon',image='image://temporary',actions=[dict(identifier='open',text='Open')],seen=False)],paused=True)
            backend.save(state)
            saved = backend.load()
            self.assertEqual(saved['items'][0]['body'], state['items'][0]['body'])
            self.assertEqual(saved['items'][0]['desktopEntry'], 'org.example.Mail')
            self.assertTrue(saved['paused'])
            self.assertFalse(saved['items'][0]['seen'])
            self.assertEqual(saved['items'][0]['actions'], [])
            self.assertEqual(saved['items'][0]['appIcon'], '')
            self.assertEqual(saved['items'][0]['image'], '')
            self.assertEqual(backend.state_path().stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(backend.state_path().parent.glob('.notifications-*')), [])

    def test_history_is_bounded_and_clear_is_persistent(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_STATE_HOME=directory):
            backend.save(dict(items=[dict(id=str(i),body='文'*20000) for i in range(150)],paused=False))
            saved = backend.load()
            self.assertEqual(len(saved['items']), 100)
            self.assertEqual(len(saved['items'][0]['body']), 16384)
            backend.save(dict(items=[],paused=False))
            self.assertEqual(backend.load()['items'], [])
            for value in ({}, dict(items=[],paused='yes')):
                with self.assertRaises(ValueError): backend.save(value)

    def test_explicit_dunst_migration_preserves_history_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_STATE_HOME=directory):
            old = json.dumps(dict(data=[[dict(id={'data':2},appname={'data':'Mail'},summary={'data':'New mail'},body={'data':'<b>Hello</b> &amp; friends'},timestamp={'data':1000000})]]))
            with patch.object(backend.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,old),subprocess.CompletedProcess([],0,'true')]):
                result = backend.import_dunst()
            self.assertEqual(result['items'][0]['body'], 'Hello & friends')
            self.assertTrue(result['paused'])
            self.assertTrue(result['items'][0]['seen'])
            with self.assertRaises(ValueError): backend.import_dunst()


@unittest.skipUnless(fixtures.QS and shutil.which('dbus-run-session'),'Quickshell and private D-Bus are required')
class HistoryQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        run = subprocess.run
        def isolated(command, **kwargs):
            if command[0] == fixtures.QS:
                kwargs['env']['XDG_STATE_HOME'] = str(Path(kwargs['env']['XDG_CONFIG_HOME']).parent/'state')
                command = ['dbus-run-session', '--', *command]
            return run(command, **kwargs)
        with patch.object(fixtures.subprocess,'run',side_effect=isolated):
            return fixtures.DisplayQmlTests.run_qml(self,body,setup)

    def test_missing_images_do_not_render_placeholders_and_actions_get_optional_icons(self):
        def setup(root):
            (root/'artwork.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#ff465c"/></svg>')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/notifications"
ShellRoot {
 property string lastAction:""
 property real plainHeight:0
 property int stage:0
 FloatingWindow {implicitWidth:268;implicitHeight:700
  NotificationCard {
   id:card;width:parent.width
   record:({id:"sample",app:"Desktop",summary:"A notification",body:"Keep the content compact.",timestamp:1792570000,urgency:1,appIcon:"missing-notification-fixture",image:"image://icon/missing-notification-fixture",progress:-1,
    actions:[{identifier:"open",text:"Open folder"},{identifier:"play",text:"Play album"},{identifier:"unknown",text:"Recalculate orbit"},{identifier:"media-playback-pause",text:"Пауза"}]})
   onActionRequested:identifier=>lastAction=identifier
  }
 }
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer {interval:180;repeat:true;running:true;onTriggered:{try{
  const artwork=find(card,"notificationArtwork:sample");
  if(stage===0){
   check(card.artworkSource===""&&card.appIconSource===""&&!artwork.visible,"missing icon requested checkerboard or left artwork visible");
   const open=find(card,"notificationAction:sample:open"),play=find(card,"notificationAction:sample:play"),unknown=find(card,"notificationAction:sample:unknown"),pause=find(card,"notificationAction:sample:media-playback-pause");
   check(open.iconName==="folder-open"&&play.iconName==="play"&&pause.iconName==="pause"&&unknown.iconName==="","optional action icons incorrect");
   check(open.text==="Open folder"&&unknown.text==="Recalculate orbit","action labels replaced");
   check(open.width<=card.width&&play.width<=card.width,"narrow action buttons overflow");
   play.clicked();check(lastAction==="play","icon mapping changed action identifier");plainHeight=card.implicitHeight;
   card.record=Object.assign({},card.record,{appIcon:"",image:""});
  }else if(stage===1){
   check(card.implicitHeight===plainHeight,"missing image reserved blank space");
   card.record=Object.assign({},card.record,{image:Qt.resolvedUrl("artwork.svg").toString()});
  }else if(stage===2){
   check(artwork.visible&&artwork.status===Image.Ready&&card.implicitHeight>plainHeight,"valid artwork disappeared");
   card.record=Object.assign({},card.record,{image:"file:///nonexistent-notification-fixture.png"});
  }else if(stage===3){
   check(!artwork.visible&&card.implicitHeight===plainHeight,"failed file image left blank space");card.record=Object.assign({},card.record,{urgency:0});
  }else if(stage>=4&&stage<=6){
   const expected=["Low urgency","Normal urgency","Critical urgency"][stage-4],icon=["arrow-down","info","triangle-alert"][stage-4];
   check(find(card,"notificationUrgencyIcon:sample").name===icon,"urgency icon unclear");
   check(find(card,"notificationUrgency:sample").hint===expected&&card.urgencyText===expected,"urgency tooltip incorrect");
   check(card.implicitHeight===plainHeight,"urgency change shifted content");
   if(stage<6)card.record=Object.assign({},card.record,{urgency:stage-3});else card.compact=true;
  }else if(stage===7){
   check(find(card,"notificationUrgencyIcon:sample").name==="triangle-alert"&&find(card,"notificationUrgency:sample").visible,"popup urgency indicator missing");console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''',setup)

    def test_simple_drawer_clear_is_immediate_and_cards_keep_their_identity(self):
        self.run_qml('''import QtQuick
import Quickshell
import "drawers"
ShellRoot {
 QtObject {
  id:mock
  property string error:""
  property var state:({items:[{id:"two",app:"Mail",summary:"New message",body:"A plain-text message.",timestamp:1792570000,urgency:1,appIcon:"",image:"",progress:-1,actions:[]}],paused:true})
  property string lastOp:""
  function request(op,id,value){lastOp=op;if(op==="clear")state=Object.assign({},state,{items:[]});}
  function invoke(key,identifier){}
 }
 FloatingWindow {implicitWidth:480;implicitHeight:820;NotificationsDrawer{id:drawer;anchors.fill:parent;active:true;service:mock}
  Loader {id:header;sourceComponent:drawer.headerActions}
 }
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 property var original:null
 property int stage:0
 Timer {interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){original=find(drawer,"notificationDismiss:two");check(original,"card missing");drawer.width=268;mock.state=Object.assign({},mock.state,{paused:false});}
  else if(stage===1){check(find(drawer,"notificationDismiss:two")===original,"quiet change rebuilt card");find(header.item,"notificationsClear").clicked();check(mock.lastOp==="clear"&&mock.state.items.length===0,"clear required confirmation");}
  else {console.log("DISPLAY_PASS");Qt.quit();}stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''')

    def test_unseen_count_survives_popup_timeout_and_follows_explicit_acknowledgement(self):
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 property string thirdKey:""
 property bool invoked:false
 Component.onCompleted:center.start()
 Process {id:sender;stdout:SplitParser {onRead:line=>{if(line.trim()==="open")invoked=true;}}}
 function send(title){sender.command=["notify-send","--expire-time=300",title];sender.running=true;}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(stage===0&&center.initialized){send("First");ticks=0;stage++;}
  else if(stage===1&&center.state.items.length===1&&ticks>6){
   check(center.unseenCount===1&&center.popups.count===0,"popup timeout acknowledged unseen notification");
   center.drawerOpen=true;check(center.unseenCount===0,"opening drawer did not mark seen");send("While open");stage++;
  }else if(stage===2&&center.state.items.length===2){
   check(center.unseenCount===0&&center.popups.count===0,"open drawer did not acknowledge/suppress new notification");
   center.drawerOpen=false;send("Third");stage++;
  }else if(stage===3&&center.state.items.length===3){
   thirdKey=center.state.items[0].id;check(center.unseenCount===1&&center.popups.count===1,"closed drawer suppressed ordinary popup");
   center.markSeen(thirdKey);center.hidePopup(thirdKey);check(center.unseenCount===0,"explicit popup dismissal did not acknowledge");
   center.request("pause","",true);send("Quiet");stage++;
  }else if(stage===4&&center.state.items.length===4){
   check(center.unseenCount===1&&center.popups.count===0,"quiet notification did not remain unseen");
   center.request("pause","",false);check(center.unseenCount===1&&center.popups.count===0,"ending quiet mode acknowledged or replayed notifications");
   center.markSeen();
   const third=center.state.items.find(row=>row.id===thirdKey);
   sender.command=["notify-send","--replace-id="+third.liveId,"--expire-time=0","--action=open=Open","Third updated"];sender.running=true;stage++;
  }else if(stage===5&&center.state.items[0]?.summary==="Third updated"){
   check(center.unseenCount===1&&center.state.items.length===4,"replacement lost unseen state or duplicated history");
   center.invoke(thirdKey,"open");stage++;
  }else if(stage===6&&invoked){
   check(center.unseenCount===0&&center.state.items.find(row=>row.id===thirdKey).seen,"action closure reverted seen state");
   center.request("clear");check(center.unseenCount===0,"clear retained unseen count");console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>60)throw Error("timeout at "+stage+" "+center.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''')

    def test_quiet_transients_expire_and_client_withdrawal_removes_history(self):
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Component.onCompleted:center.start()
 Process {id:sender}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(stage===0&&center.initialized){
   center.request("pause","",true);
   sender.command=["notify-send","--hint=boolean:transient:true","--expire-time=300","Quiet transient","Do not retain"];sender.running=true;ticks=0;stage++;
  }else if(stage===1&&ticks>6){
   check(center.state.items.length===0&&center.popups.count===0&&Object.keys(center.live).length===0,"quiet transient stayed tracked");
   sender.command=["notify-send","--expire-time=0","Withdrawn","Remove from history"];sender.running=true;stage++;
  }else if(stage===2&&center.state.items.length===1){
   sender.command=["busctl","--user","call","org.freedesktop.Notifications","/org/freedesktop/Notifications","org.freedesktop.Notifications","CloseNotification","u",String(center.state.items[0].liveId)];sender.running=true;stage++;
  }else if(stage===3&&center.state.items.length===0&&!sender.running){
   check(Object.keys(center.live).length===0,"withdrawal left tracked notification");console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>50)throw Error("timeout at "+stage);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''')

    def test_reload_restores_live_actions_without_replaying_popups(self):
        def setup(root):
            (root/'config/notification-reload').write_text('')
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Component.onCompleted:center.start()
 FileView {
  id:phase;path:Quickshell.env("XDG_CONFIG_HOME")+"/notification-reload";blockLoading:true
  onSaved:if(text().trim()==="reload")Quickshell.reload(false)
 }
 Process {id:sender;command:["notify-send","--expire-time=0","--action=open=Open","Reload fixture","Keep this action"]}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(!center.initialized)return;
  if(phase.text().trim()!=="reload"){
   if(stage===0){sender.running=true;stage++;}
   else if(stage===1&&center.state.items.length===1){ticks=0;stage++;}
   else if(stage===2&&ticks>5){phase.setText("reload");stage++;}
  }else if(stage===0&&Object.keys(center.live).length===1){
   check(center.state.items.length===1&&center.state.items[0].actions.length===1,"reload lost live action or duplicated history");
   check(center.popups.count===0,"reload replayed popup");check(center.unseenCount===1,"reload lost unseen state");
   center.invoke(center.state.items[0].id,"open");
   check(center.state.items[0].actions.length===0&&center.unseenCount===0,"reloaded action did not close or acknowledge notification");center.request("clear");ticks=0;stage=10;
  }else if(stage===10&&ticks>4){check(!center.error,"storage error");console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>50)throw Error("timeout at "+stage+" "+Object.keys(center.live).length+" "+center.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''',setup)

    def test_real_dbus_replacement_actions_quiet_transience_and_hover(self):
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Io
import "drawers"
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 property int notificationId:0
 property string key:""
 property bool invoked:false
 Component.onCompleted:center.start()
 FloatingWindow {implicitWidth:390;implicitHeight:820;NotificationsDrawer{id:drawer;anchors.fill:parent;active:true}}
 Process {
  id:sender
  stdout: SplitParser {onRead: data=>{const line=data.trim();if(/^\\d+$/.test(line))notificationId=Number(line);if(line==="open")invoked=true;}}
 }
 Process {id:replace;stdout:SplitParser {onRead:data=>{if(data.trim()==="open")invoked=true;}}}
 function send(args){sender.command=["notify-send","--print-id","--app-name=Fixture",...args];sender.running=true;}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(stage===0&&center.initialized){send(["--expire-time=1200","--wait","--hint=string:desktop-entry:org.example.Fixture","--action=open=Open","First","<b>Hello</b> &amp; friends"]);stage++;}
  else if(stage===1&&center.state.items.length===1&&notificationId){
   key=center.state.items[0].id;check(center.state.items[0].body==="Hello & friends","body formatting");
   check(center.state.items[0].desktopEntry==="org.example.Fixture","notification sender desktop ID was dropped");
   check(center.state.items[0].actions.length===1&&center.popups.count===1,"action or popup missing");
   center.hoverPopup(key,true);ticks=0;stage++;
  }else if(stage===2&&ticks>15){
   check(center.popups.count===1,"hover did not pause timeout");
   replace.command=["notify-send","--replace-id="+notificationId,"--expire-time=1200","--action=open=Open","--app-name=Fixture","Replacement","Updated body"];replace.running=true;stage++;
  }else if(stage===3&&center.state.items[0]?.summary==="Replacement"){
   check(center.state.items.length===1&&center.state.items[0].id===key&&center.popups.count===1,"replacement duplicated notification");
   check(center.popups.get(0).hovered,"replacement discarded hover state");
   center.invoke(key,"open");stage++;
  }else if(stage===4&&invoked){
   check(center.state.items.length===1&&center.state.items[0].actions.length===0&&center.popups.count===0,"closed action stayed active");
   center.request("pause","",true);send(["--expire-time=300","Quiet","Saved quietly"]);stage++;
  }else if(stage===5&&center.state.items.length===2){
   check(center.popups.count===0,"quiet notification made popup");center.request("pause","",false);check(center.popups.count===0,"quiet notifications replayed");
   send(["--hint=boolean:transient:true","--expire-time=300","Transient","Do not retain"]);ticks=0;stage++;
  }else if(stage===6&&ticks>8){
   check(center.state.items.length===2&&center.popups.count===0,"transient retained or did not expire");
   invoked=false;send(["--hint=boolean:transient:true","--expire-time=1500","--wait","--action=open=Open","Transient action","Do not retain"]);stage++;
  }else if(stage===7&&center.popups.count===1){
   center.invoke(center.popups.get(0).key,"open");stage++;
  }else if(stage===8&&invoked){
   check(center.state.items.length===2&&center.popups.count===0,"transient action retained history or popup");
   center.request("clear");check(center.state.items.length===0&&Object.keys(center.live).length===0,"clear left live notifications");ticks=0;stage++;
  }else if(stage===9&&ticks>3){check(!center.error,"storage error: "+center.error);console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>60)throw Error("timeout at "+stage+" "+center.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''')
