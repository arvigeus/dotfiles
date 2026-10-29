"""Shared fixtures: repository paths, helper loaders, the isolated QML runner and
a fake Hyprland IPC."""

import copy
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DESKTOP = REPO / 'modules/desktop/quickshell/symlinks/home/.config/quickshell/desktop'
AUDIO_LIB = REPO / 'modules/media/tools/audio/files/usr/local/lib/audio-tools'
sys.path.insert(0, str(AUDIO_LIB))
PALETTE = REPO / 'modules/look-and-feel/palette/symlinks/etc/desktop-palette.json'
QS = shutil.which('qs')


def load(name, path):
    """Import a helper script as a module without writing bytecode next to it."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    disabled = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = disabled
    return module


backend = load('desktop_displays', DESKTOP / 'drawers/displays/backend.py')


def display(name='eDP-1', **values):
    return dict(
        dict(
            name=name,
            identity=[name, 'Test', '', '', '123'],
            label='Test display',
            enabled=True,
            mode='1920x1080@60.00Hz',
            modes=['1920x1080@60.00Hz', '1920x1080@120.00Hz', '1280x720@60.00Hz'],
            scale=1,
            transform=0,
            x=0,
            y=0,
            mirror='none',
            dpms=True,
        ),
        **values,
    )


def described(name, description, **values):
    return display(name, identity=[name, description, '', '', ''], **values)


def state(rows):
    return dict(
        available=True, displays=copy.deepcopy(rows), token=backend.fingerprint(rows)
    )


def floating_window(path, width=None, height=None):
    """Replace the first PanelWindow in path with a FloatingWindow.

    Offscreen QPA has no layer shell. Only that window's own layer-shell
    declarations (grouped or single-line) are removed; content, input, focus and
    bindings run unchanged.
    """
    source = path.read_text()
    start = re.search(r'^( *)PanelWindow \{\n', source, flags=re.M)
    end = start and re.compile(rf'^{start[1]}\}}\n', re.M).search(source, start.end())
    if not end:
        raise AssertionError(f'{path}: no PanelWindow block to replace')
    inner = start[1] + '    '
    body = re.sub(
        rf'^{inner}(?:(?:anchors|margins) \{{[^}}]*\}}'
        r'|(?:anchors|margins|exclusionMode|exclusiveZone|WlrLayershell)\b.*)\n',
        '',
        source[start.end() : end.start()],
        flags=re.M,
    )
    size = ''.join(
        f'{inner}{name}: {value}\n'
        for name, value in (('implicitWidth', width), ('implicitHeight', height))
        if value
    )
    path.write_text(
        f'{source[: start.start()]}{start[1]}FloatingWindow {{\n{size}{body}{source[end.start() :]}'
    )


def private_bus(root):
    """Return a dbus-run-session prefix for a bus that activates nothing.

    The stock session bus configuration activates real portals and daemons from
    the system service directories into the test's runtime directory.
    """
    config = root / 'bus.conf'
    config.write_text(f"""<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:dir={root}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
