"""Read and validate the ordinary V4L2 controls exposed by a webcam."""

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

LABELS = {
    'privacy': 'Camera privacy',
    'brightness': 'Brightness',
    'contrast': 'Contrast',
    'saturation': 'Saturation',
    'sharpness': 'Sharpness',
    'gain': 'Gain',
    'white_balance_automatic': 'Auto white balance',
    'white_balance_temperature_auto': 'Auto white balance',
    'white_balance_temperature': 'White balance',
    'auto_exposure': 'Exposure mode',
    'exposure_auto': 'Exposure mode',
    'exposure_time_absolute': 'Exposure',
    'exposure_absolute': 'Exposure',
    'focus_automatic_continuous': 'Autofocus',
    'focus_auto': 'Autofocus',
    'focus_absolute': 'Focus',
    'zoom_absolute': 'Zoom',
    'power_line_frequency': 'Anti-flicker',
    'backlight_compensation': 'Backlight compensation',
}


def identity(device):
    """Device number and sysfs path; a different camera node invalidates stale UI actions.

    Image controls are harmless on any camera and every write is range-checked
    against that device's fresh control list, so no deeper fingerprint is needed.
    """
    if not isinstance(device, str) or not re.fullmatch(r'/dev/video\d+', device):
        raise ValueError('This camera does not expose Linux webcam controls.')
    info = os.stat(device)
    if not stat.S_ISCHR(info.st_mode):
        raise ValueError('The webcam is no longer connected.')
    node = (Path('/sys/class/video4linux') / Path(device).name).resolve(strict=True)
    return f'{info.st_rdev}:{node}'


def command(device, *args):
    try:
        result = subprocess.run(
            ['v4l2-ctl', '--device', device, *args],
            capture_output=True,
            text=True,
            timeout=4,
            env={**os.environ, 'LC_ALL': 'C'},
        )
    except FileNotFoundError:
        raise ValueError('Install v4l-utils for camera settings.') from None
    if result.returncode:
        raise ValueError(
            result.stderr.strip() or 'The camera settings are unavailable.'
        )
    return result.stdout


def parse_controls(text):
    controls = []
    current = None
    for line in text.splitlines():
        match = re.match(r'\s*(\w+)\s+0x[\da-fA-F]+\s+\(([^)]+)\)\s*:\s*(.*)', line)
        if match:
            key, kind, data = match.groups()
            current = None
            if key not in LABELS or kind not in ('int', 'bool', 'menu', 'intmenu'):
                continue
            values = dict(re.findall(r'(min|max|step|default|value)=(-?\d+)', data))
            if 'value' not in values:
                continue
            flags = data.split('flags=', 1)[-1].split(',') if 'flags=' in data else []
            flags = [flag.strip() for flag in flags]
            current = dict(
                key=key,
                label=LABELS[key],
                kind=kind,
                value=int(values['value']),
                minimum=int(values.get('min', 0)),
                maximum=int(values.get('max', 1)),
                step=max(1, int(values.get('step', 1))),
                writable=not any(
                    flag in flags
                    for flag in (
                        'read-only',
                        'inactive',
                        'disabled',
                        'grabbed',
                        'write-only',
                    )
                ),
                choices=[],
            )
            controls.append(current)
        elif current and current['kind'] in ('menu', 'intmenu'):
            choice = re.match(r'\s*(-?\d+):\s*(.+)', line)
            if choice:
                current['choices'].append(
                    dict(value=int(choice[1]), label=choice[2].strip())
                )
    return controls


def snapshot(device):
    return dict(
        token=identity(device),
        controls=parse_controls(command(device, '--list-ctrls-menus')),
    )


def handle(request):
    device = request.get('device')
    state = snapshot(device)
    op = request.get('op', 'status')
    if op == 'status':
        return state
    if op != 'set':
        raise ValueError('Unknown webcam action.')
    if request.get('token') != state['token']:
        raise ValueError('The webcam changed. Reopen its settings.')
    control = next(
        (row for row in state['controls'] if row['key'] == request.get('key')), None
    )
    value = request.get('value')
    if not control or not control['writable']:
        raise ValueError('This camera control is unavailable or automatic.')
    if type(value) is not int or not control['minimum'] <= value <= control['maximum']:
        raise ValueError('Invalid camera setting.')
    if control['kind'] in ('menu', 'intmenu'):
        if value not in [choice['value'] for choice in control['choices']]:
            raise ValueError('Invalid camera setting.')
    elif (value - control['minimum']) % control['step']:
        raise ValueError('Invalid camera setting step.')
    command(device, '--set-ctrl', f'{control["key"]}={value}')
    return snapshot(device)


if __name__ == '__main__':
    try:
        print(json.dumps(dict(ok=True, **handle(json.loads(sys.stdin.readline())))))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(ok=False, error=str(error))))
