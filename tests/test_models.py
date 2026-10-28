"""Plain snapshots must refresh reordered rows without losing their delegates."""

import unittest

import support


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ModelTests(unittest.TestCase):
    def test_update_and_reorder_preserve_delegate_and_current_record(self):
        support.run_qml(
            self,
            """import QtQuick
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
}""",
        )

    def test_unchanged_snapshots_keep_bindings_and_focus(self):
        support.run_qml(
            self,
            """import QtQuick
import QtQuick.Controls
import Quickshell
import "ui"
import "ui/Models.js" as Models
ShellRoot {
 property int changes: 0
 property int evaluations: 0
 function rows(order, value) {
  // Python snapshots can enumerate keys in any order; nested values are lists.
  const all = {a: {key: "a", value: value, routes: [{name: "x"}]}, b: {routes: [{name: "y"}], value: 2, key: "b"}};
  return order.map(key => all[key]);
 }
 FloatingWindow {
  id: window
  visible: true
  Column {
   Repeater {
    id: items
    model: KeyedModel { id: keyed; values: rows(["a", "b"], 1) }
    delegate: TextField {
     required property var modelData
     text: modelData.key ?? ""
     onModelDataChanged: evaluations++
    }
   }
  }
 }
 Connections { target: keyed; function onDataChanged() { changes++; } }
 ListModel { id: plain; dynamicRoles: true }
 function check(value, message) { if (!value) throw new Error(message); }
 Timer { interval: 100; running: true; onTriggered: {
  try {
   const first = items.itemAt(0);
   first.forceActiveFocus();
   const before = evaluations;
   keyed.values = rows(["a", "b"], 1);
   keyed.values = rows(["a", "b"], 1).map(row => {
    const reversed = {};
    for (const key of Object.keys(row).reverse()) reversed[key] = row[key];
    return reversed;
   });
   check(changes === 0 && evaluations === before, "unchanged records were rewritten");
   keyed.values = rows(["b", "a"], 1);
   check(changes === 0 && items.itemAt(1) === first && first.activeFocus, "a move rewrote records or lost focus");
   keyed.values = rows(["b", "a"], 3);
   check(changes === 1 && first.modelData.value === 3 && first.activeFocus, "a changed record lost focus or stayed stale");
   // Duplicate or missing keys still mirror the snapshot row for row.
   keyed.values = [{key: "d", value: 1}, {key: "d", value: 2}, {value: 3}, {value: 4}];
   keyed.values = [{key: "d", value: 5}, {value: 6}];
   check(keyed.count === 2 && items.count === 2 && items.itemAt(0).modelData.value === 5
    && items.itemAt(1).modelData.value === 6, "stale rows remained: " + keyed.count);
   Models.sync(plain, [{name: "x"}, {name: "x"}], "name");
   Models.sync(plain, [], "name");
   check(plain.count === 0, "emptied snapshot left rows");
   console.log("DISPLAY_PASS"); Qt.quit();
  } catch(e) { console.error("DISPLAY_FAIL", e); Qt.quit(); }
 }}
}""",
        )
