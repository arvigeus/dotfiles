#!/usr/bin/env python3
"""Per-output controls and user-owned persistence, including wdisplays edits."""
import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODE = re.compile(r'^(\d+)x(\d+)@(\d+(?:\.\d+)?)(?:Hz)?$')


def command(*args):
    result = subprocess.run(['hyprctl', *args], check=False, capture_output=True, text=True, timeout=4)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Hyprland is unavailable.')
    return result.stdout.strip()


def mode_parts(value):
    match = MODE.fullmatch(value)
    if not match:
        return None
    width, height, rate = map(float, match.groups())
    if not (width > 0 and height > 0 and rate > 0):
        return None
    return int(width), int(height), rate


def identity(raw):
    return [raw.get(key, '') for key in ('name', 'description', 'make', 'model', 'serial')]


def fingerprint(records):
    values = [{key: row[key] for key in ('name', 'identity', 'enabled', 'mode', 'scale', 'transform', 'x', 'y', 'mirror')} for row in records]
    return hashlib.sha256(json.dumps(sorted(values, key=lambda row: row['name']), sort_keys=True).encode()).hexdigest()


def snapshot():
    raw = json.loads(command('-j', 'monitors', 'all'))
    records = []
    names = {str(monitor["id"]): monitor["name"] for monitor in raw if "id" in monitor}
    for monitor in raw:
        modes = list(dict.fromkeys(value for value in monitor.get('availableModes', []) if mode_parts(value)))
        width, height = monitor.get('width', 0), monitor.get('height', 0)
        transform = monitor.get('transform', 0)
        # Hyprland reports the native pixel dimensions; transform applies afterwards.
        rate = monitor.get('refreshRate', 0)
        current = next((value for value in modes if mode_parts(value)[:2] == (width, height)
                        and abs(mode_parts(value)[2] - rate) < 0.02), f'{width}x{height}@{rate:.5f}Hz')
        enabled = not monitor.get('disabled', False)
        if not enabled and not mode_parts(current):
            current = modes[0] if modes else ''
        if enabled and mode_parts(current) and current not in modes:
            modes.insert(0, current)
        records.append(dict(name=monitor['name'], identity=identity(monitor),
                            label=(monitor.get('description') or monitor['name']), enabled=enabled,
                            mode=current, modes=modes, scale=monitor.get('scale') or 1,
                            transform=transform, x=monitor.get('x', 0), y=monitor.get('y', 0),
                            mirror=names.get(str(monitor.get('mirrorOf')), 'none'), dpms=monitor.get('dpmsStatus', True)))
    return dict(available=True, displays=records, token=fingerprint(records))


