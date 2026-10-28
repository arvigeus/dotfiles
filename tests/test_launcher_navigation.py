"""Exercise the production launcher's mixed input without a live compositor."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import support

DESKTOP = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell'
    / 'symlinks/home/.config/quickshell/desktop'
)
QS = shutil.which('qs')
# Records the argv of every launch. Entries named "broken" fail the way uwsm
# reports errors on a pipe: one journal priority prefix per line.
FAKE_UWSM = """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

with open(Path(__file__).with_name('launches'), 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
if 'broken' in sys.argv[-1]:
    sys.exit(f'<3>Desktop entry not found: "{sys.argv[-1]}"\\n<3>Check the entry')
"""
PROLOGUE = """import QtQuick
import QtTest
import Quickshell
import "launcher" as App
import "ui"
ShellRoot {
    id: shell
    InteractionState { id: interactions }
    App.Launcher { id: launcher; interactionState: interactions }
    Component.onCompleted: launcher.openOn(Quickshell.screens[0])
    TestCase { id: input; parent: launcher.contentItem; when: false }
    property int stage: 0
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
"""


def entry(name):
    return f'[Desktop Entry]\nType=Application\nName={name}\nExec=/usr/bin/true\n'


@unittest.skipUnless(QS, 'Quickshell is required')
class LauncherNavigationTests(unittest.TestCase):
    def run_launcher(self, root, entries, driver, env=None):
        """Run the launcher with driver QML; return the log and uwsm argv lists."""
        for name in ('launcher', 'ui', 'icons'):
            shutil.copytree(DESKTOP / name, root / name)
        # PanelWindow has no offscreen backend. Replace only its native
        # surface/shortcut plumbing; selection, handlers, models, rows and the
        # launch command line are the unchanged production source.
        support.floating_window(root / 'ui/InteractionWindow.qml', 800, 720)
        path = root / 'launcher/Launcher.qml'
        source = re.sub(r'^    WlrLayershell\..*\n', '', path.read_text(), flags=re.M)
        source = re.sub(
            r'    GlobalShortcut \{.*?\n    \}\n', '', source, count=1, flags=re.S
        )
        path.write_text(source)
        apps = root / 'data/applications'
        for name, text in entries.items():
            (apps / name).parent.mkdir(parents=True, exist_ok=True)
            (apps / name).write_text(text)
        stubs = root / 'bin'
        stubs.mkdir()
        (stubs / 'uwsm').write_text(FAKE_UWSM)
        (stubs / 'uwsm').chmod(0o755)
        (root / 'shell.qml').write_text(PROLOGUE + driver + '}\n')
        config = root / 'config/quickshell/desktop'
        config.mkdir(parents=True)
        (config / 'theme-mode').write_text('dark\n')
        env = {
            **os.environ,
            'PATH': f'{stubs}{os.pathsep}{os.environ.get("PATH", "")}',
            'QT_QPA_PLATFORM': 'offscreen',
            'XDG_CONFIG_HOME': str(root / 'config'),
            'XDG_DATA_HOME': str(root / 'data'),
            'XDG_DATA_DIRS': str(root / 'empty'),
            **(env or {}),
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
        self.assertNotIn('NAVIGATION_FAIL', log)
        self.assertNotIn('TypeError', log)
        record = stubs / 'launches'
        lines = record.read_text().splitlines() if record.exists() else []
        return log, [json.loads(line) for line in lines]

    def test_pointer_keyboard_scroll_and_activation_share_one_target(self):
        with tempfile.TemporaryDirectory() as directory:
            entries = {f'item{i:02}.desktop': entry(f'Item {i:02}') for i in range(35)}
            log, launches = self.run_launcher(
                Path(directory),
                entries,
                """
    property int pointerIndex: -1
    property string favoriteId: ""
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
""",
            )
            passed = re.search(r'NAVIGATION_PASS (item\d+)', log)
            self.assertIsNotNone(passed, log)
            self.assertEqual(
                launches, [['app', '-t', 'service', '--', passed[1] + '.desktop']]
            )

    def test_refresh_typed_enter_unusual_ids_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apps = root / 'data/applications'
            names = ('Alpha', 'Beta', 'Zeta', 'Hollow Knight', 'Other')
            entries = {f'{name.lower()}.desktop': entry(name) for name in names}
            entries['Hollow Knight.desktop'] = entries.pop('hollow knight.desktop')
            entries['other-broken.desktop'] = entries.pop('other.desktop')
            entries['broken.desktop'] = entry('Broken %1 app')
            entries['wine/Programs/Notepad++/Notepad++.desktop'] = entry('Notepad++')
            pending = root / 'pending/aaa.desktop'
            pending.parent.mkdir()
            pending.write_text(entry('Aaa'))
            log, launches = self.run_launcher(
                root,
                entries,
                """
    property string kept: ""
    // Typing and Enter in one event-loop turn arrive before the debounce.
    function submit(query) {
        for (const c of query) input.keyClick(c);
        input.keyClick(Qt.Key_Return);
    }
    function settled() { return !launcher.launching || retries++ > 50; }
    Timer { interval: 100; running: true; repeat: true; onTriggered: {
        try {
            const view = find(launcher.contentItem, "applicationResults");
            const field = find(launcher.contentItem, "applicationSearch");
            if (stage === 0) {
                check(view.count === 7 && view.currentIndex === 0, "initial selection");
                field.forceActiveFocus();
                input.keyClick(Qt.Key_Down); input.keyClick(Qt.Key_Down);
                kept = view.currentItem.modelData.id;
                check(view.currentIndex === 2 && kept === "broken", "keyboard selection");
                // A newly installed entry sorts first and rebuilds the results.
                Quickshell.execDetached(["mv", Quickshell.env("PENDING_ENTRY"), Quickshell.env("XDG_DATA_HOME") + "/applications/"]);
            } else if (stage === 1) {
                if (view.count !== 8 && retries++ < 50) return;
                check(view.count === 8, "catalogue did not refresh");
            } else if (stage === 2) {
                check(view.currentIndex === 3 && view.currentItem.modelData.id === kept, "catalogue refresh moved the Enter target"); oneHighlight(view);
                submit("zeta");
            } else if (stage === 3) {
                if (!settled()) return;
                check(!launcher.opened, "typed Enter did not launch");
                launcher.openOn(Quickshell.screens[0]);
            } else if (stage === 4) {
                field.forceActiveFocus(); submit("hollow");
            } else if (stage === 5) {
                if (!settled()) return;
                check(!launcher.opened, "entry ID with a space did not launch");
                launcher.openOn(Quickshell.screens[0]);
            } else if (stage === 6) {
                field.forceActiveFocus(); submit("notepad");
            } else if (stage === 7) {
                if (!settled()) return;
                check(!launcher.opened, "nested entry ID with + did not launch");
                launcher.openOn(Quickshell.screens[0]);
            } else if (stage === 8) {
                field.forceActiveFocus(); submit("broken");
            } else if (stage === 9) {
                if (!settled()) return;
                check(launcher.opened && launcher.errorMessage === 'Could not open Broken %1 app. Desktop entry not found: "broken.desktop"\\nCheck the entry',
                    "unexpected error: " + launcher.errorMessage);
                input.keyClick(Qt.Key_A, Qt.ControlModifier);
                submit("other");
            } else if (stage === 10) {
                if (!settled()) return;
                check(launcher.opened && launcher.errorMessage === 'Could not open Other. Desktop entry not found: "other-broken.desktop"\\nCheck the entry',
                    "stale or missing error: " + launcher.errorMessage);
                console.log("NAVIGATION_PASS"); Qt.quit(); return;
            }
            retries = 0;
            stage++;
        } catch (e) { console.error("NAVIGATION_FAIL", stage, e.message); Qt.quit(); }
    } }
""",
                env={'PENDING_ENTRY': str(pending)},
            )
            self.assertIn('NAVIGATION_PASS', log)
            prefix = ['app', '-t', 'service', '--']
            self.assertEqual(
                launches,
                [
                    prefix + ['zeta.desktop'],
                    prefix + [str(apps / 'Hollow Knight.desktop')],
                    prefix + [str(apps / 'wine/Programs/Notepad++/Notepad++.desktop')],
                    prefix + ['broken.desktop'],
                    prefix + ['other-broken.desktop'],
                ],
            )
