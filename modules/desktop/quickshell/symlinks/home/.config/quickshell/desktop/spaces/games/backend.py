#!/usr/bin/env python3
"""Games catalogue and local-library worker. QML communicates with JSON lines."""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.games import store_metadata
from spaces.games.igdb import Client as IGDBClient
from spaces.games.igdb import normalize as normalize_igdb_game
from spaces.games import gog, hltb, presentation
from spaces.movies.worker import serve, own_process_group
from spaces.movies.local import LocalLibrary

CONFIG = (
    Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    / 'quickshell/desktop/spaces/games/games.json'
)
DATA = (
    Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    / 'quickshell/desktop/spaces/games'
)
PROTONDB_SUMMARY = 'https://www.protondb.com/api/v1/reports/summaries/{}.json'
PROTONDB_PAGE = 'https://www.protondb.com/app/{}'
UMU_DATABASE = 'https://umu.openwinecomponents.org/umu_api.php'
PAGE_SIZE = 50
CACHE_RETENTION = 90 * 86400
ALLOWED_PROTONDB_TIERS = {'platinum', 'gold', 'silver', 'bronze', 'borked', 'pending'}
STORE_LABELS = {'steam': 'Steam', 'epic': 'Epic Games Store', 'gog': 'GOG'}
_PROTONDB_LOCK = threading.Lock()
_LAST_PROTONDB_REQUEST = 0.0


class GamesError(RuntimeError):
    pass


def _safe_text(value, limit=200):
    if not isinstance(value, str):
        value = str(value or '')
    return ''.join(char for char in value[:limit] if char >= ' ' and char not in '\x7f')


def _steam_id(value):
    text = str(value or '').strip()
    return text if re.fullmatch(r'[1-9][0-9]{0,9}', text) else ''


def _epic_id(value):
    text = _safe_text(value, 160).strip()
    return text if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', text) else ''


def protondb_url(app_id):
    valid = _steam_id(app_id)
    return PROTONDB_PAGE.format(valid) if valid else ''


def _title_key(title):
    """Compare titles while retaining edition words and sequel numbers."""
    normalized = unicodedata.normalize('NFKC', str(title or ''))
    # Catalogue and launcher names sometimes spell sequels differently (Alan
    # Wake II / Alan Wake 2). Only standalone Roman numerals II–X qualify;
    # edition and DLC words still have to match, and ambiguous matches fail.
    roman_numbers = {
        'II': '2',
        'III': '3',
        'IV': '4',
        'V': '5',
        'VI': '6',
        'VII': '7',
        'VIII': '8',
        'IX': '9',
        'X': '10',
    }
    normalized = re.sub(
        r'\b(?:VIII|VII|III|VI|IV|II|IX|V|X)\b',
        lambda match: roman_numbers[match[0].upper()],
        normalized,
        flags=re.IGNORECASE,
    ).casefold()
    return ' '.join(re.findall(r'[\w]+', normalized, flags=re.UNICODE))


def _library_indexes(libraries):
    indexes = {}
    for store in STORE_LABELS:
        items = (libraries or {}).get(store, {}).get('items', [])
        titles = {}
        for item in items:
            titles.setdefault(_title_key(item.get('title', '')), []).append(item)
        indexes[store] = {
            'ids': {
                str(item['externalId']): item
                for item in items
                if item.get('externalId')
            },
            'titles': titles,
        }
    return indexes


def match_library_item(game, store, library_items, override='', index=None):
    """Match by an intentional override, an exact store ID, then unique exact title."""
    references = [
        str(reference.get('externalId', ''))
        for reference in (game.get('storeReferences') or [])
        if reference.get('store') == store and reference.get('externalId')
    ]
    by_id = (
        index['ids']
        if index is not None
        else {
            str(item.get('externalId', '')): item
            for item in library_items
            if item.get('externalId')
        }
    )
    if override:
        return (by_id[override], 'override') if override in by_id else (None, '')
    for external_id in references:
        if external_id in by_id:
            return by_id[external_id], 'store-id'
        if store == 'gog':
            matching = [
                item for item in library_items if item.get('slug') == external_id
            ]
            if len(matching) == 1:
                return matching[0], 'store-id'
    # A Steam AppID is the same identity used by local manifests; falling back
    # from a failed explicit ID risks selecting another edition. Epic catalog
    # product IDs may differ from Legendary's app names, so an exact title can
    # still help unless the user supplied a deliberate override.
    # Library records carry launcher IDs, so they need no catalogue fallback.
    # In particular, an ambiguous title split into separate rows must not gain
    # another store's game just because that store has one title match.
    if (
        (store == 'steam' and references)
        or (store == 'gog' and any(gog.product_id(value) for value in references))
        or game.get('catalogProvider') == 'library'
    ):
        return None, ''

    key = _title_key(game.get('title', ''))
    if not key:
        return None, ''
    matching = (
        index['titles'].get(key, [])
        if index is not None
        else [
            item for item in library_items if _title_key(item.get('title', '')) == key
        ]
    )
    # Edition names are intentionally not stripped; duplicate exact-title entries are ambiguous.
    if len(matching) == 1:
        return matching[0], 'exact-title'
    return None, ''


def steam_app_id(game, libraries, override=''):
    """Resolve ProtonDB identity only from an explicit ID or a centralized library match."""
    override = _steam_id(override)
    if override:
        return override
    references = [
        _steam_id(reference.get('externalId', ''))
        for reference in (game.get('storeReferences') or [])
        if reference.get('store') == 'steam'
    ]
    references = [value for value in references if value]
    if len(references) == 1:
        return references[0]
    if references:
        return ''
    provider = (libraries or {}).get('steam', {})
    match, _ = match_library_item(game, 'steam', provider.get('items', []))
    return _steam_id((match or {}).get('externalId', ''))


