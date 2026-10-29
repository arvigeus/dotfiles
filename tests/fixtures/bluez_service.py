"""A test-only BlueZ with one adapter, intended for a private dbus-run-session.

Arguments are a JSON state file and a call log. The state holds `devices`, a list
of Device1 properties with an optional `script`, and `start_delay`, the
milliseconds StartDiscovery takes. A script may name the `agent` method Pair()
calls, the `reply` that method must return, `remove` (the device disappears
during Pair), `trust_delay` (milliseconds before setting Trusted is answered)
and `connect: "fail"`. As in BlueZ, discovery sessions belong to
their callers: stopping is refused without a session and while its start is
pending. Pair() prompts the agent its caller registered. Each answered call is
appended to the log with its outcome. The bus address is printed once the name
is owned; closing stdin stops the service.
"""

import json
import os
import sys
from pathlib import Path

from gi.repository import Gio, GLib

ADAPTER = '/org/bluez/hci0'
ADAPTER_PROPERTIES = dict(
    Address='s',
    Name='s',
    Alias='s',
    Powered='b',
    PowerState='s',
    Discoverable='b',
    DiscoverableTimeout='u',
    Discovering='b',
    Pairable='b',
    PairableTimeout='u',
)
DEVICE_PROPERTIES = dict(
    Address='s',
    Name='s',
    Alias='s',
    Icon='s',
    Connected='b',
    Paired='b',
    Bonded='b',
    Trusted='b',
    Blocked='b',
    WakeAllowed='b',
    Adapter='o',
)


def interface(name, methods, properties=None):
    return Gio.DBusNodeInfo.new_for_xml(
        f'<node><interface name="{name}">{methods}'
        + ''.join(
            f'<property name="{key}" type="{kind}" access="readwrite"/>'
            for key, kind in (properties or {}).items()
        )
        + '</interface></node>'
    ).interfaces[0]


MANAGER = interface(
    'org.freedesktop.DBus.ObjectManager',
    '<method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>'
    '<signal name="InterfacesAdded"><arg type="o"/><arg type="a{sa{sv}}"/></signal>'
    '<signal name="InterfacesRemoved"><arg type="o"/><arg type="as"/></signal>',
)
AGENTS = interface(
    'org.bluez.AgentManager1',
    '<method name="RegisterAgent"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>'
    '<method name="UnregisterAgent"><arg type="o" direction="in"/></method>',
)
ADAPTER1 = interface(
    'org.bluez.Adapter1',
    '<method name="StartDiscovery"/><method name="StopDiscovery"/>'
    '<method name="RemoveDevice"><arg type="o" direction="in"/></method>',
    ADAPTER_PROPERTIES,
)
DEVICE1 = interface(
    'org.bluez.Device1',
    '<method name="Connect"/><method name="Disconnect"/>'
    '<method name="Pair"/><method name="CancelPairing"/>',
    DEVICE_PROPERTIES,
)
AGENT_SIGNATURES = dict(
    RequestPinCode='(o)', RequestPasskey='(o)', RequestConfirmation='(ou)'
)
PASSKEY = 123456

state = json.loads(Path(sys.argv[1]).read_text())
log = Path(sys.argv[2])
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
objects = {
    ADAPTER: dict(
        Address='00:00:00:00:00:01',
        Name='hci0',
        Alias='Laptop',
        Powered=True,
        PowerState='on',
        Discoverable=False,
        DiscoverableTimeout=180,
        Discovering=False,
        Pairable=True,
        PairableTimeout=0,
    )
}
scripts, registrations = {}, {}
sessions = {}  # discovery caller -> 'starting' | 'active'
agents = {}  # caller -> agent path
pairings = {}  # device path -> pending Pair() request


def record(sender, path, method, args, outcome):
    with log.open('a') as stream:
        stream.write(
            json.dumps(
                dict(
                    sender=sender, path=path, method=method, args=args, outcome=outcome
                )
            )
            + '\n'
        )


