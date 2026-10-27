#!/usr/bin/env bash
set -Eeuo pipefail
# Archinstall generates the device-specific command line and UKI presets.
# Preserve its initramfs hooks and disk-unlock parameters.
jq -e '.bootloader_config | .bootloader == "Efistub" and .uki == true' \
    /run/system-configuration.json > /dev/null || {
    echo 'Boot configuration requires EFI stub boot with UKIs.' >&2
    exit 1
}
python3 - /etc/kernel/cmdline /etc/mkinitcpio.d << 'PY_BOOT'
from pathlib import Path
import os
import re
import sys
import tempfile

cmdline, presets = map(Path, sys.argv[1:])
active_presets = list(presets.glob('*.preset'))
if not active_presets or not any(re.search(r'^\w+_uki=', p.read_text(), re.M) for p in active_presets):
    sys.exit('No UKI preset found; configure UKIs before applying boot settings.')
parameters = cmdline.read_text().split()
if not any(p.startswith('root=') for p in parameters):
    sys.exit('Kernel command line has no root device.')
# Archinstall enables mkinitcpio's stock Arch splash. Leave firmware graphics
# visible instead; preserve custom splash paths and other preset options.
for preset in active_presets:
    original = preset.read_text()
    updated = re.sub(
        r'(?m)^(\w+_options=)(["\'])--splash /usr/share/systemd/bootctl/splash-arch\.bmp\2$',
        r'\1\2\2', original)
    if updated != original:
        preset.write_text(updated)
settings = {
    'mitigations': 'mitigations=off',
    'quiet': 'quiet',
    'loglevel': 'loglevel=3',
    'systemd.show_status': 'systemd.show_status=auto',
    'rd.systemd.show_status': 'rd.systemd.show_status=auto',
    'udev.log_level': 'udev.log_level=3',
    'rd.udev.log_level': 'rd.udev.log_level=3',
    'vt.global_cursor_default': 'vt.global_cursor_default=0',
}
result = []
for parameter in parameters:
    if parameter.split('=', 1)[0] not in settings:
        result.append(parameter)
result.extend(settings.values())
# Do not replace the active command line until all checks have passed.
with tempfile.NamedTemporaryFile(mode='w', dir=cmdline.parent, delete=False) as temporary:
    target = Path(temporary.name)
    try:
        temporary.write(' '.join(result) + '\n')
        temporary.close()
        os.chmod(target, 0o644)
        target.replace(cmdline)
    finally:
        target.unlink(missing_ok=True)
PY_BOOT
# Rebuild the UKIs with the updated kernel parameters and existing hooks.
mkinitcpio -P
