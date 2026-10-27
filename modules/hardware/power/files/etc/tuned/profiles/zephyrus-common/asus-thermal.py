#!/usr/bin/python3 -I
"""TuneD's one-shot delegation to asusd; never a resident thermal controller."""

from pathlib import Path
import os
import sys

SYS = Path('/sys')
SERVICE = 'xyz.ljones.Asusd'
PATH = '/xyz/ljones'
PLATFORM = 'xyz.ljones.Platform'
FANS = 'xyz.ljones.FanCurves'
ARMOURY = 'xyz.ljones.AsusArmoury'
PROPERTIES = 'org.freedesktop.DBus.Properties'
TEMPS = {
    'CPU': (20, 40, 50, 55, 60, 65, 70, 85),
    'GPU': (20, 50, 60, 65, 70, 75, 80, 85),
}
CURVES = {
    'CPU': (51, 102, 166, 204, 230, 242, 255, 255),
    'GPU': (56, 77, 115, 153, 191, 217, 242, 255),
}
DAILY_TEMPS = (20, 50, 60, 65, 70, 75, 80, 85)
DAILY_CURVE = (0, 0, 0, 115, 153, 191, 230, 255)
PLATFORMS = {'balanced': 0, 'performance': 1, 'quiet': 2}


def setting(name):
    # TuneD exports the merged profile's variables for start/stop/verify.
    # No active-profile file race and no second copy of the power targets.
    value = os.environ.get('TUNED_' + name)
    if value is None:
        raise RuntimeError('Thermal policy must be invoked through TuneD')
    return value


def fan_policy():
    platform = PLATFORMS[setting('asus_platform')]
    if platform == 1:
        return platform, TEMPS, CURVES
    return (
        platform,
        {name: DAILY_TEMPS for name in CURVES},
        {name: DAILY_CURVE for name in CURVES},
    )


def read(path):
    return path.read_text().strip()


class Bus:
    def __init__(self):
        from gi.repository import Gio

        self.connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def call(self, interface, method, signature, values, path=PATH):
        from gi.repository import Gio, GLib

        result = self.connection.call_sync(
            SERVICE,
            path,
            interface,
            method,
            GLib.Variant(signature, values),
            None,
            Gio.DBusCallFlags.NO_AUTO_START,
            3000,
            None,
        )
        return result.unpack()[0] if result.n_children() else None

    def get(self, interface, name, path=PATH):
        return self.call(PROPERTIES, 'Get', '(ss)', (interface, name), path)

    def set(self, interface, name, kind, value, path=PATH):
        from gi.repository import GLib

        self.call(
            PROPERTIES,
            'Set',
            '(ssv)',
            (interface, name, GLib.Variant(kind, value)),
            path,
        )


def targets(bus):
    result = {}
    for name, option in [
        ('ppt_apu_sppt', 'asus_apu_limit'),
        ('ppt_platform_sppt', 'asus_platform_limit'),
    ]:
        target = int(setting(option))
        path = PATH + '/asus_armoury/' + name
        low, high = (bus.get(ARMOURY, prop, path) for prop in ('MinValue', 'MaxValue'))
        if not isinstance(low, int) or not isinstance(high, int) or not 0 < low <= high:
            raise RuntimeError('Invalid firmware limits: ' + name)
        # DC firmware exposes lower maxima. Never bypass its supported range.
        result[name] = min(high, max(low, target))
    return result


def verify(bus):
    platform, temperatures, curves = fan_policy()
    if bus.get(PLATFORM, 'PlatformProfile') != platform:
        raise RuntimeError('Selected platform was not applied')
    if not bus.get(PLATFORM, 'EnablePptGroup'):
        raise RuntimeError('ASUS power limits are not enabled')
    for name, target in targets(bus).items():
        if bus.get(ARMOURY, 'CurrentValue', PATH + '/asus_armoury/' + name) != target:
            raise RuntimeError('ASUS power-limit readback failed: ' + name)
    chips = [
        p
        for p in (SYS / 'class/hwmon').glob('*')
        if read(p / 'name') == 'asus_custom_fan_curve'
    ]
    if len(chips) != 1:
        raise RuntimeError('ASUS fan control is unavailable')
    chip = chips[0]
    for number, name in enumerate(('CPU', 'GPU'), 1):
        if read(chip / f'pwm{number}_enable') != '1':
            raise RuntimeError(name + ' fan curve is not active')
        for point, (temp, pwm) in enumerate(zip(temperatures[name], curves[name]), 1):
            if read(chip / f'pwm{number}_auto_point{point}_temp') != str(temp) or read(
                chip / f'pwm{number}_auto_point{point}_pwm'
            ) != str(pwm):
                raise RuntimeError(name + ' fan-curve readback failed')


def apply(bus):
    if 'GA402RK' not in read(SYS / 'devices/virtual/dmi/id/product_name'):
        raise RuntimeError('This thermal policy is measured only on GA402RK')
    platform, temperatures, curves = fan_policy()
    if bus.get(PLATFORM, 'PlatformProfile') != platform:
        raise RuntimeError('Refusing thermal changes before platform selection')
    for name, pwm in curves.items():
        bus.call(
            FANS,
            'SetFanCurve',
            '(u(s(yyyyyyyy)(yyyyyyyy)b))',
            (platform, (name, pwm, temperatures[name], True)),
        )
    bus.call(FANS, 'SetFanCurvesEnabled', '(ub)', (platform, True))
    bus.set(PLATFORM, 'EnablePptGroup', 'b', True)
    for name, target in targets(bus).items():
        bus.set(ARMOURY, 'CurrentValue', 'i', target, PATH + '/asus_armoury/' + name)
    verify(bus)


def restore(bus):
    # Called before TuneD rolls the platform back. Disabling the tuning group
    # asks asusd to restore firmware defaults; it also reasserts that platform.
    platform = bus.get(PLATFORM, 'PlatformProfile')
    if platform not in PLATFORMS.values():
        raise RuntimeError('Cannot restore an unsupported ASUS platform')
    bus.set(PLATFORM, 'EnablePptGroup', 'b', False)
    bus.call(FANS, 'SetFanCurvesEnabled', '(ub)', (platform, False))


def fail_safe():
    # TuneD remains the owner of these controls, including its failure path.
    # The drawer and `tuned-adm verify` expose the resulting policy mismatch.
    for path, value in [
        ('devices/system/cpu/cpufreq/boost', '0'),
        ('firmware/acpi/platform_profile', 'quiet'),
    ]:
        try:
            (SYS / path).write_text(value)
        except OSError:
            pass


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action not in ('start', 'stop', 'verify'):
        raise SystemExit('Expected start, stop or verify')
    try:
        bus = Bus()
        {'start': apply, 'stop': restore, 'verify': verify}[action](bus)
    except Exception as error:
        if action == 'start':
            fail_safe()
        raise SystemExit(str(error))


if __name__ == '__main__':
    main()