def number(value, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Display settings must be finite numbers.')
    if value < low or value > high or (integer and value != int(value)):
        raise ValueError('Display setting is outside its supported range.')
    return int(value) if integer else value


def dimensions(row):
    width, height, _ = mode_parts(row['mode'])
    if row['transform'] % 2:
        width, height = height, width
    return round(width / row['scale']), round(height / row['scale'])


def validate(request, state):
    if request.get('token') != state['token']:
        raise ValueError('Displays changed while editing. Reload the current setup and try again.')
    rows = request.get('displays')
    known = {row['name']: row for row in state['displays']}
    if not isinstance(rows, list) or len(rows) != len(known):
        raise ValueError('The connected displays changed. Reload the current setup.')
    checked, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get('name') not in known or row['name'] in seen:
            raise ValueError('Unknown or duplicate display.')
        seen.add(row['name'])
        original = known[row['name']]
        if type(row.get('enabled')) is not bool:
            raise ValueError('Enabled state must be true or false.')
        result = dict(original, enabled=row['enabled'])
        if result['enabled']:
            mode = row.get('mode')
            if mode not in original['modes'] or not mode_parts(mode):
                raise ValueError('This display no longer supports the selected mode.')
            result.update(mode=mode, scale=number(row.get('scale'), 0.5, 4),
                          transform=number(row.get('transform'), 0, 7, True),
                          x=number(row.get('x'), -32768, 32768, True),
                          y=number(row.get('y'), -32768, 32768, True))
            width, height, _ = mode_parts(mode)
            if any(abs(size / result['scale'] - round(size / result['scale'])) > 0.01 for size in (width, height)):
                raise ValueError('Choose a scale that produces whole logical pixels for this resolution.')
        result['mirror'] = row.get('mirror', original['mirror'])
        checked.append(result)
    active = [row for row in checked if row['enabled']]
    if not active:
        raise ValueError('Keep at least one display enabled.')
    by_name = {row['name']: row for row in checked}
    for row in active:
        if row['mirror'] in ('none', '', None, -1):
            row['mirror'] = 'none'
            continue
        target = by_name.get(row['mirror'])
        if not target or not target['enabled'] or target['name'] == row['name']:
            raise ValueError('Choose a different enabled display to mirror.')
        if target['mirror'] not in ('none', '', None, -1):
            raise ValueError('A mirrored display cannot be used as a mirror source.')
    if not any(row['mirror'] == 'none' for row in active):
        raise ValueError('Keep at least one independent display enabled.')
    for index, first in enumerate(active):
        if first['mirror'] != 'none':
            continue
        aw, ah = dimensions(first)
        for second in active[index + 1:]:
            if second['mirror'] != 'none':
                continue
            bw, bh = dimensions(second)
            if first['x'] < second['x'] + bw and second['x'] < first['x'] + aw and first['y'] < second['y'] + bh and second['y'] < first['y'] + ah:
                raise ValueError('Displays would overlap. Adjust the arrangement in wdisplays first.')
    return checked


def lua_string(value):
    # Lua decimal escapes avoid interpolation, control characters and unicode ambiguity.
    return '"' + ''.join(f'\\{byte:03d}' for byte in value.encode()) + '"'


def apply_rows(rows):
    # Enable replacements before disabling outputs, even across separate refreshes.
    for enabled in (True, False):
        scripts = []
        for row in sorted(rows, key=lambda row: row.get('mirror', 'none') != 'none'):
            if row['enabled'] != enabled:
                continue
            fields = [f'output={lua_string(row["name"])}', f'disabled={str(not enabled).lower()}']
            if enabled:
                fields += [f'mode={lua_string(row["mode"].removesuffix("Hz"))}',
                           f'position={lua_string(str(row["x"]) + "x" + str(row["y"]))}',
                           f'scale={row["scale"]}', f'transform={row["transform"]}',
                           f'mirror={lua_string("" if row["mirror"] == "none" else row["mirror"])}']
            scripts.append('hl.monitor({' + ','.join(fields) + '})')
        if scripts:
            reply = command('eval', ';'.join(scripts))
            if reply != 'ok':
                raise RuntimeError(reply or 'Hyprland rejected the display change.')
            if enabled and any(not row['enabled'] for row in rows):
                # A successful eval can still fall back or fail a modeset. Do not
                # disable the old screen until replacements are actually usable.
                replacements = [row for row in rows if row['enabled']]
                names = {row['name'] for row in replacements}
                until = time.monotonic() + 3
                while True:
                    current = snapshot()
                    current['displays'] = [row for row in current['displays'] if row['name'] in names]
                    if matches(replacements, current):
                        break
                    if time.monotonic() >= until:
                        raise ValueError('Could not activate the replacement display. Existing displays were left enabled.')
                    time.sleep(0.1)


def topology(state):
    return sorted((row['name'], row['identity']) for row in state['displays'])


def matches(expected, actual):
    if topology(dict(displays=expected)) != topology(actual):
        return False
    current = {row['name']: row for row in actual['displays']}
    for row in expected:
        other = current[row['name']]
        if row['enabled'] != other['enabled'] or (row['enabled'] and row['mirror'] != other['mirror']):
            return False
        if row['enabled']:
            if (row['mirror'] == 'none' and any(row[key] != other[key] for key in ('x', 'y'))) or row['transform'] != other['transform'] or abs(row['scale'] - other['scale']) > 0.001:
                return False
            a, b = mode_parts(row['mode']), mode_parts(other['mode'])
            if not a or not b or a[:2] != b[:2] or abs(a[2] - b[2]) > 0.1 or not other['dpms']:
                return False
    return True


def restore(before):
    current = snapshot()
    connected = {row['name']: row for row in current['displays']}
    rows = [row for row in before['displays'] if row['name'] in connected and row['identity'] == connected[row['name']]['identity']]
    if not any(row['enabled'] and row['mirror'] == 'none' for row in rows):
        fallback = next((row for row in current['displays'] if row['enabled'] and row['mirror'] == 'none'), None)
        fallback = fallback or next((dict(row, enabled=True, mirror='none', mode=row['modes'][0], scale=1, transform=0, x=0, y=0)
                                     for row in current['displays'] if row['modes']), None)
        if fallback:
            rows = [row for row in rows if row['name'] != fallback['name']] + [fallback]
    independent = {row['name'] for row in rows if row['enabled'] and row['mirror'] == 'none'}
    rows = [dict(row, mirror='none') if row['mirror'] != 'none' and row['mirror'] not in independent else row for row in rows]
    apply_rows(rows)


def prepare_change(request, state):
    original = next((row for row in state['displays'] if row['name'] == request.get('name')), None)
    if not original or original['identity'] != request.get('identity'):
        raise ValueError('The display changed or disconnected. Refresh and try again.')
    values = request.get('values')
    if not isinstance(values, dict) or not values or not set(values) <= {'mode', 'scale', 'transform', 'mirror', 'enabled'}:
        raise ValueError('Unsupported display setting.')
    rows = [dict(row) for row in state['displays']]
    target = next(row for row in rows if row['name'] == original['name'])
    target.update(values)
    if not original['enabled'] and values.get('enabled') is not True:
        raise ValueError('Enable this display before changing its settings.')
    # Validate values before calculating geometry with them. Overlap is checked
    # after preserving the gaps to displays on the right/below a resized output.
    if target['enabled']:
        if target['mode'] not in original['modes']:
            raise ValueError('This display no longer supports the selected mode.')
        number(target['scale'], 0.5, 4)
        number(target['transform'], 0, 7, True)
        if target['mirror'] == 'none':
            others = [row for row in rows if row['name'] != target['name'] and row['enabled'] and row['mirror'] == 'none']
            if not original['enabled'] or original['mirror'] != 'none':
                target['x'] = max((row['x'] + dimensions(row)[0] for row in others), default=0)
                target['y'] = min((row['y'] for row in others), default=0)
            else:
                old_width, old_height = dimensions(original)
                width, height = dimensions(target)
                for row in others:
                    if row['x'] >= original['x'] + old_width:
                        row['x'] += width - old_width
                    if row['y'] >= original['y'] + old_height:
                        row['y'] += height - old_height
    return validate(dict(token=state['token'], displays=rows), state)


def control(request, before=None):
    before = before or snapshot()
    rows = prepare_change(request, before)
    return apply_setup(rows, before)


def apply_setup(rows, before):
    changed = [row for row, previous in zip(rows, before['displays'])
               if row['enabled'] != previous['enabled'] or (row['enabled'] and fingerprint([row]) != fingerprint([previous]))]
    if not changed:
        return before
    # Include a usable independent output when disabling an output so that
    # apply_rows verifies it before the disable operation.
    if any(not row['enabled'] for row in changed) and not any(row['enabled'] and row['mirror'] == 'none' for row in changed):
        changed.append(next(row for row in rows if row['enabled'] and row['mirror'] == 'none'))
    try:
        apply_rows(changed)
        until = time.monotonic() + 3
        while True:
            current = snapshot()
            if matches(rows, current):
                return current
            if time.monotonic() >= until:
                raise ValueError('The display could not activate the requested settings.')
            time.sleep(0.1)
    except Exception as exc:
        try:
            restore(before)
        except Exception as restore_error:
            raise RuntimeError(f'{exc} Could not restore the previous setup: {restore_error}') from exc
        raise


class Preferences:
    """User-owned output preferences, independent of repository monitor rules."""

    fields = ('name', 'identity', 'enabled', 'mode', 'scale', 'transform', 'x', 'y', 'mirror')

    def __init__(self, path=None):
        config_home = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        if not config_home.is_absolute():
            config_home = Path.home() / '.config'
        self.path = path or config_home / 'quickshell/desktop/displays.json'
        self.saved = None
        self.baseline = None
        self.restoring = False

    @staticmethod
    def key(row):
        return json.dumps(row['identity'])

    def load(self):
        if self.saved is not None:
            return
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.saved = {}
            return
        try:
            if data['version'] != 1 or not isinstance(data['outputs'], list):
                raise ValueError()
            saved = {}
            for row in data['outputs']:
                if not isinstance(row, dict) or any(key not in row for key in self.fields):
                    raise ValueError()
                if (not isinstance(row['name'], str) or not isinstance(row['identity'], list)
                        or len(row['identity']) != 5 or row['identity'][0] != row['name']
                        or not all(isinstance(value, str) for value in row['identity'])
                        or type(row['enabled']) is not bool or not isinstance(row['mirror'], str)
                        or not isinstance(row['mode'], str) or not mode_parts(row['mode'])):
                    raise ValueError()
                number(row['scale'], 0.5, 4)
                number(row['transform'], 0, 7, True)
                number(row['x'], -32768, 32768, True)
                number(row['y'], -32768, 32768, True)
                key = self.key(row)
                if key in saved:
                    raise ValueError()
                saved[key] = row
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Invalid saved display settings in {self.path}; the file was left untouched.') from exc
        self.saved = saved

    def remember(self, current, before=None, geometry_before=None):
        self.load()
        previous = {self.key(row): row for row in (before or dict(displays=[]))['displays']}
        geometry_previous = {self.key(row): row for row in (geometry_before or before or dict(displays=[]))['displays']}
        connected = {row['name']: row for row in current['displays']}
        saved = dict(self.saved)
        for row in current['displays']:
            key = self.key(row)
            old = previous.get(key)
            if old and key in saved and fingerprint([old]) == fingerprint([row]):
                continue
            value = {field: row[field] for field in self.fields}
            # Disabled outputs can report placeholder modes and transforms. Keep
            # their last usable geometry for the next enable/reconnect.
            if not row['enabled']:
                geometry = geometry_previous.get(key)
                geometry = geometry if geometry and geometry['enabled'] else saved.get(key)
                if geometry:
                    for field in ('mode', 'scale', 'transform', 'x', 'y'):
                        value[field] = geometry[field]
            if not mode_parts(value['mode']):
                continue
            target = connected.get(row['mirror'])
            value['mirrorIdentity'] = target['identity'] if target else None
            saved[key] = value
        if saved != self.saved:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.displays-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(dict(version=1, outputs=list(saved.values())), stream, indent=2, allow_nan=False)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.saved = saved
        self.baseline = current

    def plan(self, current):
        rows = []
        for live in current['displays']:
            saved = self.saved.get(self.key(live))
            row = dict(live)
            if saved and not saved['enabled']:
                row['enabled'] = False
            if saved and saved['mode'] in live['modes']:
                candidate = dict(row, **{key: saved[key] for key in self.fields})
                width, height, _ = mode_parts(candidate['mode'])
                if all(abs(size / candidate['scale'] - round(size / candidate['scale'])) < 0.01 for size in (width, height)):
                    row = candidate
            rows.append(row)
        by_name = {row['name']: row for row in rows}
        for row in rows:
            if row['mirror'] == 'none':
                continue
            target = by_name.get(row['mirror'])
            saved = self.saved.get(self.key(row), {})
            if (not target or not target['enabled'] or target is row or target['mirror'] != 'none'
                    or saved.get('mirrorIdentity', target['identity']) != target['identity']):
                row['mirror'] = 'none'
        if rows and not any(row['enabled'] and row['mirror'] == 'none' for row in rows):
            # A dock-only preference must never leave the laptop unusable alone.
            fallback = next((row for row in current['displays'] if row['enabled'] and row['mirror'] == 'none'), None)
            fallback = fallback or next((dict(row, enabled=True, mirror='none', mode=row['modes'][0], scale=1, transform=0)
                                         for row in current['displays'] if row['modes']), None)
            if fallback:
                rows = [dict(fallback) if row['name'] == fallback['name'] else row for row in rows]
        # Missing mirror sources or newly attached outputs can create overlap.
        # Keep saved placement where possible and move conflicting outputs right.
        placed = []
        for row in sorted(rows, key=lambda row: self.key(row) not in self.saved):
            if not row['enabled'] or row['mirror'] != 'none':
                continue
            width, height = dimensions(row)
            if any(row['x'] < other['x'] + dimensions(other)[0] and other['x'] < row['x'] + width
                   and row['y'] < other['y'] + dimensions(other)[1] and other['y'] < row['y'] + height for other in placed):
                row['x'] = max(other['x'] + dimensions(other)[0] for other in placed)
            placed.append(row)
        return validate(dict(token=current['token'], displays=rows), current)

    def observe(self, current, force=False):
        self.load()
        if not current['displays']:
            self.baseline = current
            return current
        if force or self.baseline is None or topology(current) != topology(self.baseline):
            self.baseline = current
            self.restoring = True
            rows = self.plan(current)
            result = apply_setup(rows, current)
            self.baseline = result
            self.restoring = False
            # Only newly discovered outputs are seeded here. Existing saved
            # preferences survive temporary dock/mirror safety fallbacks.
            self.remember(result, result)
            return result
        # The shell invokes this once after an event burst settles, supplying
        # the last acknowledged state across short-lived helper invocations.
        self.remember(current, self.baseline)
        return current


def handle(request, preferences=None):
    if preferences and 'baseline' in request:
        preferences.baseline = request['baseline']
    op = request.get('op')
    if op == 'status':
        return snapshot()
    if op == 'sync' and preferences:
        return preferences.observe(snapshot())
    if op == 'restore' and preferences:
        return preferences.observe(snapshot(), force=True)
    if op == 'change':
        before = snapshot() if preferences else None
        if preferences:
            preferences.load()
            live = next((row for row in before['displays'] if row['name'] == request.get('name')), None)
            if live and not live['enabled'] and isinstance(request.get('values'), dict) and request['values'].get('enabled') is True:
                saved = preferences.saved.get(preferences.key(live))
                if saved and saved['mode'] in live['modes']:
                    values = {key: saved[key] for key in ('mode', 'scale', 'transform')}
                    request = dict(request, values=dict(values, **request['values']))
        current = control(request, before)
        if preferences:
            # Include external edits since the last observation, but preserve
            # the exact pre-disable geometry reported just before this action.
            preferences.remember(current, preferences.baseline or before, before)
        return current
    raise ValueError('Unknown display operation.')


def response(request, preferences=None):
    try:
        data = handle(request, preferences)
        return dict(ok=True, error='', data=data, baseline=preferences.baseline if preferences else None)
    except Exception as exc:
        try:
            data = snapshot()
        except Exception:
            data = dict(available=False, displays=[], token='')
        if preferences and preferences.restoring:
            # A failed restore can itself emit output events. Acknowledge the
            # actual rollback/fallback state so those echoes cannot retry it
            # endlessly or save it over the user's preference.
            preferences.baseline = data if data['available'] else preferences.baseline
        return dict(ok=False, error=str(exc), data=data, baseline=preferences.baseline if preferences else None)


def main():
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
    session = hashlib.sha256(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '').encode()).hexdigest()[:16]
    with (runtime / f'quickshell-displays-{os.getuid()}-{session}.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps(dict(ok=False, error='Another display editor is open.', data=dict(available=False, displays=[], token=''))), flush=True)
            return
        preferences = Preferences()
        # One request per process; the shell owns event subscriptions and queues.
        line = sys.stdin.readline()
        if line:
            try:
                result = response(json.loads(line), preferences)
            except Exception as exc:
                result = dict(ok=False, error=str(exc), data=dict(available=False, displays=[], token=''))
            print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
