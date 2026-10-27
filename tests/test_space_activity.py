"""Current Space work stays visible, readable and absent when idle."""
import json
from pathlib import Path
import tempfile
import unittest

import support


@unittest.skipUnless(support.QS, "Quickshell is required")
class SpaceActivityTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_concurrent_progress_and_no_idle_or_hidden_history(self):
        self.run_qml("""import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "spaces/movies"
FloatingWindow {
 id:root
 implicitWidth:500;implicitHeight:250
 property int stage:0
 ActivityIndicator {id:activity;x:30;y:30;spinnerName:"testSpinner"}
 TextField {id:field;x:30;y:120;width:220;height:40}
 TestCase {id:input;parent:root.contentItem;when:false}
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name,seen){
  if(!item)return null;seen=seen||new Set();if(seen.has(item))return null;seen.add(item);
  if(item.objectName===name)return item;
  for(const child of [...(item.children||[]),...(item.data||[])]){const found=find(child,name,seen);if(found)return found;}
  return null;
 }
 function hover(){input.mouseMove(root.contentItem,400,200);input.mouseMove(activity,14,14);}
 Timer{id:driver;interval:100;running:true;repeat:true;onTriggered:{driver.stop();try{
  const tip=find(activity,"spaceActivityTooltip"),spinner=find(activity,"testSpinner");
  if(stage===0){
   check(!activity.visible&&!activity.tooltipText,"idle indicator appeared");
   activity.tasks=[activity.task(true,"catalogue","Loading videos…"),activity.task(true,"details","Loading details…")];
   field.forceActiveFocus();hover();stage++;return;
  }
  if(stage===1){
   if(!tip.visible)return;
   check(spinner.running&&tip.text.includes("Loading videos")&&tip.text.includes("Loading details"),"concurrent tasks missing");
   check(field.activeFocus&&!tip.grabFocus,"activity tooltip took focus");
   activity.tasks=[activity.task(true,"details","Loading details…")];stage++;return;
  }
  if(stage===2){
   check(tip.text==="Loading details…","completed task remained in current work");
   activity.tasks=[];stage++;return;
  }
  if(stage===3){
   check(!activity.visible&&!spinner.running&&!tip.visible&&!activity.tooltipText,"idle completion or tooltip remained");
   activity.jobs=[{job_id:"one",title:"Save song",state:"running",detail:"Downloading",done:50,total:100},
                  {job_id:"two",title:"Analyze video",state:"queued",detail:"Queued",done:0,total:0}];
   hover();stage++;return;
  }
  if(stage===4){
   if(!tip.visible)return;
   check(spinner.running&&tip.text.includes("50%")&&tip.text.includes("Analyze video"),"concurrent job progress missing");
   activity.jobs=[{job_id:"one",title:"Save song",state:"finished",result:{message:"Saved to Music."}},
                  {job_id:"two",title:"Analyze video",state:"running",detail:"Analyzing"}];stage++;return;
  }
  if(stage===5){
   check(tip.text==="Analyze video · Analyzing","completed job remained in current work");
   activity.active=false;
   check(!activity.visible&&!spinner.running&&!activity.tooltipText,"hidden indicator kept animating or describing work");
   activity.jobs=[{job_id:"one",title:"Save song",state:"finished"},{job_id:"two",title:"Analyze video",state:"finished"}];stage++;return;
  }
  if(stage===6){activity.active=true;activity.jobs=activity.jobs.slice();stage++;return;}
  if(stage===7){
   check(!activity.visible&&!activity.busy&&!activity.tooltipText,"background completion reappeared on restore");
   activity.jobs=[{job_id:"fail",title:"Download",state:"failed",error:"Connection failed."},
                  {job_id:"cancel",title:"Download",state:"cancelled"}];stage++;return;
  }
  if(stage===8){
   check(!activity.visible&&!activity.tooltipText,"finished failures/cancellations remained in spinner");
   activity.jobs=[{id:"torrent",title:"Import movie",active:true,progress:0.4}];stage++;return;
  }
  if(stage===9){
   check(activity.visible&&activity.tooltipText.includes("40%"),"torrent progress missing");
   activity.jobs=[{id:"torrent",title:"Import movie",active:false,status:"review"}];stage++;return;
  }
  if(stage===10){
   check(!activity.visible&&!tip.visible&&!activity.tooltipText,"review status became idle history");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(error){console.error("DISPLAY_FAIL",stage,error.message);Qt.quit();}finally{driver.restart();}}}
 Timer{interval:10000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage);Qt.quit();}}
}""")

    def test_spinner_renders_red_after_becoming_busy(self):
        from PySide6.QtGui import QImage
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spinner.png'
            self.run_qml("""import QtQuick
import Quickshell
import "spaces/movies"
FloatingWindow {
 implicitWidth:120;implicitHeight:100;color:"#09090b"
 property int stage:0
 Item {id:sample;anchors.fill:parent
  ActivityIndicator {id:activity;x:30;y:30}
 }
 Timer{id:driver;interval:250;running:true;repeat:true;onTriggered:{
  if(stage===0){activity.tasks=[activity.task(true,"work","Loading…")];stage++;return;}
  driver.stop();sample.grabToImage(result=>{result.saveToFile(OUTPUT);console.log("DISPLAY_PASS");Qt.quit();});
 }}
}""".replace('OUTPUT', json.dumps(str(path))))
            image = QImage(str(path))
            self.assertFalse(image.isNull())
            red = sum(image.pixelColor(x,y).alpha() > 128
                      and image.pixelColor(x,y).red() > 150
                      and image.pixelColor(x,y).green() < 80
                      and image.pixelColor(x,y).blue() < 80
                      for x in range(30,58) for y in range(30,58))
            self.assertGreater(red, 30, 'The active ring did not render with the Space accent color')


if __name__ == "__main__":
    unittest.main()
