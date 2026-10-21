"""Private shared accounts, DAV conflicts/recurrence, caching and production drawers."""
import copy
from datetime import datetime, timezone
import importlib.util
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
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import test_display_drawer as fixtures

DESKTOP = fixtures.DESKTOP
sys.path.insert(0, str(DESKTOP))
from integrations import nextcloud as accounts
from integrations import import_account
from drawers.events import backend, caldav


def account():
    return dict(url='https://cloud.example/nextcloud/', username='alice',
                credentials={'dav': dict(provider='file', file='app-password')}, capabilities={'dav': dict(credential='dav')})


def todo(*lines):
    return '\r\n'.join(['BEGIN:VCALENDAR', 'VERSION:2.0', 'BEGIN:VTODO', 'UID:task-1', 'SUMMARY:Test', *lines, 'END:VTODO', 'END:VCALENDAR', ''])


def collection():
    return dict(name='Tasks', slug='tasks', url='https://cloud.example/tasks/', writable=True, components={'VTODO'})


class AccountTests(unittest.TestCase):
    def test_shared_credentials_and_transport_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / 'credentials/nextcloud/app-password'; secret.parent.mkdir(parents=True)
            secret.write_text('example-secret'); secret.chmod(0o600)
            self.assertEqual(accounts.credential(account(), root=root), 'example-secret')
            secret.chmod(0o644)
            with self.assertRaises(accounts.NextcloudError): accounts.credential(account(), root=root)
            secret.unlink(); secret.symlink_to(root / 'another')
            with self.assertRaises(accounts.NextcloudError): accounts.credential(account(), root=root)
        with patch.object(accounts, 'credential', return_value='example-secret'):
            client = caldav.Client(account(), opener=Mock())
        for url in ['http://cloud.example/', 'https://evil.example/', client.home + '../bob/a.ics', client.home + '%2e%2e/bob/a.ics', client.home + 'x.ics?x=1', client.home.replace('alice/', 'alice2/')]:
            with self.subTest(url=url), self.assertRaises(accounts.NextcloudError): client.request('GET', url)
        client.opener.open.assert_not_called()

    def test_dav_errors_explain_data_rejection_without_exposing_response_body(self):
        with patch.object(accounts, 'credential', return_value='example-secret'):
            client = caldav.Client(account(), opener=Mock())
        for code in (400, 415, 422):
            client.opener.open.side_effect = HTTPError(client.home, code, 'Rejected', {}, io.BytesIO(b'private server details'))
            with self.subTest(code=code), self.assertRaisesRegex(accounts.NextcloudError, rf'rejected the submitted data \(HTTP {code}\)') as raised:
                client.request('PUT', client.home + 'task.ics', b'calendar')
            self.assertNotIn('private', str(raised.exception))
            client.opener.open.side_effect.close()

    def test_config_references_and_provider_are_validated(self):
        for url in ['http://cloud.example', 'https://alice:password@cloud.example', 'https://cloud.example/%2e%2e/']:
            with self.assertRaises(accounts.NextcloudError): accounts.validate_account(dict(account(), url=url))
        for file in ['../secret', '/tmp/secret', 'a/./secret']:
            config = account(); config['credentials']['dav']['file'] = file
            with self.assertRaises(accounts.NextcloudError): accounts.validate_account(config)
        with self.assertRaises(accounts.NextcloudError): caldav.selection(dict(calendars=[42]), 'calendars')

    def test_import_privacy_conflicts_and_originals_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source'; source.mkdir()
            config = source/'nextcloud.json'; config.write_text(json.dumps(account()))
            secret = source/'credentials/nextcloud/app-password'; secret.parent.mkdir(parents=True)
            secret.write_text('test-secret'); secret.chmod(0o755)
            destination = root/'destination/integrations'
            import_account.install(config, destination=destination)
            target = destination/'credentials/nextcloud/app-password'
            self.assertEqual(target.read_text(), 'test-secret')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(secret.stat().st_mode & 0o777, 0o755)
            import_account.install(config, destination=destination)
            secret.write_text('different-secret')
            with self.assertRaises(ValueError): import_account.install(config, destination=destination)
            self.assertEqual(target.read_text(), 'test-secret')


