"""BlueZ drawer worker. JSON lines in/out; GLib keeps pairing replies asynchronous."""
import json
import os
import sys

from gi.repository import Gio, GLib

ADAPTER = 'org.bluez.Adapter1'
DEVICE = 'org.bluez.Device1'
AGENT_PATH = '/dotfiles/bluetooth/agent'
AGENT_XML = '''<node><interface name="org.bluez.Agent1">
<method name="Release"/><method name="Cancel"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
</interface></node>'''


def error_text(error):
    name = Gio.dbus_error_get_remote_error(error) or ''
    messages = {
        'AuthenticationCanceled': 'Pairing canceled.',
        'AuthenticationRejected': 'Pairing was rejected by the device.',
        'AuthenticationFailed': 'Pairing failed. Check the code and try again.',
        'AuthenticationTimeout': 'The device did not respond. Put it in pairing mode and try again.',
        'NotReady': 'The Bluetooth adapter is off or not ready.',
        'NotSupported': 'This device does not support that action.',
        'NotAvailable': 'The requested Bluetooth service is unavailable.',
        'NotAuthorized': 'Bluetooth access was denied.',
        'ConnectionAttemptFailed': 'Could not connect. Make sure the device is awake and nearby.',
        'InProgress': 'Another Bluetooth change is already in progress.',
    }
    Gio.dbus_error_strip_remote_error(error)
    return messages.get(name.rsplit('.', 1)[-1], error.message)


def inventory(objects):
    adapters, devices = [], []
    for path, interfaces in objects.items():
        if ADAPTER in interfaces:
            p = interfaces[ADAPTER]
            adapters.append(dict(key=path, name=p.get('Alias') or p.get('Name') or path.rsplit('/', 1)[-1],
                                 address=p.get('Address', ''), powered=p.get('Powered', False)))
        if DEVICE in interfaces:
            p = interfaces[DEVICE]
            battery = interfaces.get('org.bluez.Battery1', {}).get('Percentage')
            devices.append(dict(key=path, adapter=p.get('Adapter', ''), address=p.get('Address', ''),
                                name=p.get('Alias') or p.get('Name') or p.get('Address', 'Unknown device'),
                                icon=p.get('Icon', ''), paired=p.get('Paired', False),
                                connected=p.get('Connected', False), blocked=p.get('Blocked', False),
                                battery=battery if type(battery) is int and 0 <= battery <= 100 else -1))
    return dict(adapters=sorted(adapters, key=lambda a: a['key']),
                devices=sorted(devices, key=lambda d: (not d['connected'], not d['paired'], d['name'].casefold(), d['key'])))


