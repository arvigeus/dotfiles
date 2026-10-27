#!/usr/bin/env bash
set -Eeuo pipefail

# The running daemon owns and persists its configuration. Offline provisioning
# edits the seed/file instead. Keep charge limits, lighting and other preferences.
if [[ ${CONFIG_MODE:-install} == live ]] && systemctl is-active --quiet asusd.service; then
    for property in PlatformProfileLinkedEpp ChangePlatformProfileOnBattery ChangePlatformProfileOnAc; do
        busctl --system set-property xyz.ljones.Asusd /xyz/ljones xyz.ljones.Platform "$property" b false
    done
elif [[ ! -f /etc/asusd/asusd.ron ]]; then
    install -Dm0644 /usr/local/share/dotfiles/power/asusd.ron /etc/asusd/asusd.ron
else
    python3 -I - << 'PY'
from pathlib import Path
import os
import re
import tempfile

path = Path('/etc/asusd/asusd.ron')
original = path.read_text()
updated = original
for name in ('platform_profile_linked_epp', 'change_platform_profile_on_battery', 'change_platform_profile_on_ac'):
    updated, count = re.subn(r'(?m)^(\s*' + name + r':\s*)(?:true|false)(\s*,)', r'\g<1>false\2', updated)
    if count != 1:
        raise SystemExit(f'Cannot safely configure ASUS ownership: expected one {name} field')
if updated != original:
    fd, temporary = tempfile.mkstemp(prefix='.power-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
PY
fi
