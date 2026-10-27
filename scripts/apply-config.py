#!/usr/bin/env python3
"""Reconcile the selected configuration without installation-only operations."""

import argparse
from contextlib import redirect_stdout
import fcntl
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

from reconcile import Files, State, publish_tree, tree_entries
from reconcile_packages import Inventory, review_removals

RUNTIME_CONFIG = Path('/run/system-configuration.json')
STATE_ROOT = Path('/var/lib/dotfiles')
APPLY_LOCK = Path('/run/lock/dotfiles-apply.lock')


def run(*args):
    subprocess.run(args, check=True)


def acquire_lock(path):
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
    )
    stream = os.fdopen(descriptor, 'a')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        raise ValueError('Another apply is already running') from None
    return stream


class LiveInstaller:
    """Collect native packages, services, commands and files in a staging root."""

    def __init__(self, config, target=Path('/')):
        self.target = target
        self.kernels = config.kernels
        self.packages = list(config.packages) + config.kernels + config.firmware_optdeps
        self.services = []
        self.disabled_services = []
        self.commands = []
        self.pacman = SimpleNamespace(strap=self.add_additional_packages)

    def add_additional_packages(self, packages):
        self.packages.extend([packages] if isinstance(packages, str) else packages)

    def enable_service(self, services):
        self.services.extend([services] if isinstance(services, str) else services)

    def disable_service(self, services):
        self.disabled_services.extend(
            [services] if isinstance(services, str) else services
        )

    def arch_chroot(self, command, run_as=None, peek_output=False):
        self.commands.append((command, run_as))

    def configure_nic(self, nic):
        path = self.target / f'etc/systemd/network/10-{nic.iface}.network'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(nic.as_systemd_config()))

    def systemd_resolved_stub_mode(self):
        path = self.target / 'etc/resolv.conf'
        path.unlink(missing_ok=True)
        path.symlink_to('/run/systemd/resolve/stub-resolv.conf')


def native_config(raw):
    from archinstall.lib.args import ArchConfig, Arguments

    ignored = {
        'disk_config',
        'bootloader_config',
        'auth_config',
        'custom_commands',
        'extra',
    }
    return ArchConfig.from_config(
        {key: value for key, value in raw.items() if key not in ignored},
        Arguments(silent=True, offline=True, no_pkg_lookups=True),
    )


def native_plan(config, target):
    from archinstall.lib.applications.application_handler import ApplicationHandler
    from archinstall.lib.installer import Installer
    from archinstall.lib.models.network import NicType
    from archinstall.lib.network.network_handler import install_network_config
    from archinstall.lib.profile.profiles_handler import profile_handler

    installation = LiveInstaller(config, target)
    (target / 'etc/systemd').mkdir(parents=True, exist_ok=True)
    # The native UFW handler edits its package default before installation.
    if (
        config.app_config
        and config.app_config.firewall_config
        and config.app_config.firewall_config.firewall.value == 'ufw'
    ):
        seed = Path('/etc/ufw/ufw.conf')
        (target / 'etc/ufw').mkdir()
        (target / 'etc/ufw/ufw.conf').write_text(
            seed.read_text() if seed.exists() else 'ENABLED=no\n'
        )
    if config.network_config and config.network_config.type != NicType.ISO:
        install_network_config(
            config.network_config, installation, config.profile_config
        )
    if config.app_config:
        ApplicationHandler().install_applications(installation, config.app_config)
    if config.profile_config:
        profile_handler.install_profile_config(installation, config.profile_config)
    if config.locale_config:
        Installer.set_vconsole(installation, config.locale_config)
    if config.swap and config.swap.enabled:
        Installer.setup_swap(installation, algo=config.swap.algorithm)
    if config.hostname:
        Installer.set_hostname(installation, config.hostname)
    if config.timezone:
        zone = Path('/usr/share/zoneinfo') / config.timezone
        if not zone.is_file() or not zone.resolve().is_relative_to(
            '/usr/share/zoneinfo'
        ):
            raise ValueError(f'Invalid timezone: {config.timezone}')
        (target / 'etc/localtime').symlink_to(zone)
    installation.enable_service(config.services)
    if config.ntp:
        installation.enable_service('systemd-timesyncd.service')
    installation.packages = list(dict.fromkeys(installation.packages))
    return installation


class DeclaredMirrors:
    def __init__(self, regions):
        self.regions = {region.name: region.urls for region in regions}

    def get_status_by_region(self, region, speed_sort=False):
        return [SimpleNamespace(server_url=url) for url in self.regions[region]]


