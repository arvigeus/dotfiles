"""Exercise shared scrolling through Qt input delivery and native view geometry."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

UI = (Path(__file__).resolve().parents[1] / 'modules/desktop/quickshell'
      / 'symlinks/home/.config/quickshell/desktop/ui')
RUNNER = shutil.which('qmltestrunner6')
if not RUNNER and Path('/usr/lib/qt6/bin/qmltestrunner').is_file():
    RUNNER = '/usr/lib/qt6/bin/qmltestrunner'


@unittest.skipUnless(RUNNER, 'Qt 6 Quick Test is required')
class WheelScrollTests(unittest.TestCase):
    def test_wheel_input_and_native_views(self):
        qml = r'''
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
'''
        with tempfile.TemporaryDirectory() as directory:
            # Load the unchanged, Qt-only component without ui/qmldir's theme:
            # Quickshell's static plugins are registered only by the qs binary.
            for name in ('WheelScroll.qml', 'ScrollListView.qml'):
                shutil.copyfile(UI / name, Path(directory, name))
            Path(directory, 'tst_wheel.qml').write_text(
                qml.replace('UI_URL', Path(directory).as_uri()))
            result = subprocess.run(
                [RUNNER, '-input', directory], text=True, capture_output=True,
                env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
