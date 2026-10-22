"""Exercise the production launcher's mixed input without a live compositor."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


DESKTOP = (Path(__file__).resolve().parents[1] / 'modules/desktop/quickshell'
           / 'symlinks/home/.config/quickshell/desktop')
QS = shutil.which('qs')


@unittest.skipUnless(QS, 'Quickshell is required')
class LauncherNavigationTests(unittest.TestCase):
    def test_pointer_keyboard_scroll_and_activation_share_one_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('launcher', 'ui', 'icons'):
                shutil.copytree(DESKTOP / name, root / name)
            # PanelWindow has no offscreen backend. Replace only its native
            # surface/shortcut plumbing; selection, handlers, models and rows
            # are the unchanged production source running inside Quickshell.
            path = root / 'ui/InteractionWindow.qml'
            source = path.read_text().replace(
                'PanelWindow {', 'FloatingWindow {\n    implicitWidth: 800; implicitHeight: 720', 1)
            source = source.replace('    anchors { top: true; bottom: true; left: true; right: true }\n', '')
            source = source.replace('    exclusionMode: ExclusionMode.Ignore\n', '')
            source = re.sub(r'^    WlrLayershell\..*\n', '', source, flags=re.M)
            path.write_text(source)
            path = root / 'launcher/Launcher.qml'
            source = path.read_text()
            source = re.sub(r'^    WlrLayershell\..*\n', '', source, flags=re.M)
            source = re.sub(r'    GlobalShortcut \{.*?\n    \}\n', '', source, count=1, flags=re.S)
            # The activation fixture records the actual ID passed by activate().
            source = source.replace('["uwsm", "app", "-t", "service", "--", entry.id + ".desktop"]',
                                    '["/usr/bin/python3", Quickshell.env("LAUNCH_FIXTURE"), "--", entry.id]')
            path.write_text(source)
            apps = root / 'data/applications'
            apps.mkdir(parents=True)
            for i in range(35):
                (apps / f'item{i:02}.desktop').write_text(
                    f'[Desktop Entry]\nType=Application\nName=Item {i:02}\nExec=/usr/bin/true\n')
            fixture = root / 'launch.py'
            fixture.write_text('from pathlib import Path\nimport sys\n'
                               'Path(__file__).with_name("launched-id").write_text(sys.argv[-1])\n')
            (root / 'shell.qml').write_text('''import QtQuick
import QtTest
import Quickshell
import "launcher" as App
import "ui"
ShellRoot {
    InteractionState { id: interactions }
    App.Launcher { id: launcher; interactionState: interactions }
    Component.onCompleted: launcher.openOn(Quickshell.screens[0])
    TestCase { id: input; parent: launcher.contentItem; when: false }
    property int stage: 0
    property int pointerIndex: -1
    property string favoriteId: ""
    property int retries: 0
    function check(condition, message) { if (!condition) throw new Error(message); }
    function find(obj, name) {
        if (obj.objectName === name) return obj;
        for (const child of obj.children || []) { const result = find(child, name); if (result) return result; }
        return null;
    }
    function oneHighlight(view) {
        const rows = Array.from(view.contentItem.children).filter(c => c.rowHighlighted !== undefined);
        check(rows.filter(c => c.rowHighlighted).length === 1, "not exactly one highlighted row");
        check(view.currentItem.rowHighlighted, "Enter target is not highlighted");
    }
    Timer { interval: 100; running: true; repeat: true; onTriggered: {
        try {
            const view = find(launcher.contentItem, "applicationResults");
            const field = find(launcher.contentItem, "applicationSearch");
            if (stage === 0) {
                check(view.count === 35 && view.currentIndex === 0, "initial selection"); oneHighlight(view);
                field.forceActiveFocus(); input.mouseMove(field, 30, 20);
            } else if (stage === 1) {
                input.mouseMove(view.itemAtIndex(3), 120, 27);
                check(view.currentIndex === 3, "pointer movement did not select hovered row"); oneHighlight(view);
            } else if (stage === 2) {
                input.keyClick(Qt.Key_Down);
                check(view.currentIndex === 4, "Down did not follow hovered row"); oneHighlight(view);
            } else if (stage === 3) {
                for (let i = 0; i < 22; i++) input.keyClick(Qt.Key_Down);
                check(view.currentIndex === 26 && view.contentY > view.originY, "keyboard scrolling lost target"); oneHighlight(view);
            } else if (stage === 4) {
                check(view.currentIndex === 26, "deferred layout/hover stole keyboard target");
                const local = view.mapFromItem(launcher.contentItem, launcher.lastPointerPosition.x, launcher.lastPointerPosition.y);
                const before = view.contentY;
                input.mouseWheel(view, local.x, local.y, 0, -120, Qt.NoButton, Qt.NoModifier, 0);
                check(view.contentY > before && view.currentIndex === 26, "wheel changed selection or failed to scroll");
            } else if (stage === 5) {
                check(view.currentIndex === 26, "wheel's deferred hover changed selection");
                let y = view.height / 3;
                while ((pointerIndex = view.indexAt(120, view.contentY + y)) < 0 && y < view.height) y++;
                const row = view.itemAtIndex(pointerIndex);
                input.mouseMove(row, 120, row.height / 2);
                check(pointerIndex !== 26 && view.currentIndex === pointerIndex, "real motion did not resume pointer selection"); oneHighlight(view);
            } else if (stage === 6) {
                input.keyClick(Qt.Key_Down);
                check(view.currentIndex === pointerIndex + 1, "keyboard takeover after scrolling"); oneHighlight(view);
                const scrollbar = view.children.find(c => c.size !== undefined && c.position !== undefined);
                input.mouseMove(scrollbar, scrollbar.width / 2, scrollbar.height / 2);
                check(view.currentIndex === pointerIndex + 1, "scrollbar hover selected a row behind it");
            } else if (stage === 7) {
                const row = view.itemAtIndex(view.currentIndex + 1);
                favoriteId = row.modelData.id;
                const star = find(row, "favorite-" + favoriteId);
                input.mouseMove(star, star.width / 2, star.height / 2);
                check(view.currentIndex === row.index, "star hover did not select its row");
                input.mouseClick(star, star.width / 2, star.height / 2);
                check(launcher.opened && !launcher.launching && field.activeFocus, "star changed focus or launched");
            } else if (stage === 8) {
                check(view.currentIndex === 0 && view.currentItem.modelData.id === favoriteId, "favorite reorder lost selected ID"); oneHighlight(view);
                input.keyClick(Qt.Key_Return);
            } else {
                if (launcher.launching && retries++ < 30) return;
                check(!launcher.opened && !launcher.launching, "Enter did not activate/dismiss");
                console.log("NAVIGATION_PASS", favoriteId); Qt.quit(); return;
            }
            stage++;
        } catch (e) { console.error("NAVIGATION_FAIL", stage, e.message); Qt.quit(); }
    } }
}
''')
            config = root / 'config/quickshell/desktop'
            config.mkdir(parents=True)
            (config / 'theme-mode').write_text('dark\n')
            env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
                   'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_DATA_HOME': str(root / 'data'),
                   'XDG_DATA_DIRS': str(root / 'empty'), 'LAUNCH_FIXTURE': str(fixture)}
            for key in ('WAYLAND_DISPLAY', 'HYPRLAND_INSTANCE_SIGNATURE'):
                env.pop(key, None)
            result = subprocess.run([QS, '--no-color', '-p', str(root / 'shell.qml')],
                                    env=env, text=True, capture_output=True, timeout=15)
            log = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, log)
            self.assertNotIn('NAVIGATION_FAIL', log)
            self.assertNotIn('TypeError', log)
            passed = re.search(r'NAVIGATION_PASS (item\d+)', log)
            self.assertIsNotNone(passed, log)
            self.assertEqual((root / 'launched-id').read_text(), passed[1])
