#!/usr/bin/env python3
"""Recoverable charge-once actions and bounded performance recordings."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import backend

STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'quickshell/power'


class Session:
    def __init__(self, directory=STATE, controller=None):
        self.directory = directory
        self.path = directory / 'session.json'
        self.controller = controller or backend.Controller()
        self.data = dict(once=None, recording=None)
        migrate = False
        try:
            saved = json.loads(self.path.read_text())
            if isinstance(saved, dict):
                once = saved.get('once')
                if (isinstance(once, dict) and isinstance(once.get('key'), str)
                        and type(once.get('previous')) is int and 0 <= once['previous'] < 100
                        and isinstance(once.get('boot'), str)):
                    self.data['once'] = once
                recording = saved.get('recording')
                if isinstance(recording, dict) and isinstance(recording.get('path'), str) and Path(recording['path']).is_absolute():
                    self.data['recording'] = recording
                migrate = saved != self.data
        except (OSError, ValueError):
            pass
        self.battery = dict(available=False, summary=None, onBattery=None, peripherals=[])
        self.error = ''
        self.dirty = False
        self.child = None
        self.log = None
        self.boot = backend.read(Path('/proc/sys/kernel/random/boot_id'))
        self.record_available = bool(shutil.which('power-study'))
        recording = self.data['recording']
        if recording:
            recording['running'] = False
            self.read_recording()

        if migrate:
            self.save()

    def save(self):
        self.dirty = True
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump(self.data, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        self.dirty = False

    def state(self):
        return dict(self.data, error=self.error,
                    recordAvailable=self.record_available)

    def refresh(self, force=False):
        if force or self.data['once']:
            self.battery = backend.battery_snapshot(self.controller.bus)
            self.reconcile()

    def restore_charge(self):
        once = self.data['once']
        if not once:
            return
        rows, _ = self.controller.hardware()
        row = next((r for r in rows if r['key'] == once['key']), None)
        if not row or row.get('limit') is None:
            raise ValueError('Battery care is unavailable; the previous charge limit is still pending restoration.')
        if row['limit'] == 100:
            self.controller.handle(dict(op='charge-limit', key=row['key'], identity=row['identity'],
                                        previous=100, value=once['previous']))
        # Respect a limit changed outside this utility.
        self.data['once'] = None
        self.save()
        self.error = ''

    def reconcile(self):
        once = self.data['once']
        if once and self.battery['available'] and (self.battery.get('onBattery') is True or once.get('boot') != self.boot):
            self.restore_charge()

    def handle(self, request):
        self.error = ''
        op = request.get('op')
        if op in ('profile', 'charge-limit'):
            self.controller.handle(request)
            if op == 'charge-limit':
                self.data['once'] = None
                self.save()
        elif op == 'charge-once':
            self.refresh(force=True)
            if self.data['once']:
                raise ValueError('A one-time full charge is already active.')
            if self.battery.get('onBattery') is not False or not self.battery.get('summary'):
                raise ValueError('Connect external power before starting a one-time full charge.')
            rows, _ = self.controller.hardware()
            row = next((r for r in rows if r['key'] == request.get('key')), None)
            if not row or row.get('limit') is None or row['limit'] >= 100 or row.get('maximum', 0) < 100:
                raise ValueError('One-time full charging is unavailable.')
            if any(row.get(k) != request.get(k) for k in ('identity', 'limit')):
                raise ValueError('The charge limit changed. Refresh and try again.')
            self.data['once'] = dict(key=row['key'], previous=row['limit'], boot=self.boot)
            self.save()  # Write restoration intent before changing hardware.
            try:
                self.controller.handle(dict(op='charge-limit', key=row['key'], identity=row['identity'], previous=row['limit'], value=100))
            except Exception:
                rows, _ = self.controller.hardware()
                actual = next((r.get('limit') for r in rows if r['key'] == row['key']), None)
                if actual is not None and actual != 100:
                    self.data['once'] = None
                    self.save()
                raise
        elif op == 'restore-charge':
            self.restore_charge()
        elif op == 'record':
            self.record(request)
        elif op == 'stop-recording':
            if self.child and self.child.poll() is None:
                self.child.terminate()
        else:
            raise ValueError('Unknown power utility.')
        self.refresh()

    def record(self, request):
        if self.child or not self.record_available:
            raise ValueError('Performance recording is unavailable or already running.')
        minutes = request.get('minutes', 2)
        if type(minutes) is not int or not 1 <= minutes <= 60:
            raise ValueError('Choose a recording duration from 1 to 60 minutes.')
        path = self.directory / ('recording-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(time.time_ns() % 1000000))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log = (self.directory / 'recording.log').open('w')
        try:
            # Battery-safe default: no GPU sensor reads, no synthetic workload.
            self.child = subprocess.Popen(['power-study', '--duration', str(minutes * 60), '--warmup', '0',
                '--interval', '2', '--output', str(path), 'desktop'], stdout=self.log, stderr=self.log)
        except Exception:
            self.log.close()
            self.log = None
            raise
        self.data['recording'] = dict(running=True, path=str(path), summary=None, error='')
        self.save()

    def read_recording(self):
        row = self.data['recording']
        if not row:
            return
        try:
            summary = json.loads((Path(row['path']) / 'summary.json').read_text())
            if not isinstance(summary, dict):
                raise ValueError('Invalid recording summary')
            row['summary'] = summary
            row['error'] = ''
        except (OSError, ValueError):
            row['summary'] = None
            row['error'] = 'Recording ended without a summary. Open the recording folder for details.'

    def poll_recording(self):
        if not self.child or self.child.poll() is None:
            return False
        code = self.child.returncode
        self.child = None
        self.log.close()
        self.log = None
        self.data['recording']['running'] = False
        self.read_recording()
        if code and not self.data['recording'].get('summary'):
            self.data['recording']['error'] += f' Recorder exit status: {code}.'
        self.save()
        return True

    def close(self):
        if self.child:
            self.child.terminate()
            try:
                self.child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
            self.poll_recording()
        if self.dirty:
            self.save()


def main():
    from gi.repository import Gio, GLib, GLibUnix
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (STATE / 'session.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 1
    session = Session()
    loop = GLib.MainLoop()
    pending = {'refresh': 0, 'recording': 0}

    def emit(reply=False):
        print(json.dumps(dict(state=session.state(), reply=reply), allow_nan=False), flush=True)
        if session.child and not pending['recording']:
            pending['recording'] = GLib.timeout_add_seconds(2, recording)

    def recording():
        try:
            finished = session.poll_recording()
        except Exception as error:
            session.error = str(error)
            finished = True
        if finished:
            pending['recording'] = 0
            emit()
            return False
        return True

    def refresh():
        pending['refresh'] = 0
        try:
            session.refresh()
        except Exception as error:
            session.error = str(error)
        emit()
        return False

    def changed(*_):
        if session.data['once'] and not pending['refresh']:
            pending['refresh'] = GLib.timeout_add(250, refresh)

    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    session.controller.bus.connection = bus
    bus.signal_subscribe(backend.UPOWER, None, None, None, None, Gio.DBusSignalFlags.NONE, changed)
    bus.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged', '/org/freedesktop/DBus',
                         backend.UPOWER, Gio.DBusSignalFlags.NONE, changed)
    bus.signal_subscribe('org.freedesktop.login1', 'org.freedesktop.login1.Manager', 'PrepareForSleep',
                         None, None, Gio.DBusSignalFlags.NONE, changed)

    # Nonblocking stdin prevents a partial JSON line from blocking D-Bus events.
    os.set_blocking(sys.stdin.fileno(), False)
    buffer = bytearray()
    def command(_fd, condition):
        if condition & GLib.IOCondition.IN:
            chunk = os.read(sys.stdin.fileno(), 65536)
            if not chunk:
                loop.quit()
                return False
            buffer.extend(chunk)
            while b'\n' in buffer:
                line, _, tail = buffer.partition(b'\n')
                buffer[:] = tail
                try:
                    session.handle(json.loads(line))
                except Exception as error:
                    session.error = str(error)
                    # A failed readback may still have applied a change. Reconcile
                    # fresh daemon state before publishing utility status.
                    try:
                        session.refresh()
                    except Exception:
                        pass
                emit(reply=True)
        if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
            loop.quit()
            return False
        return True
    GLib.io_add_watch(sys.stdin.fileno(), GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR, command)
    def stop(*_):
        loop.quit()
        return False
    for signum in (signal.SIGTERM, signal.SIGINT):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signum, stop)
    try:
        refresh()
        loop.run()
    finally:
        session.close()
    return 0


def supervise():
    """QProcess kills its direct child on destruction, bypassing Python cleanup.

    Keep that child an idle supervisor. Its session child gets stdin EOF from
    Quickshell and can stop its recorder independently of QProcess teardown.
    No polling or pipe forwarding is needed; both inherit the original pipes.
    """
    pid = os.fork()
    if not pid:
        os.setsid()
        return main()

    def forward(signum, _frame):
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, forward)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == '__main__':
    raise SystemExit(supervise() if sys.argv[1:] == ['--supervise'] else main())
