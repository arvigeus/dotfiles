"""Independent editor and profile restoration, using isolated displays and helper."""

import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from support import REPO, backend, described, display, load, state

ui = load(
    'display_arrangement_ui',
    REPO
    / 'modules/desktop/quickshell/files/usr/local/lib/display-tools/display_gui.py',
)


class EditorCases:
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = self.root / 'state.json'
        self.log = self.root / 'requests.jsonl'
        self.current = state([display(), described('DP-1', 'Dell external', x=1920)])
        self.fixture.write_text(json.dumps(self.current))
        self.helper = self.root / 'helper.py'
        self.helper.write_text(
            'import json,sys,time\n'
            f'from pathlib import Path\np=Path({str(self.fixture)!r})\n'
            f'log=Path({str(self.log)!r})\n'
            'r=json.loads(sys.stdin.readline())\n'
            'with log.open("a") as f:f.write(json.dumps(r)+"\\n")\n'
            's=json.loads(p.read_text())\n'
            'if r["op"]=="arrange":\n'
            ' for row in s["displays"]:row.update(r["positions"].get(row["name"],{}))\n'
            ' s["token"]="applied"\n'
            ' p.write_text(json.dumps(s))\n'
            'time.sleep(.08)\n'
            'print(json.dumps(dict(ok=True,data=s)))\n'
        )
        self.window = ui.DisplayArrangement(auto_load=False, helper=self.helper)
        self.window.show()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.process.kill()
        self.window.process.waitForFinished(1000)
        self.window.baseline = None
        self.window.items = {}
        self.window.mode = ''
        self.window.close()

    def wait_idle(self):
        until = time.monotonic() + 4
        while self.window.mode and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertFalse(self.window.mode, self.window.status.text())

    def test_logical_geometry_selection_keyboard_and_coordinates(self):
        rows = [display(scale=1.25, transform=1), described('DP-1', 'External', x=864)]
        self.window.load_state(state(rows))
        item = self.window.items['eDP-1']
        self.assertEqual((item.box.width(), item.box.height()), (864, 1536))
        self.assertFalse(self.window.dirty())
        self.window.x.setValue(-100)
        self.assertEqual(item.pos(), QPointF(-100, 0))
        self.assertTrue(self.window.apply.isEnabled())
        self.window.view.setFocus()
        item.setFocus()
        QTest.keyClick(
            self.window.view.viewport(),
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.ShiftModifier,
        )
        self.assertEqual(item.pos().x(), -110)
        self.assertEqual(self.window.x.value(), -110)

    def test_apply_is_async_and_saves_without_a_second_action(self):
        self.window.refresh()
        self.wait_idle()
        self.window.x.setValue(-1920)
        self.window.apply_arrangement()
        self.assertEqual(self.window.mode, 'arrange')
        self.assertFalse(self.window.close_button.isEnabled())
        self.wait_idle()
        requests = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(
            requests[-1],
            dict(
                op='arrange',
                token=self.current['token'],
                positions={'eDP-1': {'x': -1920, 'y': 0}, 'DP-1': {'x': 1920, 'y': 0}},
            ),
        )
        self.assertFalse(self.window.dirty())
        self.assertIn('saved for these connected displays', self.window.status.text())

    def test_drag_snaps_edges_and_shift_allows_precise_gaps(self):
        self.window.load_state(self.current)
        self.app.processEvents()
        item = self.window.items['DP-1']
        viewport = self.window.view.viewport()

        def move(point, modifiers=Qt.KeyboardModifier.NoModifier):
            event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(point),
                QPointF(viewport.mapToGlobal(point)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                modifiers,
            )
            QApplication.sendEvent(viewport, event)

        start = self.window.view.mapFromScene(item.sceneBoundingRect().center())
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        move(start + QPoint(-60, 0))
        self.assertLess(item.pos().x(), 1920)
        move(start + QPoint(5, 0))
        QTest.mouseRelease(
            viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(5, 0)
        )
        self.assertEqual(item.pos().x(), 1920)
        start = self.window.view.mapFromScene(item.sceneBoundingRect().center())
        QTest.mousePress(
            viewport,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            pos=start,
        )
        QTest.keyPress(viewport, Qt.Key.Key_Shift)
        move(start + QPoint(60, 0), Qt.KeyboardModifier.ShiftModifier)
        move(start + QPoint(5, 0), Qt.KeyboardModifier.ShiftModifier)
        QTest.mouseRelease(
            viewport,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier,
            pos=start + QPoint(5, 0),
        )
        QTest.keyRelease(viewport, Qt.Key.Key_Shift)
        self.assertGreater(item.pos().x(), 1920)

    def test_external_change_keeps_draft_but_blocks_stale_apply(self):
        self.window.load_state(self.current)
        self.window.x.setValue(-1920)
        changed = state([display()])
        self.fixture.write_text(json.dumps(changed))
        self.window.refresh()
        self.wait_idle()
        self.assertTrue(self.window.stale)
        self.assertFalse(self.window.apply.isEnabled())
        self.assertEqual(self.window.items['eDP-1'].pos().x(), -1920)
        self.assertIn('Reload', self.window.status.text())

    def test_clean_external_change_reconciles_inventory(self):
        self.window.load_state(self.current)
        self.fixture.write_text(json.dumps(state([display()])))
        self.window.refresh()
        self.wait_idle()
        self.assertEqual(set(self.window.items), {'eDP-1'})
        self.assertFalse(self.window.stale)

    def test_discard_confirmation_closes_and_no_keeps_edits_for_every_close_path(self):
        for trigger in ('button', 'window', 'escape'):
            with self.subTest(trigger=trigger):
                self.window.show()
                self.window.load_state(self.current)
                self.window.x.setValue(-1920)
                confirmations = []

                def respond(answer):
                    dialog = self.app.activeModalWidget()
                    if isinstance(dialog, QMessageBox):
                        confirmations.append(dialog.text())
                        QTest.mouseClick(
                            dialog.button(answer), Qt.MouseButton.LeftButton
                        )

                def close_with(answer):
                    QTimer.singleShot(0, lambda: respond(answer))
                    if trigger == 'button':
                        QTest.mouseClick(
                            self.window.close_button, Qt.MouseButton.LeftButton
                        )
                    elif trigger == 'window':
                        self.window.close()
                    else:
                        QTest.keyClick(self.window, Qt.Key.Key_Escape)
                    self.app.processEvents()

                close_with(QMessageBox.StandardButton.No)
                self.assertTrue(self.window.isVisible())
                self.assertTrue(self.window.dirty())
                self.assertEqual(self.window.items['eDP-1'].pos().x(), -1920)
                close_with(QMessageBox.StandardButton.Yes)
                self.assertFalse(self.window.isVisible())
                self.assertEqual(self.window.result(), ui.QDialog.DialogCode.Rejected)
                self.assertEqual(
                    confirmations, ['Close without applying your position edits?'] * 2
                )
                self.assertFalse(self.log.exists(), 'Discard sent a helper request')
                self.assertEqual(json.loads(self.fixture.read_text()), self.current)

    def test_close_without_edits_does_not_prompt(self):
        self.window.load_state(self.current)
        with patch.object(QMessageBox, 'question') as question:
            QTest.mouseClick(self.window.close_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.window.isVisible())
        question.assert_not_called()


class ProfileRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        environment = patch.dict(os.environ, XDG_CONFIG_HOME=self.temporary.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.panel = described('eDP-1', 'Laptop panel')
        self.dell = described('DP-1', 'Dell', x=1920)

    def test_restore_exact_set_and_unknown_set_never_learns_transient_layouts(self):
        docked = state([dict(self.panel, enabled=False), self.dell])
        backend.persist(docked, False)
        saved = backend.profiles_path().read_text()
        current = state([self.panel, self.dell])
        with patch.object(backend, 'apply_setup', return_value=docked) as apply:
            backend.ensure(current)
        self.assertFalse(apply.call_args.args[0][0]['enabled'])
        with patch.object(backend, 'apply_setup') as apply:
            backend.ensure(state([self.panel]))
            backend.ensure(state([self.panel, dict(self.dell, dpms=False)]))
        apply.assert_not_called()
        self.assertEqual(backend.profiles_path().read_text(), saved)

    def test_unsupported_saved_mode_preserves_source_and_does_not_apply(self):
        backend.persist(state([self.panel]), False)
        current = state(
            [dict(self.panel, modes=['1280x720@60.00Hz'], mode='1280x720@60.00Hz')]
        )
        saved = backend.profiles_path().read_text()
        with (
            patch.object(backend, 'apply_setup') as apply,
            self.assertRaisesRegex(ValueError, 'no longer available'),
        ):
            backend.ensure(current)
        apply.assert_not_called()
        self.assertEqual(backend.profiles_path().read_text(), saved)

    def test_shell_and_editor_lock_serializes_independent_processes(self):
        root = Path(self.temporary.name)
        log = root / 'lock-events'
        script = root / 'lock.py'
        script.write_text(
            'import sys,time\n'
            f'sys.path.insert(0,{str(REPO / "tests")!r})\n'
            'from support import backend\n'
            f'from pathlib import Path\nlog=Path({str(log)!r})\n'
            'with backend.control_lock():\n'
            ' with log.open("a") as f:f.write("enter\\n")\n'
            ' time.sleep(.1)\n'
            ' with log.open("a") as f:f.write("exit\\n")\n'
        )
        env = dict(
            os.environ,
            XDG_RUNTIME_DIR=str(root),
            HYPRLAND_INSTANCE_SIGNATURE='isolated-display-test',
        )
        processes = [
            subprocess.Popen([sys.executable, str(script)], env=env) for _ in range(2)
        ]
        for process in processes:
            self.assertEqual(process.wait(timeout=4), 0)
        self.assertEqual(
            log.read_text().splitlines(), ['enter', 'exit', 'enter', 'exit']
        )

    def test_corrupt_profiles_are_not_overwritten_by_an_edit(self):
        path = backend.profiles_path()
        path.parent.mkdir(parents=True)
        path.write_text('{broken')
        with self.assertRaises(ValueError):
            backend.persist(state([self.panel]), False)
        self.assertEqual(path.read_text(), '{broken')

    def test_powersave_arrangement_retains_uncapped_preference(self):
        panel = dict(self.panel, mode='1920x1080@120.00Hz')
        backend.persist(state([panel]), False)
        capped = state([dict(panel, mode='1920x1080@60.00Hz', x=100)])
        backend.persist(capped, True)
        self.assertEqual(backend.profile_rows(capped)[0]['mode'], '1920x1080@120.00Hz')
        saved = backend.profiles_path().read_text()
        with patch.object(backend, 'apply_setup') as apply:
            backend.ensure(capped, True)
        apply.assert_not_called()
        self.assertEqual(backend.profiles_path().read_text(), saved)


class ArrangementUiTests(unittest.TestCase):
    def test_native_editor_interactions_in_an_isolated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            env = dict(
                os.environ,
                QT_QPA_PLATFORM='offscreen',
                XDG_RUNTIME_DIR=str(runtime),
                XDG_CONFIG_HOME=str(root / 'config'),
                XDG_STATE_HOME=str(root / 'state'),
                XDG_DATA_HOME=str(root / 'data'),
                PIPEWIRE_REMOTE='dotfiles-tests-unavailable',
            )
            env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
            env.pop('WAYLAND_DISPLAY', None)
            result = subprocess.run(
                [sys.executable, __file__, '--ui-child'],
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    if '--ui-child' in sys.argv:

        class NativeEditorTests(EditorCases, unittest.TestCase):
            pass

        unittest.main(argv=[sys.argv[0], 'NativeEditorTests', '-v'])
    else:
        unittest.main()
