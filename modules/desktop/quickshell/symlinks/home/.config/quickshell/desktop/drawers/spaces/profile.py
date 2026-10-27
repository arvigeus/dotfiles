"""Read the local account's display name and photo without changing settings."""

import json
import os
from pathlib import Path
import pwd


def account_properties(uid):
    try:
        from gi.repository import Gio, GLib
    except ImportError:
        return {}
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        path = bus.call_sync(
            'org.freedesktop.Accounts',
            '/org/freedesktop/Accounts',
            'org.freedesktop.Accounts',
            'FindUserById',
            GLib.Variant('(x)', (uid,)),
            GLib.VariantType.new('(o)'),
            Gio.DBusCallFlags.NONE,
            1500,
            None,
        ).unpack()[0]
        return bus.call_sync(
            'org.freedesktop.Accounts',
            path,
            'org.freedesktop.DBus.Properties',
            'GetAll',
            GLib.Variant('(s)', ('org.freedesktop.Accounts.User',)),
            GLib.VariantType.new('(a{sv})'),
            Gio.DBusCallFlags.NONE,
            1500,
            None,
        ).unpack()[0]
    except GLib.Error:
        return {}


def profile():
    account = pwd.getpwuid(os.getuid())
    properties = account_properties(account.pw_uid)
    name = properties.get('RealName') or account.pw_gecos.split(',', 1)[0].strip()
    candidates = [
        properties.get('IconFile'),
        Path(account.pw_dir) / '.face',
        Path(account.pw_dir) / '.face.icon',
        Path('/var/lib/AccountsService/icons') / account.pw_name,
    ]
    avatar = ''
    for value in candidates:
        if not value:
            continue
        try:
            path = Path(value).resolve()
            if path.is_file() and os.access(path, os.R_OK):
                avatar = path.as_uri() + '?v=' + str(path.stat().st_mtime_ns)
                break
        except OSError:
            continue
    return dict(name=name, username=account.pw_name, avatar=avatar)


if __name__ == '__main__':
    print(json.dumps(profile()))
