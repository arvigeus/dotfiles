"""Read Heroic's GOG library without handling account credentials or game execution."""

import json
from pathlib import Path
import re
import subprocess
import urllib.parse

from spaces.games import store_metadata

APP_ID = 'com.heroicgameslauncher.hgl'
LIBRARY_PATHS = ('store_cache/gog_library.json', 'gog_store/library.json')
MAX_CACHE_BYTES = 16 * 1024 * 1024


def product_id(value):
    text = str(value or '').strip()
    return text if re.fullmatch(r'[1-9][0-9]{0,19}', text) else ''


def store_slug(value):
    if not isinstance(value, str) or len(value) > 2048:
        return ''
    try:
        parsed = urllib.parse.urlsplit(value)
        match = re.fullmatch(
            r'/(?:[a-z]{2}/)?game/([A-Za-z0-9][A-Za-z0-9_-]*)/?', parsed.path
        )
        if (
            parsed.scheme == 'https'
            and parsed.hostname in {'gog.com', 'www.gog.com'}
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and not parsed.query
            and not parsed.fragment
            and match
        ):
            return match[1]
    except ValueError:
        pass
    return ''


def store_url(value):
    slug = store_slug(value)
    return f'https://www.gog.com/en/game/{slug}' if slug else ''


def _read(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return None, 'invalid'
        return json.loads(raw), 'ok'
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, ValueError, UnicodeError):
        return None, 'invalid'


def _records(raw, key):
    return (
        raw[key] if isinstance(raw, dict) and isinstance(raw.get(key), list) else None
    )


def read(env, which, runner):
    home = Path(env.get('HOME', str(Path.home())))
    native_root = Path(env.get('XDG_CONFIG_HOME', home / '.config')) / 'heroic'
    flatpak_root = home / '.var/app' / APP_ID / 'config/heroic'
    native = which('heroic')
    flatpak = which('flatpak')
    flatpak_available = False
    if flatpak:
        try:
            result = runner(
                [flatpak, 'info', APP_ID],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env=env,
            )
            flatpak_available = result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    profiles = [
        (native_root, [native] if native else []),
        (flatpak_root, [flatpak, 'run', APP_ID] if flatpak_available else []),
    ]
    populated = [
        (root, command)
        for root, command in profiles
        if any(
            (root / path).exists()
            for path in (*LIBRARY_PATHS, 'gog_store/installed.json')
        )
    ]
    preferred = [profile for profile in populated if profile[1]]
    available = [profile for profile in profiles if profile[1]]
    root, command = (preferred or populated or available or profiles)[0]
    library_path = next(
        (root / path for path in LIBRARY_PATHS if (root / path).exists()),
        root / LIBRARY_PATHS[0],
    )
    library_raw, library_status = _read(library_path)
    library = _records(library_raw, 'games')
    ownership_known = library_status == 'ok' and library is not None
    owned = {}
    for record in library or []:
        if not isinstance(record, dict):
            ownership_known = False
            continue
        identifier = product_id(record.get('app_name'))
        title = store_metadata.plain_text(record.get('title'))[:180]
        install = (
            record.get('install') if isinstance(record.get('install'), dict) else {}
        )
        if not identifier or not title or install.get('is_dlc') is True:
            continue
        url = store_url(record.get('store_url'))
        owned[identifier] = {
            'store': 'gog',
            'externalId': identifier,
            'title': title,
            'installed': False,
            'launchable': False,
            'storeUrl': url,
            'slug': store_slug(url),
            'metadata': store_metadata.gog_details(record),
        }
    installed_raw, installed_status = _read(root / 'gog_store/installed.json')
    installed = _records(installed_raw, 'installed')
    installation_known = installed_status == 'missing' or (
        installed_status == 'ok' and installed is not None
    )
    items = dict(owned)
    for record in installed or []:
        if not isinstance(record, dict):
            installation_known = False
            continue
        identifier = product_id(record.get('appName'))
        path = record.get('install_path')
        if not identifier or not isinstance(path, str) or len(path) > 4096:
            continue
        try:
            exists = Path(path).is_absolute() and Path(path).is_dir()
        except (OSError, ValueError):
            exists = False
        if not exists:
            continue
        item = items.get(
            identifier,
            {'store': 'gog', 'externalId': identifier, 'title': f'GOG {identifier}'},
        )
        items[identifier] = dict(
            item,
            installed=True,
            installPath=path,
            launchable=bool(
                command
                and identifier in owned
                and record.get('platform') in {'linux', 'windows'}
            ),
        )
    if not command:
        message = 'Install Heroic Games Launcher to manage GOG games.'
    elif library_status == 'invalid' or (
        library_status == 'ok' and not ownership_known
    ):
        message = "Heroic's GOG library cache could not be read. Refresh it in Heroic, then refresh Games."
    elif not ownership_known:
        message = 'Sign into GOG in Heroic and refresh its library, then refresh Games.'
    elif not installation_known:
        message = "Heroic's GOG installation records could not be read. Refresh them in Heroic."
    else:
        message = ''
    return {
        'available': bool(command),
        'command': command,
        'ownershipKnown': ownership_known,
        'installationKnown': installation_known,
        'ownedIds': list(owned) if ownership_known else [],
        'items': list(items.values()),
        'message': message,
    }
