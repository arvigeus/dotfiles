#!/usr/bin/env python3
"""One JSON request on stdin, one JSON reply. NetworkManager owns connection lifetime.

Covers what Quickshell.Networking does not: VPN/WireGuard profiles, user-scoped
profiles for new Wi-Fi networks, IP details and Cloudflare WARP. Secrets travel
over stdin and D-Bus, never argv, logs, or status snapshots.
"""

import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import time
import uuid

PROFILE_TYPES = ('vpn', 'wireguard')


def import_wireguard():
    """Run the chooser and editor outside the shell's layer-surface lifetime."""
    try:
        selected = subprocess.run(
            [
                'zenity',
                '--file-selection',
                '--title=Import WireGuard configuration',
                '--filename=' + str(Path.home() / 'Downloads') + '/',
                '--file-filter=WireGuard configurations | *.conf',
                '--file-filter=All files | *',
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if selected.returncode:
            return
        # Zenity terminates its output with one newline. Preserve whitespace
        # within the filename and pass it as one argument without a shell.
        filename = selected.stdout.removesuffix('\n')
        if not filename:
            return
        editor = subprocess.run(
            [
                'nm-connection-editor',
                '--type',
                'wireguard',
                '--import',
                filename,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if not editor.returncode:
            return
    except OSError:
        pass
    # Never surface CLI output: it can include configuration or credentials.
    subprocess.run(
        [
            'zenity',
            '--error',
            '--title=WireGuard import',
            '--text=Could not open the connection editor. Check that nm-connection-editor is installed.',
        ],
        capture_output=True,
        check=False,
    )


def command(argv, timeout=20):
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, 'LC_ALL': 'C'},
        )
    except FileNotFoundError:
        raise ValueError(f'{argv[0]} is not installed.') from None
    except subprocess.TimeoutExpired:
        raise ValueError(
            'The operation timed out. Its current state appears shortly.'
        ) from None


def checked(argv, timeout=20):
    result = command(argv, timeout)
    if result.returncode:
        # CLI diagnostics can echo credentials/configuration. Never forward them.
        raise ValueError(
            'The action failed. Check service availability and desktop authorization.'
        )
    return result.stdout.strip()


WARP_MODES = ('warp+doh', 'warp+dot', 'warp', 'doh', 'dot', 'tunnel_only', 'proxy')


def warp_mode(value):
    return {
        'WarpWithDnsOverHttps': 'warp+doh',
        'WarpWithDnsOverTls': 'warp+dot',
        'DnsOverHttps': 'doh',
        'DnsOverTls': 'dot',
        'Warp': 'warp',
        'TunnelOnly': 'tunnel_only',
        'WarpProxy': 'proxy',
    }.get(value, value)


def warp_status():
    if not shutil.which('warp-cli'):
        return {
            'available': False,
            'state': 'Not installed',
            'connected': False,
            'running': False,
            'mode': '',
        }
    service = command(
        ['systemctl', 'show', 'warp-svc.service', '--property=ActiveState', '--value']
    )
    if service.stdout.strip() not in ('active', 'activating', 'reloading'):
        return {
            'available': True,
            'state': 'Off · daemon stopped',
            'connected': False,
            'running': False,
            'mode': '',
        }
    result = command(['warp-cli', '--accept-tos', '--no-ansi', 'status'])
    match = re.search(r'^Status update:\s*(\w+)', result.stdout, re.M)
    status = match.group(1) if match else 'Unavailable · check WARP registration'
    mode = command(['warp-cli', '--accept-tos', '--no-ansi', 'settings'])
    mode_match = re.search(r'(?:WarpMode|WARP mode|Mode):\s*(\S+)', mode.stdout, re.I)
    return {
        'available': True,
        'state': status,
        'running': True,
        'connected': status.lower() == 'connected',
        'mode': warp_mode(mode_match.group(1)) if mode_match else '',
    }


def warp_control(request):
    action = request.get('action')
    if action == 'disconnect':
        # Even a broken/missing registration must not prevent stopping the daemon.
        try:
            command(['warp-cli', '--accept-tos', 'disconnect'])
        except ValueError:
            pass  # Stopping the daemon also tears down its tunnel and DNS proxy.
        warp_checked(
            ['systemctl', '--no-ask-password', 'stop', 'warp-svc.service'],
            'Could not stop WARP. Check desktop authorization and warp-svc.service.',
            45,
        )
        return
    if action not in ('connect', 'mode'):
        raise ValueError('Unknown WARP action.')
    mode = request.get('mode', 'warp+doh')
    if mode not in WARP_MODES:
        raise ValueError('Choose a supported WARP mode.')
    if action == 'mode':
        warp_checked(
            ['warp-cli', '--accept-tos', 'mode', mode], 'Could not change WARP mode.'
        )
        return
    try:
        warp_checked(
            ['systemctl', '--no-ask-password', 'start', 'warp-svc.service'],
            'Could not start WARP. Check desktop authorization and warp-svc.service.',
            45,
        )
        # systemd's start reply can precede readiness of the daemon's IPC socket.
        for _ in range(30):
            probe = command(['warp-cli', '--accept-tos', '--json', 'status'])
            code = warp_code(probe)
            if code != 'FailedToConnectToDaemon':
                break
            time.sleep(0.2)
        else:
            raise ValueError(
                'WARP daemon did not become ready. Check warp-svc.service.'
            )
        # Reuse existing registration. Only the CLI's specific missing-registration
        # result permits creating one; network/authentication failures never do.
        registration = command(
            ['warp-cli', '--accept-tos', '--json', 'registration', 'show']
        )
        if warp_code(registration) == 'MissingRegistration':
            warp_checked(
                ['warp-cli', '--accept-tos', 'registration', 'new'],
                'Could not register WARP. Check your internet connection and try again.',
            )
        elif registration.returncode:
            raise ValueError(
                'Could not read WARP registration. Check warp-svc.service and try again.'
            )
        warp_checked(
            ['warp-cli', '--accept-tos', 'mode', mode], 'Could not change WARP mode.'
        )
        warp_checked(
            ['warp-cli', '--accept-tos', 'connect'],
            'Could not connect WARP. Check your internet connection and try again.',
        )
    except ValueError:
        # A failed start/registration/connect must not leave an idle daemon behind.
        try:
            checked(['systemctl', '--no-ask-password', 'stop', 'warp-svc.service'], 45)
        except ValueError:
            raise ValueError(
                'WARP failed and its service could not be stopped. Check warp-svc.service.'
            ) from None
        raise


def warp_code(result):
    try:
        return json.loads(result.stdout or result.stderr).get('code')
    except (ValueError, AttributeError):
        return None


def warp_checked(argv, message, timeout=20):
    try:
        return checked(argv, timeout)
    except ValueError:
        raise ValueError(message) from None


def ip_details(device):
    active = device.get_active_connection()
    details = {'connection': active.get_id() if active else ''}
    for family, config in (
        ('ipv4', device.get_ip4_config()),
        ('ipv6', device.get_ip6_config()),
    ):
        details[family] = (
            [f'{a.get_address()}/{a.get_prefix()}' for a in config.get_addresses()]
            if config
            else []
        )
        details[family + 'Gateway'] = (config.get_gateway() or '') if config else ''
        details[family + 'Dns'] = list(config.get_nameservers()) if config else []
    return details


class Network:
    def __init__(self):
        import gi

        gi.require_version('NM', '1.0')
        from gi.repository import GLib, Gio, NM

        self.NM, self.GLib, self.Gio = NM, GLib, Gio
        self.client = NM.Client.new(None)
        if not self.client.get_nm_running():
            raise ValueError('NetworkManager is not running.')

    def call(self, owner, method, *args):
        loop = self.GLib.MainLoop()
        result = {}
        cancel = self.Gio.Cancellable()

        def finished(source, response, *_):
            try:
                result['value'] = getattr(
                    source, method.removesuffix('_async') + '_finish'
                )(response)
            except self.GLib.Error as error:
                result['error'] = error
            loop.quit()

        def timeout():
            result['error'] = True
            cancel.cancel()
            loop.quit()
            return False

        timer = self.GLib.timeout_add_seconds(45, timeout)
        getattr(owner, method)(*args, cancel, finished, None)
        loop.run()
        if not cancel.is_cancelled():
            self.GLib.source_remove(timer)
        if result.get('error'):
            error = result['error']
            if isinstance(error, self.GLib.Error) and error.matches(
                self.NM.ManagerError.quark(), self.NM.ManagerError.PERMISSIONDENIED
            ):
                raise ValueError(
                    'NetworkManager denied permission. Check desktop authorization.'
                )
            raise ValueError(
                'NetworkManager could not finish this action. Retry or open the connection editor.'
            )
        return result.get('value')

    def snapshot(self):
        active = {a.get_uuid(): a for a in self.client.get_active_connections()}
        profiles = []
        for c in self.client.get_connections():
            if c.get_connection_type() not in PROFILE_TYPES:
                continue
            a = active.get(c.get_uuid())
            profiles.append(
                {
                    'uuid': c.get_uuid(),
                    'name': c.get_id(),
                    'kind': c.get_connection_type(),
                    'active': bool(a),
                    'state': a.get_state().value_nick if a else 'disconnected',
                }
            )
        profiles.sort(key=lambda p: p['name'].casefold())
        details = {
            d.get_iface(): ip_details(d)
            for d in self.client.get_devices()
            if d.get_device_type()
            in (self.NM.DeviceType.WIFI, self.NM.DeviceType.ETHERNET)
        }
        return {'profiles': profiles, 'active': sorted(active), 'details': details}

    def wait_active(self, active):
        NM = self.NM
        done = (
            NM.ActiveConnectionState.ACTIVATED,
            NM.ActiveConnectionState.DEACTIVATED,
        )
        if active.get_state() not in done:
            loop = self.GLib.MainLoop()
            timed_out = []

            def changed(*_):
                if active.get_state() in done:
                    loop.quit()

            def timeout():
                timed_out.append(True)
                loop.quit()
                return False

            handler = active.connect('state-changed', changed)
            timer = self.GLib.timeout_add_seconds(50, timeout)
            loop.run()
            active.disconnect(handler)
            if not timed_out:
                self.GLib.source_remove(timer)
        if active.get_state() != NM.ActiveConnectionState.ACTIVATED:
            raise ValueError(
                'Could not connect. Check the password and signal, or edit this connection.'
            )

    def activate(self, identity):
        profile = (
            self.client.get_connection_by_uuid(identity)
            if isinstance(identity, str)
            else None
        )
        if not profile or profile.get_connection_type() not in PROFILE_TYPES:
            raise ValueError('This profile is no longer available.')
        self.wait_active(
            self.call(self.client, 'activate_connection_async', profile, None, None)
        )

    def deactivate(self, identity):
        for a in self.client.get_active_connections():
            if a.get_uuid() == identity:
                self.call(self.client, 'deactivate_connection_async', a)

    def join(self, request):
        """Create and activate a user-scoped profile for a network without one."""
        NM, GLib = self.NM, self.GLib
        device = self.client.get_device_by_iface(request.get('interface') or '')
        if not device or device.get_device_type() != NM.DeviceType.WIFI:
            raise ValueError('This adapter is no longer available.')
        ssid = request.get('ssid', '')
        if (
            not isinstance(ssid, str)
            or not 1 <= len(ssid.encode()) <= 32
            or '\x00' in ssid
        ):
            raise ValueError('The network name must contain 1–32 bytes.')
        sec = request.get('security', 'open')
        if sec not in ('open', 'owe', 'wpa-psk', 'sae'):
            raise ValueError(
                'Use the connection editor for enterprise or WEP authentication.'
            )
        password = request.get('password', '')
        if sec == 'wpa-psk' and not (
            8 <= len(password) <= 63 or re.fullmatch(r'[0-9a-fA-F]{64}', password)
        ):
            raise ValueError(
                'WPA passwords need 8–63 characters or a 64-digit hexadecimal key.'
            )
        if sec == 'sae' and not 1 <= len(password) <= 63:
            raise ValueError('Enter a WPA3 password of 1–63 characters.')
        identity = str(uuid.uuid4())
        connection = NM.SimpleConnection.new()
        setting = NM.SettingConnection.new()
        setting.set_property('id', ssid)
        setting.set_property('uuid', identity)
        setting.set_property('type', '802-11-wireless')
        setting.add_permission('user', pwd.getpwuid(os.getuid()).pw_name, None)
        connection.add_setting(setting)
        wifi = NM.SettingWireless.new()
        wifi.set_property('ssid', GLib.Bytes.new(ssid.encode()))
        wifi.set_property('mode', 'infrastructure')
        connection.add_setting(wifi)
        if sec != 'open':
            auth = NM.SettingWirelessSecurity.new()
            auth.set_property('key-mgmt', sec)
            if sec in ('wpa-psk', 'sae'):
                auth.set_property('psk', password)
            connection.add_setting(auth)
        connection.normalize()
        try:
            self.wait_active(
                self.call(
                    self.client,
                    'add_and_activate_connection_async',
                    connection,
                    device,
                    None,
                )
            )
        except ValueError:
            # NetworkManager saves the profile before activating it. Like nmcli,
            # keep none for a network that never connected: it would otherwise
            # appear saved and autoconnect with a wrong password.
            self.remove(identity)
            raise

    def remove(self, identity):
        profile = self.client.get_connection_by_uuid(identity)
        if profile:
            try:
                self.call(profile, 'delete_async')
            except ValueError:
                pass  # Report the connection failure, not the cleanup.


def handle(request):
    op = request.get('op')
    if op not in ('status', 'connect', 'join', 'disconnect', 'warp'):
        raise ValueError('Unknown network operation.')
    if op == 'warp':
        warp_control(request)
    network = Network()
    if op == 'connect':
        network.activate(request.get('uuid'))
    elif op == 'join':
        network.join(request)
    elif op == 'disconnect':
        network.deactivate(request.get('uuid'))
    snapshot = network.snapshot()
    try:
        snapshot['warp'] = warp_status()
    except ValueError:
        snapshot['warp'] = {
            'available': bool(shutil.which('warp-cli')),
            'running': False,
            'connected': False,
            'state': 'WARP status unavailable',
            'mode': '',
        }
    return snapshot


def main():
    line = sys.stdin.readline(65536)
    # Quickshell SIGKILLs a helper whose Process is destroyed, as on a shell
    # reload. The request runs in its own session so a started WARP setup still
    # stops a failed daemon and a failed join still removes its profile; this
    # process only waits for it.
    child = os.fork()
    if child:
        sys.exit(os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]))
    os.setsid()
    result = respond(line)
    try:
        print(json.dumps(result), flush=True)
    except OSError:
        # The shell went away; the change has finished regardless.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def respond(line):
    try:
        result = {'ok': True, 'data': handle(json.loads(line))}
    except ValueError as error:
        result = {'ok': False, 'error': str(error)}
    except ImportError:
        result = {
            'ok': False,
            'error': 'Install python-gobject and NetworkManager to use network controls.',
        }
    except Exception:
        # libnm exceptions may contain configuration values. Keep the boundary quiet.
        result = {
            'ok': False,
            'error': 'Network control failed. Check NetworkManager, WARP and desktop authorization.',
        }
    return result


if __name__ == '__main__':
    if sys.argv[1:] == ['--import-wireguard']:
        import_wireguard()
    else:
        main()
