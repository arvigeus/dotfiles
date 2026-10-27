#!/usr/bin/env python3
"""Shared display controls and monitor-set profiles, applied through native rules."""

from contextlib import contextmanager
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
INTERNAL = re.compile(r'^(eDP|LVDS|DSI)-')
RULE = re.compile(r'^\s*hl\.monitor\(\{\s*output\s*=\s*("(?:[^"\\\n]|\\.)*")')
RULE_MODE = re.compile(r'\bmode\s*=\s*("(?:[^"\\\n]|\\.)*")')
HEADER = [
    '-- Generated active display layout. Preferences live in display-profiles.json.',
    '-- The display service selects the profile for the connected monitors.',
]


def command(*args):
    result = subprocess.run(
        ['hyprctl', *args], check=False, capture_output=True, text=True, timeout=4
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or 'Hyprland is unavailable.'
        )
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
    return [
        raw.get(key, '') for key in ('name', 'description', 'make', 'model', 'serial')
    ]


def fingerprint(records):
    values = [
        {
            key: row[key]
            for key in (
                'name',
                'identity',
                'enabled',
                'mode',
                'scale',
                'transform',
                'x',
                'y',
                'mirror',
            )
        }
        for row in records
    ]
    return hashlib.sha256(
        json.dumps(sorted(values, key=lambda row: row['name']), sort_keys=True).encode()
    ).hexdigest()


def snapshot():
    raw = json.loads(command('-j', 'monitors', 'all'))
    records = []
    names = {str(monitor['id']): monitor['name'] for monitor in raw if 'id' in monitor}
    for monitor in raw:
        # Hyprland creates this invisible output when the last real one goes
        # away. It must not satisfy the safety check or become a preference.
        if monitor['name'] == 'FALLBACK':
            continue
        modes = list(
            dict.fromkeys(
                value
                for value in monitor.get('availableModes', [])
                if mode_parts(value)
            )
        )
        width, height = monitor.get('width', 0), monitor.get('height', 0)
        transform = monitor.get('transform', 0)
        # Hyprland reports the native pixel dimensions; transform applies afterwards.
        rate = monitor.get('refreshRate', 0)
        current = next(
            (
                value
                for value in modes
                if mode_parts(value)[:2] == (width, height)
                and abs(mode_parts(value)[2] - rate) < 0.02
            ),
            f'{width}x{height}@{rate:.5f}Hz',
        )
        enabled = not monitor.get('disabled', False)
        if not enabled and not mode_parts(current):
            current = modes[0] if modes else ''
        if enabled and mode_parts(current) and current not in modes:
            modes.insert(0, current)
        records.append(
            dict(
                name=monitor['name'],
                identity=identity(monitor),
                label=(monitor.get('description') or monitor['name']),
                enabled=enabled,
                mode=current,
                modes=modes,
                scale=monitor.get('scale') or 1,
                transform=transform,
                x=monitor.get('x', 0),
                y=monitor.get('y', 0),
                mirror=names.get(str(monitor.get('mirrorOf')), 'none'),
                dpms=monitor.get('dpmsStatus', True),
            )
        )
    return dict(available=True, displays=records, token=fingerprint(records))


def number(value, low, high, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
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
        raise ValueError(
            'Displays changed while editing. Reload the current setup and try again.'
        )
    rows = request.get('displays')
    known = {row['name']: row for row in state['displays']}
    if not isinstance(rows, list) or len(rows) != len(known):
        raise ValueError('The connected displays changed. Reload the current setup.')
    checked, seen = [], set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get('name') not in known
            or row['name'] in seen
        ):
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
            result.update(
                mode=mode,
                scale=number(row.get('scale'), 0.5, 4),
                transform=number(row.get('transform'), 0, 7, True),
                x=number(row.get('x'), -32768, 32768, True),
                y=number(row.get('y'), -32768, 32768, True),
            )
            width, height, _ = mode_parts(mode)
            if any(
                abs(size / result['scale'] - round(size / result['scale'])) > 0.01
                for size in (width, height)
            ):
                raise ValueError(
                    'Choose a scale that produces whole logical pixels for this resolution.'
                )
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
        for second in active[index + 1 :]:
            if second['mirror'] != 'none':
                continue
            bw, bh = dimensions(second)
            if (
                first['x'] < second['x'] + bw
                and second['x'] < first['x'] + aw
                and first['y'] < second['y'] + bh
                and second['y'] < first['y'] + ah
            ):
                raise ValueError(
                    'Displays would overlap. Adjust their positions in Display arrangement.'
                )
    return checked