""")
    return ['dbus-run-session', f'--config-file={config}', '--']


class FakeHyprland:
    """Answer Quickshell's Hyprland IPC from fixture state and record requests.

    A dispatch of `fake:` + JSON is a test control message: `at` moves clients,
    then `events` are sent on the event socket in order. Other dispatches are
    recorded in `dispatches`; every request is logged with its monotonic time.
    """

    def __init__(self, directory, clients, workspaces, monitors):
        self.state = dict(clients=clients, workspaces=workspaces, monitors=monitors)
        self.dispatches = []
        self.requests = []
        self.listeners = []
        self.servers = []
        directory.mkdir(parents=True)
        for name, handler in (('.socket.sock', self.answer), ('.socket2.sock', None)):
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(directory / name))
            server.listen()
            self.servers.append(server)
            threading.Thread(
                target=self.serve, args=(server, handler), daemon=True
            ).start()

    def serve(self, server, handler):
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            if handler:
                with connection:
                    handler(connection)
            else:
                self.listeners.append(connection)

    def answer(self, connection):
        request = connection.recv(1 << 16).decode()
        self.requests.append((time.monotonic(), request))
        if request == 'j/status':
            reply = json.dumps({'configProvider': 'lua'})
        elif request.startswith('j/'):
            reply = json.dumps(self.state.get(request[2:], []))
        elif request.startswith('dispatch fake:'):
            control = json.loads(request.removeprefix('dispatch fake:'))
            moved = control.get('at', {})
            for client in self.state['clients']:
                client['at'] = moved.get(client['address'], client['at'])
            self.send(*control.get('events', []))
            reply = 'ok'
        else:
            self.dispatches.append(request.removeprefix('dispatch '))
            reply = 'ok'
        connection.sendall(reply.encode())

    def send(self, *events):
        for event in events:
            for listener in self.listeners:
                listener.sendall(f'{event}\n'.encode())

    def close(self):
        for endpoint in self.servers + self.listeners:
            # Shutdown also wakes a thread blocked in accept().
            try:
                endpoint.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            endpoint.close()


def copy_theme_ui(root):
    """Copy the UI with a private replacement for the global palette."""
    shutil.copytree(DESKTOP / 'ui', root / 'ui')
    palette = root / 'ui/palette.json'
    shutil.copy(PALETTE, palette)
    for name in ('Theme.qml', 'theme.py'):
        path = root / 'ui' / name
        path.write_text(
            path.read_text().replace('/etc/desktop-palette.json', str(palette))
        )


def run_qml(test, body, setup=None):
    """Run body as shell.qml over a copy of the shell with private config/runtime dirs."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        copy_theme_ui(root)
        for name in ('icons', 'drawers', 'spaces'):
            shutil.copytree(DESKTOP / name, root / name)
        (root / 'runtime').mkdir(mode=0o700)
        config = root / 'config/quickshell/desktop'
        config.mkdir(parents=True)
        (config / 'theme-mode').write_text('dark\n')
        (root / 'drawers/displays/brightness.py').write_text(
            'import json,sys; json.loads(sys.stdin.readline()); print(json.dumps(dict(ok=True,values=[])))'
        )
        if setup:
            setup(root)
        (root / 'shell.qml').write_text(body)
        env = {
            **os.environ,
            'QT_QPA_PLATFORM': os.environ.get('DISPLAY_PREVIEW_PLATFORM', 'offscreen'),
            'XDG_CONFIG_HOME': str(root / 'config'),
            'XDG_RUNTIME_DIR': str(root / 'runtime'),
            'XDG_STATE_HOME': str(root / 'state'),
            'XDG_DATA_HOME': str(root / 'data'),
            'XDG_CACHE_HOME': str(root / 'cache'),
            'PIPEWIRE_REMOTE': 'dotfiles-tests-unavailable',
            'PYTHONPATH': os.pathsep.join(
                filter(None, (str(AUDIO_LIB), os.environ.get('PYTHONPATH')))
            ),
        }
        if env['QT_QPA_PLATFORM'] != 'offscreen':
            env['XDG_RUNTIME_DIR'] = os.environ['XDG_RUNTIME_DIR']
        env.pop('HYPRLAND_INSTANCE_SIGNATURE', None)
        if env['QT_QPA_PLATFORM'] == 'offscreen':
            # Qt Multimedia's FFmpeg hardware probe opens $DISPLAY on the GUI thread.
            env.pop('WAYLAND_DISPLAY', None)
            env.pop('DISPLAY', None)
        result = subprocess.run(
            [QS, '--no-color', '-p', str(root / 'shell.qml')],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    log = result.stdout + result.stderr
    test.assertEqual(result.returncode, 0, log)
    test.assertIn('DISPLAY_PASS', log)
    for error in (
        'DISPLAY_FAIL',
        'TypeError',
        'ReferenceError',
        'Binding loop',
        'Unable to assign',
        'polish() loop',
        'Polish loop',
        'Failed to load',
        'coerced to void',
    ):
        test.assertNotIn(error, log)
    return log
