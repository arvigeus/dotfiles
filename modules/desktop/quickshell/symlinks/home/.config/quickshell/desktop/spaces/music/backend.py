"""Apple Music catalog and configurable playback providers for mpv."""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock

sys.path.append('/usr/local/lib/audio-tools')
import audio_lyrics

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integrations.subsonic import MusicError as CloudError
from spaces.books.jobs import Jobs, check_cancelled, current_job, progress
from spaces.movies.local import LocalLibrary, safe_name, xdg_dir
from spaces.music.cache import JsonCache
from spaces.music.cloud_stream import StreamBroker
from spaces.music.records import (
    MusicError,
    clean_artist_biography,
    normalize_apple,
    normalized,
    parse_playlist_id,
    safe_catalog_id,
    safe_playlist_id,
    safe_stream_id,
    score_candidate,
)
from spaces.music.storage import CONFIG, DATA, atomic_write, read_json
from spaces.music.storage import MusicIpc as MpvIpc
from spaces.pictures.command_provider import CommandRunner, safe_url
from spaces.pictures.provider_plugins import ProviderError, configured_providers

APPLE_API = 'https://api.music.apple.com/v1/catalog'
USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
SEARCH_PAGE_SIZE = 25
SEARCH_MAX_LIMIT = 500
_apple_token = ''
_apple_token_expires = 0.0
_apple_token_lock = Lock()
_music_config = None
_artist_artwork_cache = {}
_artist_biography_cache = {}
_artist_biography_lock = Lock()
JOBS = Jobs(errors=(MusicError, ValueError))
STREAMS = StreamBroker()
COMMANDS = CommandRunner(label='Music')
_download_processes = set()
_download_partials = set()
_download_processes_lock = Lock()


def music_config():
    global _music_config
    if _music_config is not None:
        return _music_config
    path = CONFIG / 'music.json'
    try:
        parsed = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        parsed = {}
        atomic_write(path, '{}')
    except (OSError, ValueError) as error:
        raise MusicError('The Music configuration file could not be read.') from error
    if not isinstance(parsed, dict):
        raise MusicError('The Music configuration must contain a JSON object.')
    storefront = str(parsed.get('storefront') or 'us').strip().lower()
    if not re.fullmatch(r'[a-z]{2}', storefront):
        raise MusicError(
            'The Apple Music storefront must be a two-letter country code.'
        )
    default_playlist = parse_playlist_id(parsed.get('default_playlist'))
    providers = parsed.get('providers') or []
    if not isinstance(providers, list):
        raise MusicError('Music providers must be a JSON array.')
    providers = [item for item in providers[:12] if isinstance(item, dict)]
    for provider in providers:
        if 'command' in provider or 'plugin' in provider:
            try:
                provider.update(
                    configured_providers({'providers': [provider]}, CONFIG)[0]
                )
            except ProviderError as error:
                raise MusicError('A Music command provider is invalid.') from error
        timeout = provider.get('timeout', 24)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 1 <= timeout <= 60
        ):
            raise MusicError(
                'A Music provider timeout must be between 1 and 60 seconds.'
            )
        download = provider.get('download')
        if download is None:
            continue
        if not isinstance(download, dict) or any(
            key in download and not isinstance(download[key], str)
            for key in ('track', 'album')
        ):
            raise MusicError(
                "A Music provider download must contain optional track and album URL templates or 'stream'."
            )
        if (
            any(
                str(download.get(key) or '').strip() == 'stream'
                for key in ('track', 'album')
            )
            and not provider.get('command')
            and (not provider.get('search_url') or not provider.get('stream_url'))
        ):
            raise MusicError(
                "Stream downloads require the provider's search_url and stream_url."
            )
    _music_config = {
        'storefront': storefront,
        'catalog_token': str(parsed.get('catalog_token') or '').strip(),
        'default_playlist': default_playlist,
        'providers': providers,
    }
    return _music_config


def clean_headers(values):
    headers = {}
    for name, value in values.items() if isinstance(values, dict) else ():
        name = str(name).strip()
        value = str(value).strip()
        if name and value and not any(char in name + value for char in '\r\n\0'):
            headers[name] = value
    return headers


def request_body(url, headers=None, timeout=24):
    request_headers = {'Accept': 'application/json', 'User-Agent': USER_AGENT}
    request_headers.update(clean_headers(headers))
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise MusicError(
                    'A configured music endpoint returned an oversized response.'
                )
            return body
    except urllib.error.HTTPError as error:
        error.close()
        if error.code in (502, 503, 504):
            raise MusicError(
                'A configured music endpoint is temporarily unavailable.'
            ) from error
        raise MusicError(
            'A configured music endpoint returned HTTP ' + str(error.code) + '.'
        ) from error
    except urllib.error.URLError as error:
        raise MusicError('Could not connect to a configured music endpoint.') from error
    except TimeoutError as error:
        raise MusicError('A configured music endpoint timed out.') from error


def request_json(url, headers=None, timeout=24):
    try:
        return json.loads(request_body(url, headers, timeout).decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MusicError(
            'A configured music endpoint returned unreadable JSON.'
        ) from error


class AppleArtistPageParser(HTMLParser):
    """Read Apple's serialized artist page payload without parsing the full DOM."""

    def __init__(self):
        super().__init__()
        self.capturing = False
        self.payload = []

    def handle_starttag(self, tag, attrs):
        if (
            tag.lower() == 'script'
            and dict(attrs).get('id') == 'serialized-server-data'
        ):
            self.capturing = True

    def handle_endtag(self, tag):
        if tag.lower() == 'script' and self.capturing:
            self.capturing = False

    def handle_data(self, data):
        if self.capturing:
            self.payload.append(data)


def apple_artist_page_biography(artist_id, artist_url):
    """Fetch the artist's public Apple Music page bio when catalog data omits it."""
    try:
        parsed = urllib.parse.urlsplit(str(artist_url or ''))
    except ValueError:
        return ''
    path_parts = [part for part in parsed.path.split('/') if part]
    if (
        parsed.scheme != 'https'
        or parsed.hostname != 'music.apple.com'
        or 'artist' not in path_parts
        or str(artist_id) not in path_parts
    ):
        return ''

    cache_key = str(artist_id)
    with _artist_biography_lock:
        cached = _artist_biography_cache.get(cache_key)
    if cached:
        return cached

    try:
        page = request_body(
            urllib.parse.urlunsplit(parsed),
            {'Accept': 'text/html,application/xhtml+xml'},
            timeout=12,
        ).decode('utf-8', errors='replace')
        parser = AppleArtistPageParser()
        parser.feed(page)
        payload = json.loads(''.join(parser.payload))
    except (MusicError, json.JSONDecodeError, ValueError):
        return ''

    biographies = []

    def collect_bios(value):
        if isinstance(value, dict):
            bio = value.get('bio')
            if isinstance(bio, str):
                cleaned = clean_artist_biography(bio)
                if cleaned:
                    biographies.append(cleaned)
            for nested in value.values():
                collect_bios(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_bios(nested)

    collect_bios(payload)
    biography = max(biographies, key=len, default='')
    if biography:
        with _artist_biography_lock:
            _artist_biography_cache[cache_key] = biography
    return biography


def decode_expiration(token):
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode('ascii')))
        return float(data.get('exp') or 0)
    except (IndexError, ValueError, TypeError, UnicodeEncodeError):
        return 0.0


