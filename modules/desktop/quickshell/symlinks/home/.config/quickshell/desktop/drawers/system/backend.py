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

PACKAGE = re.compile(r'[A-Za-z0-9@._+][A-Za-z0-9@._+\-]*')


def command(argv):
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=3,
            env=dict(os.environ, LC_ALL='C', SYSTEMD_COLORS='0'),
        )
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
    phases = [
        dict(label=label.capitalize(), duration=duration.strip())
        for duration, label in re.findall(
            r'([^+]+?)\s+\((firmware|loader|kernel|initrd|userspace)\)',
            first.removeprefix('Startup finished in '),
        )
    ]
    total = first.rsplit(' = ', 1)[1].rstrip(' .') if ' = ' in first else ''
    return dict(phases=phases, total=total)


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

    state = dict(
        errors=errors, terminalAvailable=bool(shutil.which('xdg-terminal-exec'))
    )
    if section == 'info':
        state.update(system_info())
    elif section == 'boot':
        state.update(
            boot=boot_times(read('boot', ['systemd-analyze', 'time'])),
            slow=slow_units(read('slow', ['systemd-analyze', 'blame', '--no-pager'])),
        )
    elif section == 'services':
        scopes = []
        timers = []
        for scope in ('system', 'user'):
            prefix = ['systemctl'] + (['--user'] if scope == 'user' else [])
            failed = read(
                scope,
                prefix
                + ['list-units', '--failed', '--all', '--output=json', '--no-pager'],
                True,
            )
            scopes.append(
                dict(
                    scope=scope,
                    failed=[
                        dict(unit=row['unit'], description=row.get('description', ''))
                        for row in failed
                        if isinstance(row, dict) and row.get('unit')
                    ],
                )
            )
            rows = read(
                scope + 'Timers',
                prefix + ['list-timers', '--all', '--output=json', '--no-pager'],
                True,
            )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                next_time = row.get('next')
                if isinstance(next_time, (int, float)) and 0 < next_time < 2**63:
                    timers.append(
                        dict(
                            unit=row.get('unit', ''), scope=scope, next=next_time / 1000
                        )
                    )
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
    return dict(
        os=release.get('PRETTY_NAME', platform.system()),
        kernel=platform.release(),
        uptime=uptime,
        kernelChanged=kernel_changed,
    )


def action_command(action, scope='system', unit=''):
    if action == 'update':
        argv = updater()
        if not argv:
            raise ValueError('Topgrade is required for system updates.')
        return argv
    if action != 'logs' or scope not in ('system', 'user'):
        raise ValueError('Unsupported action or scope.')
    if unit and (
        unit.startswith('-') or not re.fullmatch(r'[A-Za-z0-9:_.@\\-]+', unit)
    ):
        raise ValueError('Invalid unit name.')
    return (
        ['journalctl']
        + (['--user'] if scope == 'user' else [])
        + ['-b', '-n', '200']
        + (['--unit=' + unit] if unit else ['-p', 'warning'])
    )


def maintenance_available():
    return dict(
        signing=bool(
            shutil.which('sudo')
            and shutil.which('pacman-key')
            and any(Path('/usr/share/pacman/keyrings').glob('*.gpg'))
        ),
        health=bool(shutil.which('pacman')),
    )


def run_terminal(argv, **kwargs):
    # Interactive output keeps the user's locale: under LC_ALL=C the journal
    # pager shows non-ASCII text as byte escapes.
    print('\nRunning: ' + shlex.join(argv), flush=True)
    return subprocess.run(argv, check=False, **kwargs)


def confirm(question):
    try:
        answer = input(question + ' [y/N] ')
    except EOFError:
        return False
    return answer.strip().lower() in ('y', 'yes')


def missing_files(output, privileged=False):
    """Split quiet `pacman -Qk` output into missing and unreadable files.

    Pacman lists every path it cannot lstat. A regular user cannot look into
    root-only directories such as /boot, so those files are unverified rather
    than missing; root can, so a privileged check lists only missing files.
    Lines that are not a package/path pair are returned as-is.
    """
    missing, unreadable, other = [], [], []
    for line in output.splitlines():
        package, _, path = line.partition(' ')
        if not PACKAGE.fullmatch(package) or not path.startswith('/'):
            other.append(line)
            continue
        if privileged:
            missing.append((package, path))
            continue
        try:
            os.lstat(path)
        except PermissionError:
            unreadable.append((package, path))
        except OSError:
            missing.append((package, path))
    return missing, unreadable, other


