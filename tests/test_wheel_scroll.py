"""Exercise shared scrolling through Qt input delivery and native view geometry."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support

UI = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell'
    / 'symlinks/home/.config/quickshell/desktop/ui'
)
RUNNER = shutil.which('qmltestrunner6')
if not RUNNER and Path('/usr/lib/qt6/bin/qmltestrunner').is_file():
    RUNNER = '/usr/lib/qt6/bin/qmltestrunner'


@unittest.skipUnless(RUNNER, 'Qt 6 Quick Test is required')
class WheelScrollTests(unittest.TestCase):
    def test_wheel_input_and_native_views(self):
        qml = r"""
import QtQuick
import QtQuick.Controls
import QtTest
import "UI_URL" as UI

Item {
    width: 800; height: 500
    TextField { id: field; x: 0; y: 250; width: 180; height: 40 }
    Flickable {
        id: vertical
        width: 180; height: 180
        contentWidth: width; contentHeight: 1000
        boundsBehavior: Flickable.StopAtBounds
        Button { id: button; x: 20; y: 20; width: 140; height: 40; text: "Open"; onClicked: test.clicks++ }
        UI.WheelScroll { id: verticalWheel; view: vertical }
    }
    Flickable {
        id: horizontal
        x: 200; width: 180; height: 180
        contentWidth: 1000; contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        UI.WheelScroll {
            id: horizontalWheel
            view: horizontal; orientation: Qt.Horizontal; verticalToHorizontal: true
            wheelStep: 160; scrollGestureEnabled: true
        }
    }
    Flickable {
        id: outer
        x: 400; width: 180; height: 180
        contentWidth: width; contentHeight: 1000
        boundsBehavior: Flickable.StopAtBounds
        Flickable {
            id: inner
            x: 10; y: 10; width: 150; height: 140
            contentWidth: width; contentHeight: 500
            boundsBehavior: Flickable.StopAtBounds
            UI.WheelScroll { view: inner }
        }
        UI.WheelScroll { view: outer }
    }
    ListModel { id: rows }
    UI.ScrollListView {
        id: list
        x: 600; width: 180; height: 180
        model: rows
        delegate: Rectangle { required property real rowHeight; width: 180; height: rowHeight; color: "gray" }
        boundsBehavior: Flickable.StopAtBounds
    }
    Flickable {
        id: form
        x: 200; y: 250; width: 180; height: 120
        contentWidth: width; contentHeight: fields.height
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: fields
            Repeater { id: formButtons; model: 10; Button { width: 180; height: 40; text: "Field " + index } }
            // Tab focuses the editor inside; the control is what must show.
            SpinBox { id: formSpin; width: 180; height: 60; editable: true }
        }
        UI.WheelScroll { view: form; revealFocus: true }
    }
    UI.ScrollListView {
        id: focusList
        x: 400; y: 250; width: 180; height: 120
        model: 20
        delegate: Button { required property int index; width: 180; height: 40; text: "Row " + index }
    }
    TestCase {
        id: test
        name: "WheelScroll"
        when: windowShown
        property int clicks: 0
        function wheel(item, dx, dy) { mouseWheel(item, 80, 80, dx, dy, Qt.NoButton, Qt.NoModifier, 0); }
        function init() {
            vertical.cancelFlick(); horizontal.cancelFlick(); inner.cancelFlick(); outer.cancelFlick();
            vertical.topMargin = 0; vertical.bottomMargin = 0; vertical.contentHeight = 1000;
            vertical.interactive = true; vertical.contentY = 0; horizontal.contentX = 0;
            inner.contentY = 0; outer.contentY = 0;
            clicks = 0;
        }
        function test_immediate_single_delivery_and_focus() {
            field.forceActiveFocus();
            mouseWheel(button, 60, 20, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
            compare(vertical.contentY, 120);
            verify(field.activeFocus);
            wait(250);
            compare(vertical.contentY, 120); // no second native flick or delayed tail
        }
        function test_fractional_rapid_and_reverse() {
            wheel(vertical, 0, -30); compare(vertical.contentY, 30);
            wheel(vertical, 0, -90); compare(vertical.contentY, 120);
            for (let i = 0; i < 3; i++) wheel(vertical, 0, -120);
            compare(vertical.contentY, 480);
            wheel(vertical, 0, 120); compare(vertical.contentY, 360);
        }
        function test_bounds_margins_and_short_content() {
            vertical.topMargin = 20; vertical.bottomMargin = 30; vertical.contentY = -20;
            wheel(vertical, 0, 120); compare(vertical.contentY, -20);
            for (let i = 0; i < 10; i++) wheel(vertical, 0, -120);
            compare(vertical.contentY, 850);
            vertical.contentHeight = 80; vertical.contentY = -20;
            wheel(vertical, 0, -120); compare(vertical.contentY, -20);
        }
        function test_horizontal_axes() {
            wheel(horizontal, 0, -120); compare(horizontal.contentX, 160);
            wheel(horizontal, -120, 0); compare(horizontal.contentX, 320);
            wheel(horizontal, 0, 60); compare(horizontal.contentX, 240);
        }
        function test_nested_view_and_boundary_propagation() {
            wheel(inner, 0, -120); compare(inner.contentY, 120); compare(outer.contentY, 0);
            inner.contentY = 360;
            wheel(inner, 0, -120); compare(inner.contentY, 360); compare(outer.contentY, 120);
        }
        function test_click_through() {
            mouseClick(button, 60, 20, Qt.LeftButton, Qt.NoModifier, 0);
            compare(clicks, 1);
            compare(vertical.contentY, 0);
        }
        function event(phase, angle, pixels) {
            return { phase: phase, angleDelta: Qt.point(0, angle),
                pixelDelta: Qt.point(0, pixels), accepted: false };
        }
        function test_phase_classification_and_noninteractive_view() {
            const mouse = event(Qt.NoScrollPhase, -120, -15);
            verticalWheel.scroll(mouse); compare(vertical.contentY, 120); verify(mouse.accepted);
            const touchpad = event(Qt.ScrollUpdate, -120, -7);
            verticalWheel.scroll(touchpad); compare(vertical.contentY, 120); verify(!touchpad.accepted);
            horizontalWheel.scroll(touchpad); compare(horizontal.contentX, 7); verify(touchpad.accepted);
            vertical.interactive = false;
            verticalWheel.scroll(mouse); compare(vertical.contentY, 120); verify(!mouse.accepted);
        }
        function test_shared_list_immediate_wheel_and_no_delayed_tail() {
            rows.clear();
            for (let i = 0; i < 30; i++) rows.append({rowHeight: 36});
            list.forceLayout(); list.positionViewAtBeginning();
            const origin = list.originY;
            wheel(list, 0, -120); compare(list.contentY, origin + 120);
            wait(250); compare(list.contentY, origin + 120);
        }
        function shown(view, item) {
            const top = item.mapToItem(view.contentItem, 0, 0).y;
            return top >= view.contentY && top + item.height <= view.contentY + view.height;
        }
        function test_keyboard_and_programmatic_focus_reveal() {
            form.contentY = 0;
            formButtons.itemAt(0).forceActiveFocus();
            for (let i = 0; i < 5; i++) keyClick(Qt.Key_Tab);
            verify(formButtons.itemAt(5).activeFocus);
            compare(form.contentY, 120); // the fifth row's bottom edge, no further
            for (let i = 0; i < 5; i++) keyClick(Qt.Key_Backtab);
            compare(form.contentY, 0);
            formSpin.forceActiveFocus();
            verify(formSpin.contentItem.activeFocus);
            compare(form.contentY, form.contentHeight - form.height);
            formButtons.itemAt(3).forceActiveFocus();
            compare(form.contentY, 120);
        }
        function test_pointer_focus_and_opt_out_do_not_scroll() {
            form.contentY = 100;
            mouseClick(formButtons.itemAt(2), 20, 30);
            verify(formButtons.itemAt(2).activeFocus);
            compare(form.contentY, 100);
            vertical.contentY = 200;
            button.forceActiveFocus();
            compare(vertical.contentY, 200);
        }
        function test_shared_list_reveals_tabbed_delegates() {
            focusList.positionViewAtBeginning();
            focusList.itemAtIndex(0).forceActiveFocus();
            for (let i = 0; i < 6; i++) {
                keyClick(Qt.Key_Tab);
                verify(focusList.itemAtIndex(i + 1).activeFocus);
                verify(shown(focusList, focusList.itemAtIndex(i + 1)), "row " + (i + 1) + " is hidden");
            }
            verify(focusList.contentY > focusList.originY);
        }
        function test_list_model_removal_bounds() {
            rows.clear();
            for (let i = 0; i < 30; i++) rows.append({rowHeight: 30 + i % 3 * 7});
            list.forceLayout(); list.positionViewAtEnd();
            wait(50);
            rows.remove(0, 10); list.forceLayout(); list.positionViewAtBeginning();
            compare(list.count, 20);
            const origin = list.originY;
            wheel(list, 0, -120); compare(list.contentY, origin + 120);
            wheel(list, 0, 120); compare(list.contentY, origin);
            wheel(list, 0, 120); compare(list.contentY, origin);
        }
    }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            # Load the unchanged, Qt-only component without ui/qmldir's theme:
            # Quickshell's static plugins are registered only by the qs binary.
            for name in ('WheelScroll.qml', 'ScrollListView.qml'):
                shutil.copyfile(UI / name, Path(directory, name))
            Path(directory, 'tst_wheel.qml').write_text(
                qml.replace('UI_URL', Path(directory).as_uri())
            )
            result = subprocess.run(
                [RUNNER, '-input', directory],
                text=True,
                capture_output=True,
                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'},
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


@unittest.skipUnless(support.QS, 'Quickshell is required')
class DrawerColumnTests(unittest.TestCase):
    def test_form_keeps_keyboard_focus_visible(self):
        support.run_qml(
            self,
            """import QtQuick
import QtQuick.Layouts
import QtTest
import Quickshell
import "ui"
ShellRoot {
 FloatingWindow {
  id: window
  implicitWidth: 360; implicitHeight: 200
  property real revealed: 0
  DrawerColumn {
   id: form
   anchors.fill: parent
   Repeater { id: actions; model: 8; ShellButton { required property int index; text: "Action " + index; Layout.fillWidth: true } }
   NumberField { id: minutes; from: 0; to: 59; Accessible.name: "Minutes" }
   InputField { id: note; Layout.fillWidth: true }
   RowLayout {
    id: authentication; visible: false; Layout.fillWidth: true
    InputField { id: password; Layout.fillWidth: true }
    IconButton { iconName: "x"; text: "Cancel" }
   }
   Card {
    id: camera; Layout.fillWidth: true; implicitHeight: cameraBody.implicitHeight + 24
    ColumnLayout {
     id: cameraBody; anchors.fill: parent; anchors.margins: 12
     ShellButton { text: "Test webcam"; Layout.fillWidth: true }
     Item { id: cameraPreview; visible: false; Layout.fillWidth: true; Layout.preferredHeight: 120 }
    }
   }
   Item { id: preview; Layout.fillWidth: true; Layout.preferredHeight: 80 }
  }
  TestCase { id: input; parent: window.contentItem; when: false }
 }
 property int stage: 0
 function check(value, message) { if (!value) throw new Error(message); }
 function shown(item) {
  const top = item.mapToItem(form.contentItem.contentItem, 0, 0).y, view = form.contentItem;
  return top >= view.contentY - 0.5 && top + item.height <= view.contentY + view.height + 0.5;
 }
 Timer { interval: 200; running: true; repeat: true; onTriggered: {
  try {
   const view = form.contentItem;
   if (stage === 0) {
    actions.itemAt(0).forceActiveFocus();
    for (let i = 0; i < 8; i++) input.keyClick(Qt.Key_Tab);
    // The number editor has focus; the whole field must show.
    check(minutes.contentItem.activeFocus && shown(minutes) && view.contentY > 0, "Tab left the field hidden");
    input.keyClick(Qt.Key_Tab);
    check(note.activeFocus && shown(note), "Tab left the input hidden");
    for (let i = 0; i < 9; i++) input.keyClick(Qt.Key_Backtab);
    check(actions.itemAt(0).activeFocus && view.contentY === 0, "Backtab did not return to the top");
    // A click on a partly visible control keeps it under the pointer.
    view.contentY = 20;
    input.mouseClick(actions.itemAt(0), 10, actions.itemAt(0).height - 4);
    check(actions.itemAt(0).activeFocus && view.contentY === 20, "pointer focus scrolled");
    form.wheelInput.reveal(preview);
    check(shown(preview) && view.contentY === view.contentHeight - view.height, "explicit reveal failed");
    // The column's own handler, not Qt's accelerated flick, takes the wheel.
    input.mouseWheel(form, 100, 100, 0, 120, Qt.NoButton, Qt.NoModifier, 0);
    check(view.contentY === view.contentHeight - view.height - 120, "wheel did not step the column");
    // Focus a field as it appears, before the layout has placed it.
    view.contentY = 0;
    authentication.visible = true;
    Qt.callLater(() => password.forceActiveFocus());
   } else if (stage === 1) {
    check(password.activeFocus && shown(password), "a newly shown field stayed hidden");
    view.contentY = 0;
    cameraPreview.visible = true;
    form.wheelInput.reveal(camera);
   } else if (stage === 2) {
    check(camera.height > 120 && shown(camera), "reveal used the card's height before it grew");
    input.mouseWheel(form, 100, 100, 0, 120, Qt.NoButton, Qt.NoModifier, 0);
    window.revealed = view.contentY;
   } else if (stage === 3) {
    check(view.contentY === window.revealed, "a settled reveal pulled the view back");
   } else {
    console.log("DISPLAY_PASS"); Qt.quit();
   }
   stage++;
  } catch (e) { console.error("DISPLAY_FAIL", e.message); Qt.quit(); }
 }}
}""",
        )


@unittest.skipUnless(support.QS, 'Quickshell is required')
class SpaceScrollAreaTests(unittest.TestCase):
    def test_space_scroll_area_steps_and_sizes_its_content(self):
        support.run_qml(
            self,
            """import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import "spaces/movies"
ShellRoot {
 FloatingWindow {
  id: window
  implicitWidth: 600; implicitHeight: 200
  ScrollArea {
   id: details
   width: 200; height: 200
   contentWidth: availableWidth
   ColumnLayout {
    id: column
    width: details.availableWidth
    Repeater { id: rows; model: 12; Button { required property int index; text: "Row " + index; Layout.fillWidth: true; Layout.preferredHeight: 40 } }
   }
  }
  ScrollArea {
   id: poster
   x: 200; width: 200; height: 200
   Rectangle { id: artwork; implicitWidth: 500; implicitHeight: 700 }
  }
  ScrollArea {
   id: strip
   x: 400; width: 200; height: 60
   contentHeight: height
   RowLayout { id: chips; Repeater { model: 6; Rectangle { implicitWidth: 80; implicitHeight: 40 } } }
  }
  TestCase { id: input; parent: window.contentItem; when: false }
 }
 property int stage: 0
 function check(value, message) { if (!value) throw new Error(message); }
 function shown(area, item) {
  const top = item.mapToItem(area.contentItem.contentItem, 0, 0).y, view = area.contentItem;
  return top >= view.contentY && top + item.height <= view.contentY + view.height;
 }
 Timer { interval: 200; running: true; repeat: true; onTriggered: {
  try {
   if (stage === 0) {
    // The wheel handler joins the content but must not change its size.
    check(details.contentHeight === column.implicitHeight && details.contentHeight > 400, "the column did not size the content");
    check(poster.contentWidth === 500 && poster.contentHeight === 700, "the child's implicit size was lost");
    check(strip.contentWidth === chips.implicitWidth && strip.contentHeight === 60, "an explicit size was replaced");
    artwork.implicitHeight = 900;
    check(poster.contentHeight === 900, "content size did not follow the child");
    // Qt's accelerated flick would move later and by a different distance.
    input.mouseWheel(details, 100, 100, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
    check(details.contentItem.contentY === 120, "wheel did not step the area: " + details.contentItem.contentY);
    input.mouseWheel(poster, 100, 100, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
    check(poster.contentItem.contentY === 120, "wheel did not step the implicitly sized area");
    details.contentItem.contentY = 0;
    rows.itemAt(0).forceActiveFocus();
    for (let i = 0; i < 8; i++) input.keyClick(Qt.Key_Tab);
    check(rows.itemAt(8).activeFocus && shown(details, rows.itemAt(8)), "Tab left the row hidden");
   } else {
    console.log("DISPLAY_PASS"); Qt.quit();
   }
   stage++;
  } catch (e) { console.error("DISPLAY_FAIL", e.message); Qt.quit(); }
 }}
}""",
        )
