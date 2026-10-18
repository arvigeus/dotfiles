#!/usr/bin/env python3
"""Read-only telemetry, UPower and power-profiles API; optional device adapters."""
import importlib.util
import configparser
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import sys
import time

PROVIDERS = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'devices/power/backends'
PROC = Path('/proc')
SYS = Path('/sys')
TUNED = Path('/etc/tuned')
PROPERTIES = 'org.freedesktop.DBus.Properties'
UPOWER = 'org.freedesktop.UPower'
DEVICE = UPOWER + '.Device'
POWER_PATH = '/org/freedesktop/UPower'
PROFILE_APIS = [('org.freedesktop.UPower.PowerProfiles', '/org/freedesktop/UPower/PowerProfiles'),
                ('net.hadess.PowerProfiles', '/net/hadess/PowerProfiles')]


def number(value, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if value >= minimum and (maximum is None or value <= maximum) else None


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def reading(path, scale=1):
    try:
        return number(float(read(path)) / scale)
    except ValueError:
        return None


class Bus:
    def __init__(self):
        self.connection = None

    def call(self, service, path, interface, method, signature=None, args=()):
        from gi.repository import Gio, GLib
        if self.connection is None:
            self.connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        result = self.connection.call_sync(service, path, interface, method,
            GLib.Variant(signature, args) if signature else None, None,
            Gio.DBusCallFlags.NO_AUTO_START, 2000, None)
        return result.unpack()[0] if result.n_children() else None

    def properties(self, service, path, interface):
        return self.call(service, path, PROPERTIES, 'GetAll', '(s)', (interface,))

    def set(self, service, path, interface, name, kind, value):
        from gi.repository import GLib
        self.call(service, path, PROPERTIES, 'Set', '(ssv)', (interface, name, GLib.Variant(kind, value)))

    def owner(self, service):
        return self.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                         'GetNameOwner', '(s)', (service,))


def battery_record(path, props):
    state = props.get('State', 0)
    full, design = number(props.get('EnergyFull'), 0.001), number(props.get('EnergyFullDesign'), 0.001)
    return dict(key=path, label=props.get('Model') or props.get('NativePath') or 'System battery',
                vendor=props.get('Vendor', ''), percentage=number(props.get('Percentage'), 0, 100),
                state=state, energy=number(props.get('Energy')), full=full, design=design,
                health=100 * full / design if full is not None and design is not None else None,
                cycles=number(props.get('ChargeCycles')), rate=number(props.get('EnergyRate')),
                seconds=number(props.get('TimeToFull' if state == 1 else 'TimeToEmpty'), 1) if state in (1, 2) else None)


def battery_snapshot(bus):
    try:
        props = bus.properties(UPOWER, POWER_PATH, UPOWER)
        paths = bus.call(UPOWER, POWER_PATH, UPOWER, 'EnumerateDevices')
        batteries, peripherals = [], []
        for path in paths:
            device = bus.properties(UPOWER, path, DEVICE)
            if device.get('Type') == 2 and device.get('PowerSupply') and device.get('IsPresent'):
                batteries.append(battery_record(path, device))
            elif device.get('IsPresent') and not device.get('PowerSupply') and device.get('Type', 0) > 1:
                row = battery_record(path, device)
                row.update(kind=device.get('Type'), level=device.get('BatteryLevel', 0))
                peripherals.append(row)
        # UPower's composite display device accounts for multiple batteries and
        # their charging order; never average percentages or invent time estimates.
        display = bus.properties(UPOWER, POWER_PATH + '/devices/DisplayDevice', DEVICE) if batteries else {}
        summary = battery_record('summary', display) if batteries else None
        return dict(available=True, error='', onBattery=props.get('OnBattery'), batteries=batteries, summary=summary, peripherals=peripherals)
    except Exception as error:
        return dict(available=False, error='Battery service unavailable: ' + str(error), onBattery=None, batteries=[], summary=None)


