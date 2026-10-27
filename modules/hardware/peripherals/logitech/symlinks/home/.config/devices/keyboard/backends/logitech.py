"""Optional Solaar library adapter; never load or apply saved device settings."""

import time


class Provider:
    def __init__(self):
        self.handles = {}
        self.devices = {}
        self.rows = {}
        self.next_scan = 0
        self.next_read = 0

    def scan(self):
        from solaar import configuration
        from logitech_receiver import base, device, receiver

        # This process owns live lighting state only. Solaar's default persister
        # can record reads; prevent it from touching user preferences altogether.
        configuration.persister = lambda device: None
        found = set()
        seen = set()
        for info in base.receivers_and_devices():
            found.add(info.path)
            if info.path not in self.handles:
                try:
                    obj = (
                        device.create_device(base, info)
                        if info.isDevice
                        else receiver.create_receiver(base, info)
                    )
                    if obj:
                        self.handles[info.path] = obj
                except Exception:
                    continue
            obj = self.handles.get(info.path)
            if not obj:
                continue
            try:
                for item in [obj] if info.isDevice else obj:
                    if str(item.kind) != 'keyboard' or not item.ping():
                        continue
                    serial = item.unitId or item.serial
                    if not serial:
                        continue
                    key = 'logitech:' + serial
                    seen.add(key)
                    self.devices[key] = (info.path, item)
            except Exception:
                continue
        for path in list(self.handles):
            if path not in found:
                self.handles.pop(path).close()
                for key, (owner, _) in list(self.devices.items()):
                    if owner == path:
                        self.devices.pop(key)
                        self.rows.pop(key, None)
        for key in list(self.devices):
            if key not in seen:
                self.devices.pop(key)
                self.rows.pop(key, None)

    def read(self, key, item):
        from logitech_receiver import settings_templates

        item._backlight = None  # Solaar caches the hardware's mode/level object.
        mode = settings_templates.Backlight2.build(item)
        level = settings_templates.Backlight2Level.build(item)
        if mode is None:
            return None
        selected = mode.read(cached=False)
        if selected is None:
            raise ValueError('Keyboard is asleep or disconnected.')
        selected = int(selected)
        modes = [
            dict(
                id=int(choice),
                label={0: 'On', 1: 'Automatic', 3: 'Manual', 255: 'Off'}.get(
                    int(choice), str(choice)
                ),
            )
            for choice in mode.choices
            if int(choice) in (0, 1, 3, 255)
        ]
        value = level.read(cached=False) if level else None
        maximum = int(level.range[1]) if level else 0
        available = (
            value is not None and maximum > 0 and any(row['id'] == 3 for row in modes)
        )
        return dict(
            key=key,
            identity=key,
            provider='logitech',
            label='Logitech ' + item.name,
            connection='Wireless keyboard',
            value=0 if selected == 255 else int(value or 0),
            maximum=maximum,
            available=available,
            reason='' if available else 'Brightness is controlled by the keyboard.',
            effects=[],
            effect=-1,
            rgb=False,
            color='',
            lightingPath='',
            modes=modes,
            mode=selected,
        )

    def snapshot(self, native=(), force=False):
        try:
            if time.monotonic() >= self.next_scan:
                self.scan()
                self.next_scan = time.monotonic() + 15
            if force or time.monotonic() >= self.next_read:
                for key, (_, item) in self.devices.items():
                    try:
                        row = self.read(key, item)
                        if row:
                            self.rows[key] = row
                    except Exception:
                        if key in self.rows:
                            self.rows[key] = dict(
                                self.rows[key],
                                available=False,
                                reason='Keyboard is asleep or disconnected.',
                                modes=[],
                            )
                self.next_read = time.monotonic() + 2
        except ImportError:
            return []
        return list(self.rows.values())

    def change(self, row, request):
        if request.get('op') not in ('set', 'mode'):
            raise ValueError('This keyboard does not support color or effects.')
        from logitech_receiver import settings_templates

        key = row['key']
        entry = self.devices.get(key)
        if not entry:
            raise ValueError('The keyboard disconnected.')
        item = entry[1]
        if (
            not item.ping()
            or 'logitech:' + (item.unitId or item.serial) != row['identity']
        ):
            raise ValueError('The keyboard disconnected or changed.')
        current = self.read(key, item)
        mode = settings_templates.Backlight2.build(item)
        if request['op'] == 'mode':
            value = request.get('mode')
            if type(value) is not int or value not in [
                option['id'] for option in current['modes']
            ]:
                raise ValueError('This backlight mode is not supported.')
            if mode.write(value, save=False) is None:
                raise ValueError('Could not change keyboard backlight mode.')
        else:
            value = request.get('value')
            if (
                not current['available']
                or type(value) is not int
                or not 0 <= value <= current['maximum']
                or current['maximum'] != request.get('maximum')
            ):
                raise ValueError('Invalid or stale keyboard brightness level.')
            level = settings_templates.Backlight2Level.build(item)
            previous_mode = current['mode']
            previous_value = level.read(cached=False)
            try:
                # A slider adjustment is an explicit request for manual lighting.
                if (
                    level.write(value, save=False) is None
                    or mode.write(255 if value == 0 else 3, save=False) is None
                ):
                    raise ValueError('Could not change keyboard brightness.')
            except Exception:
                level.write(previous_value, save=False)
                mode.write(previous_mode, save=False)
                raise
        updated = self.read(key, item)
        if request['op'] == 'mode' and updated['mode'] != request['mode']:
            raise ValueError('The keyboard did not confirm the backlight mode.')
        if request['op'] == 'set' and updated['value'] != request['value']:
            raise ValueError('The keyboard did not confirm brightness.')
        self.rows[key] = updated
        self.next_read = time.monotonic() + 2

    def close(self):
        for obj in self.handles.values():
            try:
                obj.close()
            except Exception:
                pass
        self.handles.clear()
        self.devices.clear()
        self.rows.clear()
