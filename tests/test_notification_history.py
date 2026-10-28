"""Native notification lifecycle, private history, and production cards/drawer."""

import configparser
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
import support

ACTIVATION = (
    support.REPO
    / 'modules/desktop/notifications/symlinks/home/.local/share/dbus-1/services'
    / 'org.freedesktop.Notifications.service'
)


class ActivationTests(unittest.TestCase):
    def test_activation_starts_only_the_managed_shell_unit(self):
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read(ACTIVATION)
        service = entry['D-BUS Service']
        self.assertEqual(service['Name'], 'org.freedesktop.Notifications')
        unit = support.REPO / 'modules/desktop/quickshell/files/etc/systemd/user'
        self.assertTrue((unit / service['SystemdService']).is_file())
        # A bus without systemd activation fails instead of starting a shell
        # outside the unit's umask, restart policy and session conditions.
        self.assertEqual(service['Exec'], '/bin/false')


@unittest.skipUnless(
    support.QS and shutil.which('dbus-run-session'),
    'Quickshell and private D-Bus are required',
)
class HistoryQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        """Own a private bus that activates nothing, so no other daemon can answer."""
        run = subprocess.run

        def isolated(command, **kwargs):
            if command[0] == support.QS:
                root = Path(kwargs['env']['XDG_CONFIG_HOME']).parent
                command = [*support.private_bus(root), *command]
            return run(command, **kwargs)

        with patch.object(support.subprocess, 'run', side_effect=isolated):
            return support.run_qml(self, body, setup)

    def test_history_loads_bounded_and_saves_normalized_snapshot(self):
        def setup(root):
            path = root / 'state/quickshell/desktop/notifications.json'
            path.parent.mkdir(parents=True)
            first = dict(
                id='one',
                app='Mail',
                desktopEntry='org.example.Mail',
                summary='New mail',
                body='Literal $(command) & text',
                timestamp=10,
                appIcon='https://example.test/icon',
                image='image://temporary',
                actions=[dict(identifier='open', text='Open')],
                seen=False,
            )
            rows = [first, dict(first, summary='Duplicate')] + [
                dict(id=str(i), body='文' * 20000) for i in range(150)
            ]
            path.write_text(json.dumps(dict(items=rows, paused=True)))
            path.chmod(0o600)

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Process {id:reader;command:["cat",Quickshell.env("XDG_STATE_HOME")+"/quickshell/desktop/notifications.json"];stdout:StdioCollector{id:output}}
 function check(v,m){if(!v)throw Error(m);}
 Component.onCompleted:center.start()
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(stage===0){
   check(center.initialized&&!center.error,"history did not load: "+center.error);
   const items=center.state.items;
   check(center.state.paused===true&&items.length===99,"loaded history was not bounded and deduplicated: "+items.length);
   check(items[0].summary==="New mail"&&items[0].body==="Literal $(command) & text"&&items[0].desktopEntry==="org.example.Mail"&&items[0].seen===false,"saved text or seen state lost");
   check(items[0].actions.length===0&&items[0].image===""&&items[0].appIcon==="","dead actions or remote images restored");
   check(items[1].body.length===16384&&items[1].seen===true,"body was not capped or seen did not default");
   center.request("pause","",false);center.request("remove","one");stage++;ticks=0;
  }else if(stage===1&&ticks>4){reader.running=true;stage++;
  }else if(stage===2&&!reader.running&&output.text){
   const saved=JSON.parse(output.text);
   check(saved.paused===false&&saved.items.length===98&&saved.items[0].id==="0"&&saved.items[0].actions.length===0,"saved snapshot was not normalized");
   check(!center.error,"storage error: "+center.error);
   console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>40)throw Error("timeout at "+stage+" "+center.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_missing_images_do_not_render_placeholders_and_actions_get_optional_icons(
        self,
    ):
        def setup(root):
            (root / 'artwork.svg').write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#ff465c"/></svg>'
            )

        self.run_qml(
            """import QtQuick
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
}""",
            setup,
        )

    def test_simple_drawer_clear_is_immediate_and_cards_keep_their_identity(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers"
ShellRoot {
 QtObject {
  id:mock
  property string error:""
  property var state:({items:[{id:"two",app:"Mail",summary:"New message",body:"A plain-text message.",timestamp:1792570000,urgency:1,appIcon:"",image:"",progress:-1,actions:[]}],paused:true})
  property string lastOp:""
  property string lastId:""
  function request(op,id,value){lastOp=op;lastId=id??"";if(op==="clear")state=Object.assign({},state,{items:[]});}
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
  else if(stage===1){
   check(find(drawer,"notificationDismiss:two")===original,"quiet change rebuilt card");
   const two=mock.state.items[0];mock.state=Object.assign({},mock.state,{items:[Object.assign({},two,{id:"three",summary:"Newer"}),Object.assign({},two,{summary:"Edited",seen:true})]});
  }else if(stage===2){
   let card=original;while(card&&card.record===undefined)card=card.parent;
   check(find(drawer,"notificationDismiss:two")===original&&card.record.summary==="Edited"&&find(drawer,"notificationDismiss:three"),"insert or edit rebuilt or staled a card");
   original.clicked();check(mock.lastOp==="remove"&&mock.lastId==="two","dismiss targeted the wrong record");
   find(header.item,"notificationsClear").clicked();check(mock.lastOp==="clear"&&mock.state.items.length===0,"clear required confirmation");
  }
  else {console.log("DISPLAY_PASS");Qt.quit();}stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")

    def test_unseen_count_survives_popup_timeout_and_follows_explicit_acknowledgement(
        self,
    ):
        self.run_qml("""import QtQuick
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
}""")

    def test_quiet_transients_expire_and_client_withdrawal_removes_history(self):
        self.run_qml("""import QtQuick
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
}""")

    def test_reload_restores_live_actions_in_place_without_replaying_popups(self):
        def setup(root):
            (root / 'config/notification-reload').write_text('')

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 id:shell
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Component.onCompleted:center.start()
 FileView {
  id:phase;path:Quickshell.env("XDG_CONFIG_HOME")+"/notification-reload";blockLoading:true
  onSaved:if(text().trim()==="reload")Quickshell.reload(false)
 }
 // notify-send waits while a notification has actions, so each send owns a process.
 Component {id:process;Process {}}
 function send(args){process.createObject(shell,{command:["notify-send","--expire-time=0",...args]}).running=true;}
 function row(summary){return center.state.items.find(item=>item.summary===summary);}
 function order(){return center.state.items.map(item=>item.summary).join(",");}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(!center.initialized)return;
  const count=center.state.items.length;
  if(phase.text().trim()!=="reload"){
   if(stage===0){send(["--action=open=Open","Older"]);stage++;}
   else if(stage===1&&count===1){send(["--action=open=Open","Closed"]);stage++;}
   else if(stage===2&&count===2){send(["--action=open=Open","Newest"]);stage++;}
   else if(stage===3&&count===3){
    center.invoke(row("Closed").id,"open");check(!row("Closed").actions.length,"invoked action stayed live");
    send(["--hint=boolean:transient:true","Transient across reload"]);stage++;
   }else if(stage===4){
    const transient=Object.values(center.live).find(notification=>notification.transient);
    if(!transient)return;
    // An earlier shell process can reuse this PID and notification ID.
    center.state=Object.assign({},center.state,{items:center.state.items.concat([{id:"earlier",summary:"Earlier process",liveId:transient.id,processId:Quickshell.processId,instanceId:"earlier-instance",timestamp:1,seen:true}])});
    center.save();ticks=0;stage++;
   }else if(stage===5&&ticks>4){check(order()==="Newest,Closed,Older,Earlier process","fixture order: "+order());phase.setText("reload");stage++;}
  }else if(stage===0&&Object.keys(center.live).length===2&&ticks>2){
   check(order()==="Newest,Closed,Older,Earlier process","reload reordered or dropped history: "+order());
   check(row("Older").actions.length===1&&row("Newest").actions.length===1&&!row("Closed").actions.length,"reload lost live actions or revived a closed one");
   check(center.popups.count===0,"reload replayed popup");check(center.unseenCount===2,"reload changed unseen state");
   send(["--replace-id="+row("Older").liveId,"--action=open=Open","Older updated"]);stage++;
  }else if(stage===1&&row("Older updated")){
   const older=row("Older updated");
   check(center.state.items[0]===older&&center.state.items.length===4&&center.popups.count===1,"replacement after reload duplicated or did not pop up: "+order());
   center.invoke(older.id,"open");
   check(!row("Older updated").actions.length&&center.unseenCount===1,"reloaded action did not close or acknowledge notification");center.request("clear");ticks=0;stage=10;
  }else if(stage===10&&ticks>4){check(!center.error,"storage error");console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>50)throw Error("timeout at "+stage+" "+Object.keys(center.live).length+" "+order()+" "+center.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_popup_removed_with_its_output_while_hovered_resumes_expiry(self):
        def setup(root):
            support.floating_window(
                root / 'drawers/notifications/NotificationPopups.qml'
            )

        self.run_qml(
            """import QtQuick
import QtTest
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Component.onCompleted:center.start()
 Loader {id:outputs;sourceComponent:Component {NotificationPopups {}}}
 FloatingWindow {id:driver;implicitWidth:10;implicitHeight:10;TestCase {id:input;when:false;parent:driver.contentItem}}
 Process {id:sender;command:["notify-send","--expire-time=1500","Output removed","Hovered when its window disappears"]}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(stage===0&&center.initialized){sender.running=true;stage++;}
  else if(stage===1&&center.popups.count===1){
   const window=outputs.item.windows[0],card=find(window.contentItem,"notificationPopup:"+center.popups.get(0).key);
   if(!card?.visible)return;
   input.mouseMove(window.contentItem,1,1);input.mouseMove(card,card.width/2,card.height/2);input.wait(30);
   check(center.popups.get(0).hovered&&!center.popups.get(0).deadline,"pointer hover did not pause the popup");
   outputs.active=false;ticks=0;stage++;
  }else if(stage===2){
   check(!center.popups.get(0).hovered&&center.popups.get(0).deadline>0,"popup window destroyed while hovered kept its deadline paused");stage++;
  }else if(stage===3&&!center.popups.count){console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>50)throw Error("timeout at "+stage);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_real_dbus_replacement_actions_quiet_transience_and_hover(self):
        self.run_qml("""import QtQuick
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
  if(stage===0&&center.initialized){send(["--expire-time=1200","--wait","--hint=string:desktop-entry:org.example.Fixture","--action=open=Open","First","<b>Hello</b> &amp; <a href='https://example.test'>friends</a>: Vec<String> x<y>z, 1 < 2"]);stage++;}
  else if(stage===1&&center.state.items.length===1&&notificationId){
   key=center.state.items[0].id;check(center.state.items[0].body==="Hello & friends: Vec<String> x<y>z, 1 < 2","markup stripped or literal text lost: "+center.state.items[0].body);
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
}""")

    def test_do_not_disturb_still_shows_critical_notifications(self):
        self.run_qml("""import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 id:shell
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Component.onCompleted:center.start()
 Component {id:process;Process {}}
 function send(args){process.createObject(shell,{command:["notify-send",...args]}).running=true;}
 function popups(){const rows=[];for(let i=0;i<center.popups.count;i++)rows.push(center.popups.get(i).record.summary);return rows.sort().join(",");}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  const count=center.state.items.length;
  if(stage===0&&center.initialized){send(["--expire-time=0","Normal before"]);send(["--urgency=critical","Critical before"]);stage++;}
  else if(stage===1&&count===2){
   check(popups()==="Critical before,Normal before","popups missing before quiet mode: "+popups());
   center.request("pause","",true);check(popups()==="Critical before","quiet mode hid a critical popup or kept a normal one: "+popups());
   send(["--expire-time=0","Normal quiet"]);stage++;
  }else if(stage===2&&count===3){
   check(popups()==="Critical before","quiet mode showed a normal notification: "+popups());
   send(["--urgency=critical","Critical quiet"]);stage++;
  }else if(stage===3&&count===4){
   check(popups()==="Critical before,Critical quiet","quiet mode suppressed a critical notification: "+popups());
   check(center.unseenCount===4,"quiet delivery changed unseen state");
   center.request("pause","",false);check(popups()==="Critical before,Critical quiet","ending quiet mode changed popups: "+popups());
   console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>50)throw Error("timeout at "+stage+" "+popups());
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")

    def test_update_streams_do_not_postpone_saving(self):
        self.run_qml("""import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/notifications"
ShellRoot {
 property var center:NotificationCenter
 property int stage:0
 property int ticks:0
 Component.onCompleted:center.start()
 // Progress replacements arrive faster than the save delay.
 Process {id:stream;command:["sh","-c","id=$(notify-send --print-id --expire-time=0 Progress 0) && for i in $(seq 1 20); do notify-send --replace-id=$id --expire-time=0 --hint=int:value:$((i*5)) Progress $i; sleep 0.05; done"]}
 FileView {id:saved;path:Quickshell.env("XDG_STATE_HOME")+"/quickshell/desktop/notifications.json";blockLoading:true;printErrors:false}
 function check(v,m){if(!v)throw Error(m);}
 Timer {interval:100;running:true;repeat:true;onTriggered:{try{
  ticks++;
  if(stage===0&&center.initialized){stream.running=true;stage++;}
  else if(stage===1&&center.state.items.length===1){ticks=0;stage++;}
  else if(stage===2&&ticks>5){
   check(stream.running,"update stream ended before the check");
   saved.reload();check(JSON.parse(saved.text()||"{}").items?.length===1,"saving waited for the update stream to end");stage++;
  }else if(stage===3&&!stream.running){check(!center.error,"storage error: "+center.error);console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>50)throw Error("timeout at "+stage);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")
