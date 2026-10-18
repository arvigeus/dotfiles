"""Zephyrus battery care; Tuned retains exclusive ownership of power profiles."""
SERVICE = 'xyz.ljones.Asusd'
PATH = '/xyz/ljones'
INTERFACE = 'xyz.ljones.Platform'
PROPERTIES = 'org.freedesktop.DBus.Properties'


class Provider:
    def __init__(self, bus):
        self.bus = bus

    def snapshot(self):
        row = dict(label='ASUS battery care', identity='', limit=None, minimum=20, maximum=100, step=1)
        try:
            supported = self.bus.call(SERVICE, PATH, INTERFACE, 'SupportedProperties')
            if 'ChargeControlEndThreshold' in supported:
                limit = self.bus.call(SERVICE, PATH, PROPERTIES, 'Get', '(ss)', (INTERFACE, 'ChargeControlEndThreshold'))
                if type(limit) is int and 20 <= limit <= 100:
                    row.update(identity=self.bus.owner(SERVICE), limit=limit)
        except Exception:
            # The vendor daemon is optional. Reads must not activate it.
            pass
        return row

    def change(self, request):
        row = self.snapshot()
        value = request.get('value')
        if not row['identity'] or row['identity'] != request.get('identity') or row['limit'] != request.get('previous'):
            raise ValueError('The ASUS charge limit changed or its controller is unavailable. Refresh and try again.')
        if type(value) is not int or not row['minimum'] <= value <= row['maximum']:
            raise ValueError('Unsupported ASUS charge limit.')
        self.bus.set(SERVICE, PATH, INTERFACE, 'ChargeControlEndThreshold', 'y', value)
        confirmed = self.snapshot()
        if confirmed['identity'] != row['identity'] or confirmed['limit'] != value:
            raise ValueError('ASUS did not confirm the requested charge limit.')
