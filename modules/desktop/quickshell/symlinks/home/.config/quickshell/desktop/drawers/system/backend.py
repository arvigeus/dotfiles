"""Read-only system overview and explicit interactive terminal actions."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import shlex
import subprocess


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=3,
                                env=dict(os.environ, LC_ALL='C', SYSTEMD_COLORS='0'))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'{argv[0]} is unavailable or timed out.') from error
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:300] or f'{argv[0]} failed.')
    return result.stdout.strip()


def updater():
    if shutil.which('system-update'):
        return ['system-update']
    return ['topgrade'] if shutil.which('topgrade') else []


def boot_times(text):
    first = text.splitlines()[0] if text else ''
    phases = [dict(label=label.capitalize(), duration=duration.strip())
              for duration, label in re.findall(
                  r'([^+]+?)\s+\((firmware|loader|kernel|initrd|userspace)\)',
                  first.removeprefix('Startup finished in '))]
    total = first.rsplit(' = ', 1)[1].rstrip(' .') if ' = ' in first else ''
    return dict(phases=phases, total=total, summary=text)


def slow_units(text):
    rows = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(.+?)\s+(\S+)\s*', line)
        if match:
            rows.append(dict(duration=match[1], unit=match[2]))
    return rows[:5]


def snapshot(section='info'):
    errors = {}

    def read(key, argv, json_output=False):
        try:
            value = command(argv)
            return json.loads(value) if json_output else value
        except (RuntimeError, ValueError) as error:
            errors[key] = str(error)
            return [] if json_output else ''

    state = dict(errors=errors, terminalAvailable=bool(shutil.which('xdg-terminal-exec')))
    if section == 'info':
        state.update(system_info())
    elif section == 'boot':
        state.update(boot=boot_times(read('boot', ['systemd-analyze', 'time'])),
                     slow=slow_units(read('slow', ['systemd-analyze', 'blame', '--no-pager'])))
    elif section == 'services':
        scopes = []
        timers = []
        for scope in ('system', 'user'):
            prefix = ['systemctl'] + (['--user'] if scope == 'user' else [])
            failed = read(scope, prefix + ['list-units', '--failed', '--all', '--output=json', '--no-pager'], True)
            scopes.append(dict(scope=scope, failed=[dict(unit=row['unit'], description=row.get('description', ''))
                                                    for row in failed if isinstance(row, dict) and row.get('unit')]))
            rows = read(scope + 'Timers', prefix + ['list-timers', '--all', '--output=json', '--no-pager'], True)
            for row in rows:
                if not isinstance(row, dict):
                    continue
                next_time = row.get('next')
                if isinstance(next_time, (int, float)) and 0 < next_time < 2**63:
                    timers.append(dict(unit=row.get('unit', ''), scope=scope, next=next_time / 1000))
        timers.sort(key=lambda row: row['next'])
        state.update(scopes=scopes, timers=timers[:5])
    else:
        raise ValueError('Unsupported system information section.')
    return state


def system_info():
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    try:
        uptime = float(Path('/proc/uptime').read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime = None
    # After a kernel upgrade, the running kernel's modules directory is gone.
    modules = Path('/usr/lib/modules')
    kernel_changed = modules.is_dir() and not (modules / platform.release()).is_dir()
    return dict(os=release.get('PRETTY_NAME', platform.system()), kernel=platform.release(),
                uptime=uptime, kernelChanged=kernel_changed)


def action_command(action, scope='system', unit=''):
    if action == 'update':
        argv = updater()
        if not argv:
            raise ValueError('Topgrade is required for system updates.')
        return argv
    if action != 'logs' or scope not in ('system', 'user'):
        raise ValueError('Unsupported action or scope.')
    if unit and (unit.startswith('-') or not re.fullmatch(r'[A-Za-z0-9:_.@\\-]+', unit)):
        raise ValueError('Invalid unit name.')
    return ['journalctl'] + (['--user'] if scope == 'user' else []) + ['-b', '-n', '200'] + (['--unit=' + unit] if unit else ['-p', 'warning'])


def maintenance_available():
    return dict(signing=bool(shutil.which('sudo') and shutil.which('pacman-key')
                             and any(Path('/usr/share/pacman/keyrings').glob('*.gpg'))),
                health=bool(shutil.which('pacman')))


def run_terminal(argv, **kwargs):
    print('\nRunning: ' + shlex.join(argv), flush=True)
    return subprocess.run(argv, check=False, env=dict(os.environ, LC_ALL='C'), **kwargs)


def repair_signing():
    if not maintenance_available()['signing']:
        raise ValueError('Signing repair requires sudo, pacman-key and installed signing keyrings.')
    print('Reloading installed signing keyrings and rebuilding trust.\n'
          'Custom keys and local signatures are kept.\n'
          'Use Update system afterwards to install newer keyring package versions.', flush=True)
    for operation in ('--init', '--populate', '--updatedb'):
        result = run_terminal(['sudo', '--', 'pacman-key', operation])
        if result.returncode:
            return result.returncode
    return 0


def check_package_health(offer_repair=True):
    if not maintenance_available()['health']:
        raise ValueError('Package health checks require pacman.')
    print('Checking the package database and missing package files.\n'
          'These checks do not change packages or verify file contents.', flush=True)
    database = run_terminal(['pacman', '-Dk'])
    files = run_terminal(['pacman', '-Qkq'], capture_output=True, text=True)
    print(files.stdout, end='', flush=True)
    print(files.stderr, end='', flush=True)
    status = int(bool(database.returncode or files.returncode))
    if not status:
        print('\nNo database inconsistencies or missing package files found.', flush=True)
        return 0
    print('\nChecks reported problems; review the output above.', flush=True)
    # Quiet check output is one package/path pair per missing file. Only offer
    # packages still present in enabled repositories; foreign packages need their
    # original source. Never turn arbitrary diagnostic text into install targets.
    missing = sorted({parts[0] for line in files.stdout.splitlines()
                      if len(parts := line.split(maxsplit=1)) == 2 and parts[1].startswith('/')
                      and re.fullmatch(r'[A-Za-z0-9@._+][A-Za-z0-9@._+\-]*', parts[0])})
    if not missing or not offer_repair:
        return status
    try:
        native = set(command(['pacman', '-Qnq']).splitlines())
    except RuntimeError as error:
        print(f'Cannot determine repository packages: {error}', flush=True)
        return status
    targets = [name for name in missing if name in native]
    foreign = [name for name in missing if name not in native]
    if foreign:
        print('Packages requiring repair from their original source: ' + ', '.join(foreign), flush=True)
    if not targets or not shutil.which('sudo'):
        return status
    print('\nRepository packages with missing files: ' + ', '.join(targets), flush=True)
    answer = input('Reinstall these packages and run a full system update? [y/N] ')
    if answer.strip().lower() not in ('y', 'yes'):
        return status
    result = run_terminal(['sudo', '--', 'pacman', '-Syu', '--', *targets])
    if result.returncode:
        return result.returncode
    print('\nChecking again after reinstalling…', flush=True)
    return check_package_health(offer_repair=False)


def run_action(action, scope='system', unit=''):
    if action == 'repair-signing':
        return repair_signing()
    if action == 'check-packages':
        return check_package_health()
    return run_terminal(action_command(action, scope, unit)).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=('update', 'logs', 'repair-signing', 'check-packages'))
    parser.add_argument('--section', choices=('info', 'boot', 'services'), default='info')
    parser.add_argument('--scope', choices=('system', 'user'), default='system')
    parser.add_argument('--unit', default='')
    args = parser.parse_args()
    if not args.action:
        print(json.dumps(snapshot(args.section)))
        return
    try:
        status = run_action(args.action, args.scope, args.unit)
        print(f'\nFinished (exit {status}).', flush=True)
    except (OSError, ValueError, EOFError) as error:
        print(str(error), flush=True)
        status = 1
    except KeyboardInterrupt:
        print('\nInterrupted.', flush=True)
        status = 130
    try:
        input('\nPress Enter to close…')
    except (EOFError, KeyboardInterrupt):
        pass
    return status


if __name__ == '__main__':
    raise SystemExit(main())