def repositories(config, extra, state):
    """Merge managed settings into pacman.conf, preserving other configuration."""
    from archinstall.lib.pacman.config import PacmanConfig
    from repository_policy import configure_signature_policy

    text = Path('/etc/pacman.conf').read_text()
    mirrors = config.mirror_config
    names = []
    if mirrors:
        configure_signature_policy(mirrors, extra)
        enabled = {
            name
            for repo in mirrors.optional_repositories
            for name in (
                ['core-testing', 'extra-testing', 'multilib-testing']
                if repo.value == 'testing'
                else [repo.value]
            )
        }
        for name in enabled:
            text = re.sub(
                rf'^#\s*(\[{re.escape(name)}\]\n)#\s*(Include[^\n]*)',
                r'\1\2',
                text,
                flags=re.M,
            )
        names = [repo.name for repo in mirrors.custom_repositories]
    for name in set(names) | set(state.data.get('repositories', [])):
        text = re.sub(
            rf'^\[{re.escape(name)}\]\n.*?(?=^\[|\Z)', '', text, flags=re.M | re.S
        )
    if mirrors and names:
        text = text.rstrip() + '\n\n' + mirrors.repositories_config().rstrip() + '\n'
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        path = stage / 'etc/pacman.conf'
        path.parent.mkdir()
        path.write_text(text)
        if config.pacman_config:
            PacmanConfig(stage).configure(config.pacman_config)
        entries = [(path, Path('/etc/pacman.conf'), 0, 0)]
        if mirrors:
            regions = mirrors.regions_config(
                DeclaredMirrors(mirrors.mirror_regions), speed_sort=False
            )
            servers = mirrors.custom_servers_config()
            if regions or servers:
                mirrorlist = stage / 'mirrorlist'
                mirrorlist.write_text(
                    '\n'.join(part for part in (servers, regions) if part)
                )
                entries.append((mirrorlist, Path('/etc/pacman.d/mirrorlist'), 0, 0))
        # Reflector owns a dynamic mirrorlist when fixed regions/servers are absent.
        tracked = state.data['files'].setdefault('pacman', {})
        if len(entries) == 1:
            tracked.pop('/etc/pacman.d/mirrorlist', None)
        Files(state, force=True).sync('pacman', entries)
    state.data['repositories'] = names
    state.save()


def services(installation, extra, state):
    run('systemctl', 'daemon-reload')
    wanted = set(installation.services)
    disabled = set(installation.disabled_services) | set(
        extra.get('disabled_services', [])
    )
    if wanted & disabled:
        raise ValueError(f'Services both enabled and disabled: {wanted & disabled}')
    old = set(state.data.get('services', []))
    for name in sorted((old - wanted) | disabled):
        run('systemctl', 'disable', name)
        old.discard(name)
        state.data['services'] = sorted(old)
        state.save()
    if wanted:
        run('systemctl', 'enable', *sorted(wanted))
    state.data['services'] = sorted(wanted)
    state.save()
    if wanted:
        # No restarts or stops: changed settings and disabled units settle on reboot.
        run('systemctl', 'start', *sorted(wanted))


def preflight(raw, repo):
    import runpy

    # Reuse the generator's asset checks without generating or selecting modules.
    runpy.run_path(str(repo / 'generate-config.py'))['validate_assets'](raw['extra'])
    for key in (
        'aur_packages',
        'cargo_packages',
        'user_services',
        'masked_user_services',
        'disabled_services',
    ):
        values = raw['extra'].get(key, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str)
            and value
            and not value.startswith('-')
            and not any(c.isspace() for c in value)
            for value in values
        ):
            raise ValueError(f'extra.{key} must be a list of names')
    if set(raw['extra'].get('user_services', [])) & set(
        raw['extra'].get('masked_user_services', [])
    ):
        raise ValueError('A user service cannot be both enabled and masked')
    for entry in raw['extra']['files']:
        if not isinstance(entry.get('mode'), str) or not re.fullmatch(
            r'[0-7]{3,4}', entry['mode']
        ):
            raise ValueError(f'Invalid asset mode: {entry}')
    for kind in ('checks', 'pre', 'scripts'):
        for name in raw['extra'][kind]:
            path = repo / name
            if not path.is_file() or not path.resolve().is_relative_to(repo):
                raise ValueError(f'Missing or external hook: {name}')
            subprocess.run(['bash', '-n', str(path)], check=True)