def profile_snapshot(bus):
    for service, path in PROFILE_APIS:
        try:
            props = bus.properties(service, path, service)
            advertised = {row.get('Profile') for row in props.get('Profiles', [])}
            choices = [name for name in ('performance', 'balanced', 'power-saver') if name in advertised]
            if not choices:
                continue
            warnings = [props.get('PerformanceDegraded', ''), policy_warning()]
            return dict(available=True, service=service, path=path, identity=bus.owner(service),
                        active=props.get('ActiveProfile', ''), choices=choices,
                        degraded='; '.join(item for item in warnings if item),
                        inhibited=props.get('PerformanceInhibited', ''),
                        holds=[dict(profile=row.get('Profile', ''), application=row.get('ApplicationId', ''),
                                    reason=row.get('Reason', '')) for row in props.get('ActiveProfileHolds', [])], error='')
        except Exception:
            continue
    return dict(available=False, active='', choices=[], degraded='', inhibited='', holds=[], error='Power profiles are unavailable.')


def policy_config():
    name = read(TUNED / 'active_profile')
    config = configparser.ConfigParser(interpolation=None)
    if name not in ('zephyrus-balanced', 'zephyrus-battery', 'zephyrus-powersave', 'zephyrus-powersave-battery',
                    'zephyrus-performance', 'zephyrus-performance-battery'):
        return name, config
    directory = TUNED / 'profiles'
    parent = {'zephyrus-performance-battery': 'zephyrus-performance', 'zephyrus-powersave-battery': 'zephyrus-powersave'}.get(name)
    parents = ['zephyrus-common'] + ([parent] if parent else [])
    config.read([directory / p / 'tuned.conf' for p in parents + [name]])
    return name, config


def policy_warning():
    """Check applied hardware state as well as the requested PPD label."""
    name, config = policy_config()
    if name.startswith('zephyrus-') and any(not config.has_option(section, option) for section, option in (
            ('acpi', 'platform_profile'), ('cpu', 'energy_performance_preference'),
            ('sysfs', '/sys/devices/system/cpu/cpufreq/boost'))):
        return 'Installed power policy is incomplete'
    mismatches = []
    for section, option, path, label in [
            ('acpi', 'platform_profile', SYS / 'firmware/acpi/platform_profile', 'platform'),
            ('sysfs', '/sys/devices/system/cpu/cpufreq/boost', SYS / 'devices/system/cpu/cpufreq/boost', 'CPU boost')]:
        expected = config.get(section, option, fallback=None)
        if expected is not None and read(path) != expected:
            mismatches.append(label)
    for option, attribute, label in [
            ('energy_performance_preference', 'energy_performance_preference', 'CPU energy preference'),
            ('governor', 'scaling_governor', 'CPU governor')]:
        expected = config.get('cpu', option, fallback=None)
        policies = list((SYS / 'devices/system/cpu/cpufreq').glob('policy*/' + attribute))
        if expected and any(read(path) != expected for path in policies):
            mismatches.append(label)
    ceiling = config.get('sysfs_cpu_limits', '/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq', fallback='')
    if ceiling and any(
            read(path / 'scaling_max_freq') != (ceiling if ceiling.isdigit() else read(path / 'cpuinfo_max_freq'))
            for path in (SYS / 'devices/system/cpu/cpufreq').glob('policy*')):
        mismatches.append('CPU frequency ceiling')
    return 'Policy not fully applied: ' + ', '.join(mismatches) if mismatches else ''


def thermal_warning():
    """Detailed drawer readback; no periodic closed-drawer WMI/GPU probing."""
    name, config = policy_config()
    if not name.startswith('zephyrus-'):
        return ''
    try:
        for attribute, option in [('ppt_apu_sppt', 'asus_apu_limit'), ('ppt_platform_sppt', 'asus_platform_limit')]:
            path = SYS / 'class/firmware-attributes/asus-armoury/attributes' / attribute
            target = min(int(read(path / 'max_value')), max(int(read(path / 'min_value')), config.getint('variables', option)))
            if int(read(path / 'current_value')) != target:
                return 'Selected power limit is not applied'
        chips = [p for p in (SYS / 'class/hwmon').glob('*') if read(p / 'name') == 'asus_custom_fan_curve']
        if len(chips) != 1 or any(read(chips[0] / f'pwm{fan}_enable') != '1' for fan in (1, 2)):
            return 'Selected fan policy is not active'
    except (ValueError, configparser.Error):
        return 'Selected thermal policy could not be verified'
    return ''


def sleeping(path):
    """Check runtime PM before reading optional device telemetry."""
    return read(path / 'power/runtime_status') in ('suspended', 'suspending')


