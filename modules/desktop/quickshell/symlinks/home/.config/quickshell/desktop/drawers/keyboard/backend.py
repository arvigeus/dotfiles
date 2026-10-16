#!/usr/bin/env python3
"""Input-language adapter. Reading state never starts an input method."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def command(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not change or read the input language.")
    return result.stdout


def provider():
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    path = config / 'quickshell/input-language.json'
    if not path.exists():
        return None
    settings = json.loads(path.read_text())
    args = settings.get('command') if isinstance(settings, dict) else None
    if not isinstance(args, list) or not args or not all(isinstance(arg, str) and arg for arg in args):
        raise ValueError('Input language command must be a nonempty array of strings.')
    if not shutil.which(args[0]):
        return None
    return args


def request(action, code=''):
    if action not in ('status', 'select') or (action == 'select' and code not in ('en', 'bg', 'vi')):
        raise ValueError('Expected status [keyboard] or select en|bg|vi.')
    args = provider()
    if args:
        state = json.loads(command([*args, action, code]))
        if not isinstance(state, dict):
            raise ValueError('The input language controller returned invalid state.')
        if state.get('error'):
            raise ValueError(state['error'])
        if state.get('language') not in ('en', 'bg', 'vi') or state.get('secondary') not in ('bg', 'vi') or not isinstance(state.get('available'), bool):
            raise ValueError('The input language controller returned invalid state.')
        return state
    devices = json.loads(command(['hyprctl', '-j', 'devices'])).get('keyboards', [])
    keyboard = next((row for row in devices if row.get('name') == code), None)
    keyboard = keyboard or next((row for row in devices if row.get('main')), None) or next(iter(devices), None)
    if not keyboard:
        raise ValueError('No keyboard is available.')
    layouts = keyboard.get('layout', 'us').split(',')
    if action == 'select':
        layout = {'en': 'us', 'bg': 'bg', 'vi': None}[code]
        if layout not in layouts:
            raise ValueError('Vietnamese requires the input language controller.' if code == 'vi' else 'This keyboard layout is not configured.')
        command(['hyprctl', 'switchxkblayout', 'all', str(layouts.index(layout))])
        return request('status')
    index = keyboard.get('active_layout_index')
    language = ('bg' if layouts[index] == 'bg' else 'en') if isinstance(index, int) and 0 <= index < len(layouts) else ('bg' if 'bulgarian' in keyboard.get('active_keymap', '').lower() else 'en')
    return dict(available=False, secondary='bg', language=language, running=False)


if __name__ == '__main__':
    try:
        print(json.dumps(request(*sys.argv[1:])))
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