def answer(invocation, path, method, args=(), error=None, message=None):
    record(invocation.get_sender(), path, method, list(args), error or 'ok')
    if error:
        invocation.return_dbus_error(f'org.bluez.Error.{error}', message or error)
    else:
        invocation.return_value(None)


def change(path, **values):
    adapter = path == ADAPTER
    kinds = ADAPTER_PROPERTIES if adapter else DEVICE_PROPERTIES
    objects[path].update(values)
    bus.emit_signal(
        None,
        path,
        'org.freedesktop.DBus.Properties',
        'PropertiesChanged',
        GLib.Variant(
            '(sa{sv}as)',
            (
                'org.bluez.Adapter1' if adapter else 'org.bluez.Device1',
                {key: GLib.Variant(kinds[key], value) for key, value in values.items()},
                [],
            ),
        ),
    )


def managed():
    return {
        path: {
            'org.bluez.Adapter1' if path == ADAPTER else 'org.bluez.Device1': {
                key: GLib.Variant(
                    (ADAPTER_PROPERTIES if path == ADAPTER else DEVICE_PROPERTIES)[key],
                    value,
                )
                for key, value in values.items()
            }
        }
        for path, values in objects.items()
    }


def remove(path):
    bus.unregister_object(registrations.pop(path))
    del objects[path]
    bus.emit_signal(
        None,
        '/',
        'org.freedesktop.DBus.ObjectManager',
        'InterfacesRemoved',
        GLib.Variant('(oas)', (path, ['org.bluez.Device1'])),
    )


def start_discovery(invocation, path, args):
    sender = invocation.get_sender()
    if sender in sessions:
        return answer(invocation, path, 'StartDiscovery', error='InProgress')
    sessions[sender] = 'starting'

    def started():
        sessions[sender] = 'active'
        answer(invocation, path, 'StartDiscovery')
        if not objects[ADAPTER]['Discovering']:
            change(ADAPTER, Discovering=True)
        return False

    GLib.timeout_add(state.get('start_delay', 0), started)


def stop_discovery(invocation, path, args):
    session = sessions.get(invocation.get_sender())
    if session != 'active':
        return answer(
            invocation,
            path,
            'StopDiscovery',
            error='InProgress' if session else 'Failed',
            message=None if session else 'No discovery started',
        )
    del sessions[invocation.get_sender()]
    answer(invocation, path, 'StopDiscovery')
    if not sessions:
        change(ADAPTER, Discovering=False)


def pair(invocation, path, args):
    sender, script = invocation.get_sender(), scripts[path]
    if objects[path]['Paired'] or path in pairings:
        return answer(invocation, path, 'Pair', error='AlreadyExists')
    request = pairings[path] = {}

    def finish(error=None):
        if pairings.pop(path, None) is not request:
            return
        if not error:
            change(path, Paired=True, Bonded=True)
        answer(invocation, path, 'Pair', error=error)

    request['finish'] = finish
    kind, agent = script.get('agent'), agents.get(sender)
    if script.get('remove'):
        # BlueZ cancels the bonding of a device it removes.
        remove(path)
        return finish('AuthenticationCanceled')
    if not kind:
        return finish()
    if not agent:
        return finish('AuthenticationFailed')

    def answered(connection, result):
        try:
            value = list(connection.call_finish(result).unpack())
        except GLib.Error as error:
            name = Gio.dbus_error_get_remote_error(error) or 'Error'
            record(sender, path, kind, [], name)
            return finish(
                'AuthenticationRejected'
                if name.endswith('Rejected')
                else 'AuthenticationCanceled'
            )
        record(sender, path, kind, [], value)
        finish(None if value == script.get('reply', []) else 'AuthenticationFailed')

    bus.call(
        sender,
        agent,
        'org.bluez.Agent1',
        kind,
        GLib.Variant(
            AGENT_SIGNATURES[kind],
            (path, PASSKEY) if kind == 'RequestConfirmation' else (path,),
        ),
        None,
        Gio.DBusCallFlags.NONE,
        30000,
        None,
        answered,
    )


