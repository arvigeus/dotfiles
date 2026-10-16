"""Native night light toggle and monitor-scoped Keep awake leases."""
import fcntl
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time

import backend


def session_directory():
    signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')
    if not signature:
        raise RuntimeError('Display controls require a Hyprland session.')
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'hypr' / signature / 'desktop-keep-awake'


def systemctl(*args):
    result = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=8)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Could not control hyprsunset.service.')
    return result.stdout.strip()


class Lease:
    """A lock proves liveness; an atomic JSON file describes protected hardware."""
    def __init__(self):
        self.fd = None
        self.lock = None
        self.path = None

    def publish(self, displays):
        if not displays:
            self.close()
            return
        directory = session_directory()
        directory.mkdir(parents=True, exist_ok=True)
        if self.fd is None:
            self.fd, name = tempfile.mkstemp(dir=directory, prefix='lease-', suffix='.lock')
            self.lock = Path(name)
            self.path = self.lock.with_suffix('.json')
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.lease-')
        try:
            with os.fdopen(descriptor, 'w') as output:
                json.dump(displays, output)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def close(self):
        if self.fd is not None:
            self.path.unlink(missing_ok=True)
            os.close(self.fd)
            self.lock.unlink(missing_ok=True)
            self.fd = None


def protected(displays):
    try:
        directory = session_directory()
    except RuntimeError:
        return set()
    live = {row['name']: row['identity'] for row in displays if row['enabled']}
    names = set()
    for path in directory.glob('lease-*.lock'):
        try:
            with path.open() as descriptor:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    values = json.loads(path.with_suffix('.json').read_text())
                    names.update(name for name, identity in values.items() if name in live and live[name] == identity)
                # An unlocked file is a dead lease, including after a crash.
        except (OSError, ValueError, AttributeError):
            continue
    return names


def idle_action(op):
    displays = backend.snapshot()['displays']
    awake = protected(displays)
    if op == 'allow-session-idle':
        return 1 if awake else 0
    if op != 'blank':
        raise ValueError('Unknown idle action.')
    for row in displays:
        if row['enabled'] and row['name'] not in awake:
            backend.command('dispatch', 'hl.dsp.dpms({action="off",monitor=' + backend.lua_string(row['name']) + '})')
    return 0


class Controller:
    def __init__(self):
        self.lease = Lease()
        self.awake = {}
        self.night_available = False
        self.night_enabled = False
        self.error = ''

    def tick(self):
        self.night_available = bool(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and shutil.which('hyprsunset'))
        if self.night_available:
            self.night_enabled = systemctl('show', 'hyprsunset.service', '--property=ActiveState', '--value') in ('active', 'activating')
        else:
            self.night_enabled = False
        if self.awake:
            rows = backend.snapshot()['displays']
            live = {row['name']: row['identity'] for row in rows if row['enabled']}
            next_awake = {name: identity for name, identity in self.awake.items() if live.get(name) == identity}
            if next_awake != self.awake:
                self.lease.publish(next_awake)
                self.awake = next_awake

    def action(self, request):
        self.error = ''
        op = request.get('op')
        if op == 'night':
            enabled = request.get('enabled')
            if type(enabled) is not bool:
                raise ValueError('Invalid night light switch.')
            if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') or not shutil.which('hyprsunset'):
                raise RuntimeError('Install hyprsunset to use Night light.')
            systemctl('enable' if enabled else 'disable', '--now', 'hyprsunset.service')
        elif op == 'awake':
            name, identity, enabled = request.get('name'), request.get('identity'), request.get('enabled')
            if not isinstance(name, str) or type(enabled) is not bool:
                raise ValueError('Invalid Keep awake switch.')
            rows = backend.snapshot()['displays']
            row = next((row for row in rows if row['name'] == name and row['identity'] == identity and row['enabled']), None)
            if row is None:
                raise ValueError('This display is no longer available. Refresh and try again.')
            values = dict(self.awake)
            if enabled:
                values[name] = identity
                if not row['dpms']:
                    backend.command('dispatch', 'hl.dsp.dpms({action="on",monitor=' + backend.lua_string(name) + '})')
            else:
                values.pop(name, None)
            self.lease.publish(values)
            self.awake = values
        elif op != 'status':
            raise ValueError('Unknown display comfort action.')
        self.tick()

    def snapshot(self):
        return dict(nightEnabled=self.night_enabled, nightAvailable=self.night_available, awake=self.awake, error=self.error)

    def close(self):
        self.lease.close()
        self.awake = {}


def main():
    controller = Controller()
    previous = None

    def emit(reply=False):
        nonlocal previous
        state = controller.snapshot()
        if reply or state != previous:
            print(json.dumps(dict(reply=reply, state=state)), flush=True)
            previous = state

    def tick():
        try:
            controller.tick()
        except Exception as error:
            controller.error = str(error)

    try:
        tick()
        emit()
        deadline = time.monotonic() + 3
        buffer = b''
        while True:
            readable, _, _ = select.select([sys.stdin], [], [], max(0, deadline - time.monotonic()))
            if readable:
                chunk = os.read(sys.stdin.fileno(), 8192)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > 65536:
                    raise ValueError('Display comfort request too large.')
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        request = json.loads(line)
                        if not isinstance(request, dict):
                            raise ValueError('Expected a display comfort request.')
                        controller.action(request)
                    except Exception as error:
                        controller.error = str(error)
                    emit(reply=True)
            if time.monotonic() >= deadline:
                tick()
                emit()
                deadline = time.monotonic() + 3
    finally:
        controller.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        try:
            sys.exit(idle_action(sys.argv[1]))
        except Exception as error:
            print(error, file=sys.stderr)
            sys.exit(1)
    main()
