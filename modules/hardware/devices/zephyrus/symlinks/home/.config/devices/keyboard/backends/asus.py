"""ASUS Aura capabilities over its public D-Bus interface; no daemon activation."""
import xml.etree.ElementTree as ET
from pathlib import Path

EFFECTS = {0: ('Solid', True), 1: ('Breathe', True), 2: ('Rainbow cycle', False),
           3: ('Rainbow wave', False), 10: ('Pulse', True)}
COLORS = ['#ffffff', '#ff0000', '#ff8000', '#ffff00', '#00ff00', '#00ffff', '#0080ff', '#8000ff']
SERVICE = 'xyz.ljones.Asusd'
INTERFACE = 'xyz.ljones.Aura'
PROPERTIES = 'org.freedesktop.DBus.Properties'


class Provider:
    def __init__(self):
        self.bus = None

    def snapshot(self, native):
        keyboards = [row for row in native if row['key'].startswith('asus:')]
        aura = self.discover() if keyboards else None
        try:
            label = Path('/sys/class/dmi/id/product_family').read_text().strip() or 'Built-in keyboard'
        except OSError:
            label = 'Built-in keyboard'
        return [dict(row, label=label, connection='Built-in keyboard',
                     **(self.describe(*aura) if aura else {})) for row in keyboards]

    def change(self, row, request):
        if request.get('op') != 'lighting':
            raise ValueError('This keyboard does not support that lighting operation.')
        if not row['lightingPath'] or row['lightingPath'] != request.get('lightingPath'):
            raise ValueError('The keyboard lighting controller changed or is unavailable.')
        self.change_lighting(row['lightingPath'], request)

    def close(self):
        self.bus = None

    def call(self, path, interface, method, signature=None, args=()):
        from gi.repository import Gio, GLib
        if self.bus is None:
            self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        result = self.bus.call_sync(SERVICE, path, interface, method,
                                   GLib.Variant(signature, args) if signature else None,
                                   None, Gio.DBusCallFlags.NO_AUTO_START, 1500, None)
        return result.unpack()[0] if result.n_children() else None

    def properties(self, path):
        return self.call(path, PROPERTIES, 'GetAll', '(s)', (INTERFACE,))

    def discover(self):
        try:
            xml = self.call('/xyz/ljones/aura', 'org.freedesktop.DBus.Introspectable', 'Introspect')
            candidates = []
            for node in ET.fromstring(xml).findall('node'):
                path = '/xyz/ljones/aura/' + node.attrib['name']
                props = self.properties(path)
                if props.get('DeviceType') in (0, 1, 2):
                    candidates.append((path, props))
            # Never associate a platform LED with an arbitrary Aura controller.
            return candidates[0] if len(candidates) == 1 else None
        except Exception:
            return None

    @staticmethod
    def describe(path, props):
        mode = props.get('LedMode', -1)
        data = props.get('LedModeData')
        return dict(lightingPath=path, effects=[dict(id=key, label=EFFECTS[key][0], colors=EFFECTS[key][1])
                    for key in props.get('SupportedBasicModes', []) if key in EFFECTS],
                    effect=mode, rgb=mode in props.get('SupportedBasicModes', []) and EFFECTS.get(mode, ('', False))[1],
                    color=('#' + ''.join(f'{part:02x}' for part in data[2])) if data else '', modes=[], mode=-1)

    def change_lighting(self, path, request):
        from gi.repository import GLib
        props = self.properties(path)
        if 'effect' in request and 'color' not in request:
            mode = request['effect']
            if type(mode) is not int or mode not in EFFECTS or mode not in props.get('SupportedBasicModes', []):
                raise ValueError('This lighting effect is not supported by this keyboard.')
            variant = GLib.Variant('u', mode)
            name = 'LedMode'
        else:
            mode = props.get('LedMode')
            color = request.get('color')
            if mode != request.get('effect') or mode not in props.get('SupportedBasicModes', []) or not EFFECTS.get(mode, ('', False))[1]:
                raise ValueError('The lighting effect changed or does not support a color.')
            if color not in COLORS:
                raise ValueError('Unknown keyboard color preset.')
            data = list(props['LedModeData'])
            data[2] = data[3] = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
            variant = GLib.Variant('(uu(yyy)(yyy)ss)', tuple(data))
            name = 'LedModeData'
        self.call(path, PROPERTIES, 'Set', '(ssv)', (INTERFACE, name, variant))
        current = self.properties(path)
        if current.get('LedMode') != mode:
            raise ValueError('The keyboard did not confirm the lighting effect.')
        if 'color' in request and self.describe(path, current)['color'] != request['color']:
            raise ValueError('The keyboard did not confirm the color.')