def apple_token():
    global _apple_token, _apple_token_expires
    with _apple_token_lock:
        now = time.time()
        if _apple_token and now < _apple_token_expires:
            return _apple_token
        configured = music_config()['catalog_token']
        if not configured:
            raise MusicError(
                'Set catalog_token in music.json to browse the Apple Music catalog.'
            )
        if configured.lower().startswith(('https://', 'http://')):
            body = request_body(configured).decode('utf-8').strip()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = body
            if isinstance(data, dict):
                token = str(data.get('dev_token') or data.get('token') or '').strip()
                try:
                    endpoint_ttl = int(data.get('cache_ttl_seconds') or 300)
                except (TypeError, ValueError):
                    endpoint_ttl = 300
            else:
                token = str(data or '').strip()
                endpoint_ttl = 300
        else:
            token = configured.removeprefix('Bearer ').strip()
            endpoint_ttl = 21600
        if not token:
            raise MusicError('The configured catalog token source returned no token.')
        expiration = decode_expiration(token)
        if not expiration:
            ttl = max(60, endpoint_ttl)
            expiration = now + min(ttl, 21600)
        _apple_token = token
        _apple_token_expires = max(now + 30, expiration - 60)
        return token


@lru_cache(maxsize=1)
def catalog_cache():
    return JsonCache('music-catalogue')


def apple_get(url):
    return catalog_cache().load(
        url,
        900,
        lambda: request_json(url, {'Authorization': 'Bearer ' + apple_token()}),
    )


def apple_url(path, params=None):
    url = APPLE_API + '/' + music_config()['storefront'] + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    return apple_get(url)


def apple_cursor(cursor, path):
    """Follow an Apple `next` cursor only when it stays on the expected catalog path."""
    url = urllib.parse.urljoin(APPLE_API + '/', str(cursor or ''))
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != 'https'
        or parsed.netloc != 'api.music.apple.com'
        or parsed.path != f'/v1/catalog/{music_config()["storefront"]}{path}'
    ):
        raise MusicError('The catalogue returned an invalid page link.')
    return apple_get(url)


def apple_artist_song_cursor(artist_id, cursor):
    return apple_cursor(cursor, f'/artists/{artist_id}/view/top-songs')


def apple_songs(response):
    """Return (songs, raw count, next cursor) for one Apple song-list response."""
    raw_items = response.get('data') or []
    songs = [item for raw in raw_items if (item := normalize_apple(raw, 'songs'))]
    return songs, len(raw_items), str(response.get('next') or '')


def add_artist_artwork(artists):
    missing = []
    for artist in artists:
        artist_id = str(artist.get('id') or '')
        if artist.get('cover') or not re.fullmatch(r'[0-9]{1,32}', artist_id):
            continue
        if artist_id in _artist_artwork_cache:
            artist['cover'] = _artist_artwork_cache[artist_id]
        else:
            missing.append(artist_id)

    if missing:
        ids = list(dict.fromkeys(missing))[:25]
        try:
            raw_artists = (
                apple_url('/artists', {'ids': ','.join(ids)}).get('data') or []
            )
        except MusicError:
            return artists
        covers = {}
        for raw in raw_artists:
            record = normalize_apple(raw, 'artists')
            if record:
                covers[record['id']] = record.get('cover') or ''
        if len(_artist_artwork_cache) + len(ids) > 4096:
            _artist_artwork_cache.clear()
        for artist_id in ids:
            _artist_artwork_cache[artist_id] = covers.get(artist_id, '')
        for artist in artists:
            artist_id = str(artist.get('id') or '')
            if not artist.get('cover') and artist_id in covers:
                artist['cover'] = covers[artist_id]
    return artists


def genre_matches(resource, genre_name):
    names = resource.get('genreNames') or resource.get('genres') or []
    wanted = normalized(genre_name)
    return any(normalized(name) == wanted for name in names)


def apple_search_page(query, category, offset=0):
    params = {
        'term': query,
        'types': category,
        'limit': SEARCH_PAGE_SIZE,
        'offset': max(0, int(offset)),
    }
    data = apple_url('/search', params).get('results') or {}
    result = data.get(category) or {}
    raw_items = result.get('data') or []
    items = [item for raw in raw_items if (item := normalize_apple(raw, category))]
    return items, len(raw_items), bool(result.get('next'))


def load_genres():
    data = apple_url('/genres', {'limit': 100})
    options = []
    seen = set()
    for item in data.get('data', []):
        attributes = item.get('attributes') or {}
        genre_id = str(item.get('id') or '')
        name = str(attributes.get('name') or '').strip()
        if not genre_id or not name or normalized(name) == 'music' or genre_id in seen:
            continue
        seen.add(genre_id)
        options.append({'id': genre_id, 'name': name})
    options.sort(key=lambda item: item['name'].casefold())
    return options


def chart_items(results, category):
    items, raw_count, has_more = [], 0, False
    for chart in results.get(category) or []:
        raw_items = chart.get('data') or []
        raw_count += len(raw_items)
        items.extend(
            item for raw in raw_items if (item := normalize_apple(raw, category))
        )
        has_more = has_more or bool(chart.get('next'))
    return items, raw_count, has_more


def charts(types, genre_id='', offset=0):
    params = {'types': types, 'chart': 'most-played', 'limit': SEARCH_PAGE_SIZE}
    if genre_id:
        params['genre'] = safe_catalog_id(genre_id)
    if offset:
        params['offset'] = max(0, int(offset))
    return apple_url('/charts', params).get('results') or {}


def playlist_page(playlist_id, offset=0, limit=SEARCH_PAGE_SIZE, cursor=''):
    playlist_id = safe_playlist_id(playlist_id)
    if cursor:
        return apple_songs(apple_cursor(cursor, f'/playlists/{playlist_id}/tracks'))
    params = {'limit': min(100, max(1, int(limit)))}
    if offset:
        params['offset'] = max(0, int(offset))
    return apple_songs(apple_url('/playlists/' + playlist_id + '/tracks', params))


