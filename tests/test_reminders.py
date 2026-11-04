"""Transient alarm/pomodoro scheduling and production popup; no real notifications."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import support

# Runs a command with a private /etc whose localtime symlink the command may
# replace, as timedated does; the host's /etc is never touched.
PRIVATE_LOCALTIME = r"""#!/bin/sh
exec unshare --map-root-user --mount sh -c '
etc=$1; shift
mount --rbind /etc "$etc" && mount -t tmpfs tmpfs /etc || exit 97
for entry in "$etc"/* "$etc"/.[!.]*; do
    if [ -e "$entry" ] || [ -L "$entry" ]; then ln -s "$entry" /etc/; fi
done
ln -sfn /usr/share/zoneinfo/Asia/Ho_Chi_Minh /etc/localtime
exec "$@"' sh "$PRIVATE_ETC" "$@"
"""


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ReminderTests(unittest.TestCase):
    def run_qml(self, body, setup=None, timezone='UTC'):
        with patch.dict(os.environ, TZ=timezone):
            return support.run_qml(self, body, setup)

    def run_with_system_timezone(self, body):
        """Run body with no TZ and a private, replaceable /etc/localtime."""
        if not all(
            Path('/usr/share/zoneinfo', zone).is_file()
            for zone in ('Asia/Ho_Chi_Minh', 'Europe/Sofia')
        ):
            self.skipTest('tzdata is required')
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        wrapper = directory / 'private-localtime'
        wrapper.write_text(PRIVATE_LOCALTIME)
        wrapper.chmod(0o755)
        (directory / 'etc').mkdir()
        with patch.dict(os.environ, PRIVATE_ETC=str(directory / 'etc')):
            os.environ.pop('TZ', None)
            os.environ.pop('DBUS_SESSION_BUS_ADDRESS', None)
            probe = subprocess.run(
                [wrapper, 'readlink', '/etc/localtime'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if probe.stdout.strip() != '/usr/share/zoneinfo/Asia/Ho_Chi_Minh':
                self.skipTest('Unprivileged user and mount namespaces are required')
            qs = directory / 'qs'
            qs.write_text(f'#!/bin/sh\nexec "{wrapper}" "{support.QS}" "$@"\n')
            qs.chmod(0o755)
            with patch.object(support, 'QS', str(qs)):
                return support.run_qml(self, body)

    def test_alarm_delivery_cancellation_and_pomodoro_transitions_after_sleep(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 id:root
 property double fakeNow:Date.UTC(2026,9,17,10,0,30)
 property var sent:[]
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:50;running:true;onTriggered:{try{
  ReminderService.clock=()=>root.fakeNow;
  ReminderService.deliver=(title,body,urgency)=>root.sent.push({title,body,urgency});
  check(!ReminderService.addAlarm("24:00","")&&!ReminderService.addAlarm("09:7",""),"invalid alarm accepted");
  check(ReminderService.addAlarm("10:01"," Tea "),"alarm rejected");
  const due=ReminderService.entries[0].deadline;
  check(due===Date.UTC(2026,9,17,10,1),"alarm scheduled at wrong minute");
  ReminderService.tick(due-1);check(sent.length===0,"alarm delivered early");
  ReminderService.tick(due);ReminderService.tick(due+1000);
  check(sent.length===1&&sent[0].title==="Reminder"&&sent[0].body==="Tea"&&ReminderService.entries.length===0,"alarm was lost or duplicated");
  check(sent[0].urgency==="critical","alarm would be hidden by Do Not Disturb");
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
  check(sent[1].urgency==="normal","focus prompt bypasses Do Not Disturb");
  fakeNow+=7200000;ReminderService.tick();entry=ReminderService.entries[0];
  check(sent.length===3&&entry.phase==="focus"&&entry.deadline===fakeNow+1500000,"sleep replayed missed phases");
  ReminderService.stop(entry.id);fakeNow+=7200000;ReminderService.tick();
  check(sent.length===3&&!ReminderService.scheduler.running,"stopped pomodoro kept running");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")

    def test_alarm_uses_next_actual_local_time_across_dst(self):
        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:50;running:true;onTriggered:{try{
  check(ReminderService.nextAlarm("01:30",Date.UTC(2026,10,1,5,45))===Date.UTC(2026,10,1,6,30),"repeated hour skipped next occurrence");
  check(ReminderService.nextAlarm("02:30",Date.UTC(2026,2,8,6))===Date.UTC(2026,2,9,6,30),"nonexistent hour silently changed time");
  ReminderService.clock=()=>Date.UTC(2026,10,1,4,30);ReminderService.deliver=()=>{throw new Error("unexpected notification");};
  check(ReminderService.addAlarm("09:00","After the change"),"alarm rejected");
  const due=ReminderService.entries[0].deadline;
  check(due===Date.UTC(2026,10,1,14),"alarm is not at 09:00 EST");
  ReminderService.tick(Date.UTC(2026,10,1,4,31));ReminderService.tick(Date.UTC(2026,10,1,7));
  check(ReminderService.entries[0].deadline===due,"DST transition moved the alarm");
  ReminderService.stop(ReminderService.entries[0].id);
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            timezone='America/New_York',
        )

    def test_alarms_keep_local_time_when_system_timezone_changes(self):
        self.run_with_system_timezone("""import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/weather"
ShellRoot {
 id:root
 // 08:00 in Ho Chi Minh City, 03:00 in Sofia.
 property double fakeNow:Date.UTC(2026,10,5,1)
 property var sent:[]
 property int stage:0
 property int tea:0
 Process{id:relink}
 function zone(name){relink.command=["ln","-sfn","/usr/share/zoneinfo/"+name,"/etc/localtime"];relink.running=true;}
 function alarm(id){return ReminderService.entries.find(entry=>entry.id===id);}
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:150;repeat:true;running:true;onTriggered:{try{
  if(relink.running)return;
  if(stage===0){
   check(new Date(fakeNow).getHours()===8,"private zone is not Ho Chi Minh City");
   ReminderService.clock=()=>root.fakeNow;ReminderService.deliver=(title,body)=>root.sent.push(body);
   check(ReminderService.addAlarm("09:00","Tea")&&ReminderService.addPomodoro(25,5),"reminders rejected");
   tea=ReminderService.entries[0].id;
   check(alarm(tea).deadline===Date.UTC(2026,10,5,2),"alarm is not at 09:00 local");
   zone("Europe/Sofia");
  }else if(stage===1){
   check(new Date(fakeNow).getHours()===3,"timezone change is not visible");
   const focus=ReminderService.entries.find(entry=>entry.kind==="pomodoro");
   ReminderService.tick();
   check(alarm(tea).deadline===Date.UTC(2026,10,5,7)&&ReminderService.dueLabel(alarm(tea).deadline)==="09:00","alarm kept the previous zone's time");
   check(ReminderService.entries.find(entry=>entry.kind==="pomodoro").deadline===focus.deadline,"focus timer moved with the timezone");
   ReminderService.stop(focus.id);
   ReminderService.tick(Date.UTC(2026,10,5,2));check(!sent.length,"alarm fired at the previous zone's time");
   check(ReminderService.addAlarm("05:00","Early"),"Sofia alarm rejected");
   zone("Asia/Ho_Chi_Minh");
  }else if(stage===2){
   // 05:00 has already passed in Ho Chi Minh City: deliver it now rather than lose it.
   ReminderService.tick();
   check(JSON.stringify(sent)==='["Early"]',"passed alarm was not delivered once: "+JSON.stringify(sent));
   check(alarm(tea).deadline===Date.UTC(2026,10,5,2),"alarm did not return to 09:00 local");
   ReminderService.tick(Date.UTC(2026,10,5,2));
   check(JSON.stringify(sent)==='["Early","Tea"]'&&!ReminderService.entries.length,"alarm did not fire at 09:00 local");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage);Qt.quit();}}
}""")

    def test_scheduler_delivers_without_an_open_drawer(self):
        self.run_qml("""import QtQuick
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
}""")

    def test_sections_popup_width_keyboard_countdown_stop_and_drawer_lifetime(self):
        self.run_qml("""import QtQuick
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
}""")

    def test_next_minute_at_midnight_and_open_editor_expiration(self):
        self.run_qml("""import QtQuick
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
}""")

    def test_default_delivery_passes_literal_arguments_to_notify_send(self):
        def setup(root):
            bindir = root / 'bin'
            bindir.mkdir()
            output = root / 'notification.json'
            output.write_text('[]')
            worker = bindir / 'notify-send'
            worker.write_text(
                '#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\nPath('
                + repr(str(output))
                + ').write_text(json.dumps(sys.argv[1:]))\n'
            )
            worker.chmod(0o755)
            environment = patch.dict(
                os.environ,
                PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                REMINDER_DELIVERY_FILE=str(output),
            )
            environment.start()
            self.addCleanup(environment.stop)

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/weather"
ShellRoot {
 FileView{id:result;path:Quickshell.env("REMINDER_DELIVERY_FILE");preload:true;watchChanges:true;onFileChanged:reload()
  onLoaded:{try{
   const args=JSON.parse(text());if(!args.length)return;
   if(args[0]!=="--app-name=Time and weather"||args[2]!=="--urgency=critical"||args[3]!=="--"||args[4]!=="Reminder"||args[5]!=="-Milk &lt;tea&gt; &amp; honey")throw new Error(JSON.stringify(args));
   console.log("DISPLAY_PASS");Qt.quit();
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}
 }
 Component.onCompleted:ReminderService.deliver("Reminder","-Milk <tea> & honey","critical")
 Timer{interval:3000;running:true;onTriggered:{console.error("DISPLAY_FAIL delivery timeout");Qt.quit();}}
}""",
            setup,
        )

    def test_saved_reminders_resume_after_reload_without_opening_the_drawer(self):
        def setup(root):
            now = int(time.time() * 1000)

            def alarm(id, deadline, message):
                stamp = datetime.fromtimestamp(deadline / 1000, timezone.utc)
                return dict(
                    id=id,
                    kind='alarm',
                    deadline=deadline,
                    date=stamp.strftime('%Y-%m-%d'),
                    time=stamp.strftime('%H:%M'),
                    zone=0,
                    message=message,
                )

            focus = dict(
                id=5,
                kind='pomodoro',
                phase='focus',
                focus=25,
                rest=5,
                deadline=now + 6e5,
            )
            store = root / 'runtime/desktop-shell/reminders.json'
            store.parent.mkdir()
            store.write_text(
                json.dumps(
                    dict(
                        entries=[
                            alarm(3, now - 60000, 'Overdue tea'),
                            alarm(7, now + 3600000, 'Later'),
                            focus,
                            dict(alarm(8, now + 60000, 'Bad time'), time='25:00'),
                            alarm(7, now + 60000, 'Duplicate id'),
                            dict(focus, id=9),
                            'garbage',
                        ]
                    )
                )
            )
            bindir = root / 'bin'
            bindir.mkdir()
            sent = root / 'sent.jsonl'
            (bindir / 'notify-send').write_text(
                '#!/usr/bin/python3\nimport json,sys\nwith open('
                + repr(str(sent))
                + ',"a") as stream:stream.write(json.dumps(sys.argv[1:])+"\\n")\n'
            )
            (bindir / 'notify-send').chmod(0o755)
            environment = patch.dict(
                os.environ,
                PATH=str(bindir) + os.pathsep + os.environ['PATH'],
                REMINDER_SENT_FILE=str(sent),
                REMINDER_STORE=str(store),
            )
            environment.start()
            self.addCleanup(environment.stop)

        self.run_qml(
            """import QtQuick
import Quickshell
import Quickshell.Io
import "drawers/weather"
ShellRoot {
 // Only the bar's status is loaded, as after a reload with the drawer closed.
 readonly property var bar: WeatherStatus
 property int stage:0
 FileView{id:sent;path:Quickshell.env("REMINDER_SENT_FILE");watchChanges:true;printErrors:false;onFileChanged:reload()}
 FileView{id:store;path:Quickshell.env("REMINDER_STORE");watchChanges:true;onFileChanged:reload()}
 function check(value,message){if(!value)throw new Error(message);}
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  const service=bar.reminders;
  if(stage===0){
   const calls=sent.text().split("\\n").filter(Boolean).map(line=>JSON.parse(line));
   if(!calls.length)return;
   check(calls.length===1&&calls[0][2]==="--urgency=critical"&&calls[0][5]==="Overdue tea","overdue alarm not delivered once: "+JSON.stringify(calls));
   check(JSON.stringify(service.entries.map(entry=>entry.id))==="[7,5]"&&service.nextId===8,"invalid or delivered entries restored");
   check(service.entries[1].phase==="focus"&&service.scheduler.running,"focus cycle not resumed");
   check(service.addAlarm("23:59","Saved"),"alarm rejected");stage++;
  }else if(stage===1){
   const saved=JSON.parse(store.text()).entries;
   if(saved.length!==3)return;
   check(JSON.stringify(saved.map(entry=>entry.id))==="[7,5,8]"&&saved[2].message==="Saved"&&saved[2].time,"new alarm not saved");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",stage,e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage,sent.text());Qt.quit();}}
}""",
            setup,
        )