def cancel_pairing(invocation, path, args):
    request = pairings.get(path)
    if not request:
        return answer(invocation, path, 'CancelPairing', error='DoesNotExist')
    answer(invocation, path, 'CancelPairing')
    request['finish']('AuthenticationCanceled')


def connect(invocation, path, args):
    if scripts[path].get('connect') == 'fail':
        return answer(
            invocation, path, 'Connect', error='Failed', message='Page Timeout'
        )
    change(path, Connected=True)
    answer(invocation, path, 'Connect')


def disconnect(invocation, path, args):
    change(path, Connected=False)
    answer(invocation, path, 'Disconnect')


def register_agent(invocation, path, args):
    agents[invocation.get_sender()] = args[0]
    answer(invocation, path, 'RegisterAgent', args)


def unregister_agent(invocation, path, args):
    agents.pop(invocation.get_sender(), None)
    answer(invocation, path, 'UnregisterAgent', args)


def remove_device(invocation, path, args):
    remove(args[0])
    answer(invocation, path, 'RemoveDevice', args)


METHODS = dict(
    StartDiscovery=start_discovery,
    StopDiscovery=stop_discovery,
    RemoveDevice=remove_device,
    Pair=pair,
    CancelPairing=cancel_pairing,
    Connect=connect,
    Disconnect=disconnect,
    RegisterAgent=register_agent,
    UnregisterAgent=unregister_agent,
)


def method(connection, sender, path, interface_name, name, parameters, invocation):
    if name == 'GetManagedObjects':
        invocation.return_value(GLib.Variant('(a{oa{sa{sv}}})', (managed(),)))
    elif interface_name == 'org.freedesktop.DBus.Properties':
        set_property(invocation, path, *parameters.unpack())
    else:
        METHODS[name](invocation, path, parameters.unpack())


def get_property(connection, sender, path, interface_name, name):
    kinds = ADAPTER_PROPERTIES if path == ADAPTER else DEVICE_PROPERTIES
    return GLib.Variant(kinds[name], objects[path][name])


def set_property(invocation, path, interface_name, name, value):
    # Without a set_property callback, GDBus routes Set here so it can be delayed.
    values = {name: value}
    if name == 'Powered':
        values['PowerState'] = 'on' if value else 'off'

    def apply():
        change(path, **values)
        answer(invocation, path, 'Set', [name, value])
        return False

    delay = scripts.get(path, {}).get('trust_delay') if name == 'Trusted' else None
    if delay:
        GLib.timeout_add(delay, apply)
    else:
        apply()


bus.register_object('/', MANAGER, method, None, None)
bus.register_object('/org/bluez', AGENTS, method, None, None)
registrations[ADAPTER] = bus.register_object(
    ADAPTER, ADAPTER1, method, get_property, None
)
for device in state['devices']:
    path = f'{ADAPTER}/dev_{device["Address"].replace(":", "_")}'
    scripts[path] = device.pop('script', {})
    objects[path] = (
        dict(
            Name=device['Alias'],
            Icon='',
            Connected=False,
            Paired=False,
            Bonded=False,
            Trusted=False,
            Blocked=False,
            WakeAllowed=False,
            Adapter=ADAPTER,
        )
        | device
    )
    registrations[path] = bus.register_object(path, DEVICE1, method, get_property, None)


def acquired(connection, name):
    print(os.environ['DBUS_SESSION_BUS_ADDRESS'], flush=True)


def stop(stream, condition):
    if not stream.readline():
        loop.quit()
        return False
    return True


Gio.bus_own_name_on_connection(
    bus, 'org.bluez', Gio.BusNameOwnerFlags.NONE, acquired, None
)
GLib.io_add_watch(sys.stdin, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, stop)
loop.run()
