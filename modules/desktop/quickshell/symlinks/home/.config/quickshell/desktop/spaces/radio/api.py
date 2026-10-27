"""Radio Browser discovery, genre normalization and finite pagination."""

import json
import math
import random
import re
import socket
import threading
from functools import lru_cache
from itertools import product
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PAGE_SIZE = 100
USER_AGENT = 'QuickshellDesktop/1.0 (Radio)'


class BrowseStream(TypedDict):
    tags: list[str]
    offset: int
    items: list[dict[str, Any]]
    cursor: int
    done: bool


class BrowseSession(TypedDict):
    streams: list[BrowseStream]
    seen: set[str]
    returned: int


browse_sessions: dict[str, BrowseSession] = {}
genre_variants = {}
browse_lock = threading.Lock()

GENRE_SYNONYMS = {
    'rocknroll': 'rock and roll',
    'rock n roll': 'rock and roll',
    'rock and roll': 'rock and roll',
    'hiphop': 'hip hop',
    'r and b': 'r&b',
    'r n b': 'r&b',
    'rnb': 'r&b',
    'rhythm and blues': 'r&b',
    'drum n bass': 'drum and bass',
    'drum and bass': 'drum and bass',
    'dnb': 'drum and bass',
    'lofi': 'lo fi',
    'kpop': 'k pop',
    'jpop': 'j pop',
    'edm': 'electronic dance music',
}
GENRE_LABELS = {
    'rock and roll': 'Rock & Roll',
    'hip hop': 'Hip-Hop',
    'r&b': 'R&B',
    'drum and bass': 'Drum and Bass',
    'lo fi': 'Lo-Fi',
    'k pop': 'K-Pop',
    'j pop': 'J-Pop',
    'electronic dance music': 'EDM',
}


class RadioError(Exception):
    pass


@lru_cache(maxsize=1)
def api_hosts():
    """Resolve the Radio Browser mirror pool and randomize the available mirrors."""
    hosts = set()
    try:
        addresses = socket.getaddrinfo(
            'all.api.radio-browser.info', 443, type=socket.SOCK_STREAM
        )
        for address in addresses:
            try:
                hostname = (
                    socket.gethostbyaddr(str(address[4][0]))[0].rstrip('.').lower()
                )
            except (OSError, socket.herror):
                continue
            if (
                hostname.endswith('.api.radio-browser.info')
                and hostname != 'all.api.radio-browser.info'
            ):
                hosts.add(hostname)
    except OSError:
        pass
    choices = list(hosts)
    random.shuffle(choices)
    # The pool name remains a DNS-backed fallback if reverse lookup is unavailable.
    choices.append('all.api.radio-browser.info')
    return choices


def api_get(path, params=None):
    query = '?' + urlencode(params) if params else ''
    last_error = None
    for host in api_hosts()[:3]:
        request = Request(
            'https://' + host + path + query,
            headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'},
        )
        try:
            with urlopen(request, timeout=8) as response:
                payload = response.read(8 * 1024 * 1024 + 1)
                if len(payload) > 8 * 1024 * 1024:
                    raise RadioError('The station directory returned too much data.')
                return json.loads(payload.decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
    raise RadioError(
        'The station directory is unavailable: '
        + (str(last_error) if last_error else 'no API mirrors were found.')
    )


def station_record(raw):
    if not isinstance(raw, dict):
        return None
    station_uuid = str(raw.get('stationuuid') or '').strip()
    name = str(raw.get('name') or '').strip()
    if not station_uuid or not name:
        return None
    return {
        'stationuuid': station_uuid,
        'name': name,
        'country': str(raw.get('country') or '').strip(),
        'countrycode': str(raw.get('countrycode') or '').strip().upper(),
        'tags': str(raw.get('tags') or '').strip(),
        'favicon': str(raw.get('favicon') or '').strip(),
        'homepage': str(raw.get('homepage') or '').strip(),
        'url': str(raw.get('url') or '').strip(),
        'url_resolved': str(raw.get('url_resolved') or '').strip(),
        'language': str(raw.get('language') or '').strip(),
        'codec': str(raw.get('codec') or '').strip(),
        'bitrate': safe_int(raw.get('bitrate')),
        'clickcount': safe_int(raw.get('clickcount')),
        'source': 'nextcloud' if raw.get('source') == 'nextcloud' else '',
    }


def safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def list_countries():
    rows = api_get(
        '/json/countries', {'order': 'name', 'hidebroken': 'true', 'limit': 1000}
    )
    if not isinstance(rows, list):
        raise RadioError('The station directory returned an invalid country list.')
    return [
        {
            'name': str(row.get('name') or '').strip(),
            'stationcount': safe_int(row.get('stationcount')),
        }
        for row in rows
        if isinstance(row, dict) and str(row.get('name') or '').strip()
    ]


def list_genres():
    rows = api_get(
        '/json/tags',
        {
            'order': 'stationcount',
            'reverse': 'true',
            'hidebroken': 'true',
            'limit': 2000,
        },
    )
    if not isinstance(rows, list):
        raise RadioError('The station directory returned an invalid genre list.')
    grouped = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or '').strip()
        if not name:
            continue
        key = genre_key(name)
        count = safe_int(row.get('stationcount'))
        group = grouped.setdefault(key, {'stationcount': 0, 'variants': []})
        group['stationcount'] = max(group['stationcount'], count)
        if name not in [variant['name'] for variant in group['variants']]:
            group['variants'].append({'name': name, 'stationcount': count})

    result = []
    genre_variants.clear()
    for key, group in grouped.items():
        variants = sorted(
            group['variants'],
            key=lambda item: (-item['stationcount'], item['name'].casefold()),
        )
        label = GENRE_LABELS.get(key, variants[0]['name'])
        genre_variants[label] = [item['name'] for item in variants]
        result.append(
            {
                'name': label,
                'stationcount': group['stationcount'],
                'variants': genre_variants[label],
            }
        )
    return sorted(
        result, key=lambda item: (-item['stationcount'], item['name'].casefold())
    )