def lua_string(value):
    # Printable ASCII stays readable; everything else uses fixed-width decimal escapes.
    return (
        '"'
        + ''.join(
            chr(byte) if 32 <= byte < 127 and byte not in (34, 92) else f'\\{byte:03d}'
            for byte in value.encode()
        )
        + '"'
    )


def lua_unquote(value):
    return re.sub(
        rb'\\(\d{1,3}|.)',
        lambda match: bytes([int(match[1])]) if match[1].isdigit() else match[1],
        value[1:-1].encode(),
    ).decode(errors='replace')


def selectors(rows):
    """Rule selectors for connected outputs: the description, unless it is ambiguous."""
    result = {}
    for row in rows:
        description = row['identity'][1]
        # Hyprland matches desc: by prefix, so it must identify exactly one connected output.
        unique = (
            description
            and sum(other['identity'][1].startswith(description) for other in rows) == 1
        )
        result[row['name']] = 'desc:' + description if unique else row['name']
    return result


def rule(row, names, mode=None):
    fields = [
        ('output', lua_string(names[row['name']])),
        ('disabled', str(not row['enabled']).lower()),
    ]
    if row['enabled']:
        fields += [
            ('mode', lua_string((mode or row['mode']).removesuffix('Hz'))),
            ('position', lua_string(f'{row["x"]}x{row["y"]}')),
            ('scale', json.dumps(row['scale'])),
            ('transform', str(row['transform'])),
            (
                'mirror',
                lua_string('' if row['mirror'] == 'none' else names[row['mirror']]),
            ),
        ]
    return (
        'hl.monitor({ ' + ', '.join(f'{key} = {value}' for key, value in fields) + ' })'
    )


def apply_rows(rows, names):
    # Enable replacements before disabling outputs, even across separate refreshes.
    for enabled in (True, False):
        scripts = [
            rule(row, names)
            for row in sorted(rows, key=lambda row: row.get('mirror', 'none') != 'none')
            if row['enabled'] == enabled
        ]
        if scripts:
            reply = command('eval', ';'.join(scripts))
            if reply != 'ok':
                raise RuntimeError(reply or 'Hyprland rejected the display change.')
            if enabled and any(not row['enabled'] for row in rows):
                # A successful eval can still fall back or fail a modeset. Do not
                # disable the old screen until replacements are actually usable.
                replacements = [row for row in rows if row['enabled']]
                wanted = {row['name'] for row in replacements}
                until = time.monotonic() + 3
                while True:
                    current = snapshot()
                    current['displays'] = [
                        row for row in current['displays'] if row['name'] in wanted
                    ]
                    if matches(replacements, current):
                        break
                    if time.monotonic() >= until:
                        raise ValueError(
                            'Could not activate the replacement display. Existing displays were left enabled.'
                        )
                    time.sleep(0.1)


def topology(state):
    return sorted((row['name'], row['identity']) for row in state['displays'])


def matches(expected, actual):
    if topology(dict(displays=expected)) != topology(actual):
        return False
    current = {row['name']: row for row in actual['displays']}
    for row in expected:
        other = current[row['name']]
        if row['enabled'] != other['enabled'] or (
            row['enabled'] and row['mirror'] != other['mirror']
        ):
            return False
        if row['enabled']:
            if (
                (
                    row['mirror'] == 'none'
                    and any(row[key] != other[key] for key in ('x', 'y'))
                )
                or row['transform'] != other['transform']
                or abs(row['scale'] - other['scale']) > 0.001
            ):
                return False
            a, b = mode_parts(row['mode']), mode_parts(other['mode'])
            if (
                not a
                or not b
                or a[:2] != b[:2]
                or abs(a[2] - b[2]) > 0.1
                or not other['dpms']
            ):
                return False
    return True


