"""Transient alarm/pomodoro scheduling and production popup; no real notifications."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import support


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ReminderTests(unittest.TestCase):
    def run_qml(self, body, setup=None, timezone='UTC'):
        with patch.dict(os.environ, TZ=timezone):
            return support.run_qml(self, body, setup)

    def test_alarm_delivery_cancellation_and_pomodoro_transitions_after_sleep(self):
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 id:root
 property double fakeNow:Date.UTC(2026,9,17,10,0,30)
 property var sent:[]
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:50;running:true;onTriggered:{try{
  ReminderService.clock=()=>root.fakeNow;
  ReminderService.deliver=(title,body)=>root.sent.push({title,body});
  check(!ReminderService.addAlarm("24:00","")&&!ReminderService.addAlarm("09:7",""),"invalid alarm accepted");
  check(ReminderService.addAlarm("10:01"," Tea "),"alarm rejected");
  const due=ReminderService.entries[0].deadline;
  check(due===Date.UTC(2026,9,17,10,1),"alarm scheduled at wrong minute");
  ReminderService.tick(due-1);check(sent.length===0,"alarm delivered early");
  ReminderService.tick(due);ReminderService.tick(due+1000);
  check(sent.length===1&&sent[0].title==="Reminder"&&sent[0].body==="Tea"&&ReminderService.entries.length===0,"alarm was lost or duplicated");
  check(ReminderService.nextAlarm("09:00",fakeNow)===Date.UTC(2026,9,18,9),"past time did not become tomorrow");
  check(!ReminderService.addAlarm("09:00","Too early",fakeNow),"past reminder on chosen day accepted");
  const midnight=Date.UTC(2026,9,17,23,59,30);
  check(ReminderService.nextAlarm("00:00",midnight,midnight+60000)===Date.UTC(2026,9,18),"next-minute midnight rollover rejected");
  ReminderService.addAlarm("11:00","Cancelled");ReminderService.stop(ReminderService.entries[0].id);
  ReminderService.tick(fakeNow+7200000);check(sent.length===1,"cancelled alarm fired");
  check(!ReminderService.addPomodoro(0,5)&&!ReminderService.addPomodoro(1.5,5),"invalid intervals accepted");
  check(ReminderService.addPomodoro(25,5)&&!ReminderService.addPomodoro(25,5),"more than one pomodoro");
  let entry=ReminderService.entries[0];
  ReminderService.tick(fakeNow+1000);check(ReminderService.remaining(entry)==="24:59","countdown incorrect");
  fakeNow=entry.deadline;ReminderService.tick();entry=ReminderService.entries[0];
  check(sent.length===2&&entry.phase==="break"&&entry.deadline===fakeNow+300000,"focus did not start break");
  fakeNow+=7200000;ReminderService.tick();entry=ReminderService.entries[0];
  check(sent.length===3&&entry.phase==="focus"&&entry.deadline===fakeNow+1500000,"sleep replayed missed phases");
  ReminderService.stop(entry.id);fakeNow+=7200000;ReminderService.tick();
  check(sent.length===3&&!ReminderService.scheduler.running,"stopped pomodoro kept running");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''')

    def test_alarm_uses_next_actual_local_time_across_dst(self):
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:50;running:true;onTriggered:{try{
  check(ReminderService.nextAlarm("01:30",Date.UTC(2026,10,1,5,45))===Date.UTC(2026,10,1,6,30),"repeated hour skipped next occurrence");
  check(ReminderService.nextAlarm("02:30",Date.UTC(2026,2,8,6))===Date.UTC(2026,2,9,6,30),"nonexistent hour silently changed time");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}''', timezone='America/New_York')

    def test_scheduler_delivers_without_an_open_drawer(self):
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 id:root
 property double fakeNow:Date.UTC(2026,9,17,10)
 property int delivered:0
 Timer{interval:50;running:true;onTriggered:{
  ReminderService.clock=()=>root.fakeNow;
  ReminderService.deliver=(title,body)=>root.delivered++;
  ReminderService.addAlarm("10:01","");fakeNow+=60000;
 }}
 Timer{interval:100;repeat:true;running:true;onTriggered:{
  if(!delivered)return;
  if(delivered!==1||ReminderService.entries.length||ReminderService.scheduler.running)console.error("DISPLAY_FAIL scheduler did not finish alarm");
  else console.log("DISPLAY_PASS");
  Qt.quit();
 }}
 Timer{interval:3000;running:true;onTriggered:{console.error("DISPLAY_FAIL scheduler timeout");Qt.quit();}}
}''')

    def test_sections_popup_width_keyboard_countdown_stop_and_drawer_lifetime(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "drawers/weather"
import "ui"
ShellRoot {
 id:root
 property double fakeNow:Date.UTC(2026,9,17,10,0,30)
 property var sent:[]
 TestCase{id:input;when:false;parent:window.contentItem}
 QtObject{id:mockWeather;property string selectedId:"east";property bool loading:false;property string error:"";
  property var state:({locations:[{id:"east",name:"Eastern city",clock:"10:00",zone:"UTC"}],location:{id:"east",name:"Eastern city"},clock:"10:00",date:"2026-10-17",zone:"UTC",updated:"10:00",stale:false,weather:{current:{temperature:18,feelsLike:17,humidity:65,wind:12,code:1,isDay:true},hourly:Array.from({length:6},(_,i)=>({label:(11+i)+":00",temperature:18,rain:10,code:1,isDay:true})),daily:Array.from({length:5},(_,i)=>({date:"2026-10-"+(17+i),today:i===0,high:22,low:13,rain:10,code:1}))}})
  function refresh(){}function fetchWeather(force){}function select(id){}
 }
 FloatingWindow{id:window;implicitWidth:480;implicitHeight:1000;visible:true;color:Theme.background
  Rectangle{anchors.fill:parent;color:Theme.background
   Loader{id:page;x:16;y:16;width:448;height:960;sourceComponent:Component{WeatherDrawer{active:true;service:mockWeather}}}
  }
 }
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function popup(drawer,focus){return find(drawer,focus?"focusToggle":"reminderAdd").data.find(item=>item.objectName===(focus?"focusPopup":"reminderPopup"));}
 function typeNumber(field,text){field.focusEditor();for(const character of text)input.keyClick(character.toUpperCase().charCodeAt(0));}
 function checkWidth(drawer,editor){
  const add=find(drawer,"reminderAdd"),focus=find(drawer,"focusToggle");
  check(Math.abs(add.width-drawer.width)<2&&Math.abs(focus.width-drawer.width)<2,"section buttons are not full width");
  check(Math.abs(editor.width-add.width)<2&&editor.width>=260,"popup squeezed or overflowing: "+editor.width);
 }
 property int stage:0
 property int alarmId:0
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  const drawer=page.item;
  if(stage===0){
   ReminderService.clock=()=>root.fakeNow;ReminderService.deliver=(title,body)=>root.sent.push({title,body});
   find(drawer,"reminderAdd").clicked();
  }else if(stage===1){
   const editor=popup(drawer,false);check(editor.visible&&drawer.escapeHandler,"reminder editor did not open");checkWidth(drawer,editor);
   const hour=find(editor.contentItem,"reminderHour"),minute=find(editor.contentItem,"reminderMinute"),message=find(editor.contentItem,"reminderAlarmMessage"),submit=find(editor.contentItem,"reminderStart");
   check(hour.number===10&&minute.number===1&&minute.contentItem.text==="01","default is not the next minute");
   check(message.width>editor.width-40,"message field squeezed");
   check(submit.text!==find(drawer,"reminderAdd").text,"reminder actions repeat");
   typeNumber(hour,"11");typeNumber(minute,"05");check(hour.number===11&&minute.number===5,"typing hours or minutes failed");
   input.keyClick(Qt.Key_Up);check(minute.number===6,"keyboard increment failed: "+minute.value+"/"+minute.number+"/"+minute.contentItem.text);
   input.keyClick(Qt.Key_Down);check(minute.number===5,"keyboard decrement failed");
   typeNumber(minute,"15");input.mouseClick(minute.up.indicator,12,9);check(minute.number===16,"step arrow increment after typing failed: "+minute.value+"/"+minute.number);
   input.mouseClick(minute.down.indicator,12,9);check(minute.number===15,"step arrow decrement failed");
   typeNumber(hour,"24");check(!hour.acceptableInput&&!submit.enabled,"invalid hour accepted");
   typeNumber(hour,"10");typeNumber(minute,"60");check(!minute.acceptableInput&&!submit.enabled,"invalid minute accepted");
   typeNumber(hour,"09");typeNumber(minute,"59");check(!submit.enabled,"past time accepted");
   typeNumber(hour,"10");typeNumber(minute,"05");check(submit.enabled,"future time rejected");
   minute.focusEditor();input.keyClick(Qt.Key_A);check(minute.number===5,"letters accepted in time");
   const toggle=find(drawer,"reminderAdd"),label=find(toggle,"reminderAddLabel");
   check(Math.abs(label.mapToItem(toggle,0,0).y+label.height/2-toggle.height/2)<1,"button label not vertically centered");
   message.text="Make tea";message.forceActiveFocus();
   input.keyClick(Qt.Key_Return);check(ReminderService.entries.length===1&&!editor.visible,"Enter did not set reminder");
   alarmId=ReminderService.entries[0].id;find(drawer,"focusToggle").clicked();
  }else if(stage===2){
   const editor=popup(drawer,true);checkWidth(drawer,editor);
   check(editor.visible&&!popup(drawer,false).visible,"focus editor did not open alone");
   const focus=find(editor.contentItem,"reminderFocusMinutes"),rest=find(editor.contentItem,"reminderBreakMinutes");
   check(focus.width>150&&rest.width>150,"focus fields squeezed");
   check(focus.number===25&&rest.number===5,"defaults changed");typeNumber(focus,"0");
   check(!find(editor.contentItem,"focusStart").enabled,"zero focus accepted");typeNumber(focus,"25");
   check(find(editor.contentItem,"focusStart").text!==find(drawer,"focusToggle").text,"focus actions repeat");
   rest.focusEditor();input.keyClick(Qt.Key_Return);
   check(ReminderService.entries.length===2&&!editor.visible,"Enter did not start focus");
   fakeNow+=60000;ReminderService.tick();
   check(find(drawer,"focusToggle").text==="Stop focus · 24:00"&&find(drawer,"focusToggle").checked,"active focus countdown missing");
   check(find(drawer,"reminder:"+alarmId).mapToItem(drawer,0,0).y>find(drawer,"reminderAdd").mapToItem(drawer,0,0).y,"reminders are not below button");
   page.active=false;
  }else if(stage===3){check(ReminderService.entries.length===2&&ReminderService.scheduler.running,"drawer dismissal stopped reminders");page.active=true;
  }else if(stage===4){
   check(find(drawer,"reminder:"+alarmId)&&find(drawer,"focusToggle").checked,"pending reminders lost on reopening");
   find(drawer,"reminderStop:"+alarmId).clicked();check(ReminderService.entries.length===1,"reminder X did not stop");
   fakeNow=ReminderService.entries[0].deadline;ReminderService.tick();
   check(sent.length===1&&find(drawer,"focusToggle").text==="Stop break · 5:00","break countdown missing");
   find(drawer,"focusToggle").clicked();
   check(ReminderService.entries.length===0&&!find(drawer,"focusToggle").checked&&find(drawer,"focusToggle").text==="Set up focus","active button did not stop cycle");
   page.width=268;find(drawer,"focusToggle").clicked();
  }else if(stage===5){
   const editor=popup(drawer,true);checkWidth(drawer,editor);
   check(find(editor.contentItem,"reminderFocusMinutes").width>100,"narrow focus input squeezed");
   drawer.escapeHandler();check(!editor.visible&&drawer.active,"Escape closed drawer");
   const scroll=find(drawer,"weatherContent").contentItem;scroll.contentY=Math.max(0,scroll.contentHeight-scroll.height);
   find(drawer,"reminderAdd").clicked();
  }else if(stage===6){
   const editor=popup(drawer,false);checkWidth(drawer,editor);
   check(find(editor.contentItem,"reminderAlarmMessage").width>220,"narrow message input squeezed");
   const add=find(drawer,"reminderAdd");input.mouseClick(add,add.width/2,add.height/2);
   check(!editor.visible,"second click did not close popup");
   add.clicked();drawer.active=false;check(!editor.visible,"inactive page kept editor open");
  }else if(stage===7){console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''')

    def test_next_minute_at_midnight_and_open_editor_expiration(self):
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 id:root
 property double fakeNow:Date.UTC(2026,9,17,23,59,30)
 property int stage:0
 FloatingWindow{implicitWidth:320;implicitHeight:500;visible:true
  ReminderControls{id:controls;x:16;y:16;width:288;active:true}
 }
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:150;repeat:true;running:true;onTriggered:{try{
  const add=find(controls,"reminderAdd"),editor=add.data.find(item=>item.objectName==="reminderPopup");
  if(stage===0){ReminderService.clock=()=>root.fakeNow;ReminderService.deliver=()=>{throw new Error("unexpected notification");};add.clicked();stage++;
  }else if(stage===1){
   check(find(editor.contentItem,"reminderHour").number===0&&find(editor.contentItem,"reminderMinute").number===0,"midnight default incorrect");
   check(find(editor.contentItem,"reminderStart").enabled,"midnight default rejected");
   fakeNow+=60000;stage++;
  }else if(stage===2){
   if(ReminderService.now!==fakeNow)return;
   check(!find(editor.contentItem,"reminderStart").enabled,"expired time stayed enabled");
   find(editor.contentItem,"reminderMinute").value=1;
   check(find(editor.contentItem,"reminderStart").enabled,"future midnight time rejected");
   find(editor.contentItem,"reminderStart").clicked();
   check(ReminderService.entries[0].deadline===Date.UTC(2026,9,18,0,1),"midnight reminder scheduled on wrong day");
   ReminderService.stop(ReminderService.entries[0].id);console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL expiry timeout");Qt.quit();}}
}''')

    def test_default_delivery_passes_literal_arguments_to_notify_send(self):
        def setup(root):
            bindir = root / 'bin'; bindir.mkdir()
            output = root / 'notification.json'; output.write_text('[]')
            worker = bindir / 'notify-send'
            worker.write_text('#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\nPath(' + repr(str(output)) + ').write_text(json.dumps(sys.argv[1:]))\n')
            worker.chmod(0o755)
            environment = patch.dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'], REMINDER_DELIVERY_FILE=str(output))
            environment.start(); self.addCleanup(environment.stop)
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/weather"
ShellRoot {
 FileView{id:result;path:Quickshell.env("REMINDER_DELIVERY_FILE");preload:true;watchChanges:true;onFileChanged:reload()
  onLoaded:{try{
   const args=JSON.parse(text());if(!args.length)return;
   if(args[0]!=="--app-name=Time and weather"||args[3]!=="--"||args[4]!=="Reminder"||args[5]!=="-Milk &lt;tea&gt; &amp; honey")throw new Error(JSON.stringify(args));
   console.log("DISPLAY_PASS");Qt.quit();
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}
 }
 Component.onCompleted:ReminderService.deliver("Reminder","-Milk <tea> & honey")
 Timer{interval:3000;running:true;onTriggered:{console.error("DISPLAY_FAIL delivery timeout");Qt.quit();}}
}''', setup)
