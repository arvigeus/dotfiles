"""On-demand session controls; systemd owns scheduled shutdowns."""
import json
import shutil
import subprocess
import sys


DELAYS = (15, 30, 60, 90, 120, 180, 240, 300)


def run(argv, *, check=True):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if check and result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip() or 'Session command failed.')
    return result


def can(method):
    try:
        result = run(['busctl', '--system', 'call', 'org.freedesktop.login1',
                      '/org/freedesktop/login1', 'org.freedesktop.login1.Manager', method])
        return result.stdout.strip() in ('s "yes"', 's "challenge"')
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def session_status():
    if not shutil.which('session-mode'):
        return {}
    try:
        return json.loads(run(['session-mode', 'status']).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def snapshot():
    scheduled = run(['systemctl', 'poweroff', '--when=show'], check=False)
    message = (scheduled.stdout or scheduled.stderr).strip()
    session = session_status()
    return dict(capabilities=dict(gaming=bool(session.get('gaming')), reload=bool(session.get('available')), suspend=can('CanSuspend'),
                                  reboot=can('CanReboot'), poweroff=can('CanPowerOff')),
                scheduledShutdown=message if scheduled.returncode == 0 and 'No scheduled shutdown' not in message else '')


def handle(request):
    action = request.get('action', 'status')
    if action == 'status':
        return snapshot()
    if action in ('gaming', 'reload'):
        argv = ['session-mode', 'gaming' if action == 'gaming' else 'desktop']
    elif action in ('suspend', 'reboot', 'poweroff'):
        argv = ['systemctl', action]
    elif action == 'schedule-poweroff':
        minutes = request.get('minutes')
        if type(minutes) is not int or minutes not in DELAYS:
            raise ValueError('Unsupported shutdown delay.')
        argv = ['systemctl', 'poweroff', f'--when=+{minutes}min']
    elif action == 'cancel-poweroff':
        argv = ['systemctl', 'poweroff', '--when=cancel']
    else:
        raise ValueError('Unknown session action.')
    run(argv)
    return snapshot()


if __name__ == '__main__':
    try:
        print(json.dumps(dict(ok=True, data=handle(json.loads(sys.argv[1])))))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as error:
        print(json.dumps(dict(ok=False, error=str(error))))