def restore(before):
    current = snapshot()
    connected = {row['name']: row for row in current['displays']}
    rows = [
        row
        for row in before['displays']
        if row['name'] in connected
        and row['identity'] == connected[row['name']]['identity']
    ]
    if not any(row['enabled'] and row['mirror'] == 'none' for row in rows):
        fallback = next(
            (
                row
                for row in current['displays']
                if row['enabled'] and row['mirror'] == 'none'
            ),
            None,
        )
        fallback = fallback or next(
            (
                dict(
                    row,
                    enabled=True,
                    mirror='none',
                    mode=row['modes'][0],
                    scale=1,
                    transform=0,
                    x=0,
                    y=0,
                )
                for row in current['displays']
                if row['modes']
            ),
            None,
        )
        if fallback:
            rows = [row for row in rows if row['name'] != fallback['name']] + [fallback]
    independent = {
        row['name'] for row in rows if row['enabled'] and row['mirror'] == 'none'
    }
    rows = [
        dict(row, mirror='none')
        if row['mirror'] != 'none' and row['mirror'] not in independent
        else row
        for row in rows
    ]
    apply_rows(rows, selectors(current['displays']))


def preferred_mode(row):
    # availableModes has no preferred flag. The native Lua inventory does;
    # query it without changing the output, then match its unrounded rate.
    value = command(
        'repl',
        'local monitor=hl.get_monitor(' + lua_string(row['name']) + '); '
        'if monitor then for _, mode in ipairs(monitor.available_modes or {}) do '
        'if mode.preferred then return string.format("%dx%d@%.5f", '
        'mode.width, mode.height, mode.refresh_rate) end end end; return ""',
    )
    preferred = mode_parts(value)
    if preferred:
        for mode in row['modes']:
            parts = mode_parts(mode)
            if parts[:2] == preferred[:2] and abs(parts[2] - preferred[2]) < 0.02:
                return mode
    raise ValueError(
        'The display did not report an available recommended mode. Choose a resolution in its settings.'
    )


def prepare_change(request, state):
    original = next(
        (row for row in state['displays'] if row['name'] == request.get('name')), None
    )
    if not original or original['identity'] != request.get('identity'):
        raise ValueError('The display changed or disconnected. Refresh and try again.')
    values = request.get('values')
    if (
        not isinstance(values, dict)
        or not values
        or not set(values) <= {'mode', 'scale', 'transform', 'mirror', 'enabled'}
    ):
        raise ValueError('Unsupported display setting.')
    if not original['enabled'] and values.get('enabled') is not True:
        raise ValueError('Enable this display before changing its settings.')
    if values.get('mode') == 'preferred':
        values = dict(values, mode=preferred_mode(original))
    rows = [dict(row) for row in state['displays']]
    target = next(row for row in rows if row['name'] == original['name'])
    target.update(values)
    if 'mode' in values and 'scale' not in values and mode_parts(target['mode']):
        if any(
            abs(size / target['scale'] - round(size / target['scale'])) > 0.01
            for size in mode_parts(target['mode'])[:2]
        ):
            target['scale'] = 1
    # Validate values before calculating geometry with them. Overlap is checked
    # after preserving the gaps to displays on the right/below a resized output.
    if target['enabled']:
        if target['mode'] not in original['modes']:
            raise ValueError('This display no longer supports the selected mode.')
        number(target['scale'], 0.5, 4)
        number(target['transform'], 0, 7, True)
        if target['mirror'] == 'none':
            others = [
                row
                for row in rows
                if row['name'] != target['name']
                and row['enabled']
                and row['mirror'] == 'none'
            ]
            if not original['enabled'] or original['mirror'] != 'none':
                target['x'] = max(
                    (row['x'] + dimensions(row)[0] for row in others), default=0
                )
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
    changed = [
        row
        for row, previous in zip(rows, before['displays'])
        if row['enabled'] != previous['enabled']
        or (row['enabled'] and fingerprint([row]) != fingerprint([previous]))
    ]
    if not changed:
        return before
    # Include a usable independent output when disabling an output so that
    # apply_rows verifies it before the disable operation.
    if any(not row['enabled'] for row in changed) and not any(
        row['enabled'] and row['mirror'] == 'none' for row in changed
    ):
        changed.append(
            next(row for row in rows if row['enabled'] and row['mirror'] == 'none')
        )
    try:
        apply_rows(changed, selectors(before['displays']))
        until = time.monotonic() + 3
        while True:
            current = snapshot()
            if matches(rows, current):
                return current
            if time.monotonic() >= until:
                raise ValueError(
                    'The display could not activate the requested settings.'
                )
            time.sleep(0.1)
    except Exception as exc:
        try:
            restore(before)
        except Exception as restore_error:
            raise RuntimeError(
                f'{exc} Could not restore the previous setup: {restore_error}'
            ) from exc
        raise


