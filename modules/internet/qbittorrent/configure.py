#!/usr/bin/env python3
"""Merge managed preferences into qBittorrent's Qt INI file."""

from pathlib import Path
import base64
import hashlib
import re
import secrets
import sys
import tempfile


SETTINGS = {
    'Appearance': {'TrayIconStyle': 'Monochrome'},
    'BitTorrent': {
        'MergeTrackersEnabled': 'true',
        r'Session\AlternativeGlobalDLSpeedLimit': '200',
        r'Session\AlternativeGlobalUPSpeedLimit': '200',
    },
    'GUI': {
        r'ConfirmActions\MergeTrackers': 'false',
        r'TransferList\UseTorrentStatesColors': 'false',
    },
    'Preferences': {
        r'Advanced\useSystemIconTheme': 'true',
        r'General\PreventFromSuspendWhenDownloading': 'true',
        r'Search\SearchEnabled': 'true',
    },
    'WebUI': {
        'Enabled': 'true',
        'Address': '127.0.0.1',
        'Port': '8080',
        'LocalHostAuth': 'false',
        r'HTTPS\Enabled': 'false',
        'UseUPnP': 'false',
        'CSRFProtection': 'true',
        'HostHeaderValidation': 'true',
        'ServerDomains': 'localhost',
    },
}


def configure(source, destination):
    # Preserve opaque Qt values, comments, and all settings we do not own.
    content = source.read_text() if source.exists() else ''
    existing = {}
    section = None
    for line in content.splitlines():
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif section == 'WebUI' and '=' in line:
            key, value = line.split('=', 1)
            existing[key.strip()] = value.strip()
    settings = {section: dict(values) for section, values in SETTINGS.items()}
    settings['WebUI']['Username'] = existing.get('Username') or 'admin'
    password = existing.get('Password_PBKDF2', '')
    if password in ('', '@ByteArray()', '""'):
        # The GUI client requires a hash even when localhost auth is bypassed.
        # Discard the random password: no credential is needed for loopback use.
        salt = secrets.token_bytes(16)
        key = hashlib.pbkdf2_hmac('sha512', secrets.token_bytes(32), salt, 100000)
        password = (
            '@ByteArray('
            + ':'.join(base64.b64encode(value).decode() for value in (salt, key))
            + ')'
        )
    settings['WebUI']['Password_PBKDF2'] = password
    pending = {section: dict(values) for section, values in settings.items()}
    lines = []
    section = None

    def flush():
        values = pending.pop(section, {})
        if not values:
            return
        blanks = []
        while lines and not lines[-1].strip():
            blanks.append(lines.pop())
        for key, value in values.items():
            lines.append(f'{key}={value}\n')
        lines.extend(reversed(blanks))

    for line in content.splitlines(keepends=True):
        header = re.fullmatch(r'\[([^\]]+)\]\s*', line.strip())
        if header:
            flush()
            section = header[1]
        key = line.split('=', 1)[0].strip() if '=' in line else None
        if key in settings.get(section, {}):
            continue
        lines.append(line if line.endswith('\n') else line + '\n')
    flush()
    for section, values in pending.items():
        lines.append(f'\n[{section}]\n')
        lines.extend(f'{key}={value}\n' for key, value in values.items())

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode='w', dir=destination.parent, delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            output.write(''.join(lines))
            output.close()
            temporary.chmod(0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    configure(*map(Path, sys.argv[1:3]))