def derived_artists(resources):
    """Artist rows named by songs or albums, for views without an artist search."""
    artists, seen = [], set()
    for resource in resources:
        name = str(resource.get('artist') or '').strip()
        key = normalized(name)
        if not name or key in seen:
            continue
        seen.add(key)
        ids = resource.get('artistIds') or []
        artists.append(
            {
                'kind': 'artist',
                'id': ids[0] if ids else 'apple-name:' + key,
                'source': 'apple',
                'name': name,
                'cover': '',
                'genres': [],
            }
        )
    return artists


def derived_albums(songs):
    albums, seen = [], set()
    for song in songs:
        title = str(song.get('album') or '').strip()
        key = str(song.get('albumId') or '') or (
            normalized(title) + '|' + normalized(song.get('artist'))
        )
        if not title or key in seen:
            continue
        seen.add(key)
        albums.append(
            {
                'kind': 'album',
                'id': str(song.get('albumId') or 'name:' + key),
                'source': 'apple',
                'title': title,
                'artist': song.get('artist') or 'Unknown Artist',
                'artists': song.get('artists') or [],
                'artistIds': song.get('artistIds') or [],
                'cover': song.get('cover') or '',
                'releaseDate': song.get('releaseDate') or '',
            }
        )
    return albums


def playlist_results(playlist_id):
    songs, raw_count, cursor = playlist_page(playlist_id)
    return {
        'artists': derived_artists(songs),
        'albums': derived_albums(songs),
        'songs': songs,
        'paging': {
            'songs': {
                'limit': raw_count,
                'hasMore': bool(cursor) and raw_count < SEARCH_MAX_LIMIT,
                'cursor': cursor,
            },
        },
    }


def chart_results(genre_id=''):
    results = charts('songs,albums', genre_id)
    songs, song_count, songs_more = chart_items(results, 'songs')
    albums, album_count, albums_more = chart_items(results, 'albums')
    return {
        'artists': derived_artists(songs + albums),
        'albums': albums,
        'songs': songs,
        'paging': {
            'albums': {'limit': album_count, 'hasMore': albums_more},
            'songs': {'limit': song_count, 'hasMore': songs_more},
        },
    }


def search_page(args):
    query = str(args.get('query') or '').strip()
    category = str(args.get('category') or 'songs').strip().lower()
    if category not in ('artists', 'albums', 'songs'):
        raise MusicError('Unknown music result type.')
    genre_id = str(args.get('genreId') or '').strip()
    genre_name = str(args.get('genreName') or '').strip()
    offset = max(0, int(args.get('offset') or 0))
    cursor = ''
    playlist_id = '' if query else music_config()['default_playlist']
    if playlist_id:
        # The default playlist only fills the Songs view.
        if category != 'songs':
            items, raw_count, has_more = [], 0, False
        else:
            items, raw_count, cursor = playlist_page(
                playlist_id,
                offset,
                SEARCH_PAGE_SIZE,
                str(args.get('cursor') or ''),
            )
            has_more = bool(cursor)
            if genre_name:
                items = [item for item in items if genre_matches(item, genre_name)]
    elif not query:
        if category == 'artists':
            items, raw_count, has_more = [], 0, False
        else:
            items, raw_count, has_more = chart_items(
                charts(category, genre_id, offset), category
            )
    else:
        items, raw_count, has_more = apple_search_page(query, category, offset)
        if category == 'artists':
            items = add_artist_artwork(items)
        if genre_id and genre_name:
            items = [item for item in items if genre_matches(item, genre_name)]
    next_offset = offset + raw_count
    return {
        'category': category,
        'items': items,
        'hasMore': has_more,
        'limit': next_offset,
        'cursor': cursor,
    }


def search(args):
    query = str(args.get('query') or '').strip()
    kind = str(args.get('kind') or 'all').strip().lower()
    genre_id = str(args.get('genreId') or '').strip()
    genre_name = str(args.get('genreName') or '').strip()
    if not query:
        playlist_id = '' if genre_id else music_config()['default_playlist']
        return playlist_results(playlist_id) if playlist_id else chart_results(genre_id)

    categories = ('songs',) if kind == 'songs' else ('artists', 'albums', 'songs')
    page_args = {'query': query, 'genreId': genre_id, 'genreName': genre_name}
    pages = {}
    failures = []
    with ThreadPoolExecutor(max_workers=len(categories)) as pool:
        futures = {
            category: pool.submit(
                search_page,
                {**page_args, 'category': category, 'limit': SEARCH_PAGE_SIZE},
            )
            for category in categories
        }
        for category, future in futures.items():
            try:
                pages[category] = future.result()
            except MusicError as error:
                failures.append(str(error))
                pages[category] = {'items': [], 'hasMore': False, 'limit': 0}
    if not any(page.get('items') for page in pages.values()) and failures:
        raise MusicError(failures[0])
    results = {
        category: pages.get(category, {}).get('items', [])
        for category in ('artists', 'albums', 'songs')
    }
    results['paging'] = {
        category: {
            'limit': pages.get(category, {}).get('limit', 0),
            'hasMore': pages.get(category, {}).get('hasMore', False),
        }
        for category in ('artists', 'albums', 'songs')
    }
    return results


def find_apple_artists(name):
    data = (
        apple_url(
            '/search',
            {'term': name, 'types': 'artists', 'limit': 25},
        ).get('results')
        or {}
    )
    candidates = (data.get('artists') or {}).get('data') or []
    wanted = normalized(name)
    exact = [
        item
        for item in candidates
        if normalized((item.get('attributes') or {}).get('name')) == wanted
    ]
    if exact:
        candidates = exact[:1]
    else:
        matches = []
        for item in candidates:
            attributes = item.get('attributes') or {}
            candidate_name = normalized(attributes.get('name'))
            if len(candidate_name) < 3:
                continue
            pattern = r'(?<![a-z0-9])' + re.escape(candidate_name) + r'(?![a-z0-9])'
            match = re.search(pattern, wanted)
            if match:
                matches.append((match.start(), item))
        candidates = [item for _, item in sorted(matches, key=lambda pair: pair[0])]

    records = []
    seen = set()
    for item in candidates:
        artist = normalize_apple(item, 'artists')
        if artist and artist['id'] not in seen:
            records.append(artist)
            seen.add(artist['id'])
    return add_artist_artwork(records)