def config_path():
    base = os.environ.get('XDG_CONFIG_HOME', '')
    return (
        Path(base) if os.path.isabs(base) else Path.home() / '.config'
    ) / 'hypr/displays.lua'


def profiles_path():
    return config_path().with_name('display-profiles.json')


def device_keys(rows):
    """Prefer hardware identity across ports; ambiguous/anonymous devices need a port."""
    candidates = {}
    for row in rows:
        _, description, make, model, serial = row['identity']
        if serial and serial.lower() not in ('unknown', 'none', '0'):
            parts = ['serial', make, model, serial]
        elif description:
            parts = ['description', description]
        else:
            parts = ['connector', row['name'], make, model]
        candidates[row['name']] = parts
    result = {}
    for name, parts in candidates.items():
        if list(candidates.values()).count(parts) > 1:
            parts = parts + ['connector', name]
        result[name] = json.dumps(parts, ensure_ascii=True, separators=(',', ':'))
    return result


def profile_key(rows):
    return hashlib.sha256(
        json.dumps(sorted(device_keys(rows).values())).encode()
    ).hexdigest()


def read_profiles():
    try:
        data = json.loads(profiles_path().read_text())
    except FileNotFoundError:
        return dict(version=1, profiles={})
    if (
        not isinstance(data, dict)
        or data.get('version') != 1
        or not isinstance(data.get('profiles'), dict)
    ):
        raise ValueError('Unsupported display profiles file.')
    return data


def profile_rows(current):
    """Resolve saved hardware/mirror identities against today's connectors and modes."""
    rows = current['displays']
    saved = read_profiles()['profiles'].get(profile_key(rows))
    if saved is None:
        return None
    keys = device_keys(rows)
    names = {key: name for name, key in keys.items()}
    if not isinstance(saved, dict) or set(saved) != set(names):
        raise ValueError('The saved monitor set is incomplete.')
    resolved = []
    for row in rows:
        values = saved[keys[row['name']]]
        if not isinstance(values, dict) or set(values) != {
            'enabled',
            'mode',
            'scale',
            'transform',
            'x',
            'y',
            'mirror',
        }:
            raise ValueError('Invalid saved display settings.')
        mirror = values['mirror']
        if mirror is not None and mirror not in names:
            raise ValueError('The saved mirror source is unavailable.')
        mode = matching_mode(row, values['mode'])
        if values['enabled'] and mode is None:
            raise ValueError(
                'A saved display mode is no longer available. Configure this monitor set again.'
            )
        resolved.append(
            dict(
                row,
                **dict(
                    values, mode=mode or row['mode'], mirror=names.get(mirror, 'none')
                ),
            )
        )
    return validate(dict(token=current['token'], displays=resolved), current)


def compile_layout(rows):
    output = '\n'.join(HEADER + [rule(row, selectors(rows)) for row in rows]) + '\n'
    if '\n'.join(saved_lines()) + '\n' != output:
        atomic_write(config_path(), output)


@contextmanager
def control_lock():
    """The shell and independent editor share one mutation/snapshot queue."""
    runtime = os.environ.get('XDG_RUNTIME_DIR', '')
    instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
    if not os.path.isabs(runtime) or not instance or '/' in instance:
        raise RuntimeError('A running Hyprland session is required.')
    path = Path(runtime) / 'hypr' / instance / 'display-controls.lock'
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def atomic_write(path, text):
    """Replace a file atomically (through symlinks), leaving no partial file behind."""
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def saved_lines():
    try:
        return config_path().read_text().splitlines()
    except FileNotFoundError:
        return []