def repair_signing():
    if not maintenance_available()['signing']:
        raise ValueError(
            'Signing repair requires sudo, pacman-key and installed signing keyrings.'
        )
    print(
        'Reloading installed signing keyrings and rebuilding trust.\n'
        'Custom keys and local signatures are kept.\n'
        'Use Update system afterwards to install newer keyring package versions.',
        flush=True,
    )
    if not confirm('\nRun pacman-key as root now?'):
        print('Nothing changed.', flush=True)
        return 0
    for operation in ('--init', '--populate', '--updatedb'):
        result = run_terminal(['sudo', '--', 'pacman-key', operation])
        if result.returncode:
            return result.returncode
    return 0


def check_package_health(offer_repair=True, as_root=None):
    if not maintenance_available()['health']:
        raise ValueError('Package health checks require pacman.')
    print(
        'Checking the package database and missing package files.\n'
        'These checks do not change packages or verify file contents.',
        flush=True,
    )
    database = run_terminal(['pacman', '-Dk'])
    # Quiet output is one untranslated package/path line per file pacman could
    # not lstat; other diagnostics go to stderr.
    files = run_terminal(['pacman', '-Qkq'], capture_output=True, text=True)
    absent, unreadable, other = missing_files(files.stdout)
    errors = files.stderr
    # Unreadable files alone make pacman fail, but are not evidence of damage.
    failed = files.returncode and (absent or other or errors.strip() or not unreadable)
    if unreadable:
        print('\nNot checked without root access (directory not readable):')
        for package, path in unreadable:
            print(f'  {package} {path}')
        unchecked = sorted({package for package, _ in unreadable})
        if as_root is None:
            as_root = bool(shutil.which('sudo')) and confirm(
                'Check these packages as root? This only reads files.'
            )
        if as_root:
            root = run_terminal(
                ['sudo', '--', 'pacman', '-Qkq', '--', *unchecked],
                capture_output=True,
                text=True,
            )
            found, _, extra = missing_files(root.stdout, privileged=True)
            absent += found
            other += extra
            errors += root.stderr
            failed = failed or root.returncode
        else:
            print(
                'Check them with: ' + shlex.join(['sudo', 'pacman', '-Qk', *unchecked])
            )
    for line in other:
        print(line)
    if absent:
        print('Missing package files:')
        for package, path in absent:
            print(f'  {package} {path}')
    print(errors, end='')
    status = int(bool(database.returncode or failed))
    if not status:
        print(
            '\nNo database inconsistencies or missing package files found.', flush=True
        )
        return 0
    print('\nChecks reported problems; review the output above.', flush=True)
    # Only offer packages still present in enabled repositories; foreign packages
    # need their original source. Never turn diagnostic text into install targets.
    missing = sorted({package for package, _ in absent})
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
        print(
            'Packages requiring repair from their original source: '
            + ', '.join(foreign),
            flush=True,
        )
    if not targets or not shutil.which('sudo'):
        return status
    print('\nRepository packages with missing files: ' + ', '.join(targets), flush=True)
    if not confirm('Reinstall these packages and run a full system update?'):
        return status
    result = run_terminal(['sudo', '--', 'pacman', '-Syu', '--', *targets])
    if result.returncode:
        return result.returncode
    print('\nChecking again after reinstalling…', flush=True)
    return check_package_health(offer_repair=False, as_root=as_root)


def run_action(action, scope='system', unit=''):
    if action == 'repair-signing':
        return repair_signing()
    if action == 'check-packages':
        return check_package_health()
    return run_terminal(action_command(action, scope, unit)).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--action', choices=('update', 'logs', 'repair-signing', 'check-packages')
    )
    parser.add_argument(
        '--section', choices=('info', 'boot', 'services'), default='info'
    )
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