def apple_artist_albums(artist_id, offset=0, limit=25):
    artist_id = safe_catalog_id(artist_id)
    offset = max(0, int(offset))
    limit = min(25, max(1, int(limit)))
    data = apple_url(
        '/artists/' + artist_id + '/albums',
        {'limit': limit, 'offset': offset},
    )
    raw_albums = data.get('data') or []
    return {
        'items': [
            item for raw in raw_albums if (item := normalize_apple(raw, 'albums'))
        ],
        'offset': offset + len(raw_albums),
        'hasMore': bool(data.get('next')),
    }


def tracks_for_album(album, all_pages=False):
    album_id = safe_catalog_id(album.get('id'))
    songs = []
    offset = 0
    while True:
        data = apple_url(
            '/albums/' + album_id + '/tracks', {'limit': 100, 'offset': offset}
        )
        raw_items = data.get('data') or []
        for raw in raw_items:
            song = normalize_apple(raw, 'songs')
            if not song:
                continue
            song['albumId'] = album_id
            song['album'] = album.get('title') or song['album']
            for field in ('cover', 'artistIds', 'releaseDate'):
                song[field] = song[field] or album.get(field) or song[field]
            songs.append(song)
        if all_pages and data.get('next') and len(songs) >= 1000:
            raise MusicError('This album has more tracks than one download can save.')
        if not all_pages or not data.get('next') or not raw_items:
            break
        offset += len(raw_items)
    return songs


def catalog_artist_records(artist_ids, artist_names=None):
    ids = []
    for value in artist_ids or []:
        value = str(value or '').strip()
        if re.fullmatch(r'[0-9]{1,32}', value) and value not in ids:
            ids.append(value)
    if ids:
        try:
            data = apple_url('/artists', {'ids': ','.join(ids[:25])}).get('data') or []
            records = [
                item for raw in data if (item := normalize_apple(raw, 'artists'))
            ]
            if records:
                return records
        except MusicError:
            pass
    records = []
    seen = set()
    for name in artist_names or []:
        for artist in find_apple_artists(str(name or '')):
            if artist['id'] not in seen:
                records.append(artist)
                seen.add(artist['id'])
    return records


def unique_songs(songs):
    output = []
    seen = set()
    for song in songs:
        key = str(song.get('id') or '')
        if key and key not in seen:
            output.append(song)
            seen.add(key)
    return output


def catalog_artist_id(item):
    """Apple ID of an artist record, searching by name for rows without one."""
    artist_id = str(item.get('id') or '')
    if item.get('source') == 'apple' and re.fullmatch(r'[0-9]{1,32}', artist_id):
        return artist_id
    matches = find_apple_artists(str(item.get('name') or ''))
    return str(matches[0].get('id') or '') if matches else ''


def artist_details(item):
    artist_id = safe_catalog_id(catalog_artist_id(item))
    artist_data = apple_url('/artists/' + artist_id).get('data') or []
    artist = normalize_apple(artist_data[0], 'artists') if artist_data else item
    album_page = apple_artist_albums(artist_id)
    warning = ''
    try:
        top = apple_url('/artists/' + artist_id + '/view/top-songs', {'limit': 25})
        songs, _, cursor = apple_songs(top)
    except MusicError:
        songs, cursor = [], ''
        warning = 'Top songs could not load. Select an album to browse its tracks.'
    return {
        'artist': artist,
        'albums': album_page['items'],
        'albumPaging': {
            'artistId': artist_id,
            'offset': album_page['offset'],
            'hasMore': album_page['hasMore'],
        },
        'songPaging': {
            'artistId': artist_id,
            'cursor': cursor,
            'albumOffset': 0,
            'hasMore': bool(cursor or album_page['items']),
        },
        'songs': unique_songs(songs),
        'trackWarning': warning,
    }


def artist_songs_page(args):
    artist_id = safe_catalog_id(args.get('artistId'))
    cursor = str(args.get('cursor') or '')
    album_offset = max(0, int(args.get('albumOffset') or 0))
    if cursor:
        songs, _, next_cursor = apple_songs(apple_artist_song_cursor(artist_id, cursor))
        return {
            'items': unique_songs(songs),
            'cursor': next_cursor,
            'albumOffset': album_offset,
            'hasMore': True,
        }
    # The top-songs view is a ranking, not the artist's full catalogue. Fetch a
    # small album batch only when the Songs pane actually reaches its end.
    page = apple_artist_albums(artist_id, offset=album_offset, limit=2)
    albums = page['items']
    with ThreadPoolExecutor(max_workers=min(2, len(albums) or 1)) as pool:
        futures = [pool.submit(tracks_for_album, album) for album in albums]
        songs = []
        failures = 0
        for future in futures:
            try:
                songs.extend(future.result())
            except MusicError:
                failures += 1
    if failures and not songs:
        raise MusicError('Album tracks could not load. Reopen the artist to retry.')
    return {
        'items': unique_songs(songs),
        'cursor': '',
        'albumOffset': page['offset'],
        'hasMore': page['hasMore'],
        'trackWarning': 'Some album tracks could not load.' if failures else '',
    }


def artist_info(item):
    if not isinstance(item, dict):
        raise MusicError('Invalid artist for information lookup.')
    artist_id = catalog_artist_id(item)
    if not artist_id:
        return {'artist': item, 'available': False}
    data = (
        apple_url('/artists/' + artist_id, {'extend': 'editorialNotes'}).get('data')
        or []
    )
    artist = normalize_apple(data[0], 'artists') if data else None
    if not artist:
        return {'artist': item, 'available': False}
    artist['biography'] = apple_artist_page_biography(artist_id, artist['url'])
    has_info = bool(
        artist.get('genres')
        or artist.get('cover')
        or artist.get('url')
        or artist.get('biography')
        or artist.get('editorialNotes')
    )
    return {'artist': artist, 'available': has_info}


def artist_albums_page(args):
    return apple_artist_albums(args.get('artistId'), offset=args.get('offset') or 0)


def album_details(item, include_tracks=True):
    album_id = str(item.get('id') or '')
    if str(item.get('source') or '') != 'apple' or not re.fullmatch(
        r'[0-9]{1,32}', album_id
    ):
        query = ' '.join(
            part
            for part in (str(item.get('artist') or ''), str(item.get('title') or ''))
            if part
        )
        matches = (
            apple_url('/search', {'term': query, 'types': 'albums', 'limit': 25})
            .get('results', {})
            .get('albums', {})
            .get('data', [])
        )
        wanted_title = normalized(item.get('title'))
        wanted_artist = normalized(item.get('artist'))
        match = next(
            (
                raw
                for raw in matches
                if normalized((raw.get('attributes') or {}).get('name')) == wanted_title
                and (
                    not wanted_artist
                    or normalized((raw.get('attributes') or {}).get('artistName'))
                    == wanted_artist
                )
            ),
            None,
        )
        album_id = str(match.get('id') or '') if match else ''
    album_id = safe_catalog_id(album_id)
    album_data = apple_url('/albums/' + album_id).get('data') or []
    album = normalize_apple(album_data[0], 'albums') if album_data else item
    artists = (
        catalog_artist_records(album.get('artistIds'), album.get('artists'))
        if include_tracks
        else []
    )
    return {
        'album': album,
        'artists': artists,
        'songs': tracks_for_album(album) if include_tracks else [],
    }