def saved_mode(lines, selector):
    """The mode of the last saved rule for an output, as written by rule()."""
    mode = None
    for line in lines:
        match = RULE.match(line)
        if match and lua_unquote(match[1]) == selector:
            found = RULE_MODE.search(line)
            mode = lua_unquote(found[1]) if found else None
    return mode


def matching_mode(row, value):
    wanted = mode_parts(value or '')
    return next(
        (
            mode
            for mode in row['modes']
            if wanted
            and mode_parts(mode)[:2] == wanted[:2]
            and abs(mode_parts(mode)[2] - wanted[2]) < 0.02
        ),
        None,
    )


def capped_mode(row):
    """Powersave target: the fastest advertised 59-60 Hz mode at the current resolution."""
    current = mode_parts(row['mode'])
    if not current or current[2] <= 60.1:
        return None
    candidates = [
        mode
        for mode in row['modes']
        if mode_parts(mode)[:2] == current[:2] and 59 <= mode_parts(mode)[2] <= 60.1
    ]
    return max(candidates, key=lambda mode: mode_parts(mode)[2], default=None)


def configured_mode(row, lines, names):
    """The refresh the panel would use without Powersave, if it currently looks capped.

    The saved rule is authoritative; without one the host default (preferred mode) applies.
    """
    current = mode_parts(row['mode'])
    if not current or current[2] > 60.1:
        return None
    target = matching_mode(row, saved_mode(lines, names[row['name']]))
    if target is None and saved_mode(lines, names[row['name']]) is None:
        try:
            target = preferred_mode(row)
        except (ValueError, RuntimeError):
            return None
    parts = mode_parts(target or '')
    return target if parts and parts[:2] == current[:2] and parts[2] > 60.1 else None


def persist(current, capped):
    """Only explicit edits save preferences; hotplug and power policy never do."""
    rows = [dict(row) for row in current['displays']]
    names = selectors(rows)
    lines = saved_lines()
    for row in rows:
        internal = INTERNAL.match(row['name'])
        mode = configured_mode(row, lines, names) if capped and internal else None
        if mode:
            row['mode'] = mode
    keys = device_keys(rows)
    saved = {}
    for row in rows:
        saved[keys[row['name']]] = {
            key: row[key] for key in ('enabled', 'mode', 'scale', 'transform', 'x', 'y')
        } | dict(mirror=keys.get(row['mirror']))
    data = read_profiles()
    data['profiles'][profile_key(rows)] = saved
    previous = {}
    for path in (profiles_path(), config_path()):
        previous[path] = path.read_text() if path.exists() else None
    try:
        atomic_write(profiles_path(), json.dumps(data, indent=2) + '\n')
        compile_layout(rows)
    except Exception:
        for path, text in previous.items():
            if text is None:
                path.unlink(missing_ok=True)
            elif path.read_text() != text:
                atomic_write(path, text)
        raise


def save_change(current, before, capped):
    try:
        persist(current, capped)
    except Exception:
        restore(before)
        raise


def power(current, powersave):
    """Stateless Powersave refresh policy for enabled internal panels.

    Powersave caps them to 60 Hz in Hyprland's live rules only; leaving it
    re-applies the saved (or default) refresh. displays.lua is never touched.
    Returns the new state and whether a blank panel still needs the policy.
    """
    rows = [dict(row) for row in current['displays']]
    names, lines, pending = selectors(rows), None, False
    for row in rows:
        if not row['enabled'] or not INTERNAL.match(row['name']):
            continue
        if not row['dpms']:
            # Blank panels are not woken for policy; the wake event retries.
            pending = True
            continue
        if powersave:
            target = capped_mode(row)
        else:
            lines = saved_lines() if lines is None else lines
            target = configured_mode(row, lines, names)
        if target:
            row['mode'] = target
    if fingerprint(rows) == current['token']:
        return current, pending
    return apply_setup(rows, current), pending