class CalendarTests(unittest.TestCase):
    def client(self, data):
        client = caldav.Client.__new__(caldav.Client)
        client.propfind = lambda: [collection()]
        client.request = Mock(return_value=(data.encode(), {'ETag': '"1"'}))
        return client

    def test_future_recurring_and_completed_tasks_remain_available(self):
        entries = [('https://cloud.example/tasks/a.ics', '"1"', todo('DUE;VALUE=DATE:20301022', 'RRULE:FREQ=YEARLY', 'PRIORITY:1', 'PERCENT-COMPLETE:25', 'CATEGORIES:home,work', 'RELATED-TO:parent')),
                   ('https://cloud.example/tasks/b.ics', '"1"', todo('STATUS:COMPLETED', 'PERCENT-COMPLETE:100'))]
        rows = caldav.tasks_from(entries, collection(), ZoneInfo('UTC'))
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0]['actionable']); self.assertTrue(rows[0]['recurring'])
        self.assertEqual((rows[0]['priority'], rows[0]['percent'], rows[0]['parent']), (1, 25, 'parent'))
        self.assertTrue(rows[1]['completed'])

    def test_rich_task_create_and_validation(self):
        fields = caldav.entry_fields('VTODO', dict(summary='Water plants\r\nnot a property', description='notes', start_date='2026-10-21', start_time='08:30', due='2026-10-22', due_time='09:15', priority=2, percent=40, status='IN-PROCESS', categories='home, plants', parent='parent', recurrence_rule='FREQ=WEEKLY;INTERVAL=2;COUNT=4'))
        self.assertIn('RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=4', fields)
        self.assertIn('PERCENT-COMPLETE:40', fields)
        self.assertTrue(any(line.startswith('DUE:') for line in fields))
        self.assertFalse(any('\r' in line or '\n' in line for line in fields))
        for values in [dict(priority=10), dict(percent=-1), dict(recurrence_rule='FREQ=SECONDLY', due='2026-10-22'), dict(recurrence_rule='FREQ=DAILY'), dict(start_date='2026-10-23', due='2026-10-22')]:
            with self.subTest(values=values), self.assertRaises(ValueError): caldav.entry_fields('VTODO', dict(summary='Test', **values))

    def test_completion_and_reopening_replace_existing_modification_timestamp(self):
        original = todo('DTSTAMP:20260101T000000Z', 'LAST-MODIFIED:20260101T000000Z',
                        'DESCRIPTION:Keep this', 'BEGIN:VALARM', 'ACTION:DISPLAY',
                        'TRIGGER:-PT15M', 'END:VALARM')
        entry = dict(collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"1"')
        for completed in (True, False, True):
            client = self.client(original)
            client.set_completed({}, entry, completed)
            updated = client.request.call_args.args[2].decode()
            props = caldav.components(updated)[0][1]
            self.assertEqual(len(props['LAST-MODIFIED']), 1)
            self.assertEqual(caldav.first(props, 'STATUS')[1], 'COMPLETED' if completed else 'NEEDS-ACTION')
            self.assertEqual('COMPLETED' in props, completed)
            self.assertIn('DESCRIPTION:Keep this', updated)
            self.assertIn('TRIGGER:-PT15M', updated)
            original = updated

    def test_recurrence_completion_is_atomic_preserves_alarm_and_count(self):
        data = todo('LAST-MODIFIED:20260101T000000Z', 'DUE;VALUE=DATE:20261021', 'DTSTART;VALUE=DATE:20261020', 'RRULE:FREQ=DAILY;COUNT=3', 'X-CUSTOM:keep', 'BEGIN:VALARM', 'ACTION:DISPLAY', 'TRIGGER:-PT15M', 'END:VALARM')
        client = self.client(data)
        entry = dict(collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"1"')
        client.set_completed({}, entry, True)
        writes = [call for call in client.request.call_args_list if call.args[0] == 'PUT']
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0].args[3]['If-Match'], '"1"')
        text = writes[0].args[2].decode()
        records = [props for kind, props in caldav.components(text)]
        self.assertEqual(len(records), 2)
        master, done = records
        self.assertTrue(all(len(props['LAST-MODIFIED']) == 1 for props in records))
        self.assertEqual(caldav.first(master, 'DUE')[1], '20261022')
        self.assertEqual(caldav.first(master, 'DTSTART')[1], '20261021')
        self.assertEqual(caldav.first(master, 'RRULE')[1], 'FREQ=DAILY;COUNT=2')
        self.assertEqual(caldav.first(done, 'RECURRENCE-ID')[1], '20261021')
        self.assertEqual(caldav.first(done, 'STATUS')[1], 'COMPLETED')
        self.assertEqual(text.count('X-CUSTOM:keep'), 2)
        self.assertEqual(text.count('BEGIN:VALARM'), 2)
        # A second completion must retain the first exception and advance once.
        updated = caldav.advance_task(text, master)
        self.assertEqual(updated.count('BEGIN:VTODO'), 3)
        updated_records = [props for kind, props in caldav.components(updated)]
        self.assertTrue(all(len(props['LAST-MODIFIED']) == 1 for props in updated_records))
        self.assertEqual(updated_records[1]['LAST-MODIFIED'], done['LAST-MODIFIED'])
        self.assertIn('DUE;VALUE=DATE:20261023', updated)

    def test_last_occurrence_until_and_dst(self):
        for rule in ('FREQ=DAILY;COUNT=1', 'FREQ=DAILY;UNTIL=20261021'):
            data = todo('DUE;VALUE=DATE:20261021', 'RRULE:' + rule)
            props = caldav.components(data)[0][1]
            updated = caldav.advance_task(data, props)
            self.assertIn('STATUS:COMPLETED', updated)
            self.assertEqual(updated.count('BEGIN:VTODO'), 1)
        data = todo('DUE;TZID=America/New_York:20261031T090000', 'RRULE:FREQ=DAILY;COUNT=3')
        updated = caldav.advance_task(data, caldav.components(data)[0][1])
        self.assertIn('DUE;TZID=America/New_York:20261101T090000', updated)

    def test_conflict_read_only_and_reopen(self):
        entry = dict(collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"old"')
        client = self.client(todo('STATUS:COMPLETED'))
        with self.assertRaisesRegex(accounts.NextcloudError, 'changed'): client.set_completed({}, entry, False)
        self.assertEqual([call.args[0] for call in client.request.call_args_list], ['GET'])
        entry['etag'] = '"1"'
        client.request.reset_mock(); client.set_completed({}, entry, False)
        self.assertIn(b'STATUS:NEEDS-ACTION', client.request.call_args.args[2])
        self.assertNotIn(b'COMPLETED:', client.request.call_args.args[2])
        with self.assertRaises(accounts.NextcloudError): client.delete_item(dict(task_lists=[]), 'VTODO', entry)

    def test_edit_master_preserves_exceptions_and_other_properties(self):
        data = todo('DUE;VALUE=DATE:20261021', 'RRULE:FREQ=WEEKLY', 'X-PRIVATE:keep')
        data = caldav.advance_task(data, caldav.components(data)[0][1])
        updated = caldav.update_ical(data, 'VTODO', ['SUMMARY:Changed'], {'SUMMARY'}).decode()
        self.assertEqual(updated.count('SUMMARY:Changed'), 1)
        self.assertIn('RECURRENCE-ID;VALUE=DATE:20261021', updated)
        self.assertEqual(updated.count('X-PRIVATE:keep'), 2)

    def test_edits_preserve_timezone_and_reject_parent_cycles(self):
        data = todo('DUE;TZID=America/New_York:20261031T090030', 'RRULE:FREQ=DAILY')
        moment, _ = caldav.date_value(caldav.first(caldav.components(data)[0][1], 'DUE'), ZoneInfo('UTC'))
        utc = moment.astimezone(timezone.utc).strftime('%Y%m%dT%H%M00Z')
        self.assertEqual(caldav.preserve_task_dates(data, ['DUE:' + utc]), ['DUE;TZID=America/New_York:20261031T090030'])
        client = self.client(data)
        child = todo('RELATED-TO:task-1').replace('UID:task-1', 'UID:child')
        client.report = Mock(return_value=[('a', '1', data), ('b', '1', child)])
        with self.assertRaisesRegex(accounts.NextcloudError, 'ancestor'):
            client.save_item({}, 'VTODO', dict(summary='Test', collection='tasks', uid='task-1', parent='child'))
        client.request.assert_not_called()

    def test_events_expand_recurrence_and_respect_exclusions(self):
        data = 'BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:e\nSUMMARY:Meeting\nDTSTART:20261020T090000Z\nDTEND:20261020T100000Z\nRRULE:FREQ=DAILY;COUNT=3\nEXDATE:20261021T090000Z\nEND:VEVENT\nEND:VCALENDAR'
        rows = caldav.events_from([('https://cloud.example/e.ics', '"1"', data)], collection(), datetime(2026,10,20,tzinfo=timezone.utc), datetime(2026,10,24,tzinfo=timezone.utc), ZoneInfo('UTC'))
        self.assertEqual([row['date'] for row in rows], ['2026-10-20', '2026-10-22'])
        self.assertFalse(rows[0]['editable'])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, XDG_CONFIG_HOME=self.tmp.name+'/config', XDG_CACHE_HOME=self.tmp.name+'/cache')
        env.start(); self.addCleanup(env.stop)
        folder = accounts.config_root(); folder.mkdir(parents=True)
        (folder/'nextcloud.json').write_text(json.dumps(account()))
        secret = folder/'credentials/nextcloud/app-password'; secret.parent.mkdir(parents=True)
        secret.write_text('test-secret'); secret.chmod(0o600)
        self.request = dict(op='status', start='2026-10-01', end='2026-11-01')

    def test_cached_open_failure_backoff_and_account_change(self):
        self.assertTrue(backend.handle(self.request)['due'])
        payload = dict(events=[], tasks=[], calendars=[], task_count=0)
        with patch.object(caldav, 'snapshot', return_value=payload) as fetch, patch.object(backend.time, 'time', return_value=1000):
            backend.handle(dict(self.request, op='fetch'))
            cached = backend.handle(self.request)
            self.assertFalse(cached['due']); self.assertEqual(fetch.call_count, 1)
        with patch.object(backend.time, 'time', return_value=2000), patch.object(caldav, 'snapshot', side_effect=accounts.NextcloudError('Offline')):
            result = backend.handle(dict(self.request, op='fetch'))
            self.assertTrue(result['stale']); self.assertEqual(result['error'], 'Offline')
            self.assertFalse(backend.handle(self.request)['due'])
        config = account(); config['username'] = 'bob'
        (accounts.config_root()/'nextcloud.json').write_text(json.dumps(config))
        self.assertEqual(backend.handle(self.request)['state'], 'loading')
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in backend.cache_root().glob('*.json')))

    def test_missing_account_and_credential_and_feature_cannot_override_account(self):
        (backend.config_root()/'calendar.json').write_text(json.dumps(dict(url='https://evil.example', calendars=[])))
        config, _, _ = backend.context(self.request)
        self.assertEqual(config['url'], account()['url'])
        self.assertEqual(config['calendars'], [])
        (accounts.config_root()/'credentials/nextcloud/app-password').unlink()
        self.assertEqual(backend.handle(self.request)['state'], 'needs_password')
        (accounts.config_root()/'nextcloud.json').unlink()
        self.assertEqual(backend.handle(self.request)['state'], 'unconfigured')

    def test_first_network_failure_backs_off_and_manual_refresh_recovers(self):
        with patch.object(backend.time, 'time', return_value=1000), patch.object(caldav, 'snapshot', side_effect=accounts.NextcloudError('Offline')):
            result = backend.handle(dict(self.request, op='fetch'))
            self.assertEqual(result['state'], 'unavailable')
            self.assertFalse(backend.handle(self.request)['due'])
        with patch.object(backend.time, 'time', return_value=1400):
            self.assertTrue(backend.handle(self.request)['due'])
        with patch.object(caldav, 'snapshot', return_value=dict(events=[],tasks=[],calendars=[])):
            self.assertEqual(backend.handle(dict(self.request, op='fetch'))['state'], 'ready')

    def seed(self):
        payload = dict(events=[], tasks=[dict(href='https://cloud.example/tasks/a.ics', uid='task-1', summary='First', due='', completed=False, etag='"1"'),
                                        dict(href='https://cloud.example/tasks/b.ics', uid='task-2', summary='Other', due='', completed=False, etag='"1"')], calendars=[], task_count=2)
        with patch.object(caldav, 'snapshot', return_value=payload):
            backend.handle(dict(self.request, op='fetch'))
            backend.handle(dict(self.request, op='fetch', start='2026-11-01', end='2026-12-01'))
        return payload

    def mutation(self):
        return dict(self.request, op='complete', kind='VTODO', completed=True,
                    entry=dict(collection='tasks', href='https://cloud.example/tasks/a.ics', etag='"1"', summary='First'),
                    account_id=backend.handle(self.request)['account_id'])

    def writer(self):
        client = Mock()
        client.set_completed.return_value = dict(saved=True, href='https://cloud.example/tasks/a.ics', collection=collection())
        client.request.return_value = (todo('STATUS:COMPLETED', 'PERCENT-COMPLETE:100').encode(), {'ETag': '"2"'})
        return client

    def test_writes_patch_all_month_caches_and_return_only_changed_resource(self):
        self.seed(); client = self.writer()
        with patch.object(caldav, 'Client', return_value=client), patch.object(caldav, 'snapshot') as network:
            response = backend.handle(self.mutation())
            network.assert_not_called()
        self.assertEqual(len(response['tasks']), 1)
        self.assertEqual(response['tasks'][0]['etag'], '"2"')
        for start, end in [('2026-10-01','2026-11-01'), ('2026-11-01','2026-12-01')]:
            state = backend.handle(dict(self.request,start=start,end=end))
            self.assertEqual(len(state['tasks']), 2)
            self.assertTrue(next(row for row in state['tasks'] if row['uid']=='task-1')['completed'])
            self.assertFalse(next(row for row in state['tasks'] if row['uid']=='task-2')['completed'])
        self.assertEqual(client.request.call_args_list[0].args, ('GET','https://cloud.example/tasks/a.ics'))
        self.assertEqual(len(list(backend.cache_root().glob('*.json'))), 2)
        self.assertEqual(backend.revision() % 2, 0)

    def test_slow_refresh_does_not_block_cache_or_overwrite_confirmed_write(self):
        payload = self.seed(); entered = threading.Event(); release = threading.Event()
        def fetch(*args, **kwargs):
            entered.set(); release.wait(4); return copy.deepcopy(payload)
        with ThreadPoolExecutor(max_workers=2) as executor, patch.object(caldav,'snapshot',side_effect=fetch), patch.object(caldav,'Client',return_value=self.writer()):
            slow = executor.submit(backend.handle, dict(self.request, op='fetch'))
            self.assertTrue(entered.wait(1))
            try:
                cached = executor.submit(backend.handle, self.request).result(timeout=1)
                self.assertEqual(len(cached['tasks']),2)
                backend.handle(self.mutation())
            finally:
                release.set()
            self.assertTrue(slow.result(timeout=2)['superseded'])
        state = backend.handle(self.request)
        self.assertTrue(next(row for row in state['tasks'] if row['uid']=='task-1')['completed'])

    def test_failed_write_retains_cache_and_unknown_readback_never_replays_put(self):
        original = self.seed(); client = self.writer()
        client.set_completed.side_effect = accounts.NextcloudError('Conflict')
        with patch.object(caldav,'Client',return_value=client), self.assertRaisesRegex(accounts.NextcloudError,'Conflict'):
            backend.handle(self.mutation())
        cached = backend.handle(self.request)
        self.assertEqual(cached['tasks'],original['tasks']); self.assertTrue(cached['stale']); self.assertTrue(cached['due'])
        client.set_completed.side_effect = None
        client.request.side_effect = accounts.NextcloudError('Offline')
        with patch.object(caldav,'Client',return_value=client):
            result = backend.handle(self.mutation())
        self.assertTrue(result['saved']); self.assertTrue(result['reconcile'])
        self.assertEqual(client.set_completed.call_count,2)  # One explicit attempt per user request.
        self.assertEqual(backend.revision() % 2,0)

    def test_cached_tasks_survive_uncached_month_and_failure_does_not_fake_coverage(self):
        self.seed()
        other = dict(self.request,start='2030-01-01',end='2030-02-01')
        state = backend.handle(other)
        self.assertTrue(state['tasksReady']); self.assertFalse(state['eventsReady']); self.assertTrue(state['due'])
        with patch.object(caldav,'snapshot',side_effect=accounts.NextcloudError('Offline')):
            failed = backend.handle(dict(other,op='fetch'))
        self.assertEqual(len(failed['tasks']),2)
        self.assertFalse(failed['eventsReady']); self.assertFalse(failed['due'])
        self.assertFalse(backend.handle(other)['due'])

    def test_queued_write_cannot_switch_to_another_account(self):
        self.seed(); request = self.mutation()
        config = account(); config['username']='bob'
        (accounts.config_root()/'nextcloud.json').write_text(json.dumps(config))
        with patch.object(caldav,'Client') as client, self.assertRaisesRegex(accounts.NextcloudError,'account'):
            backend.handle(request)
        client.assert_not_called()

    def test_task_cache_is_global_and_terminated_writer_recovers_without_retry(self):
        self.seed()
        _, path, _ = backend.context(dict(self.request,start='2026-11-01',end='2026-12-01'))
        cached=backend.read_cache(path)
        cached['data']['tasks'][0]['summary']='Updated in another month'
        cached['fetched']+=1
        backend.atomic_json(path,cached)
        self.assertEqual(backend.handle(self.request)['tasks'][0]['summary'],'Updated in another month')
        with backend.locked(): backend.bump_revision()
        with backend.locked('write.lock'):
            backend.handle(self.request)
            self.assertEqual(backend.revision() % 2,1)
        state=backend.handle(self.request)
        self.assertEqual(backend.revision() % 2,0)
        self.assertTrue(state['stale']);self.assertTrue(state['due'])


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class CalendarQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            shutil.copytree(DESKTOP/'integrations', root/'integrations')
            if setup: setup(root)
        return fixtures.DisplayQmlTests.run_qml(self, body, prepare)

    def test_drawer_tabs_editor_and_notifications_load(self):
        self.run_qml('''import QtQuick
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
}''')

    def test_task_editor_toolbar_stays_visible(self):
        self.run_qml('''import QtQuick
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
}''')

    def test_task_and_event_deletion_requires_hold_and_cancels_on_context_change(self):
        self.run_qml('''import QtQuick
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
}''')

    def test_service_month_reply_and_write_survive_dismissal(self):
        def setup(root):
            (root/'drawers/events/backend.py').write_text("""import json,sys,time
r=json.loads(sys.stdin.readline())
time.sleep(.25)
if r['op']=='save':
 print(json.dumps(dict(ok=True,data=dict(saved=True))),flush=True)
else:
 print(json.dumps(dict(ok=True,data=dict(state='ready',events=[],tasks=[],calendars=[],month=r['start'][:7],due=False,stale=False,updated=1))),flush=True)
""")
        self.run_qml('''import QtQuick
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
}''', setup)

    def test_status_changes_do_not_move_calendar_task_controls_or_editor(self):
        self.run_qml('''import QtQuick
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
}''')

    def test_background_warm_optimistic_queue_and_failure_preserve_other_rows(self):
        def setup(root):
            (root/'drawers/events/backend.py').write_text('''import json,sys,time
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
''')
        self.run_qml('''import QtQuick
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
}''',setup)

    def test_instant_cached_month_and_optimistic_editor_draft_recovery(self):
        def setup(root):
            (root/'drawers/events/backend.py').write_text('''import json,sys,time
r=json.loads(sys.stdin.readline())
if r['op'] in ('status','fetch'):
 print(json.dumps(dict(ok=True,data=dict(state='ready',account_id='fixture',month=r['start'][:7],eventsReady=True,tasksReady=True,events=[],tasks=[],calendars=[dict(name='Tasks',slug='tasks',components=['VTODO'],writable=True,tasks_enabled=True,events_enabled=False)],due=False,stale=False,updated=1))),flush=True)
else:
 time.sleep(.25)
 print(json.dumps(dict(ok=False,error='Cannot save fixture')),flush=True)
''')
        self.run_qml('''import QtQuick
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
}''',setup)

    def test_successful_reopen_event_create_and_delete_do_not_refetch_lists(self):
        def setup(root):
            (root/'drawers/events/backend.py').write_text('''import json,sys,time
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
''')
        self.run_qml('''import QtQuick
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
}''',setup)
