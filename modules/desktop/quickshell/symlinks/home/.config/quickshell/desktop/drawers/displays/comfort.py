"""Native night light toggle and monitor-scoped Keep awake leases.

As a CLI for hypridle (via desktop-idle) it exits 0 to allow, 1 to deny and
2 when the helper itself failed, so callers can choose how to fail. A denial
also prints `defer`: Python exits 1 on a crash too, before this code can run.
"""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import backend

DEFER = 1
HELPER_ERROR = 2


def session_directory(kind='desktop-keep-awake'):
    signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')
    if not signature:
        raise RuntimeError('Display controls require a Hyprland session.')
    return (
        Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
        / 'hypr'
        / signature
        / kind
    )


def systemctl(*args):
    result = subprocess.run(
        ['systemctl', '--user', *args], capture_output=True, text=True, timeout=8
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or 'Could not control hyprsunset.service.'
        )
    return result.stdout.strip()


class Lease:
    """A lock proves liveness; an atomic JSON file describes protected hardware."""

    def __init__(self, kind='desktop-keep-awake'):
        self.kind = kind
        self.fd = None
        self.lock = None
        self.path = None

    def publish(self, displays):
        if not displays:
            self.close()
            return
        directory = session_directory(self.kind)
        directory.mkdir(parents=True, exist_ok=True)
        if self.fd is None:
            self.fd, name = tempfile.mkstemp(
                dir=directory, prefix='lease-', suffix='.lock'
            )
            self.lock = Path(name)
            self.path = self.lock.with_suffix('.json')
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        backend.atomic_write(self.path, json.dumps(displays))

    def close(self):
        if self.fd is not None:
            self.path.unlink(missing_ok=True)
            os.close(self.fd)
            self.lock.unlink(missing_ok=True)
            self.fd = None


def live_leases(kind='desktop-keep-awake'):
    try:
        directory = session_directory(kind)
    except RuntimeError:
        return
    for path in directory.glob('lease-*.lock'):
        try:
            with path.open() as descriptor:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    values = json.loads(path.with_suffix('.json').read_text())
                    if isinstance(values, dict):
                        yield values
                # An unlocked file is a dead lease, including after a crash.
        except (OSError, ValueError, AttributeError):
            continue


def protected(displays):
    live = {row['name']: row['identity'] for row in displays if row['enabled']}
    return {
        name
        for values in live_leases()
        for name, identity in values.items()
        if name in live and live[name] == identity
    }


def paused(kind):
    return any(
        values.get(kind) is True for values in live_leases('desktop-session-pauses')
    )


def idle_action(op):
    if op not in ('blank', 'allow-lock', 'allow-sleep'):
        raise ValueError('Unknown idle action.')
    if op != 'blank' and paused('locking' if op == 'allow-lock' else 'sleep'):
        return DEFER
    # Only a live Keep awake lease needs the output inventory. Without one, a
    # failed compositor query must not block suspend.
    if not any(live_leases()):
        if op == 'blank':
            backend.command('dispatch', 'hl.dsp.dpms({action="off"})')
        return 0
    displays = backend.snapshot()['displays']
    awake = protected(displays)
    if op != 'blank':
        return DEFER if awake else 0
    for row in displays:
        if row['enabled'] and row['name'] not in awake:
            backend.command(
                'dispatch',
                'hl.dsp.dpms({action="off",monitor='
                + backend.lua_string(row['name'])
                + '})',
            )
    return 0


class Controller:
    def __init__(self):
        self.lease = Lease()
        self.pause_lease = Lease('desktop-session-pauses')
        self.pauses = {}
        self.awake = {}
        self.night_available = False
        self.night_enabled = False
        self.error = ''

    def tick(self):
        self.night_available = bool(
            os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and shutil.which('hyprsunset')
        )
        if self.night_available:
            self.night_enabled = systemctl(
                'show', 'hyprsunset.service', '--property=ActiveState', '--value'
            ) in ('active', 'activating')
        else:
            self.night_enabled = False
        if self.awake:
            rows = backend.snapshot()['displays']
            live = {row['name']: row['identity'] for row in rows if row['enabled']}
            next_awake = {
                name: identity
                for name, identity in self.awake.items()
                if live.get(name) == identity
            }
            if next_awake != self.awake:
                self.lease.publish(next_awake)
                self.awake = next_awake

    def action(self, request):
        op = request.get('op')
        if op != 'status':
            self.error = ''
        if op == 'night':
            enabled = request.get('enabled')
            if type(enabled) is not bool:
                raise ValueError('Invalid night light switch.')
            if not os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') or not shutil.which(
                'hyprsunset'
            ):
                raise RuntimeError('Install hyprsunset to use Night light.')
            systemctl('enable' if enabled else 'disable', '--now', 'hyprsunset.service')
        elif op == 'awake':
            name, identity, enabled = (
                request.get('name'),
                request.get('identity'),
                request.get('enabled'),
            )
            if not isinstance(name, str) or type(enabled) is not bool:
                raise ValueError('Invalid Keep awake switch.')
            rows = backend.snapshot()['displays']
            row = next(
                (
                    row
                    for row in rows
                    if row['name'] == name
                    and row['identity'] == identity
                    and row['enabled']
                ),
                None,
            )
            if row is None:
                raise ValueError(
                    'This display is no longer available. Refresh and try again.'
                )
            values = dict(self.awake)
            if enabled:
                values[name] = identity
                if not row['dpms']:
                    backend.command(
                        'dispatch',
                        'hl.dsp.dpms({action="on",monitor='
                        + backend.lua_string(name)
                        + '})',
                    )
            else:
                values.pop(name, None)
            self.lease.publish(values)
            self.awake = values
        elif op in ('pause-sleep', 'pause-locking'):
            enabled = request.get('enabled')
            if type(enabled) is not bool:
                raise ValueError('Invalid session pause switch.')
            # Publishing a live lease requires a compositor session and never
            # writes preferences. Released locks make crash leftovers inert.
            session_directory('desktop-session-pauses')
            values = dict(self.pauses)
            key = 'sleep' if op == 'pause-sleep' else 'locking'
            if enabled:
                values[key] = True
            else:
                values.pop(key, None)
            self.pause_lease.publish(values)
            self.pauses = values
        elif op != 'status':
            raise ValueError('Unknown display comfort action.')
        self.tick()

    def snapshot(self):
        return dict(
            nightEnabled=self.night_enabled,
            nightAvailable=self.night_available,
            awake=self.awake,
            error=self.error,
            pausesAvailable=bool(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')),
            sleepPaused=bool(self.pauses.get('sleep')),
            lockingPaused=bool(self.pauses.get('locking')),
        )

    def close(self):
        self.lease.close()
        self.pause_lease.close()
        self.pauses = {}
        self.awake = {}


def main():
    """Serve newline-JSON requests; the leases live exactly as long as this process."""
    controller = Controller()

    def emit(reply):
        print(json.dumps(dict(reply=reply, state=controller.snapshot())), flush=True)

    try:
        try:
            controller.tick()
        except Exception as error:
            controller.error = str(error)
        emit(False)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Expected a display comfort request.')
                controller.action(request)
            except Exception as error:
                controller.error = str(error)
            emit(True)
    finally:
        controller.close()


def cli(op):
    try:
        result = idle_action(op)
    except Exception as error:
        print(error, file=sys.stderr)
        return HELPER_ERROR
    if result == DEFER:
        print('defer')
    return result


if __name__ == '__main__':
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1]))
    main()
