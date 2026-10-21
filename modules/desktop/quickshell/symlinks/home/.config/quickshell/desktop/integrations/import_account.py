#!/usr/bin/env python3
"""Copy an existing shared account and private credentials into this shell."""
import argparse
import json
import os
import stat
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nextcloud


def source_credential(reference, root):
    directory = root / 'credentials/nextcloud'
    path = directory / reference['file']
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('The source credential path escapes its directory.')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Source credentials must be regular files owned by you.')
        secret = stream.read(65537).strip()
    if not secret or len(secret) > 65536 or "\n" in secret or "\r" in secret:
        raise ValueError('The source credential is empty or invalid.')
    return secret


def install(account_path, calendar_path=None, destination=None):
    destination = destination or nextcloud.config_root()
    account = nextcloud.validate_account(nextcloud.read_json(account_path))
    outputs = {destination / 'nextcloud.json': (json.dumps(account, indent=2) + '\n').encode()}
    for reference in account['credentials'].values():
        secret = source_credential(reference, account_path.parent)
        outputs[destination / 'credentials/nextcloud' / reference['file']] = secret.encode()
    if calendar_path:
        selections = nextcloud.read_json(calendar_path)
        selections = selections.get('calendar', selections)
        if not isinstance(selections, dict): raise ValueError('Calendar selections must be an object.')
        options = {'provider': 'nextcloud'}
        for key in ('calendars', 'task_lists'):
            if key in selections:
                if not isinstance(selections[key], list) or any(not isinstance(name, str) for name in selections[key]):
                    raise ValueError('Calendar selections must be lists of names.')
                options[key] = selections[key]
        outputs[destination.parent / 'calendar.json'] = (json.dumps(options, indent=2) + '\n').encode()
    # Validate all destinations before writing; no source files are changed.
    for path, data in outputs.items():
        if path.is_symlink() or path.exists() and path.read_bytes().strip() != data.strip():
            raise ValueError('A destination already exists with different contents; resolve it before importing.')
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.tmp-')
        try:
            with os.fdopen(fd, 'wb') as stream: stream.write(data)
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('account', type=Path, help='Existing nextcloud.json')
    parser.add_argument('--calendar', type=Path, help='Existing calendar selections (or a configuration containing calendar)')
    args = parser.parse_args()
    try:
        install(args.account, args.calendar)
        print('Account and credentials imported. Source files were preserved.')
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
