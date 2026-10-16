#!/usr/bin/env python3
"""Physical backlight/DDC controls, independent of layout/menu requests."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import backend

BACKLIGHT = Path('/sys/class/backlight')
DRM = Path('/sys/class/drm')


def run(*args):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Brightness control is unavailable.')
    return result.stdout.strip()


def controller(row):
    name = row['name']
    # Never associate an arbitrary backlight or I2C bus with a different output.
    connectors = [path for path in DRM.glob('card*-*')
                  if re.fullmatch(r'card\d+-' + re.escape(name), path.name)
                  and (path / 'status').read_text().strip() == 'connected']
    if len(connectors) != 1:
        raise ValueError('No unambiguous hardware brightness control for this output.')
    connector = connectors[0]
    lights = [path for path in BACKLIGHT.iterdir() if connector.resolve() in path.resolve().parents]
    if len(lights) == 1:
        return dict(kind='backlight', key=lights[0].name, path=lights[0])
    if len(lights) > 1:
        raise ValueError('Multiple backlights are associated with this output.')
    if name.startswith(('eDP-', 'LVDS-', 'DSI-')):
        raise ValueError('This panel exposes no supported backlight control.')
    # DisplayPort uses the connector's AUX adapter. On AMD the ddc symlink
    # can point at an unused physical I2C bus instead of that AUX channel.
    aux = [path for path in connector.glob('i2c-*') if re.fullmatch(r'i2c-\d+', path.name)]
    if len(aux) > 1:
        raise ValueError('Multiple DDC/CI adapters are associated with this output.')
    if aux:
        return dict(kind='ddc', key=aux[0].name.removeprefix('i2c-'), path=connector)
    ddc = connector / 'ddc'
    bus = re.fullmatch(r'i2c-(\d+)', ddc.resolve().name) if ddc.exists() else None
    if not bus:
        raise ValueError('This connection exposes no DDC/CI brightness control.')
    return dict(kind='ddc', key=bus[1], path=connector)


def read_control(control):
    if control['kind'] == 'backlight':
        path = control['path']
        current = int((path / 'brightness').read_text())
        maximum = int((path / 'max_brightness').read_text())
    else:
        if not shutil.which('ddcutil'):
            raise ValueError('Install ddcutil to control this monitor’s brightness.')
        text = run('ddcutil', '--bus', control['key'], '--terse', 'getvcp', '10')
        value = re.search(r'^VCP\s+10\s+C\s+(\d+)\s+(\d+)\s*$', text, re.MULTILINE | re.IGNORECASE)
        if not value:
            raise ValueError('Brightness is unavailable. Check the monitor’s DDC/CI setting and I2C access.')
        current, maximum = map(int, value.groups())
    if maximum <= 0 or current < 0 or current > maximum:
        raise ValueError('The display returned an invalid brightness range.')
    return current, maximum


def describe(row):
    result = dict(name=row['name'], identity=row['identity'], available=False, value=0, key='', kind='', reason='')
    try:
        control = controller(row)
        result.update(key=control['key'], kind=control['kind'])
        current, maximum = read_control(control)
        result.update(available=True, value=round(current * 100 / maximum))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result['reason'] = str(exc)
    return result


def handle(request):
    rows = backend.snapshot()['displays']
    if request.get('op') == 'status':
        return [describe(row) for row in rows]
    if request.get('op') != 'brightness':
        raise ValueError('Unknown brightness operation.')
    row = next((row for row in rows if row['name'] == request.get('name')), None)
    if not row or row['identity'] != request.get('identity'):
        raise ValueError('The display changed or disconnected.')
    if not row['enabled']:
        raise ValueError('Enable this display before changing brightness.')
    value = backend.number(request.get('value'), 1, 100)
    control = controller(row)
    if (control['kind'], control['key']) != (request.get('kind'), request.get('key')):
        raise ValueError('The brightness controller changed. Refresh and try again.')
    _, maximum = read_control(control)
    raw = max(1, round(value * maximum / 100))
    if control['kind'] == 'backlight':
        run('brightnessctl', '--class=backlight', '--device', control['key'], 'set', str(raw))
    else:
        run('ddcutil', '--bus', control['key'], 'setvcp', '10', str(raw))
    # Recheck the identity after a potentially slow hardware transaction.
    current = next((item for item in backend.snapshot()['displays'] if item['name'] == row['name']), None)
    if not current or current['identity'] != row['identity']:
        raise ValueError('The display disconnected while brightness was changing.')
    return [describe(current)]


def main():
    try:
        values = handle(json.loads(sys.stdin.readline()))
        result = dict(ok=True, values=values)
    except Exception as exc:
        result = dict(ok=False, error=str(exc), values=[])
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