def derive_store_state(game, libraries, overrides=None, indexes=None):
    """Return store availability and user actions without exposing launcher internals to QML."""
    overrides = overrides or {}
    references = game.get('storeReferences') or []
    rows = []
    for store in STORE_LABELS:
        reference_ids = [
            str(value.get('externalId', ''))
            for value in references
            if value.get('store') == store and value.get('externalId')
        ]
        override = str(overrides.get(store, ''))
        provider = (libraries or {}).get(store, {})
        owned_ids = set(str(value) for value in provider.get('ownedIds', []))
        items = provider.get('items', [])
        match, match_source = match_library_item(
            game, store, items, override, (indexes or {}).get(store)
        )
        matched_id = str((match or {}).get('externalId', ''))
        identity_ids = (
            {override} if override else {value for value in reference_ids if value}
        )
        identity_ids.update([matched_id] if matched_id else [])
        owned_status = 'unknown'
        if provider.get('ownershipKnown') and identity_ids:
            owned_status = (
                'owned' if identity_ids.intersection(owned_ids) else 'not-owned'
            )
        installed = bool(match and match.get('installed'))
        launchable = bool(installed and match.get('launchable'))
        actions = []
        action_id = (
            matched_id
            or override
            or (reference_ids[0] if len(reference_ids) == 1 else '')
        )
        if launchable and action_id:
            actions.append(
                {
                    'id': f'{store}:play:{action_id}',
                    'type': 'play',
                    'label': 'Play',
                    'store': store,
                }
            )
            actions.append(
                {
                    'id': f'{store}:uninstall:{action_id}',
                    'type': 'uninstall',
                    'label': 'Uninstall',
                    'store': store,
                }
            )
        elif owned_status == 'owned' and not installed and provider.get('available'):
            install_candidates = (
                (override,) if override else (matched_id, *reference_ids)
            )
            install_id = next(
                (value for value in install_candidates if value and value in owned_ids),
                '',
            )
            if install_id and (
                store == 'steam' or provider.get('installationKnown', True)
            ):
                actions.append(
                    {
                        'id': f'{store}:install:{install_id}',
                        'type': 'install',
                        'label': 'Install',
                        'store': store,
                    }
                )

        linked = bool(reference_ids or override or match)
        installation_known = provider.get('installationKnown', store == 'steam')
        installation_label = (
            'Installed'
            if installed
            else 'Not installed'
            if linked and installation_known
            else 'No matching install found'
        )
        if installed and not launchable:
            installation_label = 'Installed · launcher unavailable'
        if not installation_known:
            installation_label = 'Installation state unavailable'
        if owned_status == 'owned':
            ownership_label = 'Owned'
        elif owned_status == 'not-owned':
            ownership_label = 'Not owned'
        elif (
            store == 'epic'
            and provider.get('available')
            and not provider.get('ownershipKnown')
        ):
            ownership_label = 'Sign in with Legendary'
        elif (
            store == 'gog'
            and provider.get('available')
            and not provider.get('ownershipKnown')
        ):
            ownership_label = 'Sign into GOG in Heroic'
        elif (
            store == 'steam'
            and provider.get('ownershipConfigured')
            and not provider.get('ownershipKnown')
        ):
            ownership_label = 'Steam profile is private or unavailable'
        elif not provider.get('available'):
            ownership_label = 'Integration unavailable'
        else:
            ownership_label = 'Ownership not checked'

        if not linked:
            primary_action = {
                'type': 'link',
                'label': 'Link',
                'enabled': True,
                'tooltip': "Add this game's store ID to match it with your library.",
            }
            status_label = 'Not linked'
        elif launchable and actions:
            primary_action = {
                **actions[0],
                'enabled': True,
                'tooltip': f'{ownership_label} · {installation_label}',
            }
            status_label = 'Installed'
        elif owned_status == 'owned' and not installed and actions:
            primary_action = {
                **actions[0],
                'enabled': True,
                'tooltip': f'{ownership_label} · {installation_label}',
            }
            status_label = 'Owned · not installed'
        elif installed:
            primary_action = {
                'type': 'disabled',
                'label': 'Unavailable',
                'enabled': False,
                'tooltip': provider.get('message')
                or 'This launcher cannot currently manage this installation.',
            }
            status_label = 'Installed'
        elif owned_status == 'not-owned':
            purchase_url = next(
                (
                    _safe_store_url(
                        value.get('url', ''), store, value.get('externalId', '')
                    )
                    for value in references
                    if value.get('store') == store
                    and _safe_store_url(
                        value.get('url', ''), store, value.get('externalId', '')
                    )
                ),
                '',
            )
            primary_action = {
                'type': 'buy' if purchase_url else 'disabled',
                'label': 'Buy' if purchase_url else 'Unavailable',
                'enabled': bool(purchase_url),
                'url': purchase_url,
                'tooltip': f'Open {STORE_LABELS[store]} to buy this game.'
                if purchase_url
                else ownership_label,
            }
            status_label = 'Not owned'
        else:
            primary_action = {
                'type': 'disabled',
                'label': 'Unavailable',
                'enabled': False,
                'tooltip': provider.get('message') or ownership_label,
            }
            status_label = (
                'Unavailable' if not provider.get('available') else 'Ownership unknown'
            )
        status_tooltip = (
            f'Ownership: {ownership_label}\nInstallation: {installation_label}'
        )
        if provider.get('message'):
            status_tooltip += '\n' + _safe_text(provider['message'], 240)
        if store == 'gog' and provider.get('available'):
            actions = [action for action in actions if action['type'] != 'uninstall']
            actions.append(
                {
                    'id': 'gog:manage',
                    'type': 'manage',
                    'label': 'Manage in Heroic…',
                    'store': 'gog',
                }
            )
            if primary_action.get('type') in {'play', 'install'}:
                primary_action['tooltip'] += '\nOpens Heroic' + (
                    "'s installation prompt."
                    if primary_action['type'] == 'install'
                    else ' to launch the game.'
                )

        rows.append(
            {
                'store': store,
                'label': STORE_LABELS[store],
                'availability': 'available' if linked else 'unavailable',
                'availabilityLabel': 'Available' if linked else 'No store ID linked',
                'ownership': owned_status,
                'ownershipLabel': ownership_label,
                'installation': 'installed'
                if installed
                else 'not-installed'
                if linked and installation_known
                else 'unknown',
                'installationLabel': installation_label,
                'installed': installed,
                'launchable': launchable,
                'statusLabel': status_label,
                'statusTooltip': status_tooltip,
                'primaryAction': primary_action,
                'matchSource': match_source,
                'externalId': action_id,
                'storeReferences': reference_ids,
                'actions': actions,
                'providerMessage': provider.get('message', ''),
                'storeUrl': next(
                    (
                        _safe_store_url(
                            value.get('url', ''), store, value.get('externalId', '')
                        )
                        for value in references
                        if value.get('store') == store
                        and _safe_store_url(
                            value.get('url', ''), store, value.get('externalId', '')
                        )
                    ),
                    _safe_store_url(
                        (match or {}).get('storeUrl', ''), store, matched_id
                    ),
                ),
            }
        )
    return rows


def parse_vdf(text):
    """Parse the quoted key/value and nested-object subset used by Steam VDF files."""
    token_pattern = re.compile(
        r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+'
    )
    tokens = [
        match.group(0)
        for match in token_pattern.finditer(str(text))
        if not match.group(0).isspace() and not match.group(0).startswith(('//', '/*'))
    ]
    position = 0

    def take():
        nonlocal position
        if position >= len(tokens):
            raise ValueError('unexpected end of VDF')
        token = tokens[position]
        position += 1
        if token.startswith('"') and token.endswith('"'):
            token = token[1:-1]
            token = re.sub(r'\\([\\"])', r'\1', token)
        return token

    def block(nested=False):
        nonlocal position
        result = {}
        while position < len(tokens):
            if tokens[position] == '}':
                if not nested:
                    raise ValueError('unexpected closing brace in VDF')
                position += 1
                return result
            key = take()
            if key in ('{', '}'):
                raise ValueError('invalid VDF key')
            if position >= len(tokens):
                raise ValueError('missing VDF value')
            value = tokens[position]
            if value == '{':
                position += 1
                result[key] = block(True)
            else:
                result[key] = take()
        if nested:
            raise ValueError('unclosed VDF object')
        return result

    return block()


def steam_manifest(raw, library, manifest_path):
    app = raw.get('AppState', {}) if isinstance(raw, dict) else {}
    if not isinstance(app, dict):
        return None
    app_id = _steam_id(app.get('appid', ''))
    if not app_id:
        match = re.fullmatch(
            r'appmanifest_([1-9][0-9]{0,9})\.acf', Path(manifest_path).name
        )
        app_id = _steam_id(match.group(1)) if match else ''
    try:
        state_flags = int(app.get('StateFlags', 0))
    except (TypeError, ValueError):
        return None
    install_dir = _safe_text(app.get('installdir', ''), 300).strip()
    title = _safe_text(app.get('name', ''), 180).strip()
    if not app_id or not title or not install_dir or not (state_flags & 4):
        return None
    install_path = Path(library) / 'steamapps/common' / install_dir
    if not install_path.is_dir():
        return None
    return {
        'store': 'steam',
        'externalId': app_id,
        'title': title,
        'installPath': str(install_path),
        'installed': True,
        'launchable': False,
    }


def parse_steam_owned_games(raw):
    """Return named Steam ownership records, or None when the response is not authoritative."""
    response = raw.get('response') if isinstance(raw, dict) else None
    values = response.get('games') if isinstance(response, dict) else None
    if not isinstance(values, list):
        return None
    games, seen = [], set()
    for value in values:
        if not isinstance(value, dict):
            continue
        app_id = _steam_id(value.get('appid', ''))
        title = _safe_text(value.get('name', ''), 180).strip()
        if not app_id or not title or app_id in seen:
            continue
        seen.add(app_id)
        games.append(
            {
                'store': 'steam',
                'externalId': app_id,
                'title': title,
                'installed': False,
                'launchable': False,
            }
        )
    return games


def _json_records(raw):
    """Accept current list JSON and older/object-wrapped Legendary JSON fixtures."""
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []
    for key in ('games', 'results', 'items'):
        if isinstance(raw.get(key), list):
            return [item for item in raw[key] if isinstance(item, dict)]
    # Some JSON versions key game objects by Epic app name.
    records = []
    for key, value in raw.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault('app_name', key)
            records.append(item)
    return records


def parse_legendary_owned(raw):
    games = []
    seen = set()
    for item in _json_records(raw):
        app_name = _epic_id(
            item.get('app_name') or item.get('appName') or item.get('app_id') or ''
        )
        title = _safe_text(
            item.get('app_title') or item.get('title') or item.get('app_name') or '',
            180,
        )
        if not app_name or not title or app_name in seen:
            continue
        seen.add(app_name)
        game = {
            'store': 'epic',
            'externalId': app_name,
            'title': title,
            'installed': False,
        }
        metadata = store_metadata.epic_details(item)
        if any(metadata.values()):
            game['metadata'] = metadata
        games.append(game)
    return games


