"""BlueZ pairing helper: python3 backend.py DEVICE_PATH ADDRESS.

BlueZ sends PIN/passkey prompts to the agent of the Pair() caller, so this
process registers the agent, owns Pair(), forwards prompts as JSON lines,
then trusts and connects the device and exits. Input: {"op": "respond", "id",
"accept", "value"} or {"op": "cancel"}; stdin EOF cancels an unfinished pairing.
"""

import json
import os
import sys

from gi.repository import Gio, GLib

DEVICE = 'org.bluez.Device1'
PROPERTIES = 'org.freedesktop.DBus.Properties'
AGENT_PATH = '/dotfiles/bluetooth/agent'
AGENT_XML = """<node><interface name="org.bluez.Agent1">
<method name="Release"/><method name="Cancel"/>
<method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
<method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
<method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
<method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
<method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
<method name="RequestAuthorization"><arg type="o" direction="in"/></method>
<method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
</interface></node>"""


def error_text(error):
    name = Gio.dbus_error_get_remote_error(error) or ''
    messages = {
        'AuthenticationCanceled': 'Pairing canceled.',
        'AuthenticationRejected': 'Pairing was rejected by the device.',
        'AuthenticationFailed': 'Pairing failed. Check the code and try again.',
        'AuthenticationTimeout': 'The device did not respond. Put it in pairing mode and try again.',
        'ConnectionAttemptFailed': 'Could not reach the device. Make sure it is awake and nearby.',
        'NotReady': 'The Bluetooth adapter is off or not ready.',
        'InProgress': 'Another Bluetooth change is already in progress.',
    }
    Gio.dbus_error_strip_remote_error(error)
    return messages.get(name.rsplit('.', 1)[-1], error.message)