def song_artists(args):
    song = args.get('song') or {}
    return catalog_artist_records(
        song.get('artistIds'), song.get('artists') or [song.get('artist')]
    )


def value_at_path(value, path):
    current = value
    for part in str(path or '').split('.'):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def provider_template(provider, template_name, values, require_values=False):
    template = str(value_at_path(provider, template_name) or '').strip()
    if not template:
        return ''
    substitutions = {
        'base_url': str(provider.get('base_url') or '').rstrip('/'),
        **{key: str(value or '') for key, value in values.items()},
    }
    placeholders = re.findall(r'\{([^{}]+)\}', template)
    if any(key not in substitutions for key in placeholders):
        raise MusicError('A provider URL template has an unknown placeholder.')
    if require_values and any(not substitutions[key] for key in placeholders):
        raise MusicError(
            'This download URL needs metadata that is missing from the selected item.'
        )
    for key, value in substitutions.items():
        encoded = value if key == 'base_url' else urllib.parse.quote(value, safe='')
        template = template.replace('{' + key + '}', encoded)
    if re.search(r'\{[^{}]+\}', template):
        raise MusicError('A provider URL template has an unknown placeholder.')
    try:
        parsed = urllib.parse.urlparse(template)
        _ = parsed.port  # Reject malformed port numbers.
        valid = (
            parsed.scheme in ('http', 'https')
            and parsed.hostname
            and not re.search(r'\s', template)
        )
    except ValueError:
        valid = False
    if not valid:
        raise MusicError('A provider URL must use a valid HTTP or HTTPS address.')
    return template


def download_providers(kind):
    return [
        provider
        for provider in music_config()['providers']
        if str((provider.get('download') or {}).get(kind) or '').strip()
    ]


def download_provider(kind):
    return next(iter(download_providers(kind)), None)


def download_capabilities():
    return {kind: download_provider(kind) is not None for kind in ('track', 'album')}


def download_url(kind, item):
    if kind not in ('track', 'album') or not isinstance(item, dict):
        raise MusicError('Choose a song or album to download.')
    provider = download_provider(kind)
    if provider is None:
        raise MusicError('No download provider is configured for this item.')
    if provider['download'][kind].strip() == 'stream':
        raise MusicError(
            'This provider saves streams instead of opening a download URL.'
        )
    title = str(item.get('title') or '').strip()
    artist = str(item.get('artist') or '').strip()
    item_id = str(item.get('id') or '').strip()
    if kind == 'album' and item_id.startswith('name:'):
        item_id = ''  # Album rows inferred from a song may have a temporary name key.
    album_id = item.get('albumId') if kind == 'track' else item_id
    values = {
        'id': item_id,
        'track_id': item_id if kind == 'track' else '',
        'album_id': str(album_id or '').strip(),
        'title': title,
        'artist': artist,
        'album': str(item.get('album') or (title if kind == 'album' else '')).strip(),
        'isrc': str(item.get('isrc') or '').strip() if kind == 'track' else '',
        'query': ' '.join(value for value in (artist, title) if value),
    }
    return provider_template(provider, 'download.' + kind, values, require_values=True)