def parse_legendary_installed(raw):
    games = []
    seen = set()
    for item in _json_records(raw):
        app_name = _epic_id(
            item.get('app_name') or item.get('appName') or item.get('app_id') or ''
        )
        title = _safe_text(
            item.get('app_title') or item.get('title') or item.get('app_name') or '',
            180,
        )
        install_path = _safe_text(
            item.get('install_path')
            or item.get('installPath')
            or item.get('install_dir')
            or '',
            2048,
        )
        if not app_name or app_name in seen:
            continue
        seen.add(app_name)
        installed = bool(install_path and Path(install_path).is_dir())
        games.append(
            {
                'store': 'epic',
                'externalId': app_name,
                'title': title or app_name,
                'installPath': install_path,
                'installed': installed,
            }
        )
    return [game for game in games if game['installed']]


def _safe_store_url(value, store, external_id):
    if store == 'gog':
        return gog.store_url(value)
    url = _safe_text(value, 1024).strip()
    parsed = urllib.parse.urlsplit(url)
    allowed_hosts = (
        {'store.steampowered.com'}
        if store == 'steam'
        else {'store.epicgames.com', 'www.epicgames.com'}
    )
    try:
        if (
            parsed.scheme == 'https'
            and parsed.hostname in allowed_hosts
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        ):
            return url
    except ValueError:
        pass
    if store == 'steam' and _steam_id(external_id):
        return f'https://store.steampowered.com/app/{external_id}/'
    return ''


