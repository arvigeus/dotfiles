"""Account tools use isolated services and never modify a real account."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

LIB = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/quickshell/files/usr/local/lib/account-tools'
)
SPEC = importlib.util.spec_from_file_location('account_core', LIB / 'account_core.py')
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class AccountTests(unittest.TestCase):
    def test_snapshot_groups_and_service_failure_preserve_local_details(self):
        account = SimpleNamespace(
            pw_uid=1234,
            pw_gid=100,
            pw_name='alice',
            pw_gecos='Alice,Room',
            pw_dir='/nonexistent',
            pw_shell='/bin/bash',
        )
        with (
            patch.object(core.os, 'getgrouplist', return_value=[100, 200, 100]),
            patch.object(
                core.grp,
                'getgrgid',
                side_effect=lambda gid: SimpleNamespace(
                    gr_name={100: 'users', 200: 'wheel'}[gid]
                ),
            ),
        ):

            def unavailable(uid):
                raise OSError('offline')

            data = core.snapshot(account, unavailable)
        self.assertEqual(data['fields']['RealName'], 'Alice')
        self.assertEqual(data['shell'], '/bin/bash')
        self.assertEqual(
            data['groups'],
            [
                dict(name='users', gid=100, primary=True),
                dict(name='wheel', gid=200, primary=False),
            ],
        )
        self.assertFalse(data['available'])
        self.assertIn('offline', data['error'])

    def test_only_current_uid_and_allowed_fields_are_written(self):
        calls = []

        class Service:
            def __init__(self, uid):
                calls.append(uid)

            def set(self, key, value):
                calls.append((key, value))

        result = core.save({'RealName': 'Alice', 'Email': 'alice@example.org'}, Service)
        self.assertEqual(
            calls, [os.getuid(), ('RealName', 'Alice'), ('Email', 'alice@example.org')]
        )
        self.assertEqual(
            result,
            dict(saved={'RealName': 'Alice', 'Email': 'alice@example.org'}, error=''),
        )
        for changes in [
            {'Shell': '/bin/zsh'},
            {'uid': '0'},
            {'RealName': 'x\x00y'},
            {'Email': 3},
            [],
            {'IconFile': 'relative.png'},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                core.save(changes, Service)
        self.assertEqual(len(calls), 3)

    def test_partial_save_reports_successful_fields(self):
        class Service:
            def __init__(self, uid):
                pass

            def set(self, key, value):
                if key == 'Email':
                    raise PermissionError('denied')

        result = core.save(
            {'RealName': 'Saved', 'Email': 'unsaved', 'Location': 'untouched'}, Service
        )
        self.assertEqual(result['saved'], {'RealName': 'Saved'})
        self.assertIn('Email', result['error'])
        self.assertIn('denied', result['error'])

    def test_real_dialog_drafts_photo_and_async_dispatch(self):
        script = """
import json, tempfile, time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QProcess
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox
from account_gui import AccountTools
app=QApplication([]); w=AccountTools(auto_load=False); w.show()
data=dict(available=True,error='',username='alice',uid=1000,gid=100,home='/home/alice',shell='/bin/bash',
 fields=dict(RealName='<Alice>',Email='',Location='',IconFile=''),
 groups=[dict(name='wheel',gid=10,primary=False)],details=dict(AccountType=1,Locked=False))
w.loaded(data); app.processEvents()
assert w.fields['RealName'].text()=='<Alice>' and not w.save.isEnabled()
assert w.groups.topLevelItem(0).text(0)=='wheel'
w.fields['Email'].setText('new@example.org'); assert w.save.isEnabled()
with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
 w.refresh(); assert w.mode=='' and w.fields['Email'].text()=='new@example.org'
w.discard_edits(); assert not w.changes()
with tempfile.TemporaryDirectory() as directory:
 path=str(Path(directory)/'portrait.jpg'); image=QImage(800,600,QImage.Format.Format_RGB32);image.fill(0xff334455);assert image.save(path)
 with patch('account_gui.QFileDialog.getOpenFileName',return_value=(path,'')):
  w.photo.click()
 assert w.changes().keys()=={'IconFile'}
 assert QImage(w.photo_path).size().width()==512
 first_photo=w.photo_path
 w.discard_edits(); assert not w.changes() and Path(first_photo).exists()
# Patch only process start; the real UI serializes a narrow changed-fields request.
w.fields['Location'].setText('Somewhere')
with patch.object(w.process,'start') as start, patch.object(w.process,'write') as write, patch.object(w.process,'closeWriteChannel'):
 w.save_profile()
 assert start.call_args.args[1][-1]=='--save'
 assert json.loads(write.call_args.args[0])=={'Location':'Somewhere'}
 assert w.mode=='save' and not w.save.isEnabled()
 w.close(); assert w.isVisible()
w.mode='';w.discard_edits()
# Exercise the asynchronous completion path with a harmless isolated helper.
with tempfile.TemporaryDirectory() as directory:
 helper=Path(directory)/'response.py'
 helper.write_text('import json; print(json.dumps('+repr(data)+'))')
 w.mode='load'
 import sys
 w.process.start(sys.executable,[str(helper)])
 deadline=time.monotonic()+5
 while w.mode:
  app.processEvents()
  assert time.monotonic()<deadline
 assert w.username.text()=='@alice'
# A partial save clears only fields the helper actually saved.
w.fields['RealName'].setText('Saved name'); w.fields['Email'].setText('keep draft')
with tempfile.TemporaryDirectory() as directory:
 helper=Path(directory)/'response.py'
 helper.write_text('import json; print(json.dumps('+repr(dict(saved={'RealName':'Saved name'},error='Email denied'))+'))')
 w.mode='save'; w.process.start(sys.executable,[str(helper)])
 deadline=time.monotonic()+5
 while w.mode:
  app.processEvents()
  assert time.monotonic()<deadline
 assert w.changes()=={'Email':'keep draft'}
 assert w.status.text()=='Email denied' and w.save.isEnabled()
w.discard_edits()
# Editing failures leave read-only account information usable.
w.loaded(dict(data,available=False,error='offline'))
assert not w.fields['RealName'].isEnabled() and not w.photo.isEnabled()
assert w.details.topLevelItemCount()>0 and w.tabs.isEnabled()
w.close(); assert not Path(first_photo).exists()
"""
        result = subprocess.run(
            [sys.executable, '-c', script],
            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(LIB)),
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
