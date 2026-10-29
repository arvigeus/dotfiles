#!/usr/bin/env python3
"""Read and format the active Hyprland keyboard bindings for the drawer."""

import json
import re
import subprocess
import sys


MODIFIERS = (
    (4, 'Ctrl'),
    (8, 'Alt'),
    (1, 'Shift'),
    (64, 'Win'),
    (2, 'Caps'),
    (16, 'Mod2'),
    (32, 'Mod3'),
    (128, 'Mod5'),
)
KEY_NAMES = {
    'return': 'Enter',
    'kp_enter': 'Keypad Enter',
    'escape': 'Esc',
    'space': 'Space',
    'left': '←',
    'right': '→',
    'up': '↑',
    'down': '↓',
    'page_up': 'Page Up',
    'page_down': 'Page Down',
    'prior': 'Page Up',
    'next': 'Page Down',
    'home': 'Home',
    'end': 'End',
    'tab': 'Tab',
    'backspace': 'Backspace',
    'delete': 'Delete',
    'insert': 'Insert',
    'print': 'Print',
    'period': '.',
    'bracketleft': '[',
    'bracketright': ']',
}


def key_label(bind):
    key = str(bind.get('key') or '').strip()
    if not key:
        keycode = bind.get('keycode')
        if keycode in (None, 0, '0', ''):
            return ''
        key = f'Code {keycode}'
    elif key.lower().startswith('code:'):
        key = f'Code {key.partition(":")[2]}'
    else:
        key = KEY_NAMES.get(key.lower(), key)

    try:
        mask = int(bind.get('modmask', 0))
    except (TypeError, ValueError):
        mask = 0
    mask = max(0, mask)
    modifiers = [label for bit, label in MODIFIERS if mask & bit]
    known_mask = sum(bit for bit, _ in MODIFIERS)
    unknown = mask & ~known_mask
    bit = 1
    while unknown:
        if unknown & bit:
            modifiers.append(f'Mod{bit.bit_length() - 1}')
            unknown &= ~bit
        bit <<= 1
    combination = '+'.join([*modifiers, key])
    submap = str(bind.get('submap') or '').strip()
    return f'{submap} · {combination}' if submap else combination


def action_label(bind):
    description = str(bind.get('description') or '').strip()
    if description:
        return description
    dispatcher = str(bind.get('dispatcher') or 'Binding').strip()
    if dispatcher.startswith('function:'):
        return 'Custom action'
    # Lua configs report HL.Dispatcher(name) with an opaque handle as the argument.
    native = re.fullmatch(r'HL\.Dispatcher\((\w+)\)', dispatcher)
    if native and native[1] == 'exec_cmd':
        return 'Run command'
    if native:
        return native[1].replace('_', ' ').capitalize()
    argument = str(bind.get('arg') or '').strip()
    label = dispatcher + (': ' + argument if argument else '')
    return label if len(label) <= 180 else label[:177].rstrip() + '…'


def bindings():
    result = subprocess.run(
        ['hyprctl', '-j', 'binds'],
        capture_output=True,
        text=True,
        timeout=3,
        check=True,
    )
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, list):
        raise ValueError('Hyprland returned an invalid binding list.')

    rows = []
    for bind in parsed:
        if not isinstance(bind, dict) or bind.get('mouse'):
            continue
        # Buttons are mouse:N and wheel steps mouse_up/down/left/right.
        if str(bind.get('key') or '').lower().startswith('mouse'):
            continue
        key = key_label(bind)
        if not key:
            continue
        rows.append({'keys': key, 'description': action_label(bind)})
    rows.sort(key=lambda row: (row['keys'].casefold(), row['description'].casefold()))
    return rows


def main():
    try:
        result = {'shortcuts': bindings(), 'error': ''}
    except FileNotFoundError:
        result = {'shortcuts': [], 'error': 'hyprctl is unavailable.'}
    except subprocess.TimeoutExpired:
        result = {'shortcuts': [], 'error': 'Hyprland did not respond.'}
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or '').strip()
        result = {
            'shortcuts': [],
            'error': detail[:180] or 'Could not read Hyprland bindings.',
        }
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        result = {'shortcuts': [], 'error': 'Could not read Hyprland bindings.'}
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