class GamesBackend:
    def __init__(
        self,
        config=CONFIG,
        data=DATA,
        env=None,
        request=None,
        runner=None,
        popen=None,
        clock=time.time,
    ):
        self.config_path = Path(config)
        self.data_root = Path(data)
        self.env = dict(os.environ if env is None else env)
        self._request = request or self._http_json
        self._runner = runner or subprocess.run
        self._popen = popen or subprocess.Popen
        self._clock = clock
        self.catalogue = IGDBClient(self.config, self._request, GamesError)
        self.beat_times = hltb.Client()
        self.data_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.data_root.chmod(0o700)
        except OSError:
            pass
        self.db_path = self.data_root / 'library.sqlite'
        self._config_lock = threading.Lock()
        self._config = {}
        self._config_error = ''
        self._config_mtime = None
        self._library_lock = threading.Lock()
        self._library_snapshot = None
        self._library_updated = 0.0
        self._metadata_lock = threading.Lock()
        self._metadata_locks = {}
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY, catalog_id INTEGER NOT NULL UNIQUE,
                    payload TEXT NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS store_matches (
                    game_id TEXT NOT NULL, store TEXT NOT NULL,
                    external_id TEXT NOT NULL, PRIMARY KEY(game_id, store)
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    game_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS hltb_matches (
                    game_id TEXT PRIMARY KEY, external_id TEXT NOT NULL
                );
            """)
            # Stale entries are still served offline; drop only long-unused ones.
            db.execute(
                'DELETE FROM cache WHERE updated < ?', (clock() - CACHE_RETENTION,)
            )
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def config(self, force=False):
        with self._config_lock:
            try:
                mtime = self.config_path.stat().st_mtime_ns
            except OSError:
                mtime = None
            if force or mtime != self._config_mtime:
                try:
                    raw = (
                        self.config_path.read_text(encoding='utf-8')
                        if mtime is not None
                        else '{}'
                    )
                    if len(raw) > 65536:
                        raise ValueError('configuration file is too large')
                    loaded = json.loads(raw)
                    if not isinstance(loaded, dict):
                        raise ValueError('configuration root must be an object')
                    self._config = loaded
                    self._config_error = ''
                except (OSError, UnicodeError, ValueError) as error:
                    self._config = {}
                    self._config_error = str(error)
                self._config_mtime = mtime
            return self._config

    def config_state(self):
        config = self.config()
        valid = bool(config.get('igdb_client_id') and config.get('igdb_client_secret'))
        return {
            'configured': valid,
            'configPath': str(self.config_path),
            'configError': self._config_error,
            'message': ''
            if valid
            else 'Add igdb_client_id and igdb_client_secret to games.json to browse games.',
        }

    @staticmethod
    def _database_catalog_id(provider, provider_id):
        provider_id = str(provider_id)
        # The existing SQLite schema uses a numeric unique key. Keep independent
        # provider namespaces without exposing this internal key as game identity.
        digest = hashlib.sha256((provider + ':' + provider_id).encode('utf-8')).digest()
        return int.from_bytes(digest[:7], 'big') or 1

    def _cache_get(self, key, ttl=None, allow_stale=False):
        with self._db() as db:
            row = db.execute(
                'SELECT value, updated FROM cache WHERE key=?', (key,)
            ).fetchone()
        if not row:
            return None, False
        try:
            value = json.loads(row['value'])
        except (TypeError, ValueError):
            return None, False
        fresh = ttl is None or self._clock() - row['updated'] <= ttl
        return (value if fresh or allow_stale else None), fresh

    def _cache_put(self, key, value):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        with self._db() as db:
            db.execute(
                'INSERT OR REPLACE INTO cache(key,value,updated) VALUES(?,?,?)',
                (key, encoded, self._clock()),
            )

    def _game_by_id(self, game_id):
        with self._db() as db:
            row = db.execute(
                'SELECT * FROM games WHERE id=?', (str(game_id),)
            ).fetchone()
        if not row:
            return None
        try:
            return int(row['catalog_id']), json.loads(row['payload'])
        except (TypeError, ValueError):
            return None

    def _save_game(self, catalog_id, game, merge=True, connection=None):
        provider = str(game.get('catalogProvider', 'igdb'))
        provider_id = str(game.get('catalogProviderId', catalog_id))
        db_catalog_id = self._database_catalog_id(provider, provider_id)
        with nullcontext(connection) if connection is not None else self._db() as db:
            if connection is None:
                db.execute('BEGIN IMMEDIATE')
            row = db.execute(
                'SELECT id,payload FROM games WHERE catalog_id=?', (db_catalog_id,)
            ).fetchone()
            game_id = row['id'] if row else uuid.uuid4().hex
            if row and merge:
                try:
                    existing = json.loads(row['payload'])
                except (TypeError, ValueError):
                    existing = {}
                merged = dict(existing)
                for key, value in game.items():
                    if (
                        key == 'officialWebsite'
                        or value not in (None, '', [], {})
                        or key not in merged
                    ):
                        merged[key] = value
                game = merged
            game['id'] = game_id
            db.execute(
                'INSERT OR REPLACE INTO games(id,catalog_id,payload,updated) VALUES(?,?,?,?)',
                (
                    game_id,
                    db_catalog_id,
                    json.dumps(game, ensure_ascii=False),
                    self._clock(),
                ),
            )
        return game

    def _save_store_match(self, game_id, store, external_id):
        if store not in STORE_LABELS:
            raise GamesError('This store cannot be matched here.')
        external_id = str(external_id or '').strip()
        if not external_id:
            with self._db() as db:
                found = db.execute(
                    'SELECT 1 FROM games WHERE id=?', (str(game_id),)
                ).fetchone()
                if not found:
                    raise GamesError('Select a game before clearing a store match.')
                db.execute(
                    'DELETE FROM store_matches WHERE game_id=? AND store=?',
                    (str(game_id), store),
                )
            return ''
        if store == 'steam':
            external_id = _steam_id(external_id)
        elif store == 'gog':
            external_id = gog.product_id(external_id)
        else:
            external_id = _epic_id(external_id)
        if not external_id:
            raise GamesError(
                'Enter a valid Steam AppID, Epic app name or numeric GOG product ID.'
            )
        with self._db() as db:
            found = db.execute(
                'SELECT 1 FROM games WHERE id=?', (str(game_id),)
            ).fetchone()
            if not found:
                raise GamesError('Select a game before saving a store match.')
            db.execute(
                'INSERT OR REPLACE INTO store_matches(game_id,store,external_id) VALUES(?,?,?)',
                (str(game_id), store, external_id),
            )
        return external_id

    def _store_overrides(self, game_id):
        with self._db() as db:
            rows = db.execute(
                'SELECT store,external_id FROM store_matches WHERE game_id=?',
                (str(game_id),),
            ).fetchall()
        return {row['store']: row['external_id'] for row in rows}

    def _http_json(
        self,
        url,
        method='GET',
        headers=None,
        body=None,
        timeout=15,
        max_bytes=4 * 1024 * 1024,
    ):
        request = urllib.request.Request(
            url, data=body, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise GamesError(
                        'The provider response was too large to read safely.'
                    )
                if not payload:
                    return {}
                return json.loads(payload.decode('utf-8'))
        except urllib.error.HTTPError as error:
            raise GamesError(f'Provider request failed (HTTP {error.code}).') from None
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeError,
            ValueError,
        ) as error:
            # Never surface a request URL or response body; either may contain a credential.
            if isinstance(error, GamesError):
                raise
            raise GamesError(
                'Provider is unreachable or returned invalid data.'
            ) from None

    def _catalog_id(self, game_id):
        found = self._game_by_id(game_id)
        if not found:
            raise GamesError(
                'This catalogue game is no longer available. Search again.'
            )
        return found

    def _with_library_indicators(self, items):
        state = (
            self._library_snapshot or self._cache_get('libraries:v1', 86400)[0] or {}
        )
        indexes = _library_indexes(state)
        ids = [str(game.get('id', '')) for game in items if game.get('id')]
        favorite_ids = set()
        overrides = {}
        if ids:
            placeholders = ','.join('?' for _ in ids)
            with self._db() as db:
                rows = db.execute(
                    f'SELECT game_id FROM favorites WHERE game_id IN ({placeholders})',
                    ids,
                ).fetchall()
                matches = db.execute(
                    f'SELECT game_id,store,external_id FROM store_matches WHERE game_id IN ({placeholders})',
                    ids,
                ).fetchall()
            favorite_ids = {row['game_id'] for row in rows}
            for match in matches:
                overrides.setdefault(match['game_id'], {})[match['store']] = match[
                    'external_id'
                ]
        output = []
        for game in items:
            displayed = dict(game)
            rows = derive_store_state(
                game, state, overrides.get(game.get('id', ''), {}), indexes
            )
            displayed['installedBy'] = [
                row['store'] for row in rows if row['installed']
            ]
            displayed['ownedBy'] = [
                row['store'] for row in rows if row['ownership'] == 'owned'
            ]
            displayed['favorite'] = str(game.get('id', '')) in favorite_ids
            output.append(displayed)
        return output

    def library_games(self, request):
        """List installed/owned store games without requiring the catalogue."""
        state = self.libraries()
        indexes = _library_indexes(state)
        query = _title_key(_safe_text(request.get('query', ''), 120).strip())
        mode = request.get('mode', 'all')
        if mode not in ('all', 'installed', 'owned'):
            raise GamesError('Choose a valid library view.')
        offset = max(0, min(int(request.get('offset', 0) or 0), 100000))
        with self._db() as db:
            saved_rows = db.execute('SELECT payload FROM games').fetchall()
            match_rows = db.execute(
                'SELECT game_id,store,external_id FROM store_matches'
            ).fetchall()
        overrides = {}
        for row in match_rows:
            overrides.setdefault(row['game_id'], {})[row['store']] = row['external_id']
        candidates = {}
        for row in saved_rows:
            try:
                game = json.loads(row['payload'])
            except (TypeError, ValueError):
                continue
            if game.get('catalogProvider') != 'igdb':
                continue
            for store in STORE_LABELS:
                item, source = match_library_item(
                    game,
                    store,
                    state.get(store, {}).get('items', []),
                    overrides.get(game['id'], {}).get(store, ''),
                    indexes[store],
                )
                if item:
                    rank = {'override': 0, 'store-id': 1, 'exact-title': 2}[source]
                    candidates.setdefault((store, item['externalId']), []).append(
                        (rank, game)
                    )

        groups = {}
        for store in STORE_LABELS:
            provider = state.get(store, {})
            owned_ids = (
                set(str(value) for value in provider.get('ownedIds', []))
                if provider.get('ownershipKnown')
                else set()
            )
            seen = set()
            for item in provider.get('items', []):
                identity = (store, str(item.get('externalId', '')))
                if not identity[1] or identity in seen:
                    continue
                seen.add(identity)
                if not item.get('installed') and identity[1] not in owned_ids:
                    continue
                matches = candidates.get(identity, [])
                best_rank = min((rank for rank, _ in matches), default=3)
                best = [game for rank, game in matches if rank == best_rank]
                catalogue_game = best[0] if len(best) == 1 else None
                key = (
                    'catalogue:' + catalogue_game['id']
                    if catalogue_game
                    else 'title:' + _title_key(item.get('title', ''))
                )
                groups.setdefault(key, []).append((store, item, catalogue_game))

        records = []
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            for key, members in groups.items():
                # Multiple editions with the same launcher title remain separate.
                stores = [store for store, _, _ in members]
                partitions = (
                    [[member] for member in members]
                    if len(stores) != len(set(stores))
                    else [members]
                )
                for group in partitions:
                    catalogue_game = group[0][2]
                    if catalogue_game:
                        game = dict(catalogue_game)
                    else:
                        references = [
                            {
                                'store': store,
                                'externalId': item['externalId'],
                                **(
                                    {'url': item['storeUrl']}
                                    if item.get('storeUrl')
                                    else {}
                                ),
                            }
                            for store, item, _ in group
                        ]
                        identity = (
                            key
                            if len(partitions) == 1
                            else group[0][0] + ':' + group[0][1]['externalId']
                        )
                        game = self._save_game(
                            identity,
                            {
                                'catalogProvider': 'library',
                                'catalogProviderId': identity,
                                'title': group[0][1]['title'],
                                'storeReferences': references,
                            },
                            merge=False,
                            connection=db,
                        )
                    game['libraryEntry'] = True
                    game['libraryStores'] = (
                        stores if len(partitions) == 1 else [group[0][0]]
                    )
                    records.append(game)
        records = self._with_library_indicators(records)
        records = [
            game
            for game in records
            if (not query or query in _title_key(game.get('title', '')))
            and (mode != 'installed' or game['installedBy'])
            and (mode != 'owned' or game['ownedBy'])
        ]
        records.sort(key=lambda game: (_title_key(game.get('title', '')), game['id']))
        warnings = [
            STORE_LABELS[store] + ': ' + provider['message']
            for store in STORE_LABELS
            if (provider := state.get(store, {})).get('message')
        ]
        return {
            'items': [
                self._enrich_library_game(game, fetch=False)[0]
                for game in records[offset : offset + PAGE_SIZE]
            ],
            'next': offset + PAGE_SIZE if len(records) > offset + PAGE_SIZE else None,
            'setupRequired': False,
            'warning': '\n'.join(warnings),
        }

    def _library_metadata_key(self, game, overrides=None):
        identity = [
            game.get('title'),
            sorted(
                (ref.get('store', ''), str(ref.get('externalId', '')))
                for ref in game.get('storeReferences', [])
            ),
            overrides or {},
        ]
        return (
            'library-igdb:v1:'
            + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        )

    def _enrich_library_game(self, game, fetch=True, refresh=False):
        """Keep store identities intact; fill descriptions/art without blocking the list."""
        state = (
            self._library_snapshot or self._cache_get('libraries:v1', 86400)[0] or {}
        )
        overrides = self._store_overrides(game['id'])
        fallback = {}
        pending = False
        warning = ''
        # Prefer Epic's supplied portrait over Steam's generic CDN fallback.
        epic, _ = match_library_item(
            game,
            'epic',
            state.get('epic', {}).get('items', []),
            overrides.get('epic', ''),
        )
        if epic:
            fallback = store_metadata.fill_missing(fallback, epic.get('metadata') or {})
        gog_item, _ = match_library_item(
            game, 'gog', state.get('gog', {}).get('items', []), overrides.get('gog', '')
        )
        if gog_item:
            fallback = store_metadata.fill_missing(
                fallback, gog_item.get('metadata') or {}
            )
        app_id = steam_app_id(game, state, overrides.get('steam', ''))
        if app_id:
            key = f'steam-metadata:v1:{app_id}'
            cached, fresh = self._cache_get(key, 7 * 86400, allow_stale=True)
            cooling, _ = self._cache_get(key + ':retry', 300)
            needs_store = not fresh and not cooling
            pending = needs_store or refresh
            if fetch and (refresh or needs_store):
                try:
                    raw = self._request(
                        'https://store.steampowered.com/api/appdetails?'
                        + urllib.parse.urlencode({'appids': app_id, 'l': 'english'}),
                        'GET',
                        {'Accept': 'application/json'},
                        None,
                        8,
                        4 * 1024 * 1024,
                    )
                    metadata = store_metadata.steam_details(raw, app_id)
                    if metadata:
                        cached = metadata
                        self._cache_put(key, cached)
                    else:
                        self._cache_put(key + ':retry', True)
                except GamesError:
                    self._cache_put(key + ':retry', True)
                    warning = 'Steam metadata is unavailable. Showing saved and launcher data.'
            fallback = store_metadata.fill_missing(fallback, cached or {})
            fallback = store_metadata.fill_missing(
                fallback, store_metadata.steam_artwork(app_id)
            )

        enriched = store_metadata.fill_missing(game, fallback)
        if game.get('catalogProvider') == 'library':
            # Refresh launcher substitutions too, then apply IGDB's preferred
            # fields below. Missing responses still retain saved metadata.
            for field, value in fallback.items():
                if value:
                    enriched[field] = value
        if (
            game.get('catalogProvider') == 'library'
            and self.config_state()['configured']
        ):
            key = self._library_metadata_key(game, overrides)
            cached, fresh = self._cache_get(key, 86400, allow_stale=True)
            cooling, _ = self._cache_get(key + ':retry', 300)
            needs_catalogue = not fresh and not cooling
            pending = pending or needs_catalogue or refresh
            if fetch and (refresh or needs_catalogue):
                try:
                    raw = self.catalogue.browse(game['title'], {}, 0, 50)
                    matches = []
                    for record in raw:
                        try:
                            candidate = normalize_igdb_game(record)
                        except (KeyError, ValueError, TypeError):
                            continue
                        if _title_key(candidate['title']) != _title_key(game['title']):
                            continue
                        ids = [
                            ref['externalId']
                            for ref in candidate['storeReferences']
                            if ref['store'] == 'steam'
                        ]
                        if app_id and ids and app_id not in ids:
                            continue
                        matches.append(candidate)
                    exact = [
                        candidate
                        for candidate in matches
                        if app_id
                        and any(
                            ref['store'] == 'steam' and ref['externalId'] == app_id
                            for ref in candidate['storeReferences']
                        )
                    ]
                    matches = exact or matches
                    cached = (
                        {
                            field: matches[0].get(field)
                            for field in store_metadata.FIELDS
                        }
                        if len(matches) == 1
                        else {}
                    )
                    self._cache_put(key, cached)
                except GamesError as error:
                    self._cache_put(key + ':retry', True)
                    warning = str(error) + ' Using store metadata where available.'
            # Catalogue fields take precedence over earlier store substitutions.
            for field, value in (cached or {}).items():
                if value:
                    enriched[field] = value
        enriched['metadataPending'] = pending if not fetch else False
        return enriched, warning

    def library_metadata(self, request):
        game_id = str(request.get('gameId', ''))
        with self._metadata_lock:
            lock = self._metadata_locks.setdefault(game_id, threading.Lock())
        with lock:
            _, saved = self._catalog_id(game_id)
            game, warning = self._enrich_library_game(
                saved, refresh=bool(request.get('refresh'))
            )
            game = self._save_game(game['catalogProviderId'], game)
            return {
                'game': self._with_library_indicators([game])[0],
                'warning': warning,
            }

    def _filter_options(self):
        key = 'catalog-filters:igdb:v1'
        cached, _ = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached
        options = self.catalogue.filters()
        self._cache_put(key, options)
        return options

    def set_favorite(self, request):
        game_id = str(request.get('gameId', ''))
        favorite = bool(request.get('favorite'))
        with self._db() as db:
            found = db.execute('SELECT 1 FROM games WHERE id=?', (game_id,)).fetchone()
            if not found:
                raise GamesError('Select a game before saving a favorite.')
            if favorite:
                db.execute(
                    'INSERT OR IGNORE INTO favorites(game_id) VALUES(?)', (game_id,)
                )
            else:
                db.execute('DELETE FROM favorites WHERE game_id=?', (game_id,))
        return {'favorite': favorite}

    def _favorite_games(self, query, offset):
        with self._db() as db:
            rows = db.execute("""
                SELECT games.payload FROM games
                JOIN favorites ON favorites.game_id = games.id
                ORDER BY games.updated DESC, games.id
            """).fetchall()
        values = []
        normalized_query = query.casefold()
        for row in rows:
            try:
                game = json.loads(row['payload'])
            except (TypeError, ValueError):
                continue
            if (
                not normalized_query
                or normalized_query in str(game.get('title', '')).casefold()
            ):
                values.append(game)
        # Library listings rewrite launcher-only rows; restore their cached metadata.
        page = [
            self._enrich_library_game(game, fetch=False)[0]
            if game.get('catalogProvider') == 'library'
            else game
            for game in values[offset : offset + PAGE_SIZE]
        ]
        return {
            'items': self._with_library_indicators(page),
            'next': offset + PAGE_SIZE if len(values) > offset + PAGE_SIZE else None,
            'setupRequired': False,
            'warning': '',
            'provider': 'igdb',
        }

    def _browse_filters(self, filters):
        filters = filters if isinstance(filters, dict) else {}
        params = {}
        for field, parameter in (('genre', 'genres'), ('platform', 'platforms')):
            value = str(filters.get(field, '') or '').strip()
            if value:
                if not value.isdigit() or int(value) <= 0:
                    raise GamesError('Choose a valid genre or platform filter.')
                params[parameter] = str(int(value))
        ordering = str(filters.get('sort', '-added') or '-added')
        if ordering not in {'-added', '-rating', '-released', '-updated', 'name'}:
            raise GamesError('Choose a valid sort order.')
        params['ordering'] = ordering
        start = str(filters.get('fromYear', '') or '').strip()
        end = str(filters.get('toYear', '') or '').strip()
        for value in (start, end):
            if value and (
                not value.isdigit() or not 1970 <= int(value) <= datetime.now().year + 8
            ):
                raise GamesError(
                    'Enter a release year between 1970 and eight years from now.'
                )
        if start and end and int(start) > int(end):
            raise GamesError('The start year must not be later than the end year.')
        if start or end:
            start_year = start or '1970'
            end_year = end or str(datetime.now().year + 8)
            params['dates'] = f'{start_year}-01-01,{end_year}-12-31'
        return params

    def browse(self, request):
        query = _safe_text(request.get('query', ''), 120).strip()
        offset = max(0, min(int(request.get('offset', 0) or 0), 100000))
        if request.get('favorites'):
            return self._favorite_games(query, offset)
        filter_params = self._browse_filters(request.get('filters', {}))
        catalog = self.config_state()
        key = (
            'browse:v4:'
            + hashlib.sha256(
                json.dumps(
                    ['igdb', query.casefold(), filter_params, offset], sort_keys=True
                ).encode()
            ).hexdigest()
        )
        cached, fresh = self._cache_get(key, 900)
        if cached is not None and not request.get('refresh'):
            cached['items'] = self._with_library_indicators(cached.get('items', []))
            return cached
        stale, _ = self._cache_get(key, 900, allow_stale=True)
        if not catalog['configured']:
            if stale:
                stale['warning'] = (
                    'Showing saved results. Add the catalogue API key to refresh them.'
                )
                stale['items'] = self._with_library_indicators(stale.get('items', []))
                return stale
            return {
                'items': [],
                'next': None,
                'setupRequired': True,
                'warning': catalog['message'],
            }
        try:
            raw_games = self.catalogue.browse(query, filter_params, offset, PAGE_SIZE)
            has_next = len(raw_games) == PAGE_SIZE
            items = []
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                for raw in raw_games:
                    if (
                        not isinstance(raw, dict)
                        or not raw.get('id')
                        or not raw.get('name')
                    ):
                        continue
                    normalized = normalize_igdb_game(raw)
                    items.append(
                        self._save_game(str(raw['id']), normalized, connection=db)
                    )
            result = {
                'items': self._with_library_indicators(items),
                'next': offset + PAGE_SIZE if has_next else None,
                'setupRequired': False,
                'warning': '',
                'provider': 'igdb',
                'providerName': 'IGDB',
            }
            self._cache_put(key, result)
            return result
        except GamesError as error:
            if stale:
                stale['warning'] = str(error) + ' Showing saved results.'
                stale['items'] = self._with_library_indicators(stale.get('items', []))
                return stale
            raise

    def details(self, request):
        result = self._details(request)
        game = result['game']
        if game.get('catalogProvider') == 'igdb':
            game, warning = self._enrich_library_game(
                game,
                fetch=not game.get('summary') or not game.get('cover'),
                refresh=bool(request.get('refresh')),
            )
            # Keep catalogue ownership and personal identity when substituting fields.
            game = self._save_game(game['catalogProviderId'], game)
            result['game'] = self._with_library_indicators([game])[0]
            if warning:
                result['warning'] = '\n'.join(
                    filter(None, [result.get('warning'), warning])
                )
        return result

    def _details(self, request):
        game_id = str(request.get('gameId', ''))
        _, saved = self._catalog_id(game_id)
        provider_id = str(saved.get('catalogProviderId', ''))
        if saved.get('catalogProvider') != 'igdb':
            if saved.get('catalogProvider') == 'library':
                return self.library_metadata(request)
            return {
                'game': self._with_library_indicators([saved])[0],
                'warning': ''
                if saved.get('catalogProvider') == 'library'
                else 'Search the catalogue to refresh this saved game.',
            }
        key = f'detail:v3:igdb:{provider_id}'
        cached, fresh = self._cache_get(key, 7 * 86400)
        if cached and not request.get('refresh'):
            return {'game': self._with_library_indicators([cached])[0], 'warning': ''}
        current_catalog = self.config_state()
        if not current_catalog['configured']:
            return {
                'game': self._with_library_indicators([saved])[0],
                'warning': current_catalog['message'],
            }
        try:
            raw = self.catalogue.details(provider_id)
            if not raw:
                raise GamesError('The game catalogue no longer has this game record.')
            game = self._save_game(provider_id, normalize_igdb_game(raw, game_id))
            self._cache_put(key, game)
            return {'game': self._with_library_indicators([game])[0], 'warning': ''}
        except GamesError as error:
            if cached:
                return {
                    'game': self._with_library_indicators([cached])[0],
                    'warning': str(error) + ' Showing saved details.',
                }
            return {
                'game': self._with_library_indicators([saved])[0],
                'warning': str(error),
            }

    def protondb(self, request):
        global _LAST_PROTONDB_REQUEST
        game_id = str(request.get('gameId', ''))
        _, game = self._catalog_id(game_id)
        override = self._store_overrides(game_id).get('steam', '')
        app_id = steam_app_id(game, self.libraries(), override)
        if not app_id:
            return {
                'available': False,
                'tier': 'unknown',
                'label': 'Unavailable',
                'url': '',
                'total': 0,
            }
        key = f'protondb:v1:{app_id}'
        cached, fresh = self._cache_get(key, 7 * 86400)
        if cached is not None:
            return cached
        cooling, _ = self._cache_get(f'protondb-cooldown:v1:{app_id}', 300)
        if cooling:
            return {
                'available': True,
                'tier': 'unknown',
                'label': 'Unknown',
                'total': 0,
                'url': protondb_url(app_id),
                'appId': app_id,
                'warning': 'Compatibility summary is temporarily unavailable.',
            }
        try:
            with _PROTONDB_LOCK:
                elapsed = time.monotonic() - _LAST_PROTONDB_REQUEST
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                _LAST_PROTONDB_REQUEST = time.monotonic()
            raw = self._request(
                PROTONDB_SUMMARY.format(app_id),
                'GET',
                {'Accept': 'application/json'},
                None,
                8,
                128 * 1024,
            )
            if not isinstance(raw, dict):
                raise GamesError('ProtonDB returned an unexpected summary.')
            tier = str(raw.get('tier', '')).casefold()
            if tier not in ALLOWED_PROTONDB_TIERS:
                tier = 'unknown'
            summary = {
                'available': True,
                'tier': tier,
                'label': tier.title() if tier != 'unknown' else 'Unknown',
                'trendingTier': str(raw.get('trendingTier', '')).casefold()
                if str(raw.get('trendingTier', '')).casefold() in ALLOWED_PROTONDB_TIERS
                else '',
                'total': max(0, int(raw.get('total', 0) or 0)),
                'confidence': _safe_text(raw.get('confidence', ''), 24),
                'url': protondb_url(app_id),
                'appId': app_id,
            }
            self._cache_put(key, summary)
            return summary
        except (GamesError, ValueError, TypeError):
            stale, _ = self._cache_get(key, 7 * 86400, allow_stale=True)
            if stale:
                stale['stale'] = True
                return stale
            self._cache_put(f'protondb-cooldown:v1:{app_id}', {'unavailable': True})
            return {
                'available': True,
                'tier': 'unknown',
                'label': 'Unknown',
                'total': 0,
                'url': protondb_url(app_id),
                'appId': app_id,
                'warning': 'Compatibility summary is unavailable.',
            }

    def _which(self, name):
        return shutil.which(name, path=self.env.get('PATH'))

    def _steam_roots(self):
        home = Path(self.env.get('HOME', str(Path.home())))
        data_home = Path(self.env.get('XDG_DATA_HOME', home / '.local/share'))
        candidates = [
            home / '.steam/steam',
            home / '.steam/root',
            data_home / 'Steam',
            home / '.var/app/com.valvesoftware.Steam/.local/share/Steam',
        ]
        roots, seen = [], set()
        for candidate in candidates:
            try:
                resolved = candidate.expanduser().resolve(strict=False)
            except OSError:
                continue
            if resolved in seen or not (resolved / 'steamapps').is_dir():
                continue
            seen.add(resolved)
            roots.append(resolved)
        return roots

    def _steam_libraries(self):
        roots = self._steam_roots()
        libraries = []
        for root in roots:
            folders = root / 'steamapps/libraryfolders.vdf'
            paths = [root]
            try:
                data = parse_vdf(folders.read_text(encoding='utf-8', errors='replace'))
                sections = data.get('libraryfolders', data)
                if isinstance(sections, dict):
                    for key, value in sections.items():
                        if not str(key).isdigit():
                            continue
                        path = (
                            value.get('path', '') if isinstance(value, dict) else value
                        )
                        if isinstance(path, str) and path:
                            paths.append(Path(path).expanduser())
            except (OSError, ValueError):
                pass
            for path in paths:
                try:
                    resolved = path.resolve(strict=False)
                except OSError:
                    continue
                if resolved not in libraries and (resolved / 'steamapps').is_dir():
                    libraries.append(resolved)
        return roots, libraries

    def _steam_owned_state(self):
        config = self.config()
        api_key = _safe_text(config.get('steam_api_key', '')).strip()
        steam_id = _safe_text(config.get('steam_id', '')).strip()
        valid_steam_id = bool(re.fullmatch(r'[0-9]{17}', steam_id))
        if not api_key or not valid_steam_id:
            if api_key and not valid_steam_id:
                message = 'Add your 17-digit SteamID64 to check ownership.'
            elif valid_steam_id and not api_key:
                message = 'Add a Steam Web API key to check ownership.'
            else:
                message = ''
            return {
                'configured': False,
                'known': False,
                'ids': [],
                'games': [],
                'message': message,
            }
        cache_key = (
            'steam-owned:'
            + hashlib.sha256((api_key + ':' + steam_id).encode()).hexdigest()
        )
        cached, fresh = self._cache_get(cache_key, 1800)
        if cached:
            return {
                'configured': True,
                'known': bool(cached.get('known')),
                'ids': cached.get('ids', []),
                'games': cached.get('games', []),
                'message': cached.get('message', ''),
            }
        key = urllib.parse.urlencode({'key': api_key, 'steamids': steam_id})
        try:
            players = self._request(
                'https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?' + key,
                'GET',
                {'Accept': 'application/json'},
                None,
                8,
                512 * 1024,
            )
            player_response = (
                (players or {}).get('response') if isinstance(players, dict) else None
            )
            player_list = (
                player_response.get('players')
                if isinstance(player_response, dict)
                else None
            )
            if (
                not isinstance(player_list, list)
                or not player_list
                or not isinstance(player_list[0], dict)
            ):
                result = {
                    'known': False,
                    'ids': [],
                    'message': 'Steam profile is private or unavailable.',
                }
            else:
                visibility = int(player_list[0].get('communityvisibilitystate', 0))
                if visibility != 3:
                    result = {
                        'known': False,
                        'ids': [],
                        'message': 'Steam profile is private or unavailable.',
                    }
                else:
                    query = urllib.parse.urlencode(
                        {
                            'key': api_key,
                            'steamid': steam_id,
                            'include_appinfo': 'true',
                            'include_played_free_games': 'true',
                        }
                    )
                    owned = self._request(
                        'https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?'
                        + query,
                        'GET',
                        {'Accept': 'application/json'},
                        None,
                        12,
                        4 * 1024 * 1024,
                    )
                    games = parse_steam_owned_games(owned)
                    if games is None:
                        result = {
                            'known': False,
                            'ids': [],
                            'message': 'Steam game details are private or unavailable.',
                        }
                    else:
                        result = {
                            'known': True,
                            'ids': [game['externalId'] for game in games],
                            'games': games,
                            'message': '',
                        }
        except (GamesError, TypeError, ValueError):
            result = {
                'known': False,
                'ids': [],
                'games': [],
                'message': 'Steam ownership could not be checked.',
            }
        self._cache_put(cache_key, result)
        return {'configured': True, **result}

    def _steam_state(self):
        executable = self._which('steam')
        if not executable:
            for root in self._steam_roots():
                candidate = root / 'steam.sh'
                if candidate.is_file():
                    executable = str(candidate)
                    break
        roots, libraries = self._steam_libraries()
        installed_items, seen = [], set()
        for library in libraries:
            for manifest_path in sorted(
                (library / 'steamapps').glob('appmanifest_*.acf')
            ):
                try:
                    raw = parse_vdf(
                        manifest_path.read_text(encoding='utf-8', errors='replace')
                    )
                    item = steam_manifest(raw, library, manifest_path)
                except (OSError, ValueError):
                    item = None
                if not item or item['externalId'] in seen:
                    continue
                seen.add(item['externalId'])
                item['launchable'] = bool(executable)
                installed_items.append(item)
        owned = self._steam_owned_state()
        items_by_id = {game['externalId']: game for game in owned.get('games', [])}
        for item in installed_items:
            merged = dict(items_by_id.get(item['externalId'], {}))
            merged.update(item)
            items_by_id[item['externalId']] = merged
        items = list(items_by_id.values())
        return {
            'available': bool(executable),
            'executable': executable or '',
            'items': items,
            'ownedIds': owned.get('ids', []),
            'ownershipKnown': bool(owned.get('known')),
            'ownershipConfigured': bool(owned.get('configured')),
            'installationKnown': bool(libraries),
            'message': owned.get('message', '')
            or (
                'Steam client was not found.'
                if not executable and roots
                else 'Steam was not found.'
                if not roots
                else ''
            ),
        }

    def _run_legendary_json(self, args, timeout=20):
        executable = self._which('legendary')
        if not executable:
            return None, 'missing'
        try:
            result = self._runner(
                [executable, *args],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=self.env,
            )
        except FileNotFoundError:
            return None, 'missing'
        except (OSError, subprocess.SubprocessError):
            return None, 'error'
        if result.returncode != 0:
            combined = ((result.stderr or '') + ' ' + (result.stdout or '')).casefold()
            return None, 'unauthenticated' if any(
                word in combined for word in ('login', 'auth', 'token', 'credential')
            ) else 'error'
        try:
            return json.loads(result.stdout or '[]'), 'ok'
        except (TypeError, ValueError):
            return None, 'malformed'

    def _epic_state(self):
        executable = self._which('legendary')
        if not executable:
            return {
                'available': False,
                'ownershipKnown': False,
                'items': [],
                'ownedIds': [],
                'installationKnown': False,
                'message': 'Legendary is not installed on PATH.',
            }
        owned_raw, owned_status = self._run_legendary_json(['list', '--json'])
        installed_raw, installed_status = self._run_legendary_json(
            ['list-installed', '--json', '--show-dirs']
        )
        owned = parse_legendary_owned(owned_raw) if owned_status == 'ok' else []
        installed = (
            parse_legendary_installed(installed_raw) if installed_status == 'ok' else []
        )
        owned_by_id = {game['externalId']: game for game in owned}
        for item in installed:
            owned_by_id[item['externalId']] = {
                **owned_by_id.get(item['externalId'], {}),
                **item,
                'launchable': True,
            }
        authenticated = owned_status == 'ok'
        status = owned_status if owned_status != 'ok' else installed_status
        if status == 'unauthenticated':
            message = 'Sign in with Legendary to show Epic ownership.'
        elif status == 'missing':
            message = 'Legendary is not installed on PATH.'
        elif status in ('error', 'malformed'):
            message = 'Legendary could not read the Epic library.'
        else:
            message = ''
        return {
            'available': True,
            'ownershipKnown': authenticated,
            'installationKnown': installed_status == 'ok',
            'ownedIds': [game['externalId'] for game in owned],
            'items': list(owned_by_id.values()),
            'message': message,
        }

    def libraries(self, force=False):
        with self._library_lock:
            if (
                not force
                and self._library_snapshot
                and self._clock() - self._library_updated < 60
            ):
                return self._library_snapshot
            snapshot = {
                'steam': self._steam_state(),
                'epic': self._epic_state(),
                'gog': gog.read(self.env, self._which, self._runner),
            }
            self._library_snapshot = snapshot
            self._library_updated = self._clock()
            self._cache_put('libraries:v1', snapshot)
            return snapshot

    def init(self):
        return {'catalog': self.config_state()}

    def availability(self, request):
        game_id = str(request.get('gameId', ''))
        _, game = self._catalog_id(game_id)
        state = self.libraries()
        overrides = self._store_overrides(game_id)
        return {'stores': derive_store_state(game, state, overrides)}

    def presentation(self, request):
        _, game = self._catalog_id(request.get('gameId', ''))
        override = self._store_overrides(game['id']).get('steam', '')
        app_id = steam_app_id(game, self.libraries(), override)
        return presentation.read(self, app_id)

    def howlongtobeat(self, request):
        _, game = self._catalog_id(request.get('gameId', ''))
        with self._db() as db:
            row = db.execute(
                'SELECT external_id FROM hltb_matches WHERE game_id=?', (game['id'],)
            ).fetchone()
        override = row['external_id'] if row else ''
        steam_override = self._store_overrides(game['id']).get('steam', '')
        app_id = steam_app_id(game, self.libraries(), steam_override)
        key = (
            'hltb:v1:'
            + hashlib.sha256(
                json.dumps([game['title'], app_id, override]).encode()
            ).hexdigest()
        )
        saved, fresh = self._cache_get(key, 30 * 86400, allow_stale=True)
        cooling, _ = self._cache_get(key + ':retry', 300)
        if not request.get('refresh') and fresh:
            return {**saved, 'override': override}
        if not request.get('refresh') and cooling:
            return {
                **(saved or {}),
                **cooling,
                'stale': bool(saved),
                'override': override,
            }
        try:
            result = self.beat_times.lookup(game['title'], app_id, override, _title_key)
            self._cache_put(key, result)
            return {**result, 'override': override}
        except hltb.HltbError:
            warning = 'HowLongToBeat is unavailable. ' + (
                'Showing saved times.'
                if saved
                else 'Try again later or set a game link.'
            )
            self._cache_put(key + ':retry', {'warning': warning})
            return {
                **(saved or {}),
                'warning': warning,
                'stale': bool(saved),
                'override': override,
            }

    def set_hltb_match(self, request):
        _, game = self._catalog_id(request.get('gameId', ''))
        value = str(request.get('externalId', '')).strip()
        try:
            identifier = hltb.game_id(value) if value else ''
        except hltb.HltbError as error:
            raise GamesError(str(error)) from None
        with self._db() as db:
            if identifier:
                db.execute(
                    'INSERT OR REPLACE INTO hltb_matches VALUES(?,?)',
                    (game['id'], identifier),
                )
            else:
                db.execute('DELETE FROM hltb_matches WHERE game_id=?', (game['id'],))
        return {'override': identifier}

    def _umu_game_id(self, app_name):
        safe_name = _safe_text(app_name, 160).strip()
        if not safe_name:
            return 'umu-default'
        key = (
            'umu-id:v1:egs:' + hashlib.sha256(safe_name.casefold().encode()).hexdigest()
        )
        cached, fresh = self._cache_get(key, 30 * 86400)
        if cached:
            return str(cached.get('gameId', 'umu-default'))
        query = urllib.parse.urlencode({'store': 'egs', 'codename': safe_name})
        try:
            result = self._request(
                UMU_DATABASE + '?' + query,
                'GET',
                {'Accept': 'application/json'},
                None,
                8,
                512 * 1024,
            )
            records = result if isinstance(result, list) else _json_records(result)
            game_id = 'umu-default'
            for record in records:
                value = str(record.get('umu_id', record.get('umuId', '')))
                if re.fullmatch(r'umu-[A-Za-z0-9_-]{1,120}', value):
                    game_id = value
                    break
        except GamesError:
            game_id = 'umu-default'
        self._cache_put(key, {'gameId': game_id})
        return game_id

    def _launch_epic(self, game_id, game, app_name):
        executable = self._which('legendary')
        if not executable:
            raise GamesError(
                'Legendary is not installed. Install it to launch Epic games.'
            )
        args = [executable, 'launch', app_name]
        env = dict(self.env)
        if self._which('umu-run'):
            steam_references = [
                ref.get('externalId', '')
                for ref in (game.get('storeReferences') or [])
                if ref.get('store') == 'steam'
            ]
            override = self._store_overrides(game_id).get('steam', '')
            steam_id = _steam_id(
                override or (steam_references[0] if len(steam_references) == 1 else '')
            )
            game_id_for_umu = (
                'umu-' + steam_id if steam_id else self._umu_game_id(app_name)
            )
            prefix_key = hashlib.sha256(
                ('egs:' + app_name.casefold()).encode()
            ).hexdigest()[:24]
            prefix_root = self.data_root / 'prefixes/egs' / prefix_key
            prefix_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            env['GAMEID'] = game_id_for_umu
            env['STORE'] = 'egs'
            env['WINEPREFIX'] = str(prefix_root)
            proton_path = _safe_text(self.config().get('proton_path', '')).strip()
            if proton_path and Path(proton_path).is_dir():
                env['PROTONPATH'] = proton_path
            args.extend(['--wrapper', 'umu-run', '--no-wine'])
        self._spawn_detached(
            args, 'The Epic launcher could not start this game.', env=env
        )
        return {'started': True, 'message': 'Epic launch started.'}

    def _spawn_detached(self, args, failure_message, env=None):
        if manager := self._which('uwsm'):
            args = [manager, 'app', '-t', 'service', '--', *args]
        try:
            process = self._popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        except (FileNotFoundError, OSError):
            raise GamesError(failure_message) from None
        # Launchers often hand off to another process. Detect quick startup failures,
        # but leave games and downloads running after that initial handoff.
        if isinstance(process, subprocess.Popen):
            for _ in range(8):
                time.sleep(0.025)
                exit_code = process.poll()
                if exit_code is not None:
                    if exit_code != 0:
                        raise GamesError(f'{failure_message} Exit code {exit_code}.')
                    break
        return process

    def action(self, request):
        game_id = str(request.get('gameId', ''))
        action_id = str(request.get('actionId', ''))
        _, game = self._catalog_id(game_id)
        stores = self.availability({'gameId': game_id})['stores']
        action = next(
            (
                value
                for row in stores
                for value in row['actions']
                if value['id'] == action_id
            ),
            None,
        )
        if not action:
            raise GamesError(
                'This action is no longer available. Refresh the library and try again.'
            )
        kind, store = action['type'], action['store']
        external_id = action_id.rsplit(':', 1)[-1]
        state = self.libraries()[store]
        if store == 'gog':
            current = gog.read(self.env, self._which, self._runner)
            command = current.get('command')
            if not command:
                raise GamesError('Heroic Games Launcher is not available.')
            if kind == 'manage':
                self._spawn_detached(command, 'Heroic could not be opened.')
            else:
                identifier = gog.product_id(external_id)
                match, _ = match_library_item(
                    game,
                    'gog',
                    current.get('items', []),
                    self._store_overrides(game_id).get('gog', ''),
                )
                if not identifier or not match or match.get('externalId') != identifier:
                    raise GamesError(
                        "GOG's library changed. Refresh Games and try again."
                    )
                if kind == 'play' and not match.get('launchable'):
                    raise GamesError(
                        'Heroic no longer reports this GOG game as installed and launchable.'
                    )
                if kind == 'install' and (
                    not current.get('ownershipKnown')
                    or identifier not in current.get('ownedIds', [])
                    or not current.get('installationKnown')
                    or match.get('installed')
                ):
                    raise GamesError(
                        'Refresh GOG ownership and installations in Heroic before installing.'
                    )
                self._spawn_detached(
                    [*command, f'heroic://launch/gog/{identifier}'],
                    f'Heroic could not start the {kind}.',
                )
            return {
                'started': True,
                'handoff': True,
                'message': 'Opened GOG in Heroic.',
            }
        if store == 'steam':
            app_id = _steam_id(external_id)
            executable = state.get('executable') or self._which('steam')
            if not app_id or not executable:
                raise GamesError('Steam is not available for this game.')
            if kind == 'play':
                installation = next(
                    (
                        item
                        for item in state['items']
                        if item.get('externalId') == app_id
                    ),
                    None,
                )
                if not installation or not installation.get('launchable'):
                    raise GamesError(
                        'Steam no longer reports this game as installed and launchable.'
                    )
                self._spawn_detached(
                    [executable, '-applaunch', app_id],
                    'Steam could not launch this game.',
                )
                return {'started': True, 'message': 'Steam launch started.'}
            self._spawn_detached(
                [executable, f'steam://{kind}/{app_id}'],
                f'Steam could not start the {kind}.',
            )
            return {'started': True, 'message': f'Steam {kind} prompt opened.'}
        if kind == 'play':
            match, _ = match_library_item(
                game,
                'epic',
                state.get('items', []),
                self._store_overrides(game_id).get('epic', ''),
            )
            if (
                not match
                or match.get('externalId') != external_id
                or not match.get('installed')
            ):
                raise GamesError('Legendary no longer reports this game as installed.')
            return self._launch_epic(game_id, game, external_id)
        if not _epic_id(external_id):
            raise GamesError('Legendary returned an invalid Epic app name.')
        if kind == 'install' and (
            not state.get('ownershipKnown')
            or external_id not in state.get('ownedIds', [])
        ):
            raise GamesError(
                'Sign in with Legendary and refresh Epic ownership before installing.'
            )
        executable = self._which('legendary')
        if not executable:
            raise GamesError('Legendary is not installed.')
        self._spawn_detached(
            [executable, '--yes', kind, external_id],
            f'Legendary could not start the {kind}.',
        )
        return {'started': True, 'message': f'Epic {kind} started in Legendary.'}

    def handle(self, request):
        op = request.get('op')
        if op == 'local_list':
            return self.local.list('game')
        if op == 'local_files':
            return self.local.files(request['title'])
        if op == 'presentation':
            return self.presentation(request)
        if op == 'howlongtobeat':
            return self.howlongtobeat(request)
        if op == 'set_hltb_match':
            return self.set_hltb_match(request)
        if op == 'init':
            return self.init()
        if op == 'browse':
            return self.browse(request)
        if op == 'library_games':
            return self.library_games(request)
        if op == 'library_metadata':
            return self.library_metadata(request)
        if op == 'catalog_filters':
            if not self.config_state()['configured']:
                raise GamesError(
                    'Add the game catalogue API key in games.json to load filter options.'
                )
            return self._filter_options()
        if op == 'set_favorite':
            return self.set_favorite(request)
        if op == 'details':
            return self.details(request)
        if op == 'protondb':
            return self.protondb(request)
        if op == 'refresh_libraries':
            self.libraries(force=True)
            return {'catalog': self.config_state()}
        if op == 'availability':
            return self.availability(request)
        if op == 'set_match':
            return {
                'externalId': self._save_store_match(
                    request.get('gameId'),
                    request.get('store'),
                    request.get('externalId'),
                )
            }
        if op == 'action':
            return self.action(request)
        raise GamesError('Unknown Games service operation.')

    @cached_property
    def local(self):
        return LocalLibrary(self.data_root)


def main():
    os.umask(0o077)
    own_process_group()
    backend = GamesBackend()
    serve(
        backend.handle,
        errors=(GamesError, ValueError, OSError),
        background=('refresh_libraries', 'library_games', 'availability', 'protondb'),
        latest=(
            'browse',
            'library_games',
            'details',
            'availability',
            'protondb',
            'presentation',
            'howlongtobeat',
        ),
        controls=('set_favorite', 'set_match', 'set_hltb_match', 'action'),
    )


if __name__ == '__main__':
    main()
