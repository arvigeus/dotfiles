#!/usr/bin/env bash
set -Eeuo pipefail
# Archinstall generates the device-specific command line and UKI presets.
# Adapt its password-based encryption parameters to systemd early userspace.
jq -e '.bootloader_config | .bootloader == "Efistub" and .uki == true' \
    /run/system-configuration.json >/dev/null || {
    echo 'Boot configuration requires EFI stub boot with UKIs.' >&2; exit 1;
}
python3 - /etc/kernel/cmdline /etc/mkinitcpio.d <<'PY_BOOT'
from pathlib import Path
import os
import re
import sys
import tempfile

cmdline, presets = map(Path, sys.argv[1:])
# Explicit preset configs bypass mkinitcpio.conf.d and would ignore our hooks.
active_presets = list(presets.glob('*.preset'))
if not active_presets or not any(re.search(r'^\w+_uki=', p.read_text(), re.M) for p in active_presets):
    sys.exit('No UKI preset found; configure UKIs before applying boot settings.')
if any(re.search(r'^\s*\w+_config=', p.read_text(), re.M) for p in active_presets):
    sys.exit('Remove explicit *_config settings from mkinitcpio presets to enable drop-ins.')

parameters = cmdline.read_text().split()
if not any(p.startswith('root=') for p in parameters):
    sys.exit('Kernel command line has no root device.')
quiet = {
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
    if parameter.startswith('cryptdevice='):
        match = re.fullmatch(r'cryptdevice=UUID=([0-9a-fA-F-]{36}):([a-zA-Z0-9_-]+)', parameter)
        if not match:
            sys.exit(f'Unsupported archinstall encryption parameter: {parameter}')
        parameter = f'rd.luks.name={match[1]}={match[2]}'
    if parameter.split('=', 1)[0] not in quiet:
        result.append(parameter)
result.extend(quiet.values())
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
# Rebuild the UKIs with the updated command line and systemd hooks.
mkinitcpio -P