def ensure(current, capped=False):
    """Restore exactly this monitor set, or place a new set safely side by side."""
    rows = current['displays']
    if not rows:
        return current
    desired = profile_rows(current)
    if desired is None:
        desired, x = [], 0
        for row in sorted(
            rows,
            key=lambda item: (not bool(INTERNAL.match(item['name'])), item['name']),
        ):
            if not row['modes']:
                desired.append(dict(row, enabled=False))
                continue
            candidate = dict(row, enabled=True, mirror='none', x=x, y=0)
            if not mode_parts(candidate['mode']):
                candidate.update(mode=row['modes'][0], scale=1, transform=0)
            if capped and INTERNAL.match(row['name']):
                candidate['mode'] = (
                    configured_mode(candidate, saved_lines(), selectors(rows))
                    or candidate['mode']
                )
            desired.append(candidate)
            x += dimensions(candidate)[0]
        desired = validate(dict(token=current['token'], displays=desired), current)
    # Do not wake dark panels or disable a replacement before it is verified.
    if any(row['enabled'] and not row['dpms'] for row in rows):
        return current
    configured = desired
    if capped:
        desired = [
            dict(row, mode=capped_mode(row) or row['mode'])
            if INTERNAL.match(row['name']) and row['enabled']
            else row
            for row in desired
        ]
    # apply_setup compares by connector, not snapshot/list order.
    by_name = {row['name']: row for row in desired}
    desired = [by_name[row['name']] for row in rows]
    if fingerprint(desired) != current['token']:
        current = apply_setup(desired, current)
    compile_layout(configured)
    return current


def emergency(current):
    """Recover an otherwise dark session even when a profile is invalid/unavailable."""
    rows = current['displays']
    if any(row['enabled'] and row['mirror'] == 'none' for row in rows):
        return current
    target = next(
        (
            row
            for row in sorted(rows, key=lambda row: not INTERNAL.match(row['name']))
            if row['modes']
        ),
        None,
    )
    if target is None:
        return current
    # Merges into the output's live rule, keeping its last geometry.
    reply = command(
        'eval',
        'hl.monitor({ output = '
        + lua_string(selectors(rows)[target['name']])
        + ', disabled = false })',
    )
    if reply != 'ok':
        raise RuntimeError(reply or 'Hyprland rejected the display change.')
    return snapshot()


def handle(request):
    op = request.get('op')
    capped = request.get('capped') is True
    if op == 'status':
        return dict(data=snapshot())
    if op == 'ensure':
        current = emergency(snapshot())
        return dict(
            data=ensure(current, capped),
            deferred=any(
                row['enabled'] and not row['dpms'] for row in current['displays']
            ),
        )
    if op == 'power':
        data, pending = power(snapshot(), capped)
        return dict(data=data, pending=pending)
    if op == 'change':
        before = snapshot()
        current = control(request, before)
        save_change(current, before, capped)
        if not capped:
            return dict(data=current)
        data, pending = power(current, True)
        return dict(data=data, pending=pending)
    if op == 'arrange':
        before = snapshot()
        positions = request.get('positions')
        if not isinstance(positions, dict) or set(positions) != {
            row['name']
            for row in before['displays']
            if row['enabled'] and row['mirror'] == 'none'
        }:
            raise ValueError('The connected displays changed. Reload the arrangement.')
        rows = []
        for row in before['displays']:
            values = positions.get(row['name'], {})
            if (
                not isinstance(values, dict)
                or set(values) - {'x', 'y'}
                or (row['name'] in positions and set(values) != {'x', 'y'})
            ):
                raise ValueError('Only display coordinates can be changed here.')
            rows.append(dict(row, **values))
        rows = validate(dict(token=request.get('token'), displays=rows), before)
        current = apply_setup(rows, before)
        # Arrangement never edits refresh: retain the uncapped panel preference.
        save_change(current, before, True)
        return dict(data=current)
    raise ValueError('Unknown display operation.')


def response(request):
    try:
        return dict(ok=True, error='', **handle(request))
    except Exception as exc:
        try:
            data = snapshot()
        except Exception:
            data = dict(available=False, displays=[], token='')
        return dict(ok=False, error=str(exc), data=data)


def main():
    # One request per process; the shell owns event subscriptions and queues.
    line = sys.stdin.readline()
    if line:
        try:
            with control_lock():
                result = response(json.loads(line))
        except Exception as exc:
            result = dict(
                ok=False,
                error=str(exc),
                data=dict(available=False, displays=[], token=''),
            )
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
