"""Check tooltip lifecycle, click and keyboard-focus behavior with the real Quickshell helper."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


UI = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell'
    / 'symlinks/home/.config/quickshell/desktop/ui'
)
QS = shutil.which('qs')


@unittest.skipUnless(QS, 'Quickshell is required')
class PassiveToolTipTests(unittest.TestCase):
    def test_hover_keyboard_focus_click_and_dismissal(self):
        qml = """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "ui" as UI
FloatingWindow {
    id: root
    implicitWidth: 500; implicitHeight: 250
    property int stage: 0
    property int clicks: 0
    Button {
        id: button
        x: 20; y: 20; width: 70; height: 40
        text: "Open application"
        hoverEnabled: true
        focusPolicy: Qt.NoFocus
        onClicked: root.clicks++
    }
    TextField { id: field; x: 20; y: 120; width: 200; height: 40 }
    Button { id: save; x: 250; y: 120; width: 90; height: 40; text: "Save draft" }
    UI.PassiveToolTip { id: saveTip; target: save }
    UI.PassiveToolTip { id: tip; target: button }
    Text { id: info; x: 300; y: 20; width: 160; height: 40; text: "A long informational device name"; elide: Text.ElideRight }
    UI.PassiveToolTip { id: infoTip; target: info; text: info.text }
    TestCase { id: input; parent: root.contentItem; when: false }
    function check(condition, message) { if (!condition) throw new Error(message); }
    function hoverButton() {
        input.mouseMove(root.contentItem, 400, 200);
        input.mouseMove(button, 35, 20);
    }
    function label() { return tip.contentItem.children[0].children[0]; }
    Timer { interval: 1000; running: true; repeat: true; onTriggered: {
        try {
            if (stage === 0) {
                for (let i = 0; i < 100; i++) button.text = "Unhovered dynamic title " + i;
                check(label().text === "", "unhovered titles requested text layout");
                button.text = "Open application";
                field.forceActiveFocus();
                hoverButton();
                check(button.hovered && !tip.visible, "hover should wait for the delay");
            } else if (stage === 1) {
                check(tip.visible && field.activeFocus, "tooltip missing or took input focus");
                check(!tip.grabFocus && tip.mask.width === 0 && tip.mask.height === 0
                    && tip.mask.regions.length === 0, "tooltip accepts input");
                check(tip.text === "Open application", "button text was replaced");
                check(!label().truncated, "short text was elided by fractional width");
                check(label().width >= label().implicitWidth, "window rounded text width down");
                input.mouseClick(button, 35, 20);
                check(root.clicks === 1 && !tip.visible && field.activeFocus, "visible tooltip blocked click/focus");
            } else if (stage === 2) {
                // Let the offscreen platform finish unmapping the popup before
                // delivering a new pointer entry to the parent window.
                hoverButton();
                check(!tip.visible, "re-entry skipped delay");
            } else if (stage === 3) {
                check(tip.visible, "re-entry did not show tooltip");
                button.text = "Changed hint";
                check(tip.visible && label().text === "Changed hint", "dynamic title hid/staled the tooltip");
            } else if (stage === 4) {
                const title = "A long changing window title with many words and a verylongunbrokenidentifier".repeat(2);
                button.text = title;
                check(tip.visible && label().text === title, "long title did not update in place");
            } else if (stage === 5) {
                check(tip.visible, "changed hint did not reappear");
                check(label().lineCount > 1 && !label().truncated, "long title did not wrap in full");
                check(tip.width <= 496, "long title exceeded shared width limit");
                input.mouseMove(root.contentItem, 400, 200);
                check(!tip.visible, "pointer exit retained tooltip");
                button.text = "";
                check(label().text === "", "hidden tooltip retained text layout");
            } else if (stage === 6) {
                hoverButton();
                check(!tip.visible, "empty text retained tooltip");
                button.text = "Final hint";
            } else if (stage === 7) {
                check(tip.visible, "restored text did not show tooltip");
                check(!label().truncated, "restored short hint was elided");
                button.enabled = false;
                check(!tip.visible, "disabled button retained tooltip");
                button.visible = false;
                check(!tip.visible, "hidden button retained tooltip");
            } else if (stage === 8) {
                input.mouseMove(info, 40, 20);
                check(!infoTip.visible, "informational tooltip skipped delay");
            } else if (stage === 9) {
                check(infoTip.visible && field.activeFocus, "informational tooltip missing or took focus: hovered="+infoTip.hovered+", requested="+infoTip.requested+", ready="+infoTip.ready+", focus="+field.activeFocus);
                check(infoTip.text === info.text, "informational tooltip lost the full name");
                info.visible = false;
                check(!infoTip.visible, "hidden informational item retained tooltip");
                button.enabled = true;
                button.visible = true;
            } else if (stage === 10) {
                hoverButton();
            } else if (stage === 11) {
                check(tip.visible, "tooltip did not return before window dismissal");
                // Hiding a surface leaves its items visible; hover must still end.
                root.visible = false;
            } else if (stage === 12) {
                check(!tip.visible && !tip.requested, "hidden window retained tooltip");
                root.visible = true;
            } else if (stage === 13) {
                check(!tip.visible, "reshown window restored a stale tooltip");
                input.mouseMove(root.contentItem, 400, 200);
                field.forceActiveFocus();
                input.keyClick(Qt.Key_Tab);
                check(save.visualFocus && !saveTip.visible, "keyboard focus skipped the delay");
            } else if (stage === 14) {
                check(saveTip.visible && save.activeFocus, "keyboard focus did not show the tooltip");
                input.keyPress(Qt.Key_Space);
                check(!saveTip.visible, "pressed button retained the focus tooltip");
                input.keyRelease(Qt.Key_Space);
                input.keyClick(Qt.Key_Backtab);
                check(field.activeFocus && !saveTip.visible, "focus loss retained the tooltip");
                input.mouseClick(save, 20, 20);
                input.mouseMove(root.contentItem, 400, 200);
                check(save.activeFocus && !save.visualFocus, "click did not take pointer focus");
            } else if (stage === 15) {
                check(!saveTip.visible, "pointer focus showed the tooltip");
                field.forceActiveFocus();
                save.forceActiveFocus();
            } else if (stage === 16) {
                check(save.activeFocus && !saveTip.visible, "programmatic focus showed the tooltip");
                field.forceActiveFocus();
                input.keyClick(Qt.Key_Tab);
            } else if (stage === 17) {
                check(saveTip.visible, "keyboard focus tooltip did not return");
                root.visible = false;
            } else if (stage === 18) {
                check(!saveTip.visible && !saveTip.requested, "hidden window retained the focus tooltip");
                console.log("PASSIVE_TOOLTIP_PASS"); Qt.quit(); return;
            }
            stage++;
        } catch (e) { console.error("PASSIVE_TOOLTIP_FAIL", stage, e.message); Qt.quit(); }
    } }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(UI, root / 'ui')
            (root / 'shell.qml').write_text(qml)
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            (root / 'runtime').mkdir(mode=0o700)
            env = {
                **os.environ,
                'QT_QPA_PLATFORM': 'offscreen',
                'XDG_CONFIG_HOME': str(root / 'config'),
                'XDG_RUNTIME_DIR': str(root / 'runtime'),
            }
            for key in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
                env.pop(key, None)
            result = subprocess.run(
                [QS, '--no-color', '-p', str(root / 'shell.qml')],
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        log = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, log)
        self.assertIn('PASSIVE_TOOLTIP_PASS', log)
        self.assertNotIn('PASSIVE_TOOLTIP_FAIL', log)
        self.assertNotIn('TypeError', log)
