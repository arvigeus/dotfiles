#!/usr/bin/env python3
"""Apply native archinstall settings without installation-only disk operations."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace


def run(*args):
    subprocess.run(args, check=True)


class LiveInstaller:
    """Small live-system adapter for archinstall's application/profile handlers."""
    def __init__(self, config, target=Path('/')):
        self.target = target
        self.kernels = config.kernels
        self.packages = list(config.packages) + config.kernels + config.firmware_optdeps
        self.services = []
        self.disabled_services = []
        self.pacman = SimpleNamespace(strap=self.add_additional_packages)

    def add_additional_packages(self, packages):
        self.packages.extend([packages] if isinstance(packages, str) else packages)

    def enable_service(self, services):
        self.services.extend([services] if isinstance(services, str) else services)

    def disable_service(self, services):
        self.disabled_services.extend([services] if isinstance(services, str) else services)

    def arch_chroot(self, command, run_as=None, peek_output=False):
        args = ['bash', '-c', command]
        if run_as:
            args = ['runuser', '-u', run_as, '--', *args]
        run(*args)

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
    # These fields belong to installation, and must not probe disks or touch users.
    ignored = {'disk_config', 'bootloader_config', 'auth_config', 'custom_commands', 'extra'}
    return ArchConfig.from_config(
        {key: value for key, value in raw.items() if key not in ignored},
        Arguments(silent=True, offline=True, no_pkg_lookups=True),
    )


class DeclaredMirrors:
    def __init__(self, regions):
        self.regions = {region.name: region.urls for region in regions}

    def get_status_by_region(self, region, speed_sort=False):
        return [SimpleNamespace(server_url=url) for url in self.regions[region]]


def apply_native(config, extra=None):
    from archinstall.lib.applications.application_handler import ApplicationHandler
    from archinstall.lib.installer import Installer
    from archinstall.lib.models.network import NicType
    from archinstall.lib.network.network_handler import install_network_config
    from archinstall.lib.pacman.config import PacmanConfig
    from archinstall.lib.profile.profiles_handler import profile_handler

    installation = LiveInstaller(config)
    pacman_config = PacmanConfig(installation.target)
    if config.mirror_config:
        from repository_policy import configure_signature_policy
        configure_signature_policy(config.mirror_config, extra or {})
        pacman_config.enable(config.mirror_config.optional_repositories)
        pacman_config.apply()
        # Update declared repository sections instead of appending on each apply.
        path = Path('/etc/pacman.conf')
        for repo in config.mirror_config.custom_repositories:
            import re
            text = path.read_text()
            block = config.mirror_config.repositories_config()
            # Each declared repository is emitted by archinstall's serializer.
            match = re.search(rf'^\[{re.escape(repo.name)}\]\n.*?(?=^\[|\Z)', block, re.M | re.S)
            if match:
                text = re.sub(rf'^\[{re.escape(repo.name)}\]\n.*?(?=^\[|\Z)', '', text, flags=re.M | re.S)
                path.write_text(text.rstrip() + '\n\n' + match[0].rstrip() + '\n')
        regions = config.mirror_config.regions_config(DeclaredMirrors(config.mirror_config.mirror_regions), speed_sort=False)
        servers = config.mirror_config.custom_servers_config()
        if regions or servers:
            Path('/etc/pacman.d/mirrorlist').write_text('\n'.join(part for part in (servers, regions) if part))
    pacman_config.configure(config.pacman_config)
    if config.network_config and config.network_config.type != NicType.ISO:
        install_network_config(config.network_config, installation, config.profile_config)
    # The native UFW handler edits its packaged config immediately. The live
    # adapter queues packages, so install UFW first on systems without it.
    if config.app_config and config.app_config.firewall_config:
        from archinstall.applications.firewall import FirewallApp
        from archinstall.lib.models.application import Firewall
        if (config.app_config.firewall_config.firewall == Firewall.UFW
                and not (installation.target / 'etc/ufw/ufw.conf').exists()):
            run('pacman', '-Syu', '--needed', '--', *FirewallApp().ufw_packages)
    if config.app_config:
        ApplicationHandler().install_applications(installation, config.app_config)
    if config.profile_config:
        profile_handler.install_profile_config(installation, config.profile_config)
    if config.locale_config:
        Installer.set_vconsole(installation, config.locale_config)
    if config.swap and config.swap.enabled:
        Installer.setup_swap(installation, algo=config.swap.algorithm)
    packages = list(dict.fromkeys(installation.packages))
    run('pacman', '-Syu', '--needed', '--', *packages)
    Installer.set_hostname(installation, config.hostname)
    if not Installer.set_timezone(installation, config.timezone):
        raise ValueError(f'Unable to apply timezone: {config.timezone}')
    installation.enable_service(config.services)
    if config.ntp:
        installation.enable_service('systemd-timesyncd.service')
    return installation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Show selected live actions without executing them')
    args = parser.parse_args()
    raw = json.loads(args.config.read_text())
    config = native_config(raw)
    if args.dry_run:
        print('Live settings: packages, repositories, console, timezone, hostname, networking, applications, profiles, services')
        print('Skipped: disk layout, formatting, encryption, bootloader, user/password creation, filesystem snapshots')
        for command in config.custom_commands or raw.get('custom_commands', []):
            print(command)
        return
    if os.geteuid() != 0 or not os.environ.get('SUDO_USER'):
        parser.error('Run through ./apply.sh as a regular user')
    repo = args.config.resolve().parent
    environment = dict(os.environ, CONFIG_REPO=str(repo), CONFIG_MODE='live')
    subprocess.run(['bash', str(repo / 'user-configuration.sh'), '--check'], env=environment, check=True)
    link = Path('/run/system-configuration.json')
    link.unlink(missing_ok=True)
    link.symlink_to(args.config.resolve())
    subprocess.run(['bash', str(repo / 'user-configuration.sh'), '--pre'], env=environment, check=True)
    installation = apply_native(config, raw.get('extra', {}))
    for command in raw.get('custom_commands', []):
        subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', command], env=environment, check=True, cwd=repo)
    run('systemctl', 'daemon-reload')
    if installation.disabled_services:
        run('systemctl', 'disable', *dict.fromkeys(installation.disabled_services))
    if installation.services:
        run('systemctl', 'enable', *dict.fromkeys(installation.services))
    # Match normal apply activation without restarting the graphical login session.
    start = installation.services
    if start:
        run('systemctl', 'start', *dict.fromkeys(start))


if __name__ == '__main__':
    main()