class Controller:
    def __init__(self, bus, emit):
        self.bus, self.emit = bus, emit
        self.active = False
        self.pending = None
        self.prompt = None
        self.invocation = None
        self.prompt_id = 0
        self.scan = ''
        self.scan_timer = 0
        self.pair_timer = 0
        self.registered = False
        self.refresh_source = 0
        self.bus.register_object(AGENT_PATH, Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0], self.agent, None, None)
        self.subscriptions = [self.bus.signal_subscribe('org.bluez', interface, None, None, None,
                              Gio.DBusSignalFlags.NONE, self.changed) for interface in
                              ('org.freedesktop.DBus.Properties', 'org.freedesktop.DBus.ObjectManager')]
        self.subscriptions.append(self.bus.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus',
                                  'NameOwnerChanged', '/org/freedesktop/DBus', 'org.bluez',
                                  Gio.DBusSignalFlags.NONE, self.owner_changed))

    def read(self):
        return self.bus.call_sync('org.bluez', '/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects',
                                  None, GLib.VariantType.new('(a{oa{sa{sv}}})'), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]

    def call(self, path, interface, method, args=None, done=None, timeout=30000):
        def finished(bus, result):
            error = ''
            try:
                bus.call_finish(result)
            except GLib.Error as exc:
                error = error_text(exc)
            if done:
                done(error)
        self.bus.call('org.bluez', path, interface, method, args, None, Gio.DBusCallFlags.NONE,
                      timeout, None, finished)

    def changed(self, *_):
        if self.active and not self.refresh_source:
            self.refresh_source = GLib.timeout_add(100, self.scheduled_refresh)

    def scheduled_refresh(self):
        self.refresh_source = 0
        if self.active:
            self.refresh()
        return False

    def owner_changed(self, *args):
        self.registered = False
        self.stop_scan()
        self.cancel_pair()
        self.changed()

    def refresh(self):
        if self.refresh_source:
            GLib.source_remove(self.refresh_source)
            self.refresh_source = 0
        try:
            state = inventory(self.read())
            if self.scan and not any(a['key'] == self.scan and a['powered'] for a in state['adapters']):
                self.stop_scan()
            if self.pending and self.pending['op'] == 'pair':
                device = next((d for d in state['devices'] if d['key'] == self.pending['key']), None)
                if not device or not any(a['key'] == device['adapter'] and a['powered'] for a in state['adapters']):
                    self.cancel_pair()
            self.emit(dict(type='state', available=True, **state))
        except GLib.Error:
            self.emit(dict(type='state', available=False, adapters=[], devices=[]))
        return False

    def finish(self, error=''):
        pending, self.pending = self.pending, None
        self.clear_prompt()
        if self.pair_timer:
            GLib.source_remove(self.pair_timer)
            self.pair_timer = 0
        self.emit(dict(type='done', error=error, key=(pending or {}).get('key', '')))
        if self.active:
            self.refresh()

    def clear_prompt(self):
        if self.invocation:
            self.invocation.return_dbus_error('org.bluez.Error.Canceled', 'Pairing canceled')
        self.invocation, self.prompt = None, None
        self.emit(dict(type='prompt', prompt=None))

    def cancel_pair(self):
        self.clear_prompt()
        if self.pending and self.pending['op'] == 'pair':
            self.pending['canceled'] = True
            self.call(self.pending['key'], DEVICE, 'CancelPairing')
        return False

    def stop_scan(self):
        path, self.scan = self.scan, ''
        if self.scan_timer:
            GLib.source_remove(self.scan_timer)
            self.scan_timer = 0
        if path:
            self.call(path, ADAPTER, 'StopDiscovery')
        self.emit(dict(type='scan', key=''))
        return False

    def agent(self, bus, sender, path, interface, method, params, invocation):
        args = params.unpack()
        # Only BlueZ may invoke this agent, and only for our explicit pairing.
        owner = self.bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'GetNameOwner', GLib.Variant('(s)', ('org.bluez',)),
                                  None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        if sender != owner:
            invocation.return_dbus_error('org.bluez.Error.Rejected', 'Unknown caller')
            return
        if method in ('Release', 'Cancel'):
            self.clear_prompt()
            if method == 'Release':
                self.registered = False
            invocation.return_value(None)
            return
        if not self.active or not self.pending or self.pending['op'] != 'pair' or args[0] != self.pending['key'] or self.pending.get('canceled'):
            invocation.return_dbus_error('org.bluez.Error.Rejected', 'No pairing requested for this device')
            return
        self.clear_prompt()
        self.prompt_id += 1
        self.prompt = dict(id=self.prompt_id, key=args[0], kind=method,
                           code=(f'{args[1]:06d}' if method in ('RequestConfirmation', 'DisplayPasskey') else
                                 args[1] if method == 'DisplayPinCode' else ''),
                           entered=args[2] if method == 'DisplayPasskey' else 0)
        if method.startswith('Display'):
            invocation.return_value(None)
        else:
            self.invocation = invocation
        self.emit(dict(type='prompt', prompt=self.prompt))

    def respond(self, request):
        if not self.prompt or request.get('id') != self.prompt['id'] or not self.invocation:
            raise ValueError('This pairing request has expired.')
        if not request.get('accept'):
            self.invocation.return_dbus_error('org.bluez.Error.Rejected', 'Pairing rejected')
            self.invocation = None
            self.cancel_pair()
            return
        kind, value = self.prompt['kind'], request.get('value', '')
        if kind == 'RequestPasskey':
            if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 6:
                raise ValueError('Enter a passkey of one to six digits.')
            result = GLib.Variant('(u)', (int(value),))
        elif kind == 'RequestPinCode':
            if not isinstance(value, str) or not 1 <= len(value) <= 16:
                raise ValueError('Enter a PIN of one to sixteen characters.')
            result = GLib.Variant('(s)', (value,))
        else:
            result = None
        self.invocation.return_value(result)
        self.invocation = None
        self.clear_prompt()

    def paired_device(self, key, address):
        objects = self.read()
        props = objects.get(key, {}).get(DEVICE, {})
        if props.get('Address') != address or not props.get('Paired'):
            raise ValueError('The paired device is no longer available. Search again.')
        if props.get('Blocked'):
            raise ValueError('This device is blocked. Unblock it in Bluetooth settings first.')
        if not objects.get(props.get('Adapter'), {}).get(ADAPTER, {}).get('Powered'):
            raise ValueError('This Bluetooth adapter is off or unavailable.')
        return props

    def trust_and_connect(self, key, address, newly_paired=False):
        def fail(error):
            self.finish(('Paired, but could not connect: ' if newly_paired else '') + error)

        def connect(error=''):
            if error:
                fail('Could not authorize automatic reconnections: ' + error)
                return
            try:
                props = self.paired_device(key, address)
                if not props.get('Trusted'):
                    raise ValueError('Could not confirm authorization for automatic reconnections.')
            except (ValueError, GLib.Error) as exc:
                fail(error_text(exc) if isinstance(exc, GLib.Error) else str(exc))
                return
            self.call(key, DEVICE, 'Connect', done=lambda error: fail(error) if error else self.finish())

        try:
            props = self.paired_device(key, address)
        except (ValueError, GLib.Error) as exc:
            fail(error_text(exc) if isinstance(exc, GLib.Error) else str(exc))
            return
        if props.get('Trusted'):
            connect()
        else:
            # Only an explicit connection or completed pairing reaches this write.
            self.call(key, 'org.freedesktop.DBus.Properties', 'Set',
                      GLib.Variant('(ssv)', (DEVICE, 'Trusted', GLib.Variant('b', True))), connect)

    def handle(self, request):
        op = request.get('op')
        if op == 'observe':
            self.active = request.get('active') is True
            if self.active:
                self.refresh()
            else:
                if self.refresh_source:
                    GLib.source_remove(self.refresh_source)
                    self.refresh_source = 0
                self.stop_scan()
                self.cancel_pair()
            return
        if op == 'respond':
            self.respond(request)
            return
        if op == 'cancel':
            self.cancel_pair()
            return
        if op == 'stop-scan':
            self.stop_scan()
            return
        if not self.active:
            raise ValueError('Open Bluetooth to make changes.')
        if self.pending:
            raise ValueError('Wait for the current Bluetooth change.')
        objects = self.read()
        key = request.get('key', '')
        if op in ('power', 'scan'):
            props = objects.get(key, {}).get(ADAPTER)
            if props is None:
                raise ValueError('This Bluetooth adapter is no longer available.')
            if op == 'power' and type(request.get('enabled')) is not bool:
                raise ValueError('Invalid Bluetooth power state.')
            if op == 'scan' and not props.get('Powered'):
                raise ValueError('Turn Bluetooth on before searching.')
        elif op in ('pair', 'connect', 'disconnect', 'forget'):
            props = objects.get(key, {}).get(DEVICE)
            if props is None or props.get('Address') != request.get('address'):
                raise ValueError('This device is no longer available. Search again.')
            adapter = objects.get(props.get('Adapter'), {}).get(ADAPTER, {})
            if not adapter.get('Powered'):
                raise ValueError('This Bluetooth adapter is off or unavailable.')
            if props.get('Blocked') and op != 'forget':
                raise ValueError('This device is blocked. Unblock it in Bluetooth settings first.')
            if op == 'pair' and props.get('Paired'):
                raise ValueError('This device is already paired. Connect instead.')
            if op == 'connect' and not props.get('Paired'):
                raise ValueError('Pair this device first.')
        else:
            raise ValueError('Unsupported Bluetooth action.')
        self.pending = dict(op=op, key=key)
        self.emit(dict(type='pending', op=op, key=key))
        if op == 'power':
            if not request['enabled']:
                self.stop_scan()
            self.call(key, 'org.freedesktop.DBus.Properties', 'Set',
                      GLib.Variant('(ssv)', (ADAPTER, 'Powered', GLib.Variant('b', request['enabled']))), self.finish)
        elif op == 'scan':
            self.stop_scan()
            def started(error):
                if not error:
                    self.scan = key
                    if self.active:
                        self.scan_timer = GLib.timeout_add_seconds(30, self.stop_scan)
                        self.emit(dict(type='scan', key=key))
                    else:
                        self.stop_scan()
                self.finish(error)
            self.call(key, ADAPTER, 'StartDiscovery', done=started)
        elif op == 'forget':
            self.call(props['Adapter'], ADAPTER, 'RemoveDevice', GLib.Variant('(o)', (key,)), self.finish)
        elif op == 'pair':
            self.stop_scan()
            self.pair_timer = GLib.timeout_add_seconds(60, self.cancel_pair)
            def paired(error):
                if error or self.pending.get('canceled'):
                    self.finish(error or 'Pairing canceled.')
                else:
                    self.clear_prompt()
                    if self.pair_timer:
                        GLib.source_remove(self.pair_timer)
                        self.pair_timer = 0
                    # Pairing has completed; its connection phase survives dismissal.
                    self.pending['op'] = 'connect'
                    self.emit(dict(type='pending', op='connect', key=key))
                    self.trust_and_connect(key, request['address'], newly_paired=True)
            def registered(error):
                if error:
                    self.finish(error)
                elif self.pending.get('canceled'):
                    self.finish('Pairing canceled.')
                else:
                    self.registered = True
                    self.call(key, DEVICE, 'Pair', done=paired, timeout=65000)
            if self.registered:
                registered('')
            else:
                self.call('/org/bluez', 'org.bluez.AgentManager1', 'RegisterAgent',
                          GLib.Variant('(os)', (AGENT_PATH, 'KeyboardDisplay')), registered)
        elif op == 'connect':
            self.trust_and_connect(key, request['address'])
        else:
            self.call(key, DEVICE, 'Disconnect', done=self.finish)


def main():
    loop = GLib.MainLoop()
    def emit(value):
        print(json.dumps(value), flush=True)
    controller = Controller(Gio.bus_get_sync(Gio.BusType.SYSTEM, None), emit)
    buffer = bytearray()
    os.set_blocking(sys.stdin.fileno(), False)
    def read_input(fd, condition):
        chunk = os.read(fd, 65536)
        if not chunk:
            controller.stop_scan()
            controller.cancel_pair()
            loop.quit()
            return False
        buffer.extend(chunk)
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Invalid Bluetooth request.')
                controller.handle(request)
            except (ValueError, GLib.Error) as exc:
                emit(dict(type='error', error=error_text(exc) if isinstance(exc, GLib.Error) else str(exc),
                          busy=controller.pending is not None))
        return True
    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, read_input)
    loop.run()


if __name__ == '__main__':
    main()
