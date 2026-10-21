#!/usr/bin/env python3
"""Private notification snapshots; delivery and actions belong to Quickshell."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from html import unescape


def state_path():
    directory = os.environ.get('XDG_STATE_HOME', '')
    root = Path(directory) if directory and Path(directory).is_absolute() else Path.home() / '.local/state'
    return root / 'quickshell/desktop/notifications.json'


def normalize(state):
    if not isinstance(state, dict) or not isinstance(state.get('items'), list) or type(state.get('paused')) is not bool:
        raise ValueError('Invalid notification history.')
    rows, seen = [], set()
    for item in state['items'][:100]:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in seen:
            continue
        seen.add(item['id'])
        row = {key: str(item.get(key, ''))[:limit] for key, limit in
               [('id', 150), ('app', 250), ('desktopEntry', 250), ('summary', 2000), ('body', 16384), ('appIcon', 2000)]}
        row['appIcon'] = row['appIcon'] if '://' not in row['appIcon'] or row['appIcon'].startswith('file:///') else ''
        for key, default in [('timestamp', time.time()), ('urgency', 1), ('progress', -1), ('processId', 0), ('liveId', 0)]:
            value = item.get(key, default)
            row[key] = value if type(value) in (int, float) and math.isfinite(value) else default
        # Actions and in-memory images belong to the live D-Bus connection.
        row.update(actions=[], image='', seen=item.get('seen') is not False)
        rows.append(row)
    return dict(items=rows, paused=state['paused'])


def load():
    path = state_path()
    if not path.exists():
        return dict(items=[], paused=False)
    with path.open() as stream:
        text = stream.read(4 * 1024 * 1024 + 1)
    if len(text) > 4 * 1024 * 1024:
        raise ValueError('Notification history is too large.')
    return normalize(json.loads(text))


def save(state):
    data = normalize(state)
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix='.notifications-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return data


def import_dunst():
    """Explicit one-time migration, before stopping the previous daemon."""
    if state_path().exists():
        raise ValueError('Notification history already exists; refusing to replace it.')
    def command(*args):
        return subprocess.run(['dunstctl', *args], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    rows = []
    for record in json.loads(command('history')).get('data', [[]])[0][:100]:
        item = {key: value.get('data') if isinstance(value, dict) else value for key, value in record.items()}
        rows.append(dict(id='imported-' + str(item['id']), app=item.get('appname', ''), summary=item.get('summary', ''),
                         body=unescape(re.sub(r'<[^>]+>', '', str(item.get('body', '')))),
                         timestamp=time.time() - max(0, time.monotonic() - int(item.get('timestamp', 0)) / 1000000)))
    return save(dict(items=rows, paused=command('is-paused') == 'true'))


def handle(request):
    if request.get('op') == 'load': return load()
    if request.get('op') == 'save': return save(request['state'])
    raise ValueError('Unknown notification storage operation.')


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--import-dunst']:
            result = import_dunst()
            print(json.dumps(dict(imported=len(result['items']))))
        else:
            print(json.dumps(dict(ok=True, data=handle(json.loads(sys.stdin.readline())))))
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError):
        print(json.dumps(dict(ok=False, error='Could not save notification history. Check the local state directory.')))
