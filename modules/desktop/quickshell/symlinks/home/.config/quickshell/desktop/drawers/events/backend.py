#!/usr/bin/env python3
"""Fast private cache reads, background synchronization and resource-level writes."""
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integrations import nextcloud
from drawers.events import caldav


def config_root():
    return nextcloud.config_root().parent


def cache_root():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'quickshell/desktop/calendar'


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def locked(name='sync.lock'):
    folder = cache_root()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(folder / name, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def configuration():
    path = config_root() / 'calendar.json'
    options = nextcloud.read_json(path) if path.exists() else {}
    if options.get('provider', 'nextcloud') != 'nextcloud':
        raise ValueError('This calendar provider is not available.')
    return {key: caldav.selection(options, key) for key in ('calendars', 'task_lists') if key in options}


def context(request):
    options = configuration()
    account = nextcloud.load_account()
    empty = dict(events=[], tasks=[], calendars=[], task_count=0, due=False, stale=False, error='', account_id='', eventsReady=False, tasksReady=False)
    if not account:
        return None, None, dict(empty, state='unconfigured')
    try:
        nextcloud.credential(account)
    except nextcloud.CredentialMissing:
        return None, None, dict(empty, state='needs_password')
    start = date.fromisoformat(request['start'])
    end = date.fromisoformat(request['end'])
    if not 0 < (end - start).days <= 180:
        raise ValueError('Choose a calendar range of at most 180 days.')
    signature = []
    for reference in account['credentials'].values():
        path = nextcloud.config_root() / 'credentials/nextcloud' / reference['file']
        try:
            info = path.stat()
            signature.append((info.st_ino, info.st_size, info.st_mtime_ns))
        except OSError:
            signature.append(None)
    identity = [account, options, signature]
    empty['account_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    # Retain the existing filename contract so installed snapshots remain usable.
    key = hashlib.sha256(json.dumps([*identity, str(start), str(end)], sort_keys=True).encode()).hexdigest()
    return {**account, **options}, cache_root() / (key + '.json'), empty


def read_cache(path):
    try:
        value = json.loads(path.read_text())
        if (not isinstance(value.get('data'), dict) or not isinstance(value.get('fetched'), (int, float))
                or any(not isinstance(value['data'].get(key), list) for key in ('events', 'tasks', 'calendars'))):
            return None
        return value
    except (OSError, ValueError, AttributeError):
        return None


def revision():
    try:
        return int((cache_root() / 'revision').read_text())
    except (OSError, ValueError):
        return 0


def bump_revision():
    value = revision() + 1
    atomic_json(cache_root() / 'revision', value)
    return value


def dirty_caches():
    for path in cache_root().glob('*.json'):
        cached = read_cache(path)
        if cached:
            cached.update(dirty=True, attempted=0)
            atomic_json(path, cached)


def recover_revision():
    """Fence a terminated writer without replaying its uncertain remote request."""
    if not revision() % 2: return
    descriptor = os.open(cache_root() / 'write.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        dirty_caches()
        bump_revision()
    finally:
        os.close(descriptor)


def envelope(data, request, account_id, fetched, **extra):
    today = date.today()
    return dict(data=data, fetched=fetched, attempted=time.time(), account_id=account_id,
                start=request['start'], end=request['end'],
                upcoming_start=str(today - timedelta(days=7)), upcoming_end=str(today + timedelta(days=60)),
                complete=True, attempt_start=request['start'], attempt_end=request['end'], **extra)


def cached_status(request, path, empty):
    """Called under the short publication lock; never performs network I/O."""
    cached = read_cache(path)
    if cached and not cached.get('account_id'):
        cached.update(account_id=empty['account_id'], start=request['start'], end=request['end'])
        # Upgrade old snapshots without changing their freshness or private data.
        atomic_json(path, cached)
    exact = cached is not None
    candidates = [value for item in cache_root().glob('*.json')
                  if (value := read_cache(item)) and value.get('account_id') == empty['account_id'] and value['fetched']]
    latest = max(candidates, key=lambda value: value['fetched'], default=None)
    if not cached: cached = latest
    covered = bool(cached and (exact and cached.get('complete', True) or
        cached.get('start', '~') <= request['start'] and cached.get('end', '') >= request['end'] or
        cached.get('upcoming_start', '~') <= request['start'] and cached.get('upcoming_end', '') >= request['end']))
    now = time.time()
    stale = not cached or cached.get('dirty', False) or now - cached['fetched'] >= 900
    same_attempt = cached and cached.get('attempt_start', cached.get('start')) == request['start'] and cached.get('attempt_end', cached.get('end')) == request['end']
    due = (stale or not covered) and (not same_attempt or now - cached.get('attempted', 0) >= 300)
    global_data = {key: latest['data'].get(key, empty.get(key)) for key in ('tasks', 'calendars', 'task_count')} if latest else {}
    return dict({**empty, **(cached['data'] if cached else {}), **global_data},
                state=('ready' if cached['fetched'] else 'unavailable') if cached else 'loading',
                stale=bool(cached and cached['fetched'] and stale), due=due,
                updated=cached['fetched'] if cached else 0, account_id=empty['account_id'],
                eventsReady=bool(cached and cached['fetched'] and covered), tasksReady=bool(latest), tasksUpdated=latest['fetched'] if latest else 0)


def sort_data(data):
    data['events'].sort(key=lambda item: item['start'])
    data['tasks'].sort(key=lambda item: (item.get('due', '') == '', item.get('due', ''), item['summary'].casefold()))
    data['task_count'] = sum(not item.get('completed') for item in data['tasks'])
    return data


def resource_rows(result, kind, request):
    if result.get('deleted'):
        return dict(events=[], tasks=[])
    href, etag, content, collection = (result[key] for key in ('href', 'etag', 'ical', 'collection'))
    entries = [(href, etag, content)]
    zone = caldav.tz.gettz()
    if kind == 'VTODO':
        return dict(tasks=caldav.tasks_from(entries, collection, zone), events=[])
    today = date.today()
    lower = min(date.fromisoformat(request['start']), today - timedelta(days=7))
    upper = max(date.fromisoformat(request['end']), today + timedelta(days=60))
    return dict(events=caldav.events_from(entries, collection,
        datetime.combine(lower, datetime.min.time(), tzinfo=zone),
        datetime.combine(upper, datetime.min.time(), tzinfo=zone), zone), tasks=[])


def patch_resource(data, href, kind, rows):
    field = 'tasks' if kind == 'VTODO' else 'events'
    updated = dict(data)
    updated[field] = [item for item in data[field] if item.get('href') != href] + rows[field]
    # sort_data mutates lists; preserve unrelated snapshot lists by copying them.
    return sort_data(dict(updated, events=list(updated['events']), tasks=list(updated['tasks'])))


def mutate(request, config, empty):
    account_id = empty['account_id']
    if request.get('account_id', account_id) != account_id:
        raise nextcloud.NextcloudError('The account or collection selection changed. Review this item before saving.')
    kind, entry = request.get('kind', 'VTODO'), request.get('entry', {})
    if kind not in ('VTODO', 'VEVENT') or not isinstance(entry, dict):
        raise ValueError('Invalid calendar item.')
    # Writers serialize separately. Cache readers never wait for DAV requests.
    with locked('write.lock'):
        with locked():
            # Repair an odd revision left by a terminated writer before starting.
            if revision() % 2:
                dirty_caches(); bump_revision()
            bump_revision()
        result = None
        try:
            client = caldav.Client(config)
            op = request['op']
            if op == 'save': result = client.save_item(config, kind, entry)
            elif op == 'complete': result = client.set_completed(config, entry, bool(request.get('completed')))
            elif op == 'delete': result = client.delete_item(config, kind, entry)
            else: raise ValueError('Unknown calendar operation.')
            if not result.get('deleted'):
                # Fetch just the changed resource, including its fresh ETag and
                # any recurring master/exception. A committed PUT is never retried.
                try:
                    raw, headers = client.request('GET', result['href'])
                    result.update(ical=raw.decode('utf-8'), etag=headers.get('ETag', ''))
                    if not result['etag']: raise ValueError('The updated item has no ETag.')
                except (ValueError, OSError):
                    result['reconcile'] = True
        finally:
            with locked():
                try:
                    for path in cache_root().glob('*.json'):
                        cached = read_cache(path)
                        if not cached: continue
                        if not cached.get('account_id'):
                            # Legacy snapshots cannot be safely patched by source.
                            path.unlink(missing_ok=True)
                            continue
                        if cached.get('account_id') != account_id: continue
                        if result and not result.get('reconcile'):
                            rows = resource_rows(result, kind, cached)
                            cached['data'] = patch_resource(cached['data'], result['href'], kind, rows)
                        else:
                            cached['dirty'] = True
                            cached['attempted'] = 0
                        atomic_json(path, cached)
                except (OSError, ValueError, KeyError):
                    # A committed remote write must not become a retryable failure
                    # merely because local publication/readback failed.
                    if result: result['reconcile'] = True
                finally:
                    bump_revision()
        response = dict(saved=True, href=result['href'], kind=kind, account_id=account_id,
                        deleted=bool(result.get('deleted')), reconcile=bool(result.get('reconcile')))
        if not response['reconcile']:
            response.update(resource_rows(result, kind, request))
        return response


def handle(request):
    op = request.get('op')
    config, path, empty = context(request)
    if not config:
        if op not in ('status', 'fetch'): raise ValueError('Configure the Nextcloud account first.')
        return empty
    if op not in ('status', 'fetch'):
        return mutate(request, config, empty)
    with locked():
        recover_revision()
        if op == 'status': return cached_status(request, path, empty)
        token = revision()
    try:
        data = caldav.snapshot(config, start=request['start'], end=request['end'])
    except (ValueError, OSError) as error:
        with locked():
            cached = read_cache(path)
            if not cached:
                candidates = [value for item in cache_root().glob('*.json')
                    if (value := read_cache(item)) and value.get('account_id') == empty['account_id'] and value['fetched']]
                cached = max(candidates, key=lambda value: value['fetched'], default=None)
                if cached: cached['complete'] = False
            if not cached:
                cached = envelope(empty.copy(), request, empty['account_id'], 0)
                cached['complete'] = False
            cached.update(attempted=time.time(), attempt_start=request['start'], attempt_end=request['end'], dirty=True)
            cached['data']['error'] = str(error)
            atomic_json(path, cached)
            return dict(cached_status(request, path, empty), stale=bool(cached['fetched']), due=False)
    with locked():
        # A full refresh started before/during a write cannot replace newer data.
        if revision() != token or token % 2:
            return dict(cached_status(request, path, empty), due=False, superseded=True)
        atomic_json(path, envelope(data, request, empty['account_id'], time.time()))
        for old in sorted(cache_root().glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True)[12:]:
            old.unlink(missing_ok=True)
        return cached_status(request, path, empty)


if __name__ == '__main__':
    try:
        print(json.dumps(dict(ok=True, data=handle(json.loads(sys.stdin.readline())))))
    except (ValueError, OSError, TypeError, KeyError, OverflowError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, (nextcloud.NextcloudError, ValueError)) else 'Could not read calendar data.'
        print(json.dumps(dict(ok=False, error=message)))