def save_stream_track(track, provider, directory):
    title = str(track.get('title') or '').strip()
    artist = str(track.get('artist') or '').strip()
    album = str(track.get('album') or '').strip()
    release_date = str(track.get('releaseDate') or '').strip()[:10]
    if not (
        title and artist and album and re.fullmatch(r'\d{4}-\d{2}-\d{2}', release_date)
    ):
        raise MusicError(
            'A song needs a title, artist, album, and full release date to save to Music.'
        )
    stem = f'{safe_name(title)} - {safe_name(artist)} - {safe_name(album)} ({release_date})'
    check_cancelled()
    progress(detail='Saving ' + title)
    resolved = resolve_track(track, providers=[provider], local_first=False)
    headers = {**provider_headers(provider), **clean_headers(resolved.get('headers'))}
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    if not any(name.lower() == 'user-agent' for name in headers):
        command += ['-user_agent', USER_AGENT]
    input_index = len(command)
    input_owner = 'download-' + uuid.uuid4().hex
    command += ['-map', '0:a:0', '-c:a', 'flac', '-f', 'flac']
    for key, value in dict(
        title=title,
        artist=artist,
        album=album,
        date=release_date,
        genre='; '.join(track.get('genreNames') or []),
    ).items():
        command += ['-metadata', key + '=' + value]
    directory.mkdir(parents=True, exist_ok=True)
    with _download_processes_lock:
        check_cancelled()
        with tempfile.NamedTemporaryFile(
            prefix='.music-', suffix='.flac', dir=directory, delete=False
        ) as output:
            temporary = Path(output.name)
        progress_path = temporary.with_suffix('.progress')
        _download_partials.update((temporary, progress_path))
    process = None
    job = current_job()
    if job:
        command += ['-progress', str(progress_path), '-stats_period', '0.5']
    try:
        source_url = STREAMS.provider_url(
            resolved['url'], {'User-Agent': USER_AGENT, **headers}
        )
        STREAMS.bind(input_owner, source_url)
        command[input_index:input_index] = ['-i', source_url]
        try:
            with _download_processes_lock:
                check_cancelled()
                process = subprocess.Popen(
                    command + [str(temporary)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                _download_processes.add(process)
        except FileNotFoundError as error:
            raise MusicError('Install ffmpeg to save music streams.') from error
        try:
            if not job:
                process.communicate(timeout=1800)
            else:
                deadline = time.monotonic() + 1800
                base = job.snapshot()['done']
                duration = float(track.get('duration') or 0)
                while True:
                    check_cancelled()
                    try:
                        process.communicate(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() > deadline:
                            raise
                        if progress_path.exists() and duration > 0:
                            text = progress_path.read_text()[-8192:]
                            values = re.findall(r'out_time_us=(\d+)', text)
                            if values:
                                fraction = min(
                                    0.99, int(values[-1]) / 1000000 / duration
                                )
                                progress(done=base + fraction)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.communicate()
            raise MusicError('Saving this music stream timed out.') from error
        if process.returncode != 0 or temporary.stat().st_size == 0:
            raise MusicError("The configured provider's stream could not be saved.")
        check_cancelled()
        for number in range(1, 1001):
            suffix = '' if number == 1 else f' ({number})'
            target = directory / (stem + suffix + '.flac')
            try:
                os.link(temporary, target)
                library = local_library()
                with library.db() as db:
                    db.execute(
                        'INSERT OR REPLACE INTO local_files VALUES (?,?,?,?,?,?)',
                        (
                            'music',
                            str(track['id']),
                            0,
                            0,
                            str(target),
                            json.dumps(dict(track, kind='music')),
                        ),
                    )
                return str(target)
            except FileExistsError:
                continue
        raise MusicError('Too many copies of this song already exist in Music.')
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            with _download_processes_lock:
                _download_processes.discard(process)
        temporary.unlink(missing_ok=True)
        progress_path.unlink(missing_ok=True)
        with _download_processes_lock:
            _download_partials.difference_update((temporary, progress_path))
        STREAMS.release(input_owner)


def stop_downloads(*_):
    JOBS.stop()
    COMMANDS.close()
    STREAMS.close()
    with _download_processes_lock:
        processes = list(_download_processes)
        partials = list(_download_partials)
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=0.3)
    for path in partials:
        path.unlink(missing_ok=True)
    for path in player_ipc.directory().glob('mpv-*.sock'):
        player_ipc.cleanup(path)


def save_track_with_fallback(track, providers, directory):
    job = current_job()
    base = job.snapshot()['done'] if job else 0
    last_error = None
    for provider in providers:
        check_cancelled()
        progress(done=base)
        try:
            path = save_stream_track(track, provider, directory)
            progress(done=base + 1)
            return path
        except MusicError as error:
            last_error = error
    if last_error:
        raise last_error
    raise MusicError('No download provider is configured for this item.')


def save_stream_download(kind, item, provider):
    if kind not in ('track', 'album') or not isinstance(item, dict):
        raise MusicError('Choose a song or album to download.')
    if not shutil.which('ffmpeg'):
        raise MusicError('Install ffmpeg to save music streams.')
    directory = xdg_dir('XDG_MUSIC_DIR', 'Music')
    providers = provider if isinstance(provider, list) else [provider]
    if kind == 'track':
        progress(total=1, unit='tracks')
        try:
            path = save_track_with_fallback(item, providers, directory)
        except OSError as error:
            raise MusicError('Could not write the music download.') from error
        return {'saved': 1, 'failed': 0, 'path': path}

    details = album_details(item, include_tracks=False)
    album = details.get('album') or item
    tracks = tracks_for_album(album, all_pages=True)
    if not tracks:
        raise MusicError('No tracks were found for this album.')
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MusicError('Could not write the music download.') from error
    progress(total=len(tracks), unit='tracks')
    saved = 0
    first_failure = None
    for index, track in enumerate(tracks):
        check_cancelled()
        progress(done=index)
        try:
            save_track_with_fallback(track, providers, directory)
            saved += 1
        except (MusicError, OSError) as error:
            if first_failure is None:
                first_failure = error
            continue
    if not saved:
        if isinstance(first_failure, MusicError):
            raise first_failure
        raise MusicError('Could not write the music download.')
    return {'saved': saved, 'failed': len(tracks) - saved, 'path': str(directory)}


def open_download(args):
    kind = args.get('kind')
    provider = download_provider(kind)
    if provider is None:
        raise MusicError('No download provider is configured for this item.')
    if provider['download'][kind].strip() == 'stream':
        providers = [
            candidate
            for candidate in download_providers(kind)
            if candidate['download'][kind].strip() == 'stream'
        ]
        return save_stream_download(kind, args.get('item'), providers)
    url = download_url(kind, args.get('item'))
    try:
        subprocess.Popen(
            ['uwsm', 'app', '-t', 'service', '--', 'xdg-open', url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError) as error:
        raise MusicError('Could not open the download URL.') from error
    return {'started': True}


def provider_headers(provider):
    return clean_headers(provider.get('headers'))


@lru_cache(maxsize=1)
def lyrics_cache():
    return JsonCache('lyrics')


def fetch_lyrics(args):
    song = args.get('song') or {}
    if not isinstance(song, dict):
        raise MusicError('Invalid song for lyrics lookup.')
    if str(song.get('lyrics') or '').strip():
        return dict(
            available=True, lyrics=song['lyrics'], provider='Song tags', saved=True
        )
    if (
        not str(song.get('title') or '').strip()
        or not str(song.get('artist') or '').strip()
    ):
        return dict(available=False, lyrics='', provider='')
    source = song.get('source')
    local_checked = False
    if source in ('nextcloud', 'music-local') and (
        song.get('local') or song.get('localPath')
    ):
        from spaces.music import local_files, tags

        try:
            local = local_files.cached(song)
            if local:
                details = tags.read(local, local_files.run)
                local_checked = True
                if details['tags']['lyrics'].strip():
                    return dict(
                        available=True,
                        lyrics=details['tags']['lyrics'],
                        provider='Song tags',
                        saved=True,
                        fileInfo=details.get('fileInfo', ''),
                    )
        except (MusicError, ValueError, OSError):
            pass
    if source == 'nextcloud' and not local_checked:
        from spaces.music.cloud import CloudLibrary

        try:
            saved = CloudLibrary().lyrics(song)
            if saved['available']:
                return saved
        except (CloudError, ValueError, OSError):
            pass
    try:
        providers = audio_lyrics.read_config()
    except audio_lyrics.LyricsError as error:
        raise MusicError(str(error)) from None
    if not providers:
        raise MusicError('No lyrics provider is configured.')
    identity = json.dumps(
        [
            [
                str(song.get(key) or '').strip().casefold()
                for key in ('title', 'artist', 'album', 'duration')
            ],
            providers,
        ],
        sort_keys=True,
    )
    cache = lyrics_cache()
    if not args.get('refresh'):
        import hashlib

        saved = cache.get(hashlib.sha256(identity.encode()).hexdigest(), 90 * 86400)
        if saved and saved.get('available'):
            return saved
    return cache.load(
        identity,
        0 if args.get('refresh') else 86400,
        lambda: lookup_lyrics(song, providers),
    )


def lookup_lyrics(song, providers):
    try:
        return audio_lyrics.lookup(song, providers)
    except audio_lyrics.LyricsError as error:
        raise MusicError(str(error)) from None


def provider_results(provider, wanted, query):
    if provider.get('command'):
        try:
            response = COMMANDS.call(
                provider, {'op': 'search', 'query': query, 'limit': 30}
            )
        except ProviderError as error:
            raise MusicError('A configured music command could not search.') from error
        results = response.get('results')
        if not isinstance(results, list):
            raise MusicError('A music command returned invalid search results.')
        return [row for row in results[:100] if isinstance(row, dict)]
    url = provider_template(
        provider,
        'search_url',
        {
            'query': query,
            'artist': wanted.get('artist') or '',
            'title': wanted.get('title') or '',
            'isrc': wanted.get('isrc') or '',
            'limit': 30,
        },
    )
    if not url:
        return []
    response = request_json(
        url, provider_headers(provider), timeout=provider.get('timeout', 24)
    )
    raw_items = value_at_path(response, provider.get('results_path', 'tracks'))
    if not isinstance(raw_items, list):
        return []
    candidates = []
    id_field = provider.get('track_id_field', 'trackId')
    title_field = provider.get('track_title_field', 'title')
    artist_field = provider.get('track_artist_field', 'artistName')
    artists_field = provider.get('track_artists_field', 'artistNames')
    isrc_field = provider.get('track_isrc_field', 'isrc')
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        artists = value_at_path(raw, artists_field)
        if not artists:
            artists = value_at_path(raw, 'artists') or value_at_path(raw, 'artistNames')
        artist = (
            value_at_path(raw, artist_field)
            or value_at_path(raw, 'artistName')
            or value_at_path(raw, 'artist')
        )
        candidate = {
            'id': value_at_path(raw, id_field) or value_at_path(raw, 'id'),
            'title': value_at_path(raw, title_field) or value_at_path(raw, 'name'),
            'artist': artist,
            'artists': artists if isinstance(artists, list) else [],
            'artistNames': artists
            if isinstance(artists, list) and all(isinstance(v, str) for v in artists)
            else [],
            'isrc': value_at_path(raw, isrc_field),
        }
        if not candidate['artistNames'] and not candidate['artists'] and artist:
            candidate['artistNames'] = [str(artist)]
        candidates.append(candidate)
    return candidates


def provider_stream(provider, candidate, values):
    headers = provider_headers(provider)
    if provider.get('command'):
        try:
            response = COMMANDS.call(
                provider,
                {
                    'op': 'resolve',
                    'ref': candidate.get('ref', candidate.get('id')),
                },
            )
        except ProviderError as error:
            raise MusicError(
                'A configured music command could not resolve this song.'
            ) from error
        url = safe_url(response.get('url'))
        if not url:
            raise MusicError('A music command returned an invalid stream URL.')
        headers.update(clean_headers(response.get('headers')))
    else:
        stream_id = safe_stream_id(candidate.get('id'))
        url = provider_template(
            provider,
            'stream_url',
            {
                **values,
                'id': stream_id,
                'track_id': stream_id,
            },
        )
    return {'url': url, 'headers': headers}


def local_library():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    DATA.chmod(0o700)
    library = LocalLibrary(DATA)
    (DATA / 'library.sqlite').chmod(0o600)
    return library


def resolve_track(track, providers=None, local_first=True):
    if local_first:
        local_files = local_library().files({**track, 'kind': 'music'})
        if local_files:
            return {'url': local_files[0]['path'], 'headers': {}}
    providers = music_config()['providers'] if providers is None else providers
    if not providers:
        raise MusicError('No playback providers are configured in music.json.')
    title = str(track.get('title') or '').strip()
    artist = str(track.get('artist') or '').strip()
    isrc = str(track.get('isrc') or '').strip()
    if not title or not artist:
        raise MusicError('This song does not have enough information to find a stream.')
    # Some providers search one field rather than a combined artist/title phrase.
    # A title-only fallback still has to pass the same artist/ISRC match score.
    queries = ([isrc] if isrc else []) + [f'{artist} {title}', title]
    provider_errors = 0
    for provider in providers:
        check_cancelled()
        if not provider.get('command') and (
            not provider.get('search_url') or not provider.get('stream_url')
        ):
            continue
        for query in queries:
            try:
                candidates = provider_results(provider, track, query)
            except MusicError:
                provider_errors += 1
                break
            ranked = sorted(
                candidates, key=lambda item: score_candidate(track, item), reverse=True
            )
            if not ranked or score_candidate(track, ranked[0]) < 120:
                continue
            try:
                return provider_stream(
                    provider,
                    ranked[0],
                    {
                        'query': query,
                        'artist': artist,
                        'title': title,
                        'isrc': isrc,
                    },
                )
            except MusicError:
                provider_errors += 1
                break
    if provider_errors:
        raise MusicError(
            'The configured playback providers could not resolve this song.'
        )
    raise MusicError(
        'No configured playback provider found a confident match for this song.'
    )


player_ipc = MpvIpc('music')


def start_player(args):
    track = args.get('track')
    if not isinstance(track, dict):
        raise MusicError('No song was selected.')
    mpv = shutil.which('mpv')
    if not mpv:
        raise MusicError('Install mpv to play music.')
    if track.get('source') in ('nextcloud', 'music-local'):
        from spaces.music.local_files import cached

        try:
            path = cached(track) if track.get('serverPath') else None
        except (MusicError, ValueError):
            if track.get('source') == 'music-local':
                raise
            path = None
        if track.get('source') == 'music-local' and path is None:
            raise MusicError('The local song is no longer available.')
        resolved = {'url': str(path) if path else STREAMS.url(track), 'headers': {}}
    else:
        resolved = (
            {'url': track['localPath'], 'headers': {}}
            if track.get('source') == 'local'
            and Path(track.get('localPath', '')).is_file()
            else resolve_track(track)
        )
    ipc_path = str(player_ipc.directory() / ('mpv-' + uuid.uuid4().hex[:16] + '.sock'))
    stream_url = resolved['url']
    if track.get('source') == 'nextcloud':
        STREAMS.bind(ipc_path, stream_url)
    elif track.get('source') not in ('music-local', 'local') and urllib.parse.urlsplit(
        stream_url
    ).scheme in ('https', 'http'):
        stream_url = STREAMS.provider_url(
            stream_url,
            {'User-Agent': USER_AGENT, **clean_headers(resolved.get('headers'))},
        )
        STREAMS.bind(ipc_path, stream_url)
    title = str(track.get('title') or 'Music').replace('\n', ' ').strip()
    command = [
        mpv,
        '--no-config',
        '--no-video',
        '--audio-client-name=Music',
        '--idle=no',
        '--keep-open=no',
        '--network-timeout=15',
        '--really-quiet',
        '--no-terminal',
        '--input-ipc-server=' + ipc_path,
        '--force-media-title=' + title,
    ]
    plugin = Path('/usr/lib/mpv-mpris/mpris.so')
    if plugin.is_file():
        command.append('--script=' + str(plugin))
    volume = args.get('volume')
    if isinstance(volume, (int, float)) and not isinstance(volume, bool):
        # Each track is a new mpv process; carry the listener's volume over.
        command.append(f'--volume={min(100, max(0, round(volume)))}')
    user_agent = USER_AGENT
    command.extend(('--user-agent=' + user_agent, '--', stream_url))
    return {'command': command, 'ipcPath': ipc_path}


def player_state(args):
    path = player_ipc.validate(args.get('ipcPath'))
    paused = player_ipc.property(path, 'pause') if path else None
    if paused is None:
        return {'ready': False}  # mpv has not opened its socket yet, or has exited.
    volume = player_ipc.property(path, 'volume')
    return {
        'ready': True,
        'position': float(player_ipc.property(path, 'time-pos') or 0),
        'duration': float(player_ipc.property(path, 'duration') or 0),
        'paused': bool(paused),
        'volume': float(volume) if volume is not None else None,
    }


def player_command(args):
    path = player_ipc.validate(args.get('ipcPath'))
    if not path:
        return {'sent': False}
    action = str(args.get('action') or '')
    if action == 'toggle-pause':
        command = ['cycle', 'pause']
    elif action == 'pause':
        command = ['set_property', 'pause', bool(args.get('value'))]
    elif action == 'seek':
        command = ['seek', max(0, float(args.get('value') or 0)), 'absolute+exact']
    elif action == 'volume':
        command = [
            'set_property',
            'volume',
            min(100, max(0, float(args.get('value') or 0))),
        ]
    else:
        raise MusicError('Unknown player command.')
    return {'sent': player_ipc.send(path, command)}


def cleanup_player(args):
    STREAMS.release(args.get('ipcPath'))
    return {'cleaned': player_ipc.cleanup(args.get('ipcPath'))}


def settings_save(settings):
    if not isinstance(settings, dict) or settings.get('section', 'library') not in (
        'library',
        'discover',
    ):
        raise MusicError(
            'Music preferences are invalid; existing records were preserved.'
        )
    views = settings.get('views', {})
    if not isinstance(views, dict):
        raise MusicError('Invalid Music views.')
    cleaned = {'section': settings.get('section', 'library'), 'views': {}}
    for section in ('library', 'discover'):
        view = views.get(section, {})
        if (
            not isinstance(view, dict)
            or view.get('category', 'songs')
            not in ('songs', 'albums', 'artists', 'playlists')
            or any(
                not isinstance(view.get(key, ''), str)
                for key in ('genreId', 'genreName')
            )
            or not isinstance(view.get('pending', False), bool)
        ):
            raise MusicError(
                'Music preferences are invalid; existing records were preserved.'
            )
        cleaned['views'][section] = {
            key: view.get(key, default)
            for key, default in {
                'category': 'songs',
                'genreId': '',
                'genreName': '',
                'pending': False,
            }.items()
        }
    atomic_write(CONFIG / 'music-ui.json', json.dumps(cleaned))
    return cleaned


def song_information(args):
    from spaces.music import local_files, tags

    song = args.get('song') or {}
    preview = dict(
        title=song.get('title', ''),
        artist=song.get('artist', ''),
        album=song.get('album', ''),
        date=song.get('releaseDate', ''),
        genre='; '.join(song.get('genreNames') or []),
        track=str(song.get('trackNumber') or ''),
        disc=str(song.get('discNumber') or ''),
        lyrics=song.get('lyrics', ''),
    )
    result = dict(
        song=song,
        tags=preview,
        relativePath=str(song.get('serverPath') or '').lstrip('/'),
        fileInfo=song.get('fileInfo', ''),
    )
    if song.get('source') in ('nextcloud', 'music-local'):
        try:
            path = local_files.cached(song) if song.get('serverPath') else None
        except (MusicError, ValueError, OSError):
            path = None
        if song.get('source') == 'nextcloud':
            from spaces.music.cloud import CloudLibrary

            try:
                result |= CloudLibrary().song_info(song)
            except MusicError:
                if not path:
                    raise
        if path:
            result |= tags.read(path, local_files.run)
    return result


def dispatch(args):
    operation = args.get('op')
    if operation == 'init':
        settings = read_json(CONFIG / 'music-ui.json', {})
        # Validate before publishing a normalized snapshot.
        settings = settings_save(settings)
        local_library()
        return dict(settings=settings)
    if operation == 'settings-save':
        return settings_save(args.get('settings'))
    if operation == 'jobs':
        return JOBS.snapshots()
    if operation == 'cancel_job':
        return JOBS.cancel(args.get('job_id'))
    if operation == 'download_start':
        return JOBS.start(
            str(args.get('title') or 'Save music'), lambda: open_download(args)
        )
    if operation == 'local-songs':
        return [
            {**item, 'kind': 'song', 'source': 'local'}
            for item in local_library().list('music')
        ]
    if operation == 'search':
        return search(args)
    if operation == 'search-page':
        return search_page(args)
    if operation == 'genres':
        return load_genres()
    if operation == 'artist':
        return artist_details(args.get('artist') or {})
    if operation == 'artist-info':
        return artist_info(args.get('artist') or {})
    if operation == 'artist-albums-page':
        return artist_albums_page(args)
    if operation == 'artist-songs-page':
        return artist_songs_page(args)
    if operation == 'album':
        return album_details(args.get('album') or {})
    if operation == 'song-artists':
        return song_artists(args)
    if operation == 'lyrics':
        return fetch_lyrics(args)
    if operation == 'song-info':
        return song_information(args)
    if operation == 'download-capabilities':
        return download_capabilities()
    if operation == 'play':
        return start_player(args)
    if operation == 'player-state':
        return player_state(args)
    if operation == 'player-command':
        return player_command(args)
    if operation == 'player-cleanup':
        return cleanup_player(args)
    raise MusicError('Unknown Music operation.')


def request_scope(request):
    """Newer requests supersede older ones only from the same view lane."""
    return (request['op'], request.get('category', ''), request.get('lane', ''))


def main():
    from spaces.movies.worker import own_process_group, serve

    own_process_group(stop_downloads)
    serve(
        dispatch,
        errors=(MusicError, CloudError),
        latest=(
            'search',
            'search-page',
            'artist',
            'artist-info',
            'album',
            'lyrics',
            'song-info',
            'play',
        ),
        controls=(
            'init',
            'settings-save',
            'download_start',
            'cancel_job',
            'player-command',
            'player-state',
            'player-cleanup',
        ),
        scope=request_scope,
    )


if __name__ == '__main__':
    main()
