"""Current-user account data and a narrow AccountsService write interface."""

import grp
import json
import os
from pathlib import Path
import pwd
import sys

EDITABLE = {
    'RealName': 'SetRealName',
    'Email': 'SetEmail',
    'Location': 'SetLocation',
    'IconFile': 'SetIconFile',
}


class Accounts:
    def __init__(self, uid):
        from gi.repository import Gio, GLib

        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.path = self.bus.call_sync(
            'org.freedesktop.Accounts',
            '/org/freedesktop/Accounts',
            'org.freedesktop.Accounts',
            'FindUserById',
            GLib.Variant('(x)', (uid,)),
            GLib.VariantType.new('(o)'),
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        ).unpack()[0]

    def properties(self):
        return self.bus.call_sync(
            'org.freedesktop.Accounts',
            self.path,
            'org.freedesktop.DBus.Properties',
            'GetAll',
            self.GLib.Variant('(s)', ('org.freedesktop.Accounts.User',)),
            self.GLib.VariantType.new('(a{sv})'),
            self.Gio.DBusCallFlags.NONE,
            5000,
            None,
        ).unpack()[0]

    def set(self, key, value):
        self.bus.call_sync(
            'org.freedesktop.Accounts',
            self.path,
            'org.freedesktop.Accounts.User',
            EDITABLE[key],
            self.GLib.Variant('(s)', (value,)),
            None,
            self.Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
            120000,
            None,
        )


def snapshot(account=None, service_factory=Accounts):
    account = account or pwd.getpwuid(os.getuid())
    error = ''
    try:
        properties = service_factory(account.pw_uid).properties()
    except Exception as failure:
        properties = {}
        error = str(failure)
    groups = []
    for gid in sorted(set(os.getgrouplist(account.pw_name, account.pw_gid))):
        try:
            name = grp.getgrgid(gid).gr_name
        except KeyError:
            name = str(gid)
        groups.append(dict(name=name, gid=gid, primary=gid == account.pw_gid))
    photo = properties.get('IconFile', '')
    if not photo:
        photo = next(
            (
                str(path)
                for path in (
                    Path(account.pw_dir) / '.face',
                    Path(account.pw_dir) / '.face.icon',
                )
                if path.is_file()
            ),
            '',
        )
    return dict(
        username=account.pw_name,
        uid=account.pw_uid,
        gid=account.pw_gid,
        home=account.pw_dir,
        shell=account.pw_shell,
        groups=groups,
        fields=dict(
            RealName=properties.get('RealName', account.pw_gecos.split(',', 1)[0]),
            Email=properties.get('Email', ''),
            Location=properties.get('Location', ''),
            IconFile=photo,
        ),
        details={
            key: properties[key]
            for key in (
                'AccountType',
                'Locked',
                'AutomaticLogin',
                'LocalAccount',
                'PasswordMode',
                'LoginTime',
            )
            if key in properties
        },
        available=not error,
        error=error,
    )


def save(changes, service_factory=Accounts):
    # Validate the whole request before applying any fields. The caller cannot select another UID.
    if not isinstance(changes, dict) or any(
        key not in EDITABLE
        or not isinstance(value, str)
        or '\x00' in value
        or len(value) > 4096
        for key, value in changes.items()
    ):
        raise ValueError('Invalid profile changes.')
    if 'IconFile' in changes:
        path = Path(changes['IconFile'])
        if not path.is_absolute() or not path.is_file():
            raise ValueError('Choose an existing photo.')
    service = service_factory(os.getuid())
    saved = {}
    for key, value in changes.items():
        try:
            service.set(key, value)
            saved[key] = value
        except Exception as error:
            return dict(saved=saved, error=f'Could not save {key}: {error}')
    return dict(saved=saved, error='')


def main():
    try:
        result = (
            save(json.load(sys.stdin)) if sys.argv[1:] == ['--save'] else snapshot()
        )
    except Exception as error:
        result = dict(error=str(error), saved={})
    print(json.dumps(result))


if __name__ == '__main__':
    main()
