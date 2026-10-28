"""A test-only AccountsService, intended for a private dbus-run-session.

Arguments are a JSON state file and a call log. The state holds the current
user's `properties`, an `icons` directory and optional `fail` messages by method.
Each call is appended to the log before it is answered. The bus address is
printed once the name is owned; closing stdin stops the service.
"""

import json
import os
from pathlib import Path
import shutil
import sys
from gi.repository import Gio, GLib

MANAGER = """<node><interface name="org.freedesktop.Accounts">
<method name="FindUserById"><arg type="x" direction="in"/><arg type="o" direction="out"/></method>
</interface></node>"""
USER = """<node><interface name="org.freedesktop.Accounts.User">
<property name="RealName" type="s" access="read"/>
<property name="Email" type="s" access="read"/>
<property name="Location" type="s" access="read"/>
<property name="IconFile" type="s" access="read"/>
<property name="AccountType" type="i" access="read"/>
<property name="Locked" type="b" access="read"/>
<property name="PasswordMode" type="i" access="read"/>
<method name="SetRealName"><arg type="s" direction="in"/></method>
<method name="SetEmail"><arg type="s" direction="in"/></method>
<method name="SetLocation"><arg type="s" direction="in"/></method>
<method name="SetIconFile"><arg type="s" direction="in"/></method>
</interface></node>"""
USER_PATH = f'/org/freedesktop/Accounts/User{os.getuid()}'

state = json.loads(Path(sys.argv[1]).read_text())
log = Path(sys.argv[2])
properties = state['properties']
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()


def get_property(connection, sender, path, interface, name):
    value = properties[name]
    kind = 'b' if isinstance(value, bool) else 'i' if isinstance(value, int) else 's'
    return GLib.Variant(kind, value)


def method(connection, sender, path, interface, name, parameters, invocation):
    (value,) = parameters.unpack()
    flags = invocation.get_message().get_flags()
    entry = dict(
        method=name,
        path=path,
        value=value,
        interactive=bool(flags & Gio.DBusMessageFlags.ALLOW_INTERACTIVE_AUTHORIZATION),
    )
    if name == 'SetIconFile':
        entry['readable'] = os.access(value, os.R_OK)
    with log.open('a') as stream:
        stream.write(json.dumps(entry) + '\n')
    if name == 'FindUserById':
        if value != os.getuid():
            invocation.return_dbus_error(
                'org.freedesktop.Accounts.Error.Failed', f'No user with uid {value}'
            )
        else:
            invocation.return_value(GLib.Variant('(o)', (USER_PATH,)))
        return
    if name in state.get('fail', {}):
        invocation.return_dbus_error(
            'org.freedesktop.Accounts.Error.PermissionDenied', state['fail'][name]
        )
        return
    if name == 'SetIconFile':
        # Like the daemon, copy the caller's file before replying.
        icon = Path(state['icons']) / 'user'
        try:
            shutil.copyfile(value, icon)
        except OSError as error:
            invocation.return_dbus_error(
                'org.freedesktop.Accounts.Error.Failed', str(error)
            )
            return
        value = str(icon)
    properties[name.removeprefix('Set')] = value
    invocation.return_value(None)


for path, xml in (('/org/freedesktop/Accounts', MANAGER), (USER_PATH, USER)):
    bus.register_object(
        path,
        Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0],
        method,
        get_property,
        None,
    )


def acquired(connection, name):
    print(os.environ['DBUS_SESSION_BUS_ADDRESS'], flush=True)


def stop(stream, condition):
    if not stream.readline():
        loop.quit()
        return False
    return True


Gio.bus_own_name_on_connection(
    bus, 'org.freedesktop.Accounts', Gio.BusNameOwnerFlags.NONE, acquired, None
)
GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, stop)
loop.run()
