"""Account tools use isolated services and never modify a real account."""

import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import support

LIB = support.REPO / 'modules/desktop/quickshell/files/usr/local/lib/account-tools'
core = support.load('account_core', LIB / 'account_core.py')
FIXTURE = Path(__file__).parent / 'fixtures/accounts_service.py'
USER = f'/org/freedesktop/Accounts/User{os.getuid()}'
PROFILE = dict(
    RealName='<b>Fixture</b> User',
    Email='fixture@example.org',
    Location='Lab',
    IconFile='/var/lib/AccountsService/icons/fixture',
    AccountType=1,
    Locked=False,
    PasswordMode=0,
)


def setUpModule():
    # In-process tests inject fakes. The real adapter would reach the session's
    # system bus, where polkit lets the current user change their own profile.
    guard = patch.object(
        core.Accounts, '__init__', side_effect=AssertionError('real AccountsService')
    )
    guard.start()
    unittest.addModuleCleanup(guard.stop)


@contextlib.contextmanager
def accounts_service(root, fail=None):
    """Yield an environment whose buses reach only a fake AccountsService, and its calls."""
    (root / 'icons').mkdir()
    state = root / 'state.json'
    state.write_text(
        json.dumps(dict(properties=PROFILE, icons=str(root / 'icons'), fail=fail or {}))
    )
    log = root / 'calls.jsonl'
    log.touch()
    service = subprocess.Popen(
        [*support.private_bus(root), sys.executable, '-B', FIXTURE, state, log],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        address = service.stdout.readline().strip()
        if not address:
            raise AssertionError('The fake AccountsService did not start.')
        env = dict(
            os.environ,
            DBUS_SYSTEM_BUS_ADDRESS=address,
            DBUS_SESSION_BUS_ADDRESS=address,
            PYTHONDONTWRITEBYTECODE='1',
        )
        yield env, lambda: [json.loads(line) for line in log.read_text().splitlines()]
    finally:
        service.stdin.close()
        service.wait(timeout=10)
        service.stdout.close()


def helper(env, *args, request=None):
    result = subprocess.run(
        [sys.executable, LIB / 'account_core.py', *args],
        input='' if request is None else json.dumps(request),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which('dbus-run-session'), 'dbus-run-session is required')
class AccountServiceTests(unittest.TestCase):
    def test_helper_reads_and_writes_only_the_current_user(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            accounts_service(Path(directory)) as (env, calls),
        ):
            snapshot = helper(env)
            self.assertTrue(snapshot['available'], snapshot['error'])
            self.assertEqual(snapshot['uid'], os.getuid())
            self.assertEqual(
                snapshot['fields'],
                {
                    key: PROFILE[key]
                    for key in ('RealName', 'Email', 'Location', 'IconFile')
                },
            )
            self.assertEqual(
                snapshot['details'], dict(AccountType=1, Locked=False, PasswordMode=0)
            )
            changes = {'RealName': 'New Name', 'Location': 'Home'}
            self.assertEqual(
                helper(env, '--save', request=changes), dict(saved=changes, error='')
            )
            self.assertEqual(helper(env)['fields']['Location'], 'Home')
            # The whole request is validated before connecting to AccountsService.
            self.assertEqual(
                helper(env, '--save', request={'RealName': 'x', 'Shell': '/bin/sh'}),
                dict(error='Invalid profile changes.', saved={}),
            )
            lookup = ('FindUserById', '/org/freedesktop/Accounts', os.getuid(), False)
            self.assertEqual(
                [
                    (call['method'], call['path'], call['value'], call['interactive'])
                    for call in calls()
                ],
                [
                    lookup,
                    lookup,
                    ('SetRealName', USER, 'New Name', True),
                    ('SetLocation', USER, 'Home', True),
                    lookup,
                ],
            )

    def test_helper_stops_at_a_denied_field_and_reports_it_plainly(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            accounts_service(Path(directory), {'SetEmail': 'Not authorized'}) as (
                env,
                calls,
            ),
        ):
            result = helper(
                env,
                '--save',
                request={'RealName': 'Saved', 'Email': 'denied', 'Location': 'Later'},
            )
            self.assertEqual(
                result,
                dict(
                    saved={'RealName': 'Saved'},
                    error='Could not save email: Not authorized',
                ),
            )
            self.assertEqual(
                [call['method'] for call in calls()],
                ['FindUserById', 'SetRealName', 'SetEmail'],
            )

    def test_helper_without_accounts_service_keeps_local_details(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(
                os.environ,
                DBUS_SYSTEM_BUS_ADDRESS=f'unix:path={directory}/missing',
                PYTHONDONTWRITEBYTECODE='1',
            )
            snapshot = helper(env)
            self.assertFalse(snapshot['available'])
            self.assertTrue(snapshot['error'])
            self.assertNotIn('error-quark', snapshot['error'])
            self.assertEqual(snapshot['uid'], os.getuid())
            self.assertTrue(snapshot['groups'])
            result = helper(env, '--save', request={'Location': 'Nowhere'})
            self.assertEqual(result['saved'], {})
            self.assertTrue(result['error'])

    def test_dialog_edits_through_the_helper_and_keeps_failed_drafts(self):
        script = """
import json, time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox
from account_gui import AccountTools
app = QApplication([])
w = AccountTools()
w.show()

def settle():
    app.processEvents()
    deadline = time.monotonic() + 10
    while w.mode:
        app.processEvents()
        assert time.monotonic() < deadline, w.status.text()

def choose(path):
    with patch('account_gui.QFileDialog.getOpenFileName', return_value=(str(path), '')):
        w.photo.click()

settle()
assert w.status.text() == 'Ready', w.status.text()
assert w.title.text() == '<b>Fixture</b> User'
assert w.title.textFormat() == Qt.TextFormat.PlainText
assert w.fields['Location'].text() == 'Lab' and not w.save.isEnabled()
rows = [w.details.topLevelItem(i) for i in range(w.details.topLevelItemCount())]
details = {row.text(0): row.text(1) for row in rows}
assert details['Account type'] == 'Administrator' and details['Password'] == 'Set'
assert w.groups.topLevelItemCount() > 0
w.fields['Email'].setText('new@example.org')
assert w.save.isEnabled()
with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
    w.refresh()
assert w.mode == '' and w.fields['Email'].text() == 'new@example.org'
w.discard_edits()
assert not w.changes()

root = Path(ROOT)
broken = root / 'broken.png'
broken.write_bytes(b'not an image')
choose(broken)
assert w.status.text() == 'Could not read this image.' and not w.changes()
portrait = root / 'portrait.jpg'
image = QImage(800, 600, QImage.Format.Format_RGB32)
image.fill(0xff334455)
assert image.save(str(portrait))
choose(portrait)
assert w.changes().keys() == {'IconFile'}
assert QImage(w.photo_path).size().width() == 512
draft = w.photo_path
w.discard_edits()
assert not w.changes() and Path(draft).exists()

# Closing is refused while a save is running.
w.fields['Location'].setText('Somewhere')
with (
    patch.object(w.process, 'start') as start,
    patch.object(w.process, 'write') as write,
    patch.object(w.process, 'closeWriteChannel'),
):
    w.save_profile()
    assert start.call_args.args[1][-1] == '--save'
    assert json.loads(write.call_args.args[0]) == {'Location': 'Somewhere'}
    assert w.mode == 'save' and not w.save.isEnabled()
    w.close()
    assert w.isVisible()
w.mode = ''
w.update_actions()

choose(portrait)
saved = w.photo_path
w.save_profile()
settle()
assert w.status.text() == 'Profile saved.' and not w.changes(), w.status.text()
w.refresh()
settle()
assert w.fields['Location'].text() == 'Somewhere' and not w.changes()
assert w.photo_path == str(root / 'icons/user')

# A denied field stays editable; fields saved before it are kept.
w.fields['RealName'].setText('Saved name')
w.fields['Email'].setText('denied@example.org')
w.save_profile()
settle()
assert w.changes() == {'Email': 'denied@example.org'}, w.changes()
assert w.status.text() == 'Could not save email: Not authorized', w.status.text()
assert w.title.text() == 'Saved name' and w.save.isEnabled()
w.discard_edits()

# Editing failures leave read-only account information usable.
w.loaded(dict(available=False, error='offline', username='alice', uid=1000, gid=100,
    home='/home/alice', shell='/bin/bash', groups=[], details={},
    fields=dict(RealName='Alice', Email='', Location='', IconFile='')))
assert not w.fields['RealName'].isEnabled() and not w.photo.isEnabled()
assert w.details.topLevelItemCount() > 0 and w.tabs.isEnabled()
assert w.status.text() == 'Profile editing unavailable: offline'

# Closing during a read stops the helper and removes photo drafts.
w.refresh()
assert w.mode == 'load'
w.close()
assert not w.isVisible() and w.process.state() == QProcess.ProcessState.NotRunning
assert not Path(draft).exists() and not Path(saved).exists()
"""
        with (
            tempfile.TemporaryDirectory() as directory,
            accounts_service(Path(directory), {'SetEmail': 'Not authorized'}) as (
                env,
                calls,
            ),
        ):
            root = Path(directory)
            (root / 'tmp').mkdir()
            result = subprocess.run(
                [sys.executable, '-c', f'ROOT = {directory!r}\n{script}'],
                env=dict(
                    env,
                    QT_QPA_PLATFORM='offscreen',
                    PYTHONPATH=str(LIB),
                    TMPDIR=str(root / 'tmp'),
                ),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            writes = [call for call in calls() if call['method'] != 'FindUserById']
            self.assertEqual(
                [(call['method'], call['interactive']) for call in writes],
                [
                    ('SetLocation', True),
                    ('SetIconFile', True),
                    ('SetRealName', True),
                    ('SetEmail', True),
                ],
            )
            photo = writes[1]
            # AccountsService copied a readable draft; the dialog then removed it.
            self.assertTrue(photo['readable'])
            self.assertEqual(Path(photo['value']).parent, root / 'tmp')
            self.assertEqual(list((root / 'tmp').iterdir()), [])
            self.assertTrue(
                all(
                    call['value'] == os.getuid()
                    for call in calls()
                    if call['method'] == 'FindUserById'
                )
            )


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
        self.assertEqual(result['error'], 'Could not save email: denied')

    def test_real_adapter_is_unreachable_from_in_process_tests(self):
        # Read-only, so a broken guard cannot change the account either.
        self.assertEqual(core.snapshot()['error'], 'real AccountsService')


if __name__ == '__main__':
    unittest.main()