def genre_key(name):
    value = name.casefold().replace('&', ' and ').replace('’', "'").replace('‘', "'")
    value = re.sub(r"['`\"]", '', value)
    value = re.sub(r'[^a-z0-9]+', ' ', value).strip()
    value = re.sub(r'\s+', ' ', value)
    return GENRE_SYNONYMS.get(value, value)


def station_search(query, country, offset, tags):
    params = {
        'order': 'clickcount',
        'reverse': 'true',
        'hidebroken': 'true',
        'limit': PAGE_SIZE,
        'offset': offset,
    }
    if query:
        params['name'] = query
    if country:
        params['country'] = country
        params['countryExact'] = 'true'
    if tags:
        params['tagList'] = ','.join(tags)

    rows = api_get('/json/stations/search', params)
    if not isinstance(rows, list):
        raise RadioError('The station directory returned an invalid station list.')
    items = [station for row in rows if (station := station_record(row)) is not None]
    return {
        'items': items,
        'nextOffset': offset + PAGE_SIZE if len(rows) == PAGE_SIZE else -1,
    }


def browse_union(query, country, tag_filters, offset):
    key = json.dumps([query, country, tag_filters], ensure_ascii=False)
    session: BrowseSession | None = None if offset == 0 else browse_sessions.get(key)
    if session is None:
        if offset != 0:
            raise RadioError('The genre result page expired. Search again to continue.')
        session = {
            'streams': [
                {'tags': tags, 'offset': 0, 'items': [], 'cursor': 0, 'done': False}
                for tags in tag_filters
            ],
            'seen': set(),
            'returned': 0,
        }
        browse_sessions[key] = session
        while len(browse_sessions) > 8:
            del browse_sessions[next(iter(browse_sessions))]
    elif offset != session['returned']:
        raise RadioError('The genre result page expired. Search again to continue.')

    def stream_has_item(stream: BrowseStream):
        while stream['cursor'] >= len(stream['items']) and not stream['done']:
            result = station_search(query, country, stream['offset'], stream['tags'])
            stream['items'] = result['items']
            stream['cursor'] = 0
            stream['done'] = result['nextOffset'] < 0
            if not stream['done']:
                stream['offset'] = result['nextOffset']
            if not stream['items'] and stream['done']:
                return False
        return stream['cursor'] < len(stream['items'])

    items = []
    while len(items) < PAGE_SIZE:
        best_stream = None
        best_station = None
        for stream in session['streams']:
            if not stream_has_item(stream):
                continue
            candidate = stream['items'][stream['cursor']]
            if (
                best_station is None
                or candidate['clickcount'] > best_station['clickcount']
            ):
                best_stream = stream
                best_station = candidate
        if best_station is None or best_stream is None:
            break
        best_stream['cursor'] += 1
        if best_station['stationuuid'] in session['seen']:
            continue
        session['seen'].add(best_station['stationuuid'])
        items.append(best_station)

    session['returned'] += len(items)
    has_more = any(
        stream['cursor'] < len(stream['items']) or not stream['done']
        for stream in session['streams']
    )
    return {'items': items, 'nextOffset': session['returned'] if has_more else -1}


def browse(args):
    query = str(args.get('query') or '').strip()
    country = str(args.get('country') or '').strip()
    tags = args.get('tags') or []
    if not isinstance(tags, list):
        tags = []
    tags = list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip()))
    try:
        offset = max(0, int(args.get('offset') or 0))
    except (TypeError, ValueError):
        offset = 0

    if not tags:
        return station_search(query, country, offset, [])

    if not genre_variants:
        list_genres()
    groups = [genre_variants.get(tag, [tag]) for tag in tags]
    if math.prod(len(group) for group in groups) > 32:
        raise RadioError('Choose fewer genres to search their spelling variations.')
    tag_filters = [list(combo) for combo in product(*groups)]
    if len(tag_filters) == 1:
        return station_search(query, country, offset, tag_filters[0])
    return browse_union(query, country, tag_filters, offset)
