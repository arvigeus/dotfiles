"""Plain snapshots must refresh reordered rows without losing their delegates."""
import unittest

import support


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ModelTests(unittest.TestCase):
    def test_update_and_reorder_preserve_delegate_and_current_record(self):
        support.run_qml(self, '''import QtQuick
import Quickshell
import "ui"
ShellRoot {
 property var rows: [{key:"a",value:1},{key:"b",value:2}]
 property var first: null
 property var second: null
 property int stage: 0
 FloatingWindow {
  visible: true
  Repeater {
   id: items
   model: KeyedModel { values: rows }
   delegate: Item { required property var modelData; property int value: modelData.value }
  }
 }
 Timer { interval: 100; running: true; repeat: true; onTriggered: {
  try {
   if(stage===0) {
    first=items.itemAt(0); second=items.itemAt(1);
    rows=[{key:"a",value:3},{key:"b",value:4}];
   } else if(stage===1) {
    if(items.itemAt(0)!==first || first.value!==3 || second.value!==4) throw Error("update lost state");
    rows=[{key:"b",value:5},{key:"a",value:6}];
   } else {
    if(items.itemAt(0)!==second || items.itemAt(1)!==first || second.value!==5 || first.value!==6)
     throw Error("reordered records are stale or delegates were replaced");
    console.log("DISPLAY_PASS"); Qt.quit();
   }
   stage++;
  } catch(e) { console.error("DISPLAY_FAIL",e); Qt.quit(); }
 }}
}''')