class Pairing:
    def __init__(self, bus, key, address, emit, quit):
        self.bus, self.key, self.address, self.emit, self.quit = (
            bus,
            key,
            address,
            emit,
            quit,
        )
        self.connecting = (
            False  # Pair() succeeded; trust and connect survive cancellation.
        )
        # Why pairing was canceled; it outranks the error BlueZ then reports.
        self.canceled = ''
        self.done = False
        self.prompt = None
        self.invocation = None
        self.prompt_id = 0
        self.timer = 0
        self.bus.register_object(
            AGENT_PATH,
            Gio.DBusNodeInfo.new_for_xml(AGENT_XML).interfaces[0],
            self.agent,
            None,
            None,
        )

    def call(self, path, interface, method, args=None, done=None, timeout=30000):
        def finished(bus, result):
            error = ''
            try:
                bus.call_finish(result)
            except GLib.Error as exc:
                error = error_text(exc)
            if done:
                done(error)

        self.bus.call(
            'org.bluez',
            path,
            interface,
            method,
            args,
            None,
            Gio.DBusCallFlags.NONE,
            timeout,
            None,
            finished,
        )

    def start(self):
        try:
            props = self.bus.call_sync(
                'org.bluez',
                self.key,
                PROPERTIES,
                'GetAll',
                GLib.Variant('(s)', (DEVICE,)),
                None,
                Gio.DBusCallFlags.NONE,
                3000,
                None,
            ).unpack()[0]
        except GLib.Error:
            props = {}
        if props.get('Address') != self.address:
            self.finish('This device is no longer available. Search again.')
        elif props.get('Paired'):
            self.finish('This device is already paired. Connect instead.')
        else:
            self.timer = GLib.timeout_add_seconds(60, self.expire)
            self.call(
                '/org/bluez',
                'org.bluez.AgentManager1',
                'RegisterAgent',
                GLib.Variant('(os)', (AGENT_PATH, 'KeyboardDisplay')),
                self.registered,
            )

    def registered(self, error):
        if error or self.canceled:
            self.finish(self.canceled or error)
        else:
            self.call(self.key, DEVICE, 'Pair', done=self.paired, timeout=65000)

    def paired(self, error):
        self.clear_prompt()
        if error:
            self.finish(self.canceled or error)
            return
        # A cancellation that reached BlueZ after pairing completed changed nothing.
        self.connecting = True
        self.emit(dict(type='connecting'))
        # Completed pairing authorizes this device's future reconnections.
        self.call(
            self.key,
            PROPERTIES,
            'Set',
            GLib.Variant('(ssv)', (DEVICE, 'Trusted', GLib.Variant('b', True))),
            self.trusted,
        )

    def trusted(self, error):
        if error:
            self.finish(
                'Paired, but could not authorize automatic reconnections: ' + error
            )
        else:
            self.call(
                self.key,
                DEVICE,
                'Connect',
                done=lambda error: self.finish(
                    'Paired, but could not connect: ' + error if error else ''
                ),
            )

    def finish(self, error=''):
        if self.done:
            return
        self.done = True
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.clear_prompt()
        self.emit(dict(type='done', error=error))
        self.quit()

    def clear_prompt(self):
        if self.invocation:
            self.invocation.return_dbus_error(
                'org.bluez.Error.Canceled', 'Pairing canceled'
            )
        had_prompt = self.prompt is not None
        self.invocation, self.prompt = None, None
        if had_prompt:
            self.emit(dict(type='prompt', prompt=None))

    def expire(self):
        self.timer = 0
        self.cancel('Pairing timed out.')
        return False

    def cancel(self, reason='Pairing canceled.'):
        if not self.connecting and not self.canceled and not self.done:
            self.canceled = reason
            self.clear_prompt()
            self.call(self.key, DEVICE, 'CancelPairing')

    def agent(self, bus, sender, path, interface, method, params, invocation):
        args = params.unpack()
        # Only BlueZ may invoke this agent, and only for the requested device.
        owner = self.bus.call_sync(
            'org.freedesktop.DBus',
            '/org/freedesktop/DBus',
            'org.freedesktop.DBus',
            'GetNameOwner',
            GLib.Variant('(s)', ('org.bluez',)),
            None,
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        ).unpack()[0]
        if sender != owner:
            invocation.return_dbus_error('org.bluez.Error.Rejected', 'Unknown caller')
            return
        if method in ('Release', 'Cancel'):
            self.clear_prompt()
            invocation.return_value(None)
            return
        if self.connecting or self.canceled or self.done or args[0] != self.key:
            invocation.return_dbus_error(
                'org.bluez.Error.Rejected', 'No pairing requested for this device'
            )
            return
        self.clear_prompt()
        self.prompt_id += 1
        self.prompt = dict(
            id=self.prompt_id,
            kind=method,
            code=(
                f'{args[1]:06d}'
                if method in ('RequestConfirmation', 'DisplayPasskey')
                else args[1]
                if method == 'DisplayPinCode'
                else ''
            ),
            entered=args[2] if method == 'DisplayPasskey' else 0,
        )
        if method.startswith('Display'):
            invocation.return_value(None)
        else:
            self.invocation = invocation
        self.emit(dict(type='prompt', prompt=self.prompt))

    def respond(self, request):
        if (
            not self.prompt
            or request.get('id') != self.prompt['id']
            or not self.invocation
        ):
            raise ValueError('This pairing request has expired.')
        if not request.get('accept'):
            self.invocation.return_dbus_error(
                'org.bluez.Error.Rejected', 'Pairing rejected'
            )
            self.invocation = None
            self.cancel()
            return
        kind, value = self.prompt['kind'], request.get('value', '')
        if kind == 'RequestPasskey':
            if (
                not isinstance(value, str)
                or not value.isascii()
                or not value.isdigit()
                or len(value) > 6
            ):
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

    def handle(self, request):
        if request.get('op') == 'respond':
            self.respond(request)
        elif request.get('op') == 'cancel':
            self.cancel()
        else:
            raise ValueError('Unsupported Bluetooth request.')


def main():
    # Quickshell SIGKILLs a helper whose Process is destroyed, as on a shell
    # reload. Pairing runs in a child in its own session, so a paired device is
    # still trusted and connected; this process only waits for it. The child
    # shares stdin, so the closed pipe still cancels an unfinished pairing.
    child = os.fork()
    if child:
        sys.exit(os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]))
    os.setsid()
    loop = GLib.MainLoop()

    def emit(value):
        try:
            print(json.dumps(value), flush=True)
        except OSError:
            pass  # Quickshell went away; finish the BlueZ calls regardless.

    pairing = Pairing(
        Gio.bus_get_sync(Gio.BusType.SYSTEM, None),
        sys.argv[1],
        sys.argv[2],
        emit,
        loop.quit,
    )
    buffer = bytearray()
    os.set_blocking(sys.stdin.fileno(), False)

    def read_input(fd, condition):
        chunk = os.read(fd, 65536)
        if not chunk:
            pairing.cancel()
            return False
        buffer.extend(chunk)
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('Invalid Bluetooth request.')
                pairing.handle(request)
            except ValueError as exc:
                emit(dict(type='error', error=str(exc)))
        return True

    GLib.io_add_watch(
        sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, read_input
    )
    pairing.start()
    if not pairing.done:
        loop.run()


if __name__ == '__main__':
    main()