@lru_cache(maxsize=1)
def pci_names():
    """Use the local PCI database without probing or opening a graphics device."""
    names, vendor = {}, ''
    for line in read(Path('/usr/share/hwdata/pci.ids')).splitlines():
        if re.match(r'^[0-9a-f]{4}  ', line):
            vendor = line[:4]
        elif re.match(r'^\t[0-9a-f]{4}  ', line):
            names[(vendor, line[1:5])] = line[7:].strip()
    return names


class Sampler:
    def __init__(self):
        self.previous = None
        self.sampled_at = None
        self.gpu_cache = {}

    def snapshot(self):
        now = time.monotonic()
        usage = None
        try:
            # guest and guest_nice are already included in user and nice.
            counters = [int(part) for part in read(PROC / 'stat').splitlines()[0].split()[1:9]]
            total, idle = sum(counters), counters[3] + counters[4]
            if self.previous and self.sampled_at is not None and 0 < now - self.sampled_at < 15:
                elapsed = total - self.previous[0]
                if elapsed > 0:
                    usage = number(100 * (elapsed - (idle - self.previous[1])) / elapsed, 0, 100)
            self.previous, self.sampled_at = (total, idle), now
        except (ValueError, IndexError):
            self.previous = None
        info = read(PROC / 'cpuinfo')
        name = re.search(r'^(?:model name|Hardware)\s*:\s*(.+)$', info, re.M)
        frequencies = [value for path in (SYS / 'devices/system/cpu/cpufreq').glob('policy*/scaling_cur_freq')
                       if (value := reading(path, 1000000)) is not None]
        temperatures, fans = [], []
        for hwmon in sorted((SYS / 'class/hwmon').glob('*')):
            device = (hwmon / 'device').resolve()
            if any(sleeping(parent) for parent in (device, *device.parents) if parent != SYS):
                continue
            chip = read(hwmon / 'name')
            # DRM sensor reads can reset a discrete GPU's autosuspend timer.
            # Collect them only through the separately paced GPU sampler.
            if chip == 'amdgpu':
                continue
            if chip in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal'):
                temperatures += [value for path in hwmon.glob('temp*_input')
                                 if (value := reading(path, 1000)) is not None and value < 150]
            for path in sorted(hwmon.glob('fan*_input')):
                value = reading(path)
                if value is not None:
                    label = read(path.with_name(path.name.replace('_input', '_label'))) or chip + ' ' + path.stem.split('_')[0]
                    fans.append(dict(key=str(path), label={'cpu_fan': 'CPU fan', 'gpu_fan': 'GPU fan'}.get(label, label), rpm=value))
        memory = {}
        for line in read(PROC / 'meminfo').splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    memory[parts[0].rstrip(':')] = int(parts[1]) * 1024
                except ValueError:
                    pass
        total, available = memory.get('MemTotal'), memory.get('MemAvailable')
        swap, swap_free = memory.get('SwapTotal'), memory.get('SwapFree')
        pressure = re.search(r'^some avg10=([\d.]+)', read(PROC / 'pressure/memory'))
        return dict(cpu=dict(label=name.group(1) if name else 'CPU', usage=usage,
                             frequency=sum(frequencies) / len(frequencies) if frequencies else None,
                             temperature=max(temperatures) if temperatures else None,
                             load=read(PROC / 'loadavg').split()[:3]),
                    memory=dict(total=total, used=max(0, total - available) if total is not None and available is not None else None,
                                swapTotal=swap, swapUsed=max(0, swap - swap_free) if swap is not None and swap_free is not None else None,
                                pressure=number(float(pressure.group(1)), 0, 100) if pressure else None),
                    gpus=self.gpus(), fans=fans)

    def gpus(self):
        rows = []
        now = time.monotonic()
        for card in sorted((SYS / 'class/drm').glob('card*')):
            if not re.fullmatch(r'card\d+', card.name):
                continue
            device = card / 'device'
            vendor = read(device / 'vendor')
            brand = {'0x1002': 'AMD', '0x10de': 'NVIDIA', '0x8086': 'Intel'}.get(vendor, 'Graphics')
            driver = (device / 'driver').resolve().name if (device / 'driver').exists() else ''
            suspended = sleeping(device)
            identifier = read(device / 'device')
            label = read(device / 'product_name') or pci_names().get((vendor.removeprefix('0x'), identifier.removeprefix('0x')))
            row = dict(key=str(device.resolve()), label=label or brand + ' GPU · ' + identifier,
                       driver=driver, sleeping=suspended, usage=None, used=None, total=None, temperature=None, junction=None, memoryTemperature=None, sampleAge=None)
            # No NVML, nvidia-smi or render-node opens: discovery and missing
            # counters must never wake a discrete GPU.
            previous = self.gpu_cache.get(row['key'])
            delay = reading(device / 'power/autosuspend_delay_ms') or 0
            interval = max(8, delay / 1000 + 1) if read(device / 'power/control') == 'auto' else 2
            if suspended:
                self.gpu_cache.pop(row['key'], None)
            elif previous and 0 <= now - previous[0] < interval:
                row.update(previous[1], sampleAge=now - previous[0])
            else:
                row.update(usage=number(reading(device / 'gpu_busy_percent'), 0, 100),
                           used=reading(device / 'mem_info_vram_used'), total=reading(device / 'mem_info_vram_total'))
                temps = [value for path in (device / 'hwmon').glob('hwmon*/temp1_input')
                         if (value := reading(path, 1000)) is not None and value < 150]
                row['temperature'] = max(temps) if temps else None
                for sensor, key in [('junction', 'junction'), ('mem', 'memoryTemperature')]:
                    for path in (device / 'hwmon').glob('hwmon*/temp*_label'):
                        if read(path) == sensor:
                            row[key] = reading(path.with_name(path.name.replace('_label', '_input')), 1000)
                fields = ('usage', 'used', 'total', 'temperature', 'junction', 'memoryTemperature')
                self.gpu_cache[row['key']] = (now, {key: row[key] for key in fields})
                row['sampleAge'] = 0
            rows.append(row)
        return rows


