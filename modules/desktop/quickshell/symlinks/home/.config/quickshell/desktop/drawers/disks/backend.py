"""Storage inventory and explicit UDisks actions; JSON secrets travel over stdin."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from gi.repository import Gio, GLib

BUS = 'org.freedesktop.UDisks2'
BASE = '/org/freedesktop/UDisks2'
BLOCK = BUS + '.Block'
DRIVE = BUS + '.Drive'
FS = BUS + '.Filesystem'
CRYPT = BUS + '.Encrypted'
ATA = DRIVE + '.Ata'
NVME = BUS + '.NVMe.Controller'


class StorageError(ValueError):
    pass


def text(value):
    return bytes(value).rstrip(b'\0').decode('utf-8', errors='replace')


def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def mounts(interfaces):
    return sorted(set(text(p) for p in interfaces.get(FS, {}).get('MountPoints', [])))


def protected(location):
    return location == '/' or any(
        location == p or location.startswith(p + '/')
        for p in ('/boot', '/efi', '/usr', '/var', '/home')
    )


def crypttab(interfaces):
    return any(
        kind == 'crypttab' for kind, _ in interfaces[BLOCK].get('Configuration', [])
    )


def slaves(device):
    # LVM/RAID mappings do not necessarily expose a UDisks Drive property.
    name = os.path.basename(device)
    if not name or name in ('.', '..'):
        return []
    try:
        return [p.name for p in (Path('/sys/class/block') / name / 'slaves').iterdir()]
    except OSError:
        return []


class Storage:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def objects(self):
        return self.bus.call_sync(
            BUS,
            BASE,
            'org.freedesktop.DBus.ObjectManager',
            'GetManagedObjects',
            None,
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        ).unpack()[0]

    def call(self, path, interface, method, password=None, options=None):
        options = options or {}
        args = (
            GLib.Variant('(sa{sv})', (password, options))
            if password is not None
            else GLib.Variant('(a{sv})', (options,))
        )
        try:
            return self.bus.call_sync(
                BUS,
                path,
                interface,
                method,
                args,
                None,
                Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
                120000,
                None,
            ).unpack()
        except GLib.Error as error:
            if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.TIMED_OUT):
                # UDisks keeps working, e.g. after a late authentication answer.
                raise StorageError(
                    'The storage service did not answer in time. Refresh to check the result.'
                ) from None
            code = (Gio.DBusError.get_remote_error(error) or '').rsplit('.', 1)[-1]
            messages = {
                'DeviceBusy': 'The device is busy. Close files and applications using it, then try again.',
                'NotAuthorized': 'Permission was denied.',
                'NotAuthorizedCanObtain': 'Authentication is required. Check that a desktop authentication agent is running.',
                'NotAuthorizedDismissed': 'Authentication was cancelled.',
                'WouldWakeup': 'The drive is asleep. Health was not refreshed to avoid waking it.',
                'AlreadyMounted': 'The volume is already mounted. Refresh and try again.',
                'NotMounted': 'The volume is no longer mounted.',
                'NotSupported': 'This operation is not supported by the device.',
            }
            # Never echo D-Bus diagnostic text: an unlock failure may contain secrets.
            raise StorageError(
                messages.get(
                    code,
                    'Unlock failed. Check the passphrase and try again.'
                    if method == 'Unlock'
                    else 'The storage operation failed. Refresh and try again.',
                )
            ) from None

    def drive_paths(self, objects, path, seen=None):
        seen = set() if seen is None else seen
        if path in seen:
            return set()
        seen.add(path)
        block = objects.get(path, {}).get(BLOCK, {})
        drive = block.get('Drive', '/')
        if drive != '/' and DRIVE in objects.get(drive, {}):
            return {drive}
        backing = block.get('CryptoBackingDevice', '/')
        if backing != '/':
            return self.drive_paths(objects, backing, seen)
        by_name = {
            os.path.basename(text(v[BLOCK].get('Device', []))): p
            for p, v in objects.items()
            if BLOCK in v
        }
        result = set()
        for name in slaves(text(block.get('Device', []))):
            if name in by_name:
                result.update(self.drive_paths(objects, by_name[name], seen))
        return result

    def drive_identity(self, objects, path):
        props = objects[path][DRIVE]
        return token(
            [
                path,
                [
                    props.get(k)
                    for k in (
                        'Id',
                        'Serial',
                        'WWN',
                        'TimeDetected',
                        'TimeMediaDetected',
                        'Size',
                    )
                ],
            ]
        )

    def block_identity(self, objects, path):
        props = objects[path][BLOCK]
        return token(
            [
                path,
                [
                    props.get(k)
                    for k in ('DeviceNumber', 'IdUUID', 'Size', 'CryptoBackingDevice')
                ],
                sorted(
                    self.drive_identity(objects, p)
                    for p in self.drive_paths(objects, path)
                ),
            ]
        )

    def drive_record(self, objects, path):
        props = objects[path][DRIVE]
        label = (
            ' '.join(str(props.get(k, '')).strip() for k in ('Vendor', 'Model')).strip()
            or 'Storage device'
        )
        return dict(
            key=path,
            identity=self.drive_identity(objects, path),
            label=label,
            size=props.get('Size', 0),
            connection=props.get('ConnectionBus', ''),
            removable=bool(props.get('Removable') or props.get('MediaRemovable')),
            healthSupported=bool(
                NVME in objects[path]
                or (
                    objects[path].get(ATA, {}).get('SmartSupported')
                    and objects[path][ATA].get('SmartEnabled')
                )
            ),
        )

    def volume_record(self, objects, path):
        interfaces = objects[path]
        block = interfaces[BLOCK]
        effective = path
        encrypted = CRYPT in interfaces
        if encrypted:
            effective = interfaces[CRYPT].get('CleartextDevice', '/')
        locked = encrypted and effective == '/'
        target = objects.get(effective, {}) if not locked else {}
        target_block = target.get(BLOCK, block)
        locations = mounts(target)
        size = target_block.get('Size', 0)
        capacity = free = used = None
        capacity_error = ''
        if locations:
            try:
                usage = os.statvfs(locations[0])
                capacity = usage.f_blocks * usage.f_frsize
                free = max(0, usage.f_bavail * usage.f_frsize)
                used = max(0, (usage.f_blocks - usage.f_bfree) * usage.f_frsize)
            except OSError:
                capacity_error = 'Free space is unavailable.'
        device = text(block.get('PreferredDevice', block.get('Device', [])))
        label = (
            target_block.get('IdLabel')
            or block.get('IdLabel')
            or ('System' if '/' in locations else os.path.basename(device))
            or 'Volume'
        )
        reason = 'System volume' if any(protected(p) for p in locations) else ''
        can_unmount = bool(locations) and not reason
        # Like Dolphin and GNOME; boot-managed mappings may have no passphrase.
        locks = can_unmount and effective != path and not crypttab(interfaces)
        return dict(
            key=path,
            identity=self.block_identity(objects, path),
            label=label,
            device=device,
            fs=target_block.get('IdType', ''),
            size=size,
            capacity=capacity,
            free=free,
            used=used,
            capacityError=capacity_error,
            mounts=locations,
            encrypted=encrypted,
            locked=locked,
            canMount=FS in target and not locations,
            canUnmount=can_unmount,
            locksOnUnmount=locks,
            reason=reason,
            target=effective,
        )

    def snapshot(self, objects=None):
        objects = self.objects() if objects is None else objects
        blocks = {p: v for p, v in objects.items() if BLOCK in v}
        associations = {p: self.drive_paths(objects, p) for p in blocks}
        records = {
            p: self.drive_record(objects, p) for p, v in objects.items() if DRIVE in v
        }
        volumes = []
        for path, interfaces in blocks.items():
            block = interfaces[BLOCK]
            locations = mounts(interfaces)
            clear = interfaces.get(CRYPT, {}).get('CleartextDevice', '/')
            if (
                block.get('HintIgnore')
                and not locations
                and not mounts(objects.get(clear, {}))
            ):
                continue
            if block.get('CryptoBackingDevice', '/') != '/' and FS in interfaces:
                # The encrypted parent represents a directly contained filesystem.
                continue
            if CRYPT in interfaces:
                clear = interfaces[CRYPT].get('CleartextDevice', '/')
                if clear != '/' and FS not in objects.get(clear, {}):
                    continue  # e.g. an unlocked LUKS container holding LVM
            elif FS not in interfaces:
                continue
            row = self.volume_record(objects, path)
            drives = associations[path]
            group = next(iter(drives)) if len(drives) == 1 else 'other'
            row['drive'] = group
            volumes.append(row)
        if any(v['drive'] == 'other' for v in volumes):
            records['other'] = dict(
                key='other',
                identity='',
                label='Other volumes',
                size=0,
                connection='',
                removable=False,
                healthSupported=False,
            )
        for key, drive in records.items():
            drive['volumes'] = sorted(
                [v for v in volumes if v['drive'] == key],
                key=lambda v: (not bool(v['mounts']), v['device']),
            )
        return dict(
            drives=sorted(records.values(), key=lambda d: (d['removable'], d['label'])),
            editorAvailable=bool(shutil.which('partitionmanager')),
            analyzerAvailable=bool(shutil.which('filelight')),
        )

    def validate(self, request, objects, drive=False):
        path = request.get('key')
        interface = DRIVE if drive else BLOCK
        if interface not in objects.get(path, {}):
            raise StorageError('The device was disconnected. Refresh and try again.')
        identity = (
            self.drive_identity(objects, path)
            if drive
            else self.block_identity(objects, path)
        )
        if identity != request.get('identity'):
            raise StorageError('The device changed. Refresh before trying again.')
        return path

    def health(self, objects, path):
        record = self.drive_record(objects, path)
        if not record['healthSupported']:
            raise StorageError(
                'Health reporting is not supported or enabled for this drive.'
            )
        interface = NVME if NVME in objects[path] else ATA
        options = {'nowakeup': GLib.Variant('b', True)} if interface == ATA else {}
        self.call(path, interface, 'SmartUpdate', options=options)
        updated = self.objects()
        self.validate(dict(key=path, identity=record['identity']), updated, drive=True)
        props = updated[path][interface]
        if not props.get('SmartUpdated'):
            raise StorageError('No health information is available yet.')
        nvme = interface == NVME
        warning = props.get('SmartCriticalWarning', []) if nvme else []
        bad = props.get('SmartNumBadSectors', 0) if not nvme else None
        failing = (
            bool(warning)
            if nvme
            else bool(
                props.get('SmartFailing')
                or bad
                or props.get('SmartNumAttributesFailing', 0)
            )
        )
        temperature = props.get('SmartTemperature', 0)
        return dict(
            key=path,
            identity=record['identity'],
            warning=failing,
            summary=('Health warning' if failing else 'No problems reported'),
            temperature=round(temperature - 273.15) if temperature > 0 else None,
            hours=props.get('SmartPowerOnHours', 0)
            if nvme
            else props.get('SmartPowerOnSeconds', 0) // 3600,
            badSectors=bad,
            detail=', '.join(warning),
            updated=props['SmartUpdated'],
        )

    def lock(self, request):
        current = self.objects()
        path = self.validate(request, current)
        clear = current[path].get(CRYPT, {}).get('CleartextDevice', '/')
        if clear == '/':
            return
        if mounts(current.get(clear, {})):
            raise StorageError('Unmounted, but the volume is still mounted elsewhere.')
        try:
            self.call(path, CRYPT, 'Lock')
        except StorageError as error:
            raise StorageError('Unmounted, but not locked. ' + str(error)) from None

    def handle(self, request):
        op = request.get('op')
        if op == 'status':
            return {}
        if op not in ('mount', 'unmount', 'unlock', 'health'):
            raise StorageError('Unsupported storage action.')
        objects = self.objects()
        path = self.validate(request, objects, drive=op == 'health')
        if op == 'health':
            return dict(health=self.health(objects, path))
        row = self.volume_record(objects, path)
        if op == 'unlock':
            password = request.get('password', '')
            if (
                not row['locked']
                or not isinstance(password, str)
                or not password
                or '\0' in password
            ):
                raise StorageError('Enter a passphrase for a locked volume.')
            self.call(path, CRYPT, 'Unlock', password=password)
        elif op == 'mount':
            if not row['canMount']:
                raise StorageError(
                    'This volume cannot be mounted. Refresh and try again.'
                )
            self.call(row['target'], FS, 'Mount')
        elif op == 'unmount':
            if not row['canUnmount']:
                raise StorageError(row['reason'] or 'This volume is not mounted.')
            self.call(row['target'], FS, 'Unmount')
            if row['locksOnUnmount']:
                self.lock(request)
        return {}

    def response(self, request):
        result = dict(ok=True, error='')
        try:
            result.update(self.handle(request))
        except StorageError as error:
            result.update(ok=False, error=str(error))
        except Exception:
            result.update(
                ok=False,
                error='Could not contact the storage service. Check that UDisks is installed and running.',
            )
        try:
            result['data'] = self.snapshot()
        except Exception:
            result.update(
                ok=False,
                error=result['error']
                or 'Could not read storage devices. Try refreshing.',
            )
        return result


def main():
    storage = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError()
            storage = storage or Storage()
            result = storage.response(request)
        except Exception:
            result = dict(
                ok=False,
                error='Could not contact the storage service. Check that UDisks is installed and running.',
            )
        print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
