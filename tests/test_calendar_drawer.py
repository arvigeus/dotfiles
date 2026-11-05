"""Private shared accounts, DAV conflicts/recurrence, caching and production drawers."""

import copy
from datetime import datetime, timedelta, timezone
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import ANY, MagicMock, Mock, patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import support

DESKTOP = support.DESKTOP
sys.path.insert(0, str(DESKTOP))
import recurring_ical_events
from icalendar import Calendar
from integrations import nextcloud as accounts
from drawers.events import backend, caldav


def account():
    return dict(url='https://cloud.example/nextcloud/', username='alice')


def todo(*lines):
    return '\r\n'.join(
        [
            'BEGIN:VCALENDAR',
            'VERSION:2.0',
            'BEGIN:VTODO',
            'UID:task-1',
            'SUMMARY:Test',
            *lines,
            'END:VTODO',
            'END:VCALENDAR',
            '',
        ]
    )


def collection():
    return dict(
        name='Tasks',
        slug='tasks',
        url='https://cloud.example/tasks/',
        writable=True,
        components={'VTODO'},
    )


def todos(data):
    return Calendar.from_ical(data).walk('VTODO')


def write_password(root, secret='test-secret'):
    path = accounts.password_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret)
    path.chmod(0o600)
    return path


class AccountTests(unittest.TestCase):
    def test_app_password_and_transport_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(accounts.CredentialMissing):
                accounts.app_password(root)
            secret = write_password(root, 'example-secret')
            self.assertEqual(accounts.app_password(root), 'example-secret')
            secret.chmod(0o644)
            with self.assertRaises(accounts.NextcloudError):
                accounts.app_password(root)
            secret.unlink()
            secret.symlink_to(root / 'another')
            with self.assertRaises(accounts.NextcloudError):
                accounts.app_password(root)
        with patch.object(accounts, 'app_password', return_value='example-secret'):
            client = caldav.Client(account(), opener=Mock())
        for url in [
            'http://cloud.example/',
            'https://evil.example/',
            client.home + '../bob/a.ics',
            client.home + '%2e%2e/bob/a.ics',
            client.home + 'x.ics?x=1',
            client.home.replace('alice/', 'alice2/'),
        ]:
            with self.subTest(url=url), self.assertRaises(accounts.NextcloudError):
                client.request('GET', url)
        client.opener.open.assert_not_called()

    def test_secret_reads_are_owner_only_bounded_and_never_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = accounts.password_path(root)
            os.mkfifo(path, 0o600)
            # Without O_NONBLOCK, opening a FIFO with no writer never returns.
            with self.assertRaisesRegex(accounts.NextcloudError, 'regular file'):
                accounts.app_password(root)
            path.unlink()
            write_password(root, 'x' * (64 * 1024 + 1))
            with self.assertRaisesRegex(accounts.NextcloudError, '64 KiB'):
                accounts.app_password(root)
            path.write_bytes(b'\xff\xfe')
            with self.assertRaisesRegex(accounts.NextcloudError, 'UTF-8'):
                accounts.app_password(root)
            path.write_text('owner-read-only\n')
            path.chmod(0o400)
            self.assertEqual(accounts.app_password(root), 'owner-read-only')

    def test_dav_scope_covers_destinations_and_needs_a_collection_path(self):
        with patch.object(accounts, 'app_password', return_value='example-secret'):
            for scope in (
                '',
                'remote.php/dav/files/alice',
                'remote.php/dav/files/../',
                'remote.php/dav/files/alice/?x=/',
            ):
                with (
                    self.subTest(scope=scope),
                    self.assertRaises(accounts.NextcloudError),
                ):
                    accounts.DAVClient(account(), scope=scope, opener=Mock())
            client = accounts.DAVClient(
                account(), scope='remote.php/dav/files/alice/Music/', opener=Mock()
            )
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.read.return_value = b''
        client.opener.open.return_value = reply
        source = client.home + 'a.flac'
        for header in ('Destination', 'destination'):
            for target in (
                'https://cloud.example/nextcloud/remote.php/dav/files/alice/Other/a.flac',
                'https://evil.example/nextcloud/remote.php/dav/files/alice/Music/a.flac',
                client.home + '../a.flac',
            ):
                with (
                    self.subTest(header=header, target=target),
                    self.assertRaises(accounts.NextcloudError),
                ):
                    client.request('MOVE', source, headers={header: target})
        client.opener.open.assert_not_called()
        client.request('COPY', source, headers={'Destination': client.home + 'b.flac'})
        client.opener.open.assert_called_once()
        # Something other than HTTP answered, e.g. a different service on the port.
        client.opener.open.side_effect = http.client.BadStatusLine('not http')
        with self.assertRaisesRegex(accounts.NextcloudError, 'invalid HTTP'):
            client.request('PROPFIND', client.home)

    def test_dav_errors_explain_data_rejection_without_exposing_response_body(self):
        with patch.object(accounts, 'app_password', return_value='example-secret'):
            client = caldav.Client(account(), opener=Mock())
        for code in (400, 415, 422):
            client.opener.open.side_effect = HTTPError(
                client.home, code, 'Rejected', {}, io.BytesIO(b'private server details')
            )
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(
                    accounts.NextcloudError,
                    rf'rejected the submitted data \(HTTP {code}\)',
                ) as raised,
            ):
                client.request('PUT', client.home + 'task.ics', b'calendar')
            self.assertNotIn('private', str(raised.exception))
            client.opener.open.side_effect.close()
        client.opener.open.side_effect = HTTPError(
            client.home, 412, 'Precondition Failed', {}, io.BytesIO(b'')
        )
        with self.assertRaises(accounts.PreconditionFailed):
            client.request('PUT', client.home + 'task.ics', b'calendar')
        client.opener.open.side_effect.close()

    def test_discovery_accepts_sabre_href_spelling_for_email_usernames(self):
        # sabre/http writes '@' literally and other escapes in lowercase hex.
        home = '/nextcloud/remote.php/dav/calendars/alice@example.com/'

        def found(href, name):
            return (
                f'<d:response><d:href>{href}</d:href><d:propstat><d:prop>'
                f'<d:displayname>{name}</d:displayname><d:resourcetype>'
                '<d:collection/><c:calendar/></d:resourcetype>'
                '<d:current-user-privilege-set><d:privilege><d:all/></d:privilege>'
                '</d:current-user-privilege-set>'
                '<d:getetag>"1"</d:getetag><c:calendar-data>'
                + todo()
                + '</c:calendar-data></d:prop>'
                '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
            )

        def multistatus(*responses):
            return (
                '<d:multistatus xmlns:d="DAV:" '
                'xmlns:c="urn:ietf:params:xml:ns:caldav">'
                + ''.join(responses)
                + '</d:multistatus>'
            ).encode()

        replies = {
            'PROPFIND': multistatus(
                found(home, 'Home'),
                found(home + 'personal/', 'Personal'),
                found(home + 'caf%c3%a9/', 'Café'),
                found(home.replace('@', '%40') + 'work/', 'Work'),
                found('/nextcloud/remote.php/dav/calendars/bob/shared/', 'Bob'),
            ),
            'REPORT': multistatus(found(home + 'personal/a.ics', '')),
            'GET': todo().encode(),
        }

        def reply(request, timeout):
            response = MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = replies[request.get_method()]
            response.headers = {'ETag': '"1"'}
            return response

        with patch.object(accounts, 'app_password', return_value='example-secret'):
            client = caldav.Client(
                dict(account(), username='alice@example.com'),
                opener=Mock(open=Mock(side_effect=reply)),
            )
            plain = caldav.Client(account(), opener=Mock())
        self.assertTrue(plain.home.endswith('/calendars/alice/'))
        collections = client.propfind()
        self.assertEqual(
            [row['slug'] for row in collections], ['personal', 'café', 'work']
        )
        self.assertEqual(
            collections[0]['url'], 'https://cloud.example' + home + 'personal/'
        )
        self.assertEqual(
            [row['url'] for row in collections[1:]],
            [client.home + 'caf%c3%a9/', client.home + 'work/'],
        )
        ((href, _, _),) = client.report(collections[0], 'VTODO')
        self.assertEqual(href, collections[0]['url'] + 'a.ics')
        # The resource href passes the transport's account scope.
        self.assertEqual(client.request('GET', href)[0], todo().encode())

    def test_account_and_selections_are_validated(self):
        for url in [
            'http://cloud.example',
            'https://alice:password@cloud.example',
            'https://cloud.example/%2e%2e/',
            'https://cloud.example:99999/',
            'https://cloud.example:0/',
            'https://cloud.example:port/',
        ]:
            with self.subTest(url=url), self.assertRaises(accounts.NextcloudError):
                accounts.validate_account(dict(account(), url=url))
        self.assertEqual(
            accounts.validate_account(
                dict(account(), url='https://cloud.example:8443/nc')
            ),
            dict(url='https://cloud.example:8443/nc/', username='alice'),
        )
        with patch.dict(os.environ, XDG_CONFIG_HOME=''):
            self.assertEqual(
                accounts.config_root(),
                Path.home() / '.config/quickshell/desktop/integrations',
            )
        with self.assertRaises(accounts.NextcloudError):
            caldav.selection(dict(calendars=[42]), 'calendars')