class Controller:
    def __init__(self):
        self.bus = Bus()
        self.sampler = Sampler()
        self.providers = {}
        self.provider_errors = []
        for path in sorted(PROVIDERS.glob('*.py')):
            try:
                spec = importlib.util.spec_from_file_location('power_' + path.stem, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.providers[path.stem] = module.Provider(self.bus)
            except Exception as error:
                self.provider_errors.append(path.stem + ': ' + str(error))

    def hardware(self):
        rows, errors = [], list(self.provider_errors)
        for key, provider in self.providers.items():
            try:
                row = provider.snapshot()
                if row:
                    rows.append(dict(row, key=key))
            except Exception as error:
                errors.append(key + ': ' + str(error))
        return rows, errors

    def snapshot(self, details=False):
        rows, errors = self.hardware()
        profiles = profile_snapshot(self.bus)
        if details and (warning := thermal_warning()):
            profiles['degraded'] = '; '.join(filter(None, (profiles.get('degraded'), warning)))
        return dict(battery=battery_snapshot(self.bus), profiles=profiles, hardware=rows,
                    hardwareErrors=errors, metrics=self.sampler.snapshot() if details else None)

    def handle(self, request):
        op = request.get('op')
        if op == 'status':
            return self.snapshot(request.get('details') is True)
        if op == 'profile':
            current = profile_snapshot(self.bus)
            target = request.get('value')
            if not current['available'] or any(request.get(key) != current.get(key) for key in ('service', 'identity', 'active')):
                raise ValueError('The power profile changed. Refresh and try again.')
            if target not in current['choices'] or (target == 'performance' and current['inhibited']):
                raise ValueError('This power profile is not currently available.')
            self.bus.set(current['service'], current['path'], current['service'], 'ActiveProfile', 's', target)
            # Read back daemon state; do not optimistically claim success.
            after = profile_snapshot(self.bus)
            if after.get('identity') != current['identity'] or after['active'] != target:
                raise ValueError('The power service did not confirm the requested profile.')
        elif op == 'charge-limit':
            key = request.get('key')
            if key not in self.providers:
                raise ValueError('The battery care controller is unavailable.')
            self.providers[key].change(request)
        else:
            raise ValueError('Unknown power operation.')
        return self.snapshot(request.get('details') is True)


def main():
    controller = Controller()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            data = controller.handle(request)
            result = dict(ok=True, data=data, error='')
        except Exception as error:
            result = dict(ok=False, error=str(error))
        print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
