#!/usr/bin/env python3
"""Generic keyboard brightness and installed hardware lighting providers."""

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

LEDS = Path('/sys/class/leds')
PROVIDERS = (
    Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    / 'devices/keyboard/backends'
)


def snapshot():
    values = []
    for path in sorted(LEDS.glob('*')):
        if not re.search(r'(^|:)kbd_backlight($|:)', path.name):
            continue
        row = dict(
            key=path.name,
            identity=str(path.resolve()),
            value=0,
            maximum=0,
            available=False,
            reason='',
        )
        try:
            row['value'] = int((path / 'brightness').read_text())
            row['maximum'] = int((path / 'max_brightness').read_text())
            if row['maximum'] <= 0 or not 0 <= row['value'] <= row['maximum']:
                raise ValueError('The keyboard returned an invalid brightness range.')
            if not shutil.which('brightnessctl'):
                raise ValueError('Keyboard brightness needs brightnessctl.')
            row['available'] = True
        except (OSError, ValueError) as error:
            row['reason'] = str(error)
        values.append(row)
    return values


def handle(request):
    values = snapshot()
    if request.get('op') == 'status':
        return values
    if request.get('op') != 'set':
        raise ValueError('Unknown keyboard backlight operation.')
    row = next((row for row in values if row['key'] == request.get('key')), None)
    if (
        not row
        or row['identity'] != request.get('identity')
        or row['maximum'] != request.get('maximum')
    ):
        raise ValueError('The keyboard backlight changed. Refresh and try again.')
    if not row['available']:
        raise ValueError(row['reason'])
    value = request.get('value')
    if type(value) is not int or not 0 <= value <= row['maximum']:
        raise ValueError('Invalid keyboard brightness level.')
    # Exact matching avoids brightnessctl's wildcard device selection.
    if any(char in row['key'] for char in '*?['):
        raise ValueError('This keyboard backlight identifier is unsupported.')
    result = subprocess.run(
        [
            'brightnessctl',
            '--class=leds',
            '--device',
            row['key'],
            '--quiet',
            'set',
            str(value),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode:
        raise ValueError(
            result.stderr.strip() or 'Could not change keyboard brightness.'
        )
    current = snapshot()
    if not any(
        item['key'] == row['key']
        and item['identity'] == row['identity']
        and item['maximum'] == row['maximum']
        for item in current
    ):
        raise ValueError(
            'The keyboard backlight disconnected while brightness was changing.'
        )
    return current


class Controller:
    def __init__(self):
        self.providers = {}
        self.native_keys = set()
        for path in sorted(PROVIDERS.glob('*.py')):
            spec = importlib.util.spec_from_file_location(
                'keyboard_lighting_' + path.stem, path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.providers[path.stem] = module.Provider()

    def snapshot(self):
        native = snapshot()
        self.native_keys = {row['key'] for row in native}
        for row in native:
            row.update(
                provider='sysfs',
                label=row['key'].split(':')[0] or 'Keyboard',
                connection='',
                effects=[],
                effect=-1,
                rgb=False,
                color='',
                lightingPath='',
                modes=[],
                mode=-1,
            )
        values = {row['key']: row for row in native}
        claimed = set()
        for name, provider in self.providers.items():
            for row in provider.snapshot(native):
                if row['key'] in claimed:
                    raise ValueError(
                        'Multiple lighting providers claimed the same keyboard.'
                    )
                claimed.add(row['key'])
                values[row['key']] = dict(row, provider=name)
        return list(values.values())

    def handle(self, request):
        if request.get('op') == 'status':
            return self.snapshot()
        values = self.snapshot()
        row = next(
            (
                row
                for row in values
                if row['key'] == request.get('key')
                and row['identity'] == request.get('identity')
            ),
            None,
        )
        if not row:
            raise ValueError('The keyboard disconnected or changed.')
        if request.get('op') == 'set' and row['key'] in self.native_keys:
            handle(request)
        elif row['provider'] in self.providers:
            self.providers[row['provider']].change(row, request)
        else:
            raise ValueError('This keyboard does not support that lighting operation.')
        return self.snapshot()

    def close(self):
        for provider in self.providers.values():
            provider.close()


def main():
    controller = Controller()
    try:
        for line in sys.stdin:
            try:
                result = dict(
                    ok=True, values=controller.handle(json.loads(line)), error=''
                )
            except Exception as error:
                result = dict(ok=False, error=str(error))
            print(json.dumps(result), flush=True)
    finally:
        controller.close()


if __name__ == '__main__':
    main()