class CalendarTests(unittest.TestCase):
    def client(self, data):
        client = caldav.Client.__new__(caldav.Client)
        client.propfind = lambda: [collection()]
        client.request = Mock(return_value=(data.encode(), {'ETag': '"1"'}))
        return client

    def written(self, client):
        writes = [
            call for call in client.request.call_args_list if call.args[0] == 'PUT'
        ]
        self.assertEqual(len(writes), 1)
        return writes[0].args[2].decode()

    def test_future_recurring_and_completed_tasks_remain_available(self):
        entries = [
            (
                'https://cloud.example/tasks/a.ics',
                '"1"',
                todo(
                    'DUE;VALUE=DATE:20301022',
                    'RRULE:FREQ=YEARLY',
                    'PRIORITY:1',
                    'PERCENT-COMPLETE:25',
                    'CATEGORIES:home,work',
                    'RELATED-TO:parent',
                ),
            ),
            (
                'https://cloud.example/tasks/b.ics',
                '"1"',
                todo('STATUS:COMPLETED', 'PERCENT-COMPLETE:100'),
            ),
            ('https://cloud.example/tasks/broken.ics', '"1"', 'not a calendar'),
        ]
        rows = caldav.tasks_from(entries, collection(), ZoneInfo('UTC'))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]['actionable'])
        self.assertTrue(rows[0]['recurring'])
        self.assertEqual(
            (
                rows[0]['priority'],
                rows[0]['percent'],
                rows[0]['parent'],
                rows[0]['categories'],
            ),
            (1, 25, 'parent', 'home, work'),
        )
        self.assertEqual(
            (rows[0]['due'], rows[0]['due_time'], rows[0]['recurrence_rule']),
            ('2030-10-22', '', 'FREQ=YEARLY'),
        )
        self.assertTrue(rows[1]['completed'])

    def test_rich_task_create_and_validation(self):
        fields = caldav.entry_fields(
            'VTODO',
            dict(
                summary='Water plants\r\nnot a property',
                description='notes',
                start_date='2026-10-21',
                start_time='08:30',
                due='2026-10-22',
                due_time='09:15',
                priority=2,
                percent=40,
                status='IN-PROCESS',
                categories='home, plants',
                parent='parent',
                recurrence_rule='FREQ=WEEKLY;INTERVAL=2;COUNT=4',
            ),
        )
        parsed = todos(
            b'BEGIN:VCALENDAR\r\n' + fields.to_ical() + b'END:VCALENDAR\r\n'
        )[0]
        self.assertEqual(str(parsed['SUMMARY']), 'Water plants\nnot a property')
        self.assertEqual(
            dict(parsed['RRULE']), dict(FREQ=['WEEKLY'], INTERVAL=[2], COUNT=[4])
        )
        self.assertEqual(
            (
                parsed['PERCENT-COMPLETE'],
                str(parsed['STATUS']),
                parsed['RELATED-TO'].params['RELTYPE'],
            ),
            (40, 'IN-PROCESS', 'PARENT'),
        )
        self.assertTrue(parsed['DUE'].to_ical().endswith(b'Z'))
        self.assertEqual(
            [str(tag) for tag in parsed['CATEGORIES'].cats], ['home', 'plants']
        )
        for values in [
            dict(priority=10),
            dict(percent=-1),
            dict(recurrence_rule='FREQ=SECONDLY', due='2026-10-22'),
            dict(recurrence_rule='FREQ=DAILY'),
            dict(start_date='2026-10-23', due='2026-10-22'),
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                caldav.entry_fields('VTODO', dict(summary='Test', **values))
        with self.assertRaisesRegex(accounts.NextcloudError, 'task time separately'):
            caldav.entry_fields(
                'VTODO',
                dict(
                    summary='Test',
                    due='2026-10-22',
                    recurrence_rule='FREQ=DAILY;BYHOUR=9',
                ),
            )

    def test_completion_and_reopening_replace_existing_modification_timestamp(self):
        original = todo(
            'DTSTAMP:20260101T000000Z',
            'LAST-MODIFIED:20260101T000000Z',
            'DESCRIPTION:Keep this',
            'BEGIN:VALARM',
            'ACTION:DISPLAY',
            'TRIGGER:-PT15M',
            'END:VALARM',
        )
        entry = dict(
            collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"1"'
        )
        for completed in (True, False, True):
            client = self.client(original)
            client.set_completed({}, entry, completed)
            updated = self.written(client)
            task = todos(updated)[0]
            self.assertNotIsInstance(task['LAST-MODIFIED'], list)
            self.assertNotEqual(task['LAST-MODIFIED'].to_ical(), b'20260101T000000Z')
            self.assertEqual(
                str(task['STATUS']), 'COMPLETED' if completed else 'NEEDS-ACTION'
            )
            self.assertEqual('COMPLETED' in task, completed)
            self.assertEqual(str(task['DESCRIPTION']), 'Keep this')
            self.assertEqual(
                str(task.walk('VALARM')[0]['TRIGGER'].to_ical(), 'ascii'), '-PT15M'
            )
            original = updated

    def test_recurrence_completion_is_atomic_preserves_alarm_and_count(self):
        data = todo(
            'LAST-MODIFIED:20260101T000000Z',
            'DUE;VALUE=DATE:20261021',
            'DTSTART;VALUE=DATE:20261020',
            'RRULE:FREQ=DAILY;COUNT=3',
            'X-CUSTOM:keep',
            'BEGIN:VALARM',
            'ACTION:DISPLAY',
            'TRIGGER:-PT15M',
            'END:VALARM',
        )
        client = self.client(data)
        entry = dict(
            collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"1"'
        )
        client.set_completed({}, entry, True)
        self.assertEqual(client.request.call_args.args[3]['If-Match'], '"1"')
        text = self.written(client)
        master, done = todos(text)
        self.assertTrue(
            all(not isinstance(task['LAST-MODIFIED'], list) for task in (master, done))
        )
        self.assertEqual(master['DUE'].to_ical(), b'20261022')
        self.assertEqual(master['DTSTART'].to_ical(), b'20261021')
        self.assertEqual(master['RRULE'].to_ical(), b'FREQ=DAILY;COUNT=2')
        # DTSTART, not DUE, identifies the occurrence (RFC 5545).
        self.assertEqual(
            (
                done['RECURRENCE-ID'].to_ical(),
                done['RECURRENCE-ID'].params.get('VALUE'),
            ),
            (b'20261020', 'DATE'),
        )
        self.assertEqual((str(done['STATUS']), 'RRULE' in done), ('COMPLETED', False))
        self.assertEqual(
            (str(master['STATUS']), 'COMPLETED' in master), ('NEEDS-ACTION', False)
        )
        self.assertEqual(text.count('X-CUSTOM:keep'), 2)
        self.assertEqual(text.count('BEGIN:VALARM'), 2)
        # A second completion retains the first exception and advances once.
        calendar = Calendar.from_ical(text)
        caldav.advance_task(calendar, caldav.master_of(calendar, 'VTODO'))
        records = calendar.walk('VTODO')
        self.assertEqual(len(records), 3)
        self.assertEqual(
            records[1]['LAST-MODIFIED'].to_ical(), done['LAST-MODIFIED'].to_ical()
        )
        self.assertEqual(records[0]['DUE'].to_ical(), b'20261023')

    def test_last_occurrence_until_and_dst(self):
        for rule in ('FREQ=DAILY;COUNT=1', 'FREQ=DAILY;UNTIL=20261021'):
            calendar = Calendar.from_ical(
                todo('DUE;VALUE=DATE:20261021', 'RRULE:' + rule)
            )
            caldav.advance_task(calendar, caldav.master_of(calendar, 'VTODO'))
            self.assertEqual(
                [str(task['STATUS']) for task in calendar.walk('VTODO')], ['COMPLETED']
            )
        calendar = Calendar.from_ical(
            todo(
                'DUE;TZID=America/New_York:20261031T090000', 'RRULE:FREQ=DAILY;COUNT=3'
            )
        )
        caldav.advance_task(calendar, caldav.master_of(calendar, 'VTODO'))
        self.assertIn(b'DUE;TZID=America/New_York:20261101T090000', calendar.to_ical())

    def test_occurrences_follow_start_and_reuse_an_existing_override(self):
        # A Monday start with a Wednesday due date repeats on Mondays.
        calendar = Calendar.from_ical(
            todo(
                'DTSTART;VALUE=DATE:20261019',
                'DUE;VALUE=DATE:20261021',
                'RRULE:FREQ=WEEKLY;BYDAY=MO',
            )
        )
        caldav.advance_task(calendar, caldav.master_of(calendar, 'VTODO'))
        master, done = calendar.walk('VTODO')
        self.assertEqual(
            (master['DTSTART'].to_ical(), master['DUE'].to_ical()),
            (b'20261026', b'20261028'),
        )
        self.assertEqual(done['RECURRENCE-ID'].to_ical(), b'20261019')
        # Other clients see one completed occurrence, then the open ones.
        self.assertEqual(
            sorted(
                (item['DTSTART'].to_ical(), str(item['STATUS']))
                for item in recurring_ical_events.of(
                    calendar, components=['VTODO']
                ).between((2026, 10, 19), (2026, 11, 3))
            ),
            [
                (b'20261019', 'COMPLETED'),
                (b'20261026', 'NEEDS-ACTION'),
                (b'20261102', 'NEEDS-ACTION'),
            ],
        )
        # A client's override of the occurrence is completed in place.
        calendar = Calendar.from_ical(
            todo('DTSTART;VALUE=DATE:20261020', 'RRULE:FREQ=DAILY;COUNT=3').replace(
                'END:VCALENDAR',
                'BEGIN:VTODO\r\nUID:task-1\r\nRECURRENCE-ID;VALUE=DATE:20261020\r\n'
                'DTSTART;VALUE=DATE:20261020\r\nSUMMARY:Moved\r\nEND:VTODO\r\n'
                'END:VCALENDAR',
            )
        )
        caldav.advance_task(calendar, caldav.master_of(calendar, 'VTODO'))
        master, override = calendar.walk('VTODO')
        self.assertEqual(
            (str(override['SUMMARY']), str(override['STATUS'])), ('Moved', 'COMPLETED')
        )
        self.assertEqual(
            (master['DTSTART'].to_ical(), master['RRULE'].to_ical()),
            (b'20261021', b'FREQ=DAILY;COUNT=2'),
        )

    def test_task_edits_keep_other_links_completion_time_and_finished_series(self):
        rows = caldav.tasks_from(
            [('h', '"1"', todo('RELATED-TO;RELTYPE=SIBLING:sibling', 'RELATED-TO:up'))],
            collection(),
            ZoneInfo('UTC'),
        )
        self.assertEqual(rows[0]['parent'], 'up')
        entry = dict(
            summary='Renamed',
            collection='tasks',
            href='https://cloud.example/tasks/a.ics',
            etag='"1"',
        )
        # The editor owns only the parent link.
        client = self.client(
            todo(
                'RELATED-TO;RELTYPE=CHILD:child',
                'RELATED-TO;RELTYPE=SIBLING:sibling',
                'RELATED-TO:old',
            )
        )
        client.report = Mock(
            return_value=[('b', '"1"', todo().replace('UID:task-1', 'UID:new'))]
        )
        client.save_item({}, 'VTODO', dict(entry, parent='new'))
        self.assertEqual(
            [
                line
                for line in self.written(client).splitlines()
                if line.startswith('RELATED-TO')
            ],
            [
                'RELATED-TO;RELTYPE=PARENT:new',
                'RELATED-TO;RELTYPE=CHILD:child',
                'RELATED-TO;RELTYPE=SIBLING:sibling',
            ],
        )
        # Editing a completed task keeps when it was completed.
        client = self.client(
            todo(
                'STATUS:COMPLETED', 'PERCENT-COMPLETE:100', 'COMPLETED:20260101T000000Z'
            )
        )
        client.save_item({}, 'VTODO', dict(entry, status='COMPLETED', percent=100))
        self.assertIn('COMPLETED:20260101T000000Z', self.written(client))
        # A finished series stays editable; an open one completes via its checkbox.
        finished = dict(entry, due='2026-10-21', status='COMPLETED', percent=100)
        client = self.client(
            todo(
                'DUE;VALUE=DATE:20261021',
                'RRULE:FREQ=DAILY;COUNT=1',
                'STATUS:COMPLETED',
                'PERCENT-COMPLETE:100',
            )
        )
        client.save_item(
            {}, 'VTODO', dict(finished, recurrence_rule='FREQ=DAILY;COUNT=1')
        )
        self.assertIn('SUMMARY:Renamed', self.written(client))
        client = self.client(todo('DUE;VALUE=DATE:20261021', 'RRULE:FREQ=DAILY'))
        with self.assertRaisesRegex(accounts.NextcloudError, 'checkbox'):
            client.save_item({}, 'VTODO', dict(finished, recurrence_rule='FREQ=DAILY'))
        # DURATION needs DTSTART: clearing the start removes it.
        for start, kept in (('2026-10-20', True), ('', False)):
            client = self.client(todo('DTSTART;VALUE=DATE:20261020', 'DURATION:P2D'))
            client.save_item({}, 'VTODO', dict(entry, start_date=start))
            self.assertEqual('DURATION:P2D' in self.written(client), kept)
        # An occurrence row never completes or advances its master.
        client = self.client(todo('DUE;VALUE=DATE:20261021', 'RRULE:FREQ=DAILY'))
        with self.assertRaisesRegex(accounts.NextcloudError, 'occurrences'):
            client.set_completed({}, dict(entry, recurrence_id='20261020'), True)
        client.request.assert_not_called()

    def test_retried_create_updates_its_committed_item_instead_of_duplicating(self):
        identity = 'a' * 32
        href = 'https://cloud.example/tasks/' + identity + '.ics'
        stored = todo('X-KEEP:1').replace('UID:task-1', f'UID:{identity}@desktop')

        def reply(method, url, body=None, headers=None):
            if method == 'PUT' and 'If-None-Match' in headers:
                raise accounts.PreconditionFailed('exists')
            return stored.encode(), {'ETag': '"7"'}

        client = self.client('')
        client.request = Mock(side_effect=reply)
        draft = dict(summary='Retried', collection='tasks', create_id=identity)
        self.assertEqual(client.save_item({}, 'VTODO', draft)['href'], href)
        puts = [call for call in client.request.call_args_list if call.args[0] == 'PUT']
        self.assertEqual([call.args[1] for call in puts], [href, href])
        self.assertEqual(puts[1].args[3], {'Content-Type': ANY, 'If-Match': '"7"'})
        written = puts[1].args[2].decode()
        self.assertEqual(written.count('BEGIN:VTODO'), 1)
        self.assertIn('SUMMARY:Retried', written)
        self.assertIn('X-KEEP:1', written)
        # Another item under that name is never overwritten.
        stored = todo()
        client.request.reset_mock()
        with self.assertRaisesRegex(accounts.NextcloudError, 'changed'):
            client.save_item({}, 'VTODO', draft)
        self.assertEqual(
            [call.args[0] for call in client.request.call_args_list], ['PUT', 'GET']
        )
        # Only a 32-digit hex identity names a resource.
        client.request = Mock(return_value=(b'', {}))
        created = client.save_item({}, 'VTODO', dict(draft, create_id='../x'))
        self.assertRegex(created['href'], r'/tasks/[0-9a-f]{32}\.ics$')
        self.assertNotIn(identity, created['href'])

    def test_conflict_read_only_and_reopen(self):
        entry = dict(
            collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"old"'
        )
        client = self.client(todo('STATUS:COMPLETED'))
        with self.assertRaisesRegex(accounts.NextcloudError, 'changed'):
            client.set_completed({}, entry, False)
        self.assertEqual(
            [call.args[0] for call in client.request.call_args_list], ['GET']
        )
        entry['etag'] = '"1"'
        client.request.reset_mock()
        client.set_completed({}, entry, False)
        self.assertIn(b'STATUS:NEEDS-ACTION', client.request.call_args.args[2])
        self.assertNotIn(b'COMPLETED:', client.request.call_args.args[2])
        with self.assertRaises(accounts.NextcloudError):
            client.delete_item(dict(task_lists=[]), 'VTODO', entry)

    def test_edit_master_preserves_exceptions_and_other_properties(self):
        calendar = Calendar.from_ical(
            todo('DUE;VALUE=DATE:20261021', 'RRULE:FREQ=WEEKLY', 'X-PRIVATE:keep')
        )
        caldav.advance_task(calendar, caldav.master_of(calendar, 'VTODO'))
        client = self.client(calendar.to_ical().decode())
        client.save_item(
            {},
            'VTODO',
            dict(
                summary='Changed',
                collection='tasks',
                href='https://cloud.example/tasks/a.ics',
                etag='"1"',
                due='2026-10-28',
                recurrence_rule='FREQ=WEEKLY',
            ),
        )
        updated = self.written(client)
        self.assertEqual(updated.count('SUMMARY:Changed'), 1)
        self.assertIn('RECURRENCE-ID;VALUE=DATE:20261021', updated)
        self.assertEqual(updated.count('X-PRIVATE:keep'), 2)
        self.assertEqual(client.request.call_args.args[3]['If-Match'], '"1"')

    def test_edits_preserve_timezone_and_reject_parent_cycles(self):
        data = todo('DUE;TZID=America/New_York:20261031T090030', 'RRULE:FREQ=DAILY')
        master = todos(data)[0]
        local = master.decoded('DUE').astimezone(caldav.tz.gettz())
        fields = caldav.entry_fields(
            'VTODO',
            dict(
                summary='Test',
                due=local.date().isoformat(),
                due_time=local.strftime('%H:%M'),
            ),
        )
        caldav.preserve_dates(master, fields)
        self.assertEqual(fields['DUE'].to_ical(), b'20261031T090030')
        self.assertEqual(fields['DUE'].params['TZID'], 'America/New_York')
        later = (
            local.replace(second=0) + (datetime(2000, 1, 1, 1) - datetime(2000, 1, 1))
        ).strftime('%H:%M')
        fields = caldav.entry_fields(
            'VTODO', dict(summary='Test', due=local.date().isoformat(), due_time=later)
        )
        caldav.preserve_dates(master, fields)
        self.assertEqual(
            (fields['DUE'].to_ical(), fields['DUE'].params['TZID']),
            (b'20261031T100000', 'America/New_York'),
        )
        client = self.client(data)
        child = todo('RELATED-TO:task-1').replace('UID:task-1', 'UID:child')
        client.report = Mock(return_value=[('a', '1', data), ('b', '1', child)])
        with self.assertRaisesRegex(accounts.NextcloudError, 'ancestor'):
            client.save_item(
                {},
                'VTODO',
                dict(summary='Test', collection='tasks', uid='task-1', parent='child'),
            )
        client.request.assert_not_called()

    def test_events_expand_recurrence_and_respect_exclusions(self):
        def rows(
            *lines,
            zone=ZoneInfo('UTC'),
            start=datetime(2026, 10, 20, tzinfo=timezone.utc),
            end=datetime(2026, 10, 24, tzinfo=timezone.utc),
        ):
            data = '\r\n'.join(
                [
                    'BEGIN:VCALENDAR',
                    'BEGIN:VEVENT',
                    'UID:e',
                    'SUMMARY:Meeting',
                    *lines,
                    'END:VEVENT',
                    'END:VCALENDAR',
                    '',
                ]
            )
            return caldav.events_from(
                [('https://cloud.example/e.ics', '"1"', data)],
                dict(collection(), components={'VEVENT'}),
                start,
                end,
                zone,
            )

        recurring = rows(
            'DTSTART:20261020T090000Z',
            'DTEND:20261020T100000Z',
            'RRULE:FREQ=DAILY;COUNT=3',
            'EXDATE:20261021T090000Z',
        )
        self.assertEqual(
            [row['date'] for row in recurring], ['2026-10-20', '2026-10-22']
        )
        self.assertFalse(recurring[0]['editable'])
        # Outlook zone names, DATE exclusions, PERIOD dates and lowercase names.
        self.assertEqual(
            rows(
                'DTSTART;TZID=W. Europe Standard Time:20261020T090000',
                'DTEND;TZID=W. Europe Standard Time:20261020T100000',
            )[0]['start'],
            '2026-10-20T09:00:00+02:00',
        )
        self.assertEqual(
            [
                row['date']
                for row in rows(
                    'DTSTART;TZID=Europe/Berlin:20261020T090000',
                    'RRULE:FREQ=DAILY;COUNT=3',
                    'EXDATE;VALUE=DATE:20261021',
                )
            ],
            ['2026-10-20', '2026-10-22'],
        )
        self.assertEqual(
            [
                row['date']
                for row in rows(
                    'DTSTART:20261020T020000Z',
                    'DTEND:20261020T030000Z',
                    'RDATE;VALUE=PERIOD:20261022T020000Z/PT1H',
                )
            ],
            ['2026-10-20', '2026-10-22'],
        )
        single = rows('dtstart;value=date:20261021', 'status:confirmed')
        self.assertEqual(
            (
                single[0]['date'],
                single[0]['last_date'],
                single[0]['all_day'],
                single[0]['editable'],
            ),
            ('2026-10-21', '2026-10-21', True, True),
        )
        self.assertEqual(rows('DTSTART:20261021T090000Z', 'STATUS:CANCELLED'), [])
        # Sub-daily rules stay bounded per resource.
        self.assertEqual(
            len(rows('DTSTART:20261020T000000Z', 'RRULE:FREQ=MINUTELY')), 2000
        )

    def test_event_edits_use_utc_and_refuse_recurring_series(self):
        event = '\r\n'.join(
            [
                'BEGIN:VCALENDAR',
                'BEGIN:VEVENT',
                'UID:e',
                'SUMMARY:Old',
                'DTSTART:20261020T090000Z',
                'X-KEEP:1',
                'END:VEVENT',
                'END:VCALENDAR',
                '',
            ]
        )
        client = self.client(event)
        client.propfind = lambda: [dict(collection(), components={'VEVENT'})]
        entry = dict(
            summary='New',
            collection='tasks',
            href='https://cloud.example/tasks/e.ics',
            etag='"1"',
            start_date='2026-10-21',
            end_date='2026-10-22',
            all_day=True,
        )
        client.save_item({}, 'VEVENT', entry)
        updated = Calendar.from_ical(self.written(client)).walk('VEVENT')[0]
        self.assertEqual(
            (
                updated['DTSTART'].to_ical(),
                updated['DTEND'].to_ical(),
                str(updated['X-KEEP']),
            ),
            (b'20261021', b'20261023', '1'),
        )
        client = self.client(event.replace('X-KEEP:1', 'RRULE:FREQ=DAILY'))
        client.propfind = lambda: [dict(collection(), components={'VEVENT'})]
        with self.assertRaisesRegex(accounts.NextcloudError, 'Recurring'):
            client.save_item({}, 'VEVENT', entry)
        fields = caldav.entry_fields(
            'VEVENT',
            dict(
                summary='Timed',
                start_date='2026-10-21',
                start_time='09:00',
                end_date='2026-10-21',
                end_time='10:00',
            ),
        )
        self.assertTrue(fields['DTSTART'].to_ical().endswith(b'Z'))

    def test_agenda_orders_instants_and_event_edits_keep_timezone(self):
        def event(*lines):
            return '\r\n'.join(
                ['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'UID:e', 'SUMMARY:Meeting']
                + list(lines)
                + ['END:VEVENT', 'END:VCALENDAR', '']
            )

        # 09:00 New York is 13:00 UTC, after a 10:00 UTC event that day.
        zoned = event(
            'DTSTART;TZID=America/New_York:20261021T090000',
            'DTEND;TZID=America/New_York:20261021T100000',
        )
        entries = [
            ('https://cloud.example/tasks/zoned.ics', '"1"', zoned),
            (
                'https://cloud.example/tasks/utc.ics',
                '"1"',
                event('DTSTART:20261021T100000Z', 'DTEND:20261021T110000Z'),
            ),
        ]
        calendars = dict(collection(), components={'VEVENT'})
        dav = Mock(propfind=Mock(return_value=[calendars]))
        dav.report.return_value = entries
        with patch.object(caldav, 'Client', return_value=dav):
            data = caldav.snapshot({}, start='2026-10-01', end='2026-11-01')
        names = [row['href'].rsplit('/', 1)[-1] for row in data['events']]
        self.assertEqual(names, ['utc.ics', 'zoned.ics'])
        data['events'].reverse()
        self.assertEqual(backend.sort_data(data)['events'][0]['href'], entries[1][0])
        # Editing the title keeps the event's own timezone.
        local = datetime(2026, 10, 21, 13, tzinfo=timezone.utc).astimezone()
        for shift, times in ((0, (b'090000', b'100000')), (1, (b'100000', b'110000'))):
            begins = local + timedelta(hours=shift)
            ends = begins + timedelta(hours=1)
            client = self.client(zoned)
            client.propfind = lambda: [calendars]
            client.save_item(
                {},
                'VEVENT',
                dict(
                    summary='Renamed',
                    collection='tasks',
                    href=entries[0][0],
                    etag='"1"',
                    start_date=begins.date().isoformat(),
                    start_time=begins.strftime('%H:%M'),
                    end_date=ends.date().isoformat(),
                    end_time=ends.strftime('%H:%M'),
                ),
            )
            written = self.written(client)
            for name, time in zip(('DTSTART', 'DTEND'), times):
                self.assertIn(
                    f'{name};TZID=America/New_York:20261021T{time.decode()}', written
                )


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(
            os.environ,
            XDG_CONFIG_HOME=self.tmp.name + '/config',
            XDG_CACHE_HOME=self.tmp.name + '/cache',
        )
        env.start()
        self.addCleanup(env.stop)
        folder = accounts.config_root()
        folder.mkdir(parents=True)
        (folder / 'nextcloud.json').write_text(json.dumps(account()))
        write_password(folder)
        self.request = dict(op='status', start='2026-10-01', end='2026-11-01')

    def test_cached_open_failure_backoff_and_account_change(self):
        self.assertTrue(backend.handle(self.request)['due'])
        payload = dict(events=[], tasks=[], calendars=[], task_count=0)
        with (
            patch.object(caldav, 'snapshot', return_value=payload) as fetch,
            patch.object(backend.time, 'time', return_value=1000),
        ):
            backend.handle(dict(self.request, op='fetch'))
            cached = backend.handle(self.request)
            self.assertFalse(cached['due'])
            self.assertEqual(fetch.call_count, 1)
        with (
            patch.object(backend.time, 'time', return_value=2000),
            patch.object(
                caldav, 'snapshot', side_effect=accounts.NextcloudError('Offline')
            ),
        ):
            result = backend.handle(dict(self.request, op='fetch'))
            self.assertTrue(result['stale'])
            self.assertEqual(result['error'], 'Offline')
            self.assertFalse(backend.handle(self.request)['due'])
        config = account()
        config['username'] = 'bob'
        (accounts.config_root() / 'nextcloud.json').write_text(json.dumps(config))
        self.assertEqual(backend.handle(self.request)['state'], 'loading')
        self.assertTrue(
            all(
                path.stat().st_mode & 0o777 == 0o600
                for path in backend.cache_root().glob('*.json')
            )
        )

    def test_missing_account_and_credential_and_feature_cannot_override_account(self):
        (backend.config_root() / 'calendar.json').write_text(
            json.dumps(dict(url='https://evil.example', calendars=[]))
        )
        config, _, _ = backend.context(self.request)
        self.assertEqual(config['url'], account()['url'])
        self.assertEqual(config['calendars'], [])
        accounts.password_path().unlink()
        self.assertEqual(backend.handle(self.request)['state'], 'needs_password')
        (accounts.config_root() / 'nextcloud.json').unlink()
        self.assertEqual(backend.handle(self.request)['state'], 'unconfigured')

    def test_first_network_failure_backs_off_and_manual_refresh_recovers(self):
        with (
            patch.object(backend.time, 'time', return_value=1000),
            patch.object(
                caldav, 'snapshot', side_effect=accounts.NextcloudError('Offline')
            ),
        ):
            result = backend.handle(dict(self.request, op='fetch'))
            self.assertEqual(result['state'], 'unavailable')
            self.assertFalse(backend.handle(self.request)['due'])
        with patch.object(backend.time, 'time', return_value=1400):
            self.assertTrue(backend.handle(self.request)['due'])
        with patch.object(
            caldav, 'snapshot', return_value=dict(events=[], tasks=[], calendars=[])
        ):
            self.assertEqual(
                backend.handle(dict(self.request, op='fetch'))['state'], 'ready'
            )

    def seed(self):
        payload = dict(
            events=[],
            tasks=[
                dict(
                    href='https://cloud.example/tasks/a.ics',
                    uid='task-1',
                    summary='First',
                    due='',
                    completed=False,
                    etag='"1"',
                ),
                dict(
                    href='https://cloud.example/tasks/b.ics',
                    uid='task-2',
                    summary='Other',
                    due='',
                    completed=False,
                    etag='"1"',
                ),
            ],
            calendars=[],
            task_count=2,
        )
        with patch.object(caldav, 'snapshot', return_value=payload):
            backend.handle(dict(self.request, op='fetch'))
            backend.handle(
                dict(self.request, op='fetch', start='2026-11-01', end='2026-12-01')
            )
        return payload

    def mutation(self):
        return dict(
            self.request,
            op='complete',
            kind='VTODO',
            completed=True,
            entry=dict(
                collection='tasks',
                href='https://cloud.example/tasks/a.ics',
                etag='"1"',
                summary='First',
            ),
            account_id=backend.handle(self.request)['account_id'],
        )

    def writer(self):
        client = Mock()
        client.set_completed.return_value = dict(
            saved=True,
            href='https://cloud.example/tasks/a.ics',
            collection=collection(),
        )
        client.request.return_value = (
            todo('STATUS:COMPLETED', 'PERCENT-COMPLETE:100').encode(),
            {'ETag': '"2"'},
        )
        return client

    def test_writes_patch_all_month_caches_and_return_only_changed_resource(self):
        self.seed()
        client = self.writer()
        with (
            patch.object(caldav, 'Client', return_value=client),
            patch.object(caldav, 'snapshot') as network,
        ):
            response = backend.handle(self.mutation())
            network.assert_not_called()
        self.assertEqual(len(response['tasks']), 1)
        self.assertEqual(response['tasks'][0]['etag'], '"2"')
        for start, end in [('2026-10-01', '2026-11-01'), ('2026-11-01', '2026-12-01')]:
            state = backend.handle(dict(self.request, start=start, end=end))
            self.assertEqual(len(state['tasks']), 2)
            self.assertTrue(
                next(row for row in state['tasks'] if row['uid'] == 'task-1')[
                    'completed'
                ]
            )
            self.assertFalse(
                next(row for row in state['tasks'] if row['uid'] == 'task-2')[
                    'completed'
                ]
            )
        self.assertEqual(
            client.request.call_args_list[0].args,
            ('GET', 'https://cloud.example/tasks/a.ics'),
        )
        self.assertEqual(len(list(backend.cache_root().glob('*.json'))), 2)
        self.assertEqual(backend.revision() % 2, 0)

    def test_slow_refresh_does_not_block_cache_or_overwrite_confirmed_write(self):
        payload = self.seed()
        entered = threading.Event()
        release = threading.Event()

        def fetch(*args, **kwargs):
            entered.set()
            release.wait(4)
            return copy.deepcopy(payload)

        with (
            ThreadPoolExecutor(max_workers=2) as executor,
            patch.object(caldav, 'snapshot', side_effect=fetch),
            patch.object(caldav, 'Client', return_value=self.writer()),
        ):
            slow = executor.submit(backend.handle, dict(self.request, op='fetch'))
            self.assertTrue(entered.wait(1))
            try:
                cached = executor.submit(backend.handle, self.request).result(timeout=1)
                self.assertEqual(len(cached['tasks']), 2)
                backend.handle(self.mutation())
            finally:
                release.set()
            self.assertTrue(slow.result(timeout=2)['superseded'])
        state = backend.handle(self.request)
        self.assertTrue(
            next(row for row in state['tasks'] if row['uid'] == 'task-1')['completed']
        )

    def test_failed_write_retains_cache_and_unknown_readback_never_replays_put(self):
        original = self.seed()
        client = self.writer()
        client.set_completed.side_effect = accounts.NextcloudError('Conflict')
        with (
            patch.object(caldav, 'Client', return_value=client),
            self.assertRaisesRegex(accounts.NextcloudError, 'Conflict'),
        ):
            backend.handle(self.mutation())
        cached = backend.handle(self.request)
        self.assertEqual(cached['tasks'], original['tasks'])
        self.assertTrue(cached['stale'])
        self.assertTrue(cached['due'])
        client.set_completed.side_effect = None
        client.request.side_effect = accounts.NextcloudError('Offline')
        with patch.object(caldav, 'Client', return_value=client):
            result = backend.handle(self.mutation())
        self.assertTrue(result['saved'])
        self.assertTrue(result['reconcile'])
        self.assertEqual(
            client.set_completed.call_count, 2
        )  # One explicit attempt per user request.
        self.assertEqual(backend.revision() % 2, 0)

    def test_cached_tasks_survive_uncached_month_and_failure_does_not_fake_coverage(
        self,
    ):
        self.seed()
        other = dict(self.request, start='2030-01-01', end='2030-02-01')
        state = backend.handle(other)
        self.assertTrue(state['tasksReady'])
        self.assertFalse(state['eventsReady'])
        self.assertTrue(state['due'])
        with patch.object(
            caldav, 'snapshot', side_effect=accounts.NextcloudError('Offline')
        ):
            failed = backend.handle(dict(other, op='fetch'))
        self.assertEqual(len(failed['tasks']), 2)
        self.assertFalse(failed['eventsReady'])
        self.assertFalse(failed['due'])
        self.assertFalse(backend.handle(other)['due'])

    def test_queued_write_cannot_switch_to_another_account(self):
        self.seed()
        request = self.mutation()
        config = account()
        config['username'] = 'bob'
        (accounts.config_root() / 'nextcloud.json').write_text(json.dumps(config))
        with (
            patch.object(caldav, 'Client') as client,
            self.assertRaisesRegex(accounts.NextcloudError, 'account'),
        ):
            backend.handle(request)
        client.assert_not_called()

    def test_task_cache_is_global_and_terminated_writer_recovers_without_retry(self):
        self.seed()
        _, path, _ = backend.context(
            dict(self.request, start='2026-11-01', end='2026-12-01')
        )
        cached = backend.read_cache(path)
        cached['data']['tasks'][0]['summary'] = 'Updated in another month'
        cached['fetched'] += 1
        backend.atomic_json(path, cached)
        self.assertEqual(
            backend.handle(self.request)['tasks'][0]['summary'],
            'Updated in another month',
        )
        with backend.locked():
            backend.bump_revision()
        with backend.locked('write.lock'):
            backend.handle(self.request)
            self.assertEqual(backend.revision() % 2, 1)
        state = backend.handle(self.request)
        self.assertEqual(backend.revision() % 2, 0)
        self.assertTrue(state['stale'])
        self.assertTrue(state['due'])


@unittest.skipUnless(support.QS, 'Quickshell is required')
class CalendarQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            shutil.copytree(DESKTOP / 'integrations', root / 'integrations')
            if setup:
                setup(root)

        return support.run_qml(self, body, prepare)

    def test_drawer_tabs_editor_and_notifications_load(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers"
ShellRoot {
 QtObject {
  id:mock
  property bool active:false
  property bool busy:false
  property bool writing:false
  property string month:"2026-10"
  property string error:""
  property var state:({state:"ready",stale:false,updated:0,calendars:[{name:"Personal",slug:"personal",components:["VEVENT","VTODO"],writable:true,events_enabled:true,tasks_enabled:true}],events:[{summary:"Meeting",date:"2026-10-21",last_date:"2026-10-21",start:"2026-10-21T09:00:00Z",end:"2026-10-21T10:00:00Z",calendar:"Personal",calendar_slug:"personal",description:"Notes",editable:true},{summary:"Later meeting",date:"2026-10-24",last_date:"2026-10-24",start:"2026-10-24T09:00:00Z",end:"2026-10-24T10:00:00Z",calendar:"Personal",calendar_slug:"personal",editable:true}],tasks:[{summary:"Recurring task",due:"2026-10-22",start_date:"2026-10-21",list:"Personal",list_slug:"personal",recurring:true,recurrence_rule:"FREQ=DAILY",completed:false,actionable:true,editable:true,priority:1,percent:20,categories:"home",description:"notes",uid:"t1"}]})
  function refresh(force){}
  property var lastRequest:null
  function mutate(op,kind,entry,completed){lastRequest={op,kind,entry,completed};}
  signal saved()
 }
 FloatingWindow { id:window; implicitWidth:480;implicitHeight:820;color:"#1b2021"
  EventsDrawer {id:drawer;width:parent.width;height:parent.height;active:true;service:mock;selectedDate:"2026-10-21"}
 }
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 property int stage:0
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  if(stage===0){check(drawer.visibleEvents.length===2&&find(drawer,"agendaDate:2026-10-24"),"combined dated agenda missing future event");
   check(find(drawer,"agendaHeading").mapToItem(drawer,0,0).y>find(drawer,"calendarDay:2026-11-08").mapToItem(drawer,0,0).y,"agenda is not below calendar");
   find(drawer,"nextYear").clicked();check(mock.month==="2027-10","year forward changed month");
   find(drawer,"previousYear").clicked();check(mock.month==="2026-10","year backward changed month");
   drawer.selectedDate="2026-10-21";
   find(drawer,"sectionAddItem").clicked();check(drawer.editingKind==="VEVENT"&&drawer.editing!==null,"agenda add did not create event");drawer.escapeHandler();const a=find(drawer,"calendarDay:2026-10-01"),b=find(drawer,"calendarDay:2026-10-02");check(a.width>30&&Math.abs(a.width-b.width)<1&&a.x+a.width<=b.x,"uneven month columns");drawer.tab="tasks";}
  else if(stage===1){check(drawer.visibleTasks.length===1,"tasks");drawer.edit("VTODO",mock.state.tasks[0]);}
  else if(stage===2){check(find(drawer,"itemTitle").text==="Recurring task","editor not loaded");check(!!drawer.escapeHandler,"editor Escape");find(drawer,"itemSave").clicked();check(mock.lastRequest?.entry.recurrence_rule==="FREQ=DAILY"&&mock.lastRequest.entry.status==="NEEDS-ACTION","editor fields did not save");drawer.escapeHandler();check(drawer.editing===null,"Escape editor");drawer.width=268;drawer.monthStep(1);check(mock.month==="2026-11","month navigation");}
  else if(stage===3){drawer.taskFilter="Completed";check(drawer.visibleTasks.length===0,"completed filter");drawer.tab="calendar";}
  else if(stage===4){const a=find(drawer,"calendarDay:2026-11-01"),b=find(drawer,"calendarDay:2026-11-02");check(drawer.width===268&&a.width>20&&a.width<45&&Math.abs(a.width-b.width)<1,"narrow month columns");
   const today=find(drawer,"calendarToday");check(today.x+today.width<=today.parent.width+1,"narrow navigation overflows");
   today.clicked();check(drawer.selectedDate===Qt.formatDate(new Date(),"yyyy-MM-dd")&&mock.month===drawer.selectedDate.slice(0,7),"Today did not reset calendar");
   drawer.active=false;check(!mock.active,"observation did not stop");console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_task_row_highlight_includes_independent_completion_control(self):
        self.run_qml("""import QtQuick
import QtTest
import Quickshell
import "drawers"
import "ui" as UI
ShellRoot {
 TestCase { id:input; when:false; parent:window.contentItem }
 QtObject {
  id:mock
  property bool active:false
  property bool busy:false
  property bool writing:false
  property string month:"2026-10"
  property string error:""
  property var state:({state:"ready",calendars:[],events:[],tasks:[{uid:"task",summary:"Test task",completed:false,actionable:true,editable:true,list_slug:"tasks",list:"Tasks"}]})
  property var requests:[]
  function refresh(force){}
  function mutate(op,kind,entry,completed){
   requests=requests.concat([{op,kind,completed}]);
   state=Object.assign({},state,{tasks:[Object.assign({},state.tasks[0],{completed})]});
  }
 }
 FloatingWindow { id:window; implicitWidth:480; implicitHeight:820
  EventsDrawer { id:drawer; anchors.fill:parent; service:mock; active:true; tab:"tasks"; taskFilter:"All" }
 }
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 property int stage:0
 Timer { interval:180; repeat:true; running:true; onTriggered:{try{
  const row=find(drawer,"taskRow:task"),box=find(drawer,"taskComplete:task"),edit=find(drawer,"taskEdit:task"),bg=find(drawer,"taskBackground:task");
  if(stage===0){input.mouseMove(box,box.width/2,box.height/2);}
  else if(stage===1){
   check(bg.highlighted&&bg.color.toString()===UI.Theme.accentSurface.toString(),"checkbox hover did not highlight task row");
   check(bg.width===row.width&&bg.height===row.height,"highlight does not cover the whole row");
   input.mouseClick(box,box.width/2,box.height/2);
   check(mock.requests.length===1&&mock.requests[0].completed===true&&!drawer.editing,"checkbox did not complete independently");
  }else if(stage===2){
   check(box.checked,"completion state did not reach checkbox");
   input.mouseClick(box,box.width/2,box.height/2);
   check(mock.requests.length===2&&mock.requests[1].completed===false&&!drawer.editing,"checkbox did not reopen independently");
   input.mouseMove(edit,edit.width/2,edit.height/2);
  }else if(stage===3){
   check(!box.checked&&bg.highlighted,"text hover did not share the row highlight");
   input.mouseMove(window.contentItem,0,0);edit.forceActiveFocus(Qt.TabFocusReason);
  }else if(stage===4){
   check(edit.visualFocus&&bg.highlighted,"task keyboard focus did not highlight row");
   input.mouseClick(edit,edit.width/2,edit.height/2);
   check(drawer.editing?.uid==="task"&&mock.requests.length===2,"editing toggled completion");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer { interval:4000; running:true; onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();} }
}""")

    def test_task_editor_toolbar_stays_visible(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers/events"
ShellRoot {
 QtObject {
  id:mock
  property bool writing:false
  property var state:({calendars:[{name:"Personal",slug:"personal",components:["VTODO"],writable:true,tasks_enabled:true}],tasks:[]})
  property var requests:[]
  function mutate(op,kind,entry){requests=requests.concat([{op,kind,entry}]);}
 }
 FloatingWindow { implicitWidth:268;implicitHeight:450
  ItemEditor {
   id:editor;anchors.fill:parent;service:mock
   entry:({summary:"Recurring task",href:"https://cloud.example/task.ics",uid:"task",editable:true,list_slug:"personal",recurring:true,recurrence_rule:"FREQ=DAILY",due:"2026-10-22"})
   onCancelled:backCount++
  }
 }
 property int backCount:0
 property int stage:0
 property real toolbarY:0
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:180;repeat:true;running:true;onTriggered:{try{
  const toolbar=find(editor,"itemToolbar"),form=find(editor,"itemForm"),save=find(editor,"itemSave"),back=find(editor,"itemBack"),remove=find(editor,"itemDelete");
  if(stage===0){
   check(back.iconName==="chevron-left"&&save.iconName==="check"&&remove.contentItem.name==="trash","Lucide toolbar actions missing");
   check(save.enabled&&save.mapToItem(editor,save.width,0).x<=editor.width+1,"narrow toolbar overflows");
   toolbarY=toolbar.mapToItem(editor,0,0).y;
   check(form.contentHeight>form.height,"fixture needs a scrolling form");
   form.contentItem.contentY=form.contentHeight-form.height;
  }else if(stage===1){
   check(toolbar.mapToItem(editor,0,0).y===toolbarY&&back.visible&&save.visible,"actions scrolled away");
   check(find(editor,"itemTitle").mapToItem(editor,0,0).y<toolbarY,"form did not scroll");
   save.clicked();check(mock.requests.length===1&&mock.requests[0].entry.recurrence_rule==="FREQ=DAILY","save lost recurrence");
   remove.clicked();check(mock.requests.length===1&&!editor.popupOpen,"click deleted or opened confirmation");
   editor.entry=Object.assign({},editor.entry,{editable:false});
  }else if(stage===2){
   check(!save.visible&&!remove.visible&&back.visible,"read-only actions incorrect");
   check(form.contentItem.contentY===0,"new entry retained old scroll position");
   back.clicked();check(backCount===1,"Back did not navigate");console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_task_and_event_deletion_requires_hold_and_cancels_on_context_change(self):
        self.run_qml("""import QtQuick
import QtTest
import Quickshell
import "drawers"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:mock
  property bool active:false
  property bool busy:false
  property bool writing:false
  property string month:"2026-10"
  property string error:""
  property var state:({state:"ready",calendars:[{name:"Personal",slug:"personal",components:["VTODO","VEVENT"],writable:true,tasks_enabled:true,events_enabled:true}],tasks:[],events:[]})
  property var requests:[]
  function refresh(force){}
  function mutate(op,kind,entry){requests=requests.concat([{op,kind,entry}]);}
 }
 property var task:({summary:"Recurring task",href:"https://cloud.example/task.ics",uid:"task",editable:true,list_slug:"personal",recurring:true,recurrence_rule:"FREQ=DAILY",due:"2026-10-22"})
 property var event:({summary:"Event",href:"https://cloud.example/event.ics",editable:true,calendar_slug:"personal",all_day:true,start:"2026-10-21T00:00:00Z",end:"2026-10-22T00:00:00Z",last_date:"2026-10-21"})
 FloatingWindow {id:window;implicitWidth:268;implicitHeight:500
  EventsDrawer {id:drawer;anchors.fill:parent;service:mock;active:true}
 }
 property int stage:0
 property var button:null
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 Timer{interval:100;repeat:true;running:true;onTriggered:{try{
  if(stage===0)drawer.edit("VTODO",task);
  else if(stage===1){
   button=find(drawer,"itemDelete");check(button.holdDuration===1300,"wrong production hold duration");
   check(button.width===34&&button.contentItem.width===18,"delete icon sizing changed");
   check(button.hint.includes("entire series"),"series deletion scope missing");button.holdDuration=350;
   input.mouseClick(button,button.width/2,button.height/2);check(mock.requests.length===0,"click deleted task");
   input.mousePress(button,button.width/2,button.height/2);
  }else if(stage===2){
   input.mouseRelease(button,button.width/2,button.height/2);check(mock.requests.length===0&&button.progress===0,"short hold deleted task");
   button.forceActiveFocus();input.keyPress(Qt.Key_Space);
  }else if(stage===3){drawer.active=false;input.keyRelease(Qt.Key_Space);
  }else if(stage===7){
   check(mock.requests.length===0&&button.progress===0,"dismissal deleted task");drawer.active=true;drawer.edit("VTODO",task);
  }else if(stage===8)input.mousePress(button,button.width/2,button.height/2);
  else if(stage===13){
   check(mock.requests.length===1&&mock.requests[0].op==="delete"&&mock.requests[0].kind==="VTODO"&&mock.requests[0].entry.collection==="personal","task hold did not delete exactly once");
   input.mouseRelease(button,button.width/2,button.height/2);input.mousePress(button,button.width/2,button.height/2);
  }else if(stage===14)drawer.edit("VEVENT",event);
  else if(stage===18){
   check(mock.requests.length===1&&button.progress===0,"switching edited item completed old hold");input.mouseRelease(button,button.width/2,button.height/2);
   check(button.hint==="Hold to delete event","event deletion label missing");button.forceActiveFocus();input.keyPress(Qt.Key_Space);
  }else if(stage===23){
   check(mock.requests.length===2&&mock.requests[1].kind==="VEVENT"&&mock.requests[1].entry.collection==="personal","keyboard hold did not delete event exactly once");input.keyRelease(Qt.Key_Space);
   drawer.edit("VEVENT",Object.assign({},event,{editable:false}));
  }else if(stage===24){
   check(!button.visible,"read-only event permits deletion");console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}""")

    def test_service_month_reply_and_write_survive_dismissal(self):
        def setup(root):
            (root / 'drawers/events/backend.py').write_text("""import json,sys,time
r=json.loads(sys.stdin.readline())
time.sleep(.25)
if r['op']=='save':
 print(json.dumps(dict(ok=True,data=dict(saved=True,href='https://cloud.example/tasks/new.ics',account_id='',reconcile=True))),flush=True)
else:
 print(json.dumps(dict(ok=True,data=dict(state='ready',events=[],tasks=[],calendars=[],month=r['start'][:7],due=False,stale=False,updated=1))),flush=True)
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/events"
ShellRoot {
 property var service:CalendarService
 property int stage:0
 property int ticks:0
 property int saves:0
 Component.onCompleted:{service.month="2026-10";service.active=true;}
 Connections{target:CalendarService;function onSaved(){saves++;}}
 function check(v,m){if(!v)throw Error(m);}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  ticks++;
  if(stage===0&&service.busy){service.month="2026-11";stage++;}
  else if(stage===1&&service.state.month==="2026-11"&&!service.busy){
   check(service.month==="2026-11","late month reply won");
   service.mutate("save","VTODO",{summary:"Test"});
   check(service.busy,"write did not start");service.active=false;stage++;
  }else if(stage===2&&saves===1&&!service.busy){
   check(!service.active&&!service.timer.running,"dismissal left observation active");
   check(service.pending==="fetch","successful closed write did not invalidate");
   service.active=true;stage++;
  }else if(stage===3&&!service.busy&&service.state.month==="2026-11"){
   check(saves===1,"write was replayed");service.active=false;
   console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>65)throw Error("timeout stage "+stage+" "+service.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_status_changes_do_not_move_calendar_task_controls_or_editor(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers"
ShellRoot {
 QtObject {
  id:mock
  property bool active:false
  property bool busy:false
  property bool writing:false
  property string month:"2026-10"
  property string error:""
  property var base:({state:"ready",stale:false,updated:0,calendars:[{name:"Personal",slug:"personal",components:["VEVENT","VTODO"],writable:true,events_enabled:true,tasks_enabled:true}],events:[{summary:"Meeting",date:"2026-10-21",last_date:"2026-10-21",start:"2026-10-21T09:00:00Z",end:"2026-10-21T10:00:00Z",calendar:"Personal"}],tasks:[{uid:"task",summary:"Task",list:"Personal",list_slug:"personal",editable:true,actionable:true,completed:false,description:"",due:"",categories:"",priority:0,percent:0}]})
  property var state:base
  function refresh(force){}
  function mutate(op,kind,entry,completed){}
  signal saved()
 }
 FloatingWindow {implicitWidth:480;implicitHeight:820
  EventsDrawer{id:drawer;width:parent.width;height:parent.height;active:true;service:mock;selectedDate:"2026-10-21"}
 }
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 property int mode:0
 property int step:-1
 property var baseline:({})
 property var cases:[{state:"loading"},{busy:true},{stale:true,updated:1792000000},{error:"Connection failed. ".repeat(35)},{state:"unconfigured"},{state:"needs_password"},{state:"unavailable"},{events:[],tasks:[]},{}]
 function prepare(){
  mock.state=mock.base;mock.error="";mock.busy=false;
  drawer.editing=null;drawer.width=mode<3?480:268;
  drawer.tab=mode%3===0?"calendar":"tasks";
  if(mode%3===2)drawer.edit("VTODO",mock.base.tasks[0]);
 }
 function positions(){
  const names=mode%3===0?["calendarNavigation","calendarDay:2026-10-21","agendaHeading","sectionStatus","agendaDate:2026-10-21"]
    :mode%3===1?["agendaHeading","sectionStatus","taskSearch","taskRow:task"]:["editorStatus","itemTitle"];
  const result={};
  for(const name of names){const item=find(drawer,name);if(item)result[name]=[item.mapToItem(drawer,0,0).y,item.height];}
  return result;
 }
 function apply(value){mock.error=value.error||"";mock.busy=!!value.busy;mock.state=Object.assign({},mock.base,value);}
 Component.onCompleted:prepare()
 Timer{interval:85;repeat:true;running:true;onTriggered:{try{
  if(step===-1){baseline=positions();step=0;apply(cases[step]);return;}
  const current=positions();
  for(const name in current){check(baseline[name]&&Math.abs(current[name][0]-baseline[name][0])<1&&Math.abs(current[name][1]-baseline[name][1])<1,"status moved "+name+" in mode "+mode+" case "+step);}
  const status=find(drawer,mode%3===2?"editorStatus":"sectionStatus");
  if(mode%3!==2&&step===0)check(status.text===(drawer.tab==="tasks"?"Loading tasks…":"Loading agenda…"),"wrong section loading message");
  if(step===3)check(status.text.includes("Connection failed."),"error was hidden");
  step++;
  if(step<cases.length)apply(cases[step]);
  else if(++mode<6){step=-1;prepare();}
  else{drawer.active=false;console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:9000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",mode,step);Qt.quit();}}
}""")

    def test_background_warm_optimistic_queue_and_failure_preserve_other_rows(self):
        def setup(root):
            (root / 'drawers/events/backend.py').write_text("""import json,sys,time
from pathlib import Path
r=json.loads(sys.stdin.readline());p=Path(__file__).with_name('fixture-state.json')
def load():
 if p.exists():return json.loads(p.read_text())
 return dict(state='ready',account_id='fixture',due=False,stale=False,eventsReady=True,tasksReady=True,updated=1,calendars=[dict(name='Tasks',slug='tasks',components=['VTODO'],writable=True,tasks_enabled=True,events_enabled=False)],events=[],tasks=[dict(uid=uid,href='https://cloud.example/tasks/'+uid+'.ics',etag='"1"',summary=uid.upper(),list='Tasks',list_slug='tasks',completed=False,actionable=True,editable=True,recurring=False,description='',due='',categories='',priority=0,percent=0) for uid in ['a','b','c']])
data=load()
if r['op'] in ('status','fetch'):
 if r['op']=='fetch':time.sleep(.9)
 data['month']=r['start'][:7]
 print(json.dumps(dict(ok=True,data=data)),flush=True)
else:
 time.sleep(.2)
 e=r['entry']
 if e['uid']=='b':print(json.dumps(dict(ok=False,error='Fixture conflict')),flush=True)
 else:
  row=next(row for row in data['tasks'] if row['href']==e['href'])
  row.update(completed=r['completed'],etag='"2"',percent=100 if r['completed'] else 0)
  p.write_text(json.dumps(data))
  print(json.dumps(dict(ok=True,data=dict(saved=True,href=e['href'],account_id='fixture',tasks=[row],events=[]))),flush=True)
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers"
import "drawers/events"
ShellRoot {
 property var service:CalendarService
 property var stableRow:null
 property var stableButton:null
 property int stage:0
 property int ticks:0
 property int saves:0
 Component.onCompleted:{service.month="2026-10";service.start();}
 Connections{target:CalendarService;function onSaved(){saves++;}}
 FloatingWindow{implicitWidth:480;implicitHeight:820;EventsDrawer{id:drawer;width:parent.width;height:parent.height;service:CalendarService;tab:"tasks"}}
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 function task(uid){return service.state.tasks.find(row=>row.uid===uid);}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  ticks++;
  if(stage===0&&service.state.tasks.length===3&&!service.busy){
   check(!service.active,"background warm needed an open drawer");drawer.active=true;stage++;
  }else if(stage===1&&!service.busy){
   stableRow=find(drawer,"taskRow:c");stableButton=find(drawer,"taskEdit:c");stableButton.forceActiveFocus();
   service.refresh(true);stage++;
  }else if(stage===2&&service.fetching){
   find(drawer,"taskComplete:a").clicked();
   service.mutate("complete","VTODO",Object.assign({},task("b"),{collection:"tasks"}),true);
   check(task("a").completed&&task("b").completed&&service.transactions.length===2,"optimism/queue waited for refresh");stage++;
  }else if(stage===3&&saves===1&&!service.writing&&service.transactions.length===0){
   check(task("a").completed&&!task("b").completed,"failure did not roll back only its own task");
   check(task("a").etag==='"2"',"changed resource did not get fresh ETag");stage++;
  }else if(stage===4&&!service.busy){
   check(task("a").completed&&!task("b").completed,"late refresh undid newer write");
   check(find(drawer,"taskRow:c")===stableRow&&find(drawer,"taskEdit:c")===stableButton&&stableButton.activeFocus,"unaffected row/focus was recreated");
   check(service.error.startsWith("Could not complete task: Fixture conflict"),"failure reason hidden behind task title");
   drawer.active=false;console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>90)throw Error("timeout "+stage+" "+service.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_instant_cached_month_and_optimistic_editor_draft_recovery(self):
        def setup(root):
            (root / 'drawers/events/backend.py').write_text("""import json,sys,time
r=json.loads(sys.stdin.readline())
if r['op'] in ('status','fetch'):
 print(json.dumps(dict(ok=True,data=dict(state='ready',account_id='fixture',month=r['start'][:7],eventsReady=True,tasksReady=True,events=[],tasks=[],calendars=[dict(name='Tasks',slug='tasks',components=['VTODO'],writable=True,tasks_enabled=True,events_enabled=False)],due=False,stale=False,updated=1))),flush=True)
else:
 time.sleep(.25)
 print(json.dumps(dict(ok=False,error='Cannot save fixture')),flush=True)
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers"
import "drawers/events"
ShellRoot {
 property var service:CalendarService
 property int stage:0
 property int ticks:0
 Component.onCompleted:{service.month="2026-10";service.start();}
 FloatingWindow{implicitWidth:480;implicitHeight:820;EventsDrawer{id:drawer;width:parent.width;height:parent.height;service:CalendarService;tab:"tasks"}}
 function check(v,m){if(!v)throw Error(m);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const result=find(child,name);if(result)return result;}return null;}
 Timer{interval:70;repeat:true;running:true;onTriggered:{try{
  ticks++;
  if(stage===0&&service.state.month==="2026-10"&&!service.busy){service.month="2026-11";stage++;}
  else if(stage===1&&service.state.month==="2026-11"&&!service.busy){
   service.month="2026-10";check(service.state.month==="2026-10"&&service.state.eventsReady,"cached month was blanked");drawer.active=true;stage++;
  }else if(stage===2&&!service.busy){
   drawer.edit("VTODO",{});
   service.mutate("save","VTODO",{summary:"Keep my draft",description:"Private notes",due:"2026-10-29",status:"NEEDS-ACTION",collection:"tasks"});
   check(drawer.editing===null&&service.state.tasks[0].summary==="Keep my draft","editor/list waited for server");stage++;
  }else if(stage===3&&service.failedDraft&&!service.writing){
   check(service.state.tasks.length===0,"failed create was not rolled back");
   check(drawer.editing?.description==="Private notes"&&drawer.editing?.due==="2026-10-29","draft lost on failure");stage++;
  }else if(stage===4){
   check(find(drawer,"itemTitle").text==="Keep my draft","failed editor did not restore fields");
   check(service.failedDraft.entry.description==="Private notes","failed draft did not survive in service");
   drawer.active=false;console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>65)throw Error("timeout "+stage+" "+service.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_successful_reopen_event_create_and_delete_do_not_refetch_lists(self):
        def setup(root):
            (root / 'drawers/events/backend.py').write_text("""import json,sys,time
from pathlib import Path
r=json.loads(sys.stdin.readline());p=Path(__file__).with_name('fixture.json')
data=json.loads(p.read_text()) if p.exists() else dict(state='ready',account_id='fixture',due=False,stale=False,updated=1,eventsReady=True,tasksReady=True,calendars=[dict(name='Personal',slug='personal',components=['VTODO','VEVENT'],writable=True,tasks_enabled=True,events_enabled=True)],tasks=[dict(uid='a',summary='Task',href='https://cloud.example/personal/a.ics',etag='"1"',completed=True,description='',due='',list='Personal',list_slug='personal')],events=[])
if r['op'] in ('status','fetch'):
 print(json.dumps(dict(ok=True,data=data)),flush=True)
else:
 time.sleep(.16)
 e=r['entry'];href=e.get('href') or 'https://cloud.example/personal/new.ics'
 if r['op']=='complete':
  data['tasks'][0].update(completed=r['completed'],etag='"2"');rows=data['tasks']
 elif r['op']=='save':
  data['events']=[dict(summary=e['summary'],href=href,etag='"2"',start='2026-10-21T00:00:00Z',end='2026-10-23T00:00:00Z',date='2026-10-21',last_date='2026-10-22',all_day=True,calendar='Personal',calendar_slug='personal',editable=True)];rows=data['events']
 else:data['events']=[];rows=[]
 p.write_text(json.dumps(data))
 print(json.dumps(dict(ok=True,data=dict(saved=True,href=href,account_id='fixture',tasks=rows if r['kind']=='VTODO' else [],events=rows if r['kind']=='VEVENT' else []))),flush=True)
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/events"
ShellRoot {
 property var service:CalendarService
 property int stage:0
 property int ticks:0
 property int saves:0
 property int fullReads:0
 Component.onCompleted:{service.month="2026-10";service.start();}
 Connections{target:CalendarService;function onSaved(){saves++;}}
 Connections{target:CalendarService.fetcher;function onRunningChanged(){if(CalendarService.fetcher.running)fullReads++;}}
 function check(v,m){if(!v)throw Error(m);}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  ticks++;
  if(stage===0&&service.state.tasksReady&&!service.busy){
   const row=service.state.tasks[0];service.mutate("complete","VTODO",Object.assign({},row,{collection:"personal"}),false);
   check(!service.state.tasks[0].completed&&service.state.tasks[0]._pending,"reopen waited for server");stage++;
  }else if(stage===1&&saves===1&&!service.busy){
   service.mutate("save","VEVENT",{summary:"Appointment",collection:"personal",start_date:"2026-10-21",end_date:"2026-10-22",all_day:true});
   check(service.state.events[0].summary==="Appointment"&&service.state.events[0].last_date==="2026-10-22","event create waited for server");stage++;
  }else if(stage===2&&saves===2&&!service.busy){
   const event=service.state.events[0];check(event.etag==='"2"'&&!event._pending,"event was not reconciled");
   service.mutate("delete","VEVENT",Object.assign({},event,{collection:"personal"}));check(service.state.events.length===0,"delete waited for server");stage++;
  }else if(stage===3&&saves===3&&!service.busy){
   check(fullReads===0,"successful write forced whole-list refresh");console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>60)throw Error("timeout "+stage+" "+service.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )

    def test_workers_that_cannot_start_release_the_queue(self):
        # Quickshell reports a failed start without an exited signal.
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        with patch.dict(os.environ, PATH=empty):
            self.run_qml("""import QtQuick
import Quickshell
import "drawers/events"
ShellRoot {
 property var service:CalendarService
 property int stage:0
 property int ticks:0
 property int failures:0
 Component.onCompleted:service.start()
 Connections{target:CalendarService;function onWriteFailed(){failures++;}}
 function check(v,m){if(!v)throw Error(m);}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  ticks++;
  if(stage===0&&!service.busy){
   check(service.error!=="","failed read start was silent");
   service.mutate("save","VTODO",{summary:"Kept"});stage++;
  }else if(stage===1&&!service.busy){
   check(failures===1&&!service.transactions.length&&service.failedDraft?.entry.summary==="Kept","failed write start wedged the queue");
   service.refresh(true);check(service.fetching,"manual refresh did not start");stage++;
  }else if(stage===2&&!service.busy){console.log("DISPLAY_PASS");Qt.quit();}
  if(ticks>60)throw Error("timeout "+stage);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""")

    def test_current_day_follows_a_running_shell(self):
        self.run_qml("""import QtQuick
import Quickshell
import "drawers"
import "drawers/events"
ShellRoot {
 QtObject {
  id:mock
  property bool active:false
  property string month:"2026-10"
  property string today:"2026-10-31"
  property string error:""
  property var state:({state:"ready",eventsReady:true,tasksReady:true,calendars:[],events:[],tasks:[{uid:"t",summary:"Pay rent",due:"2026-11-01",list:"Tasks",list_slug:"tasks",completed:false,actionable:true,editable:true}]})
  function refresh(force){}
 }
 FloatingWindow{implicitWidth:480;implicitHeight:820;EventsDrawer{id:drawer;anchors.fill:parent;service:mock;active:true;tab:"tasks";taskFilter:"Today"}}
 function check(v,m){if(!v)throw Error(m);}
 function at(day){return ()=>new Date(day+"T00:01:00");}
 Timer{interval:200;running:true;onTriggered:{try{
  const service=CalendarService;
  service.clock=at("2026-10-31");service.tick();
  check(service.today==="2026-10-31"&&service.month==="2026-10","service did not adopt the current day");
  service.clock=at("2026-11-01");service.tick();
  check(service.today==="2026-11-01"&&service.month==="2026-11","current month did not follow midnight");
  service.month="2027-01";service.clock=at("2026-12-01");service.tick();
  check(service.today==="2026-12-01"&&service.month==="2027-01","a chosen month moved");
  check(drawer.selectedDate==="2026-10-31"&&drawer.visibleTasks.length===0,"drawer ignored the service day");
  mock.today="2026-11-01";mock.month="2026-11";
  check(drawer.selectedDate==="2026-11-01"&&drawer.visibleTasks.length===1,"drawer did not follow the day");
  console.log("DISPLAY_PASS");
 }catch(e){console.error("DISPLAY_FAIL",e);}Qt.quit();}}
}""")

    def test_optimistic_order_failed_reads_and_retried_draft_identity(self):
        def setup(root):
            (root / 'drawers/events/backend.py').write_text("""import json,sys
r=json.loads(sys.stdin.readline())
def event(name,start,end):return dict(summary=name,href='https://cloud.example/p/'+name+'.ics',etag='"1"',start=start,end=end,date=start[:10],last_date=end[:10],all_day=False,calendar='P',calendar_slug='p',editable=True)
if r['op']=='status':
 print(json.dumps(dict(ok=True,data=dict(state='ready',account_id='fixture',eventsReady=True,tasksReady=True,updated=1,stale=False,due=False,calendars=[dict(name='P',slug='p',components=['VEVENT'],writable=True,events_enabled=True,tasks_enabled=False)],tasks=[],events=[event('utc','2026-10-21T10:00:00+00:00','2026-10-21T11:00:00+00:00'),event('zoned','2026-10-21T09:00:00-04:00','2026-10-21T10:00:00-04:00')]))))
elif r['op']=='fetch':print(json.dumps(dict(ok=False,error='Offline')))
else:print(json.dumps(dict(ok=False,error='Timed out '+r['entry'].get('create_id',''))))
""")

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/events"
ShellRoot {
 property var service:CalendarService
 property int stage:0
 property int ticks:0
 property string identity:""
 Component.onCompleted:{service.month="2026-10";service.start();}
 function check(v,m){if(!v)throw Error(m);}
 function names(){return service.state.events.map(row=>row.summary).join(",");}
 Timer{interval:60;repeat:true;running:true;onTriggered:{try{
  ticks++;
  if(stage===0&&service.state.eventsReady&&!service.busy){
   service.mutate("save","VEVENT",{summary:"Later",collection:"p",start_date:"2026-10-22",start_time:"09:00",end_date:"2026-10-22",end_time:"10:00"});
   check(names()==="utc,zoned,Later","optimistic sort compared offset strings: "+names());stage++;
  }else if(stage===1&&service.failedDraft&&!service.busy){
   identity=service.failedDraft.entry.create_id;
   check(/^[0-9a-f]{32}$/.test(identity)&&service.error.includes(identity),"create had no draft identity");
   check(service.state.stale&&names()==="utc,zoned","failed refresh left cached rows marked current");
   service.mutate("save","VEVENT",service.failedDraft.entry);stage++;
  }else if(stage===2&&service.failedDraft&&!service.busy){
   check(service.error.includes("Timed out "+identity),"retry used a new identity");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  if(ticks>60)throw Error("timeout "+stage+" "+service.error);
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
}""",
            setup,
        )