def show_plan(raw, repo, installation, state, uid, gid, home):
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        'reconcile_files_cli', repo / 'scripts/reconcile-files.py'
    )
    assets = module_from_spec(spec)
    spec.loader.exec_module(assets)
    missing, candidates = Inventory().status(
        installation.packages, raw['extra'].get('aur_packages', [])
    )
    print('Missing packages:', ', '.join(missing) or 'none')
    print('Package removal review (never automatic):')
    for package in candidates:
        print(f'  {package.name}: {package.desc}')
    with tempfile.TemporaryDirectory() as directory:
        Files(state).sync('assets', assets.system_assets(raw, repo, Path(directory)))
    Files(state).sync('native', tree_entries(installation.target, Path('/'), 0, 0))
    with tempfile.TemporaryDirectory() as directory:
        entries = []
        for kind in ('files', 'symlinks'):
            for entry in raw['extra'][kind]:
                if not entry['target'].startswith('home/'):
                    continue
                source = repo / entry['source']
                prepared = Path(directory) / str(len(entries))
                if kind == 'symlinks':
                    prepared.symlink_to(source)
                else:
                    shutil.copy2(source, prepared)
                    prepared.chmod(int(entry['mode'], 8))
                entries.append((prepared, home / entry['target'][5:], uid, gid))
        from reconcile import check_parents, fingerprint

        for source, target, _, _ in entries:
            check_parents(target)
            if fingerprint(source) != fingerprint(target):
                print(
                    f'Home asset draft differs: {target} (final output compared after hooks)'
                )
    print('Enabled system services:', ', '.join(sorted(set(installation.services))))
    print(
        'Enabled user services:',
        ', '.join(raw['extra'].get('user_services', [])) or 'none',
    )
    print('Hooks to run (not executed by dry-run):')
    for kind in ('checks', 'pre', 'scripts'):
        for name in raw['extra'][kind]:
            print('  ' + name)
    print(
        'Skipped: disks, formatting, encryption setup, bootloader installation, users/passwords, snapshot initialization.'
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Inspect packages/files/services without executing hooks or transactions',
    )
    parser.add_argument(
        '--no-package-review',
        action='store_true',
        help='Install desired packages without reviewing removals',
    )
    args = parser.parse_args()
    lock = None
    if not args.dry_run:
        if os.geteuid() != 0 or not os.environ.get('SUDO_USER'):
            parser.error('Run through ./apply.sh as a regular user')
        lock = acquire_lock(APPLY_LOCK)
    repo = args.config.resolve().parent
    raw_bytes = args.config.read_bytes()
    raw = json.loads(raw_bytes)
    preflight(raw, repo)
    config = native_config(raw)
    account = pwd.getpwnam(
        os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name
    )
    state_dir = STATE_ROOT / str(account.pw_uid)
    state = State(state_dir, dry_run=args.dry_run)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        with redirect_stdout(io.StringIO()):
            installation = native_plan(config, temporary / 'native')
        if set(installation.services) & (
            set(installation.disabled_services)
            | set(raw['extra'].get('disabled_services', []))
        ):
            raise ValueError('A system service cannot be both enabled and disabled')
        if args.dry_run:
            show_plan(
                raw,
                repo,
                installation,
                state,
                account.pw_uid,
                account.pw_gid,
                Path(account.pw_dir),
            )
            return
        if os.geteuid() != 0 or account.pw_uid == 0:
            parser.error('Run through ./apply.sh as a regular user')
        with lock:
            snapshot = temporary / 'configuration.json'
            snapshot.write_bytes(raw_bytes)
            environment = dict(
                os.environ,
                CONFIG_MODE='live',
                DOTFILES_CONFIG=str(snapshot),
                DOTFILES_STATE_DIR=str(state_dir),
            )
            configure = ['bash', str(repo / 'scripts/configure.sh')]
            subprocess.run(
                [*configure, '--check'], env=environment, check=True, cwd=repo
            )
            link = RUNTIME_CONFIG
            link.unlink(missing_ok=True)
            link.symlink_to(snapshot)
            try:
                subprocess.run(
                    [*configure, '--pre'], env=environment, check=True, cwd=repo
                )
                repositories(config, raw['extra'], state)
                run('pacman', '-Syu', '--needed', '--', *installation.packages)
                if not publish_tree(
                    installation.target, Path('/'), 0, 0, state, 'native'
                ):
                    parser.exit(
                        2,
                        'Native configuration conflicts remain; rerun apply after resolving them.\n',
                    )
                for command, user in installation.commands:
                    argv = ['bash', '-Eeuo', 'pipefail', '-c', command]
                    run(*(['runuser', '-u', user, '--', *argv] if user else argv))
                for command in raw.get('custom_commands', []):
                    subprocess.run(
                        ['bash', '-Eeuo', 'pipefail', '-c', command],
                        env=environment,
                        check=True,
                        cwd=repo,
                    )
                # Configure publishes file state in subprocesses; reload before
                # recording service ownership so their checkpoints are retained.
                state = State(state_dir)
                services(installation, raw['extra'], state)
                if not args.no_package_review:
                    review_removals(
                        installation.packages, raw['extra'].get('aur_packages', [])
                    )
            finally:
                link.unlink(missing_ok=True)
                link.symlink_to(args.config.resolve())
    print('Apply complete. Reboot to activate session and boot changes.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(
            'Apply interrupted; completed file changes are recorded and can be reconciled on the next run.'
        ) from None
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
