"""Shared, bounded Space discovery for the launcher and assistant. No playback."""

from contextlib import closing
import hashlib
from itertools import zip_longest
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spaces.movies.records import MediaError
from spaces.music.records import MusicError
from ui import space_filters as Filters

SEARCH_ERRORS = (
    ValueError,
    OSError,
    sqlite3.Error,
    RuntimeError,
    MediaError,
    MusicError,
)


class SearchDeadline(BaseException):
    """A provider's network-error handling must not swallow the global deadline."""


DEADLINE_MESSAGE = 'Search timed out. Saved results remain available.'

KINDS = Filters.KINDS
EPISODE = re.compile(r'\b(?:s(\d{1,3})e(\d{1,4})|(\d{1,3})x(\d{1,4}))\b', re.I)


def normalize(args):
    if not isinstance(args, dict) or set(args) - {
        'kind',
        'query',
        'online',
        'limit',
        'filters',
    }:
        raise ValueError(
            'Search requires kind, query, and optional online/limit fields.'
        )
    kind, query = args.get('kind'), args.get('query', '')
    if kind not in KINDS:
        raise ValueError('Choose a supported Space search category.')
    if (
        not isinstance(query, str)
        or len(query.strip()) > 200
        or any(ord(c) < 32 for c in query)
    ):
        raise ValueError('Search text must contain at most 200 characters.')
    online, limit = args.get('online', True), args.get('limit', 12)
    if type(online) is not bool or type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError('online must be boolean and limit must be between 1 and 12.')
    filters = Filters.normalize(kind, args.get('filters', {}))
    if online and kind in ('episode', 'youtube') and not query.strip():
        raise ValueError('Online episode and YouTube searches require query text.')
    return dict(
        kind=kind, query=query.strip(), online=online, limit=limit, filters=filters
    )


def root(variable, fallback):
    return (
        Path(os.environ.get(variable, str(Path.home() / fallback)))
        / 'quickshell/desktop/spaces'
    )


def fold(value):
    return ''.join(
        c
        for c in unicodedata.normalize('NFKD', str(value)).casefold()
        if not unicodedata.combining(c)
    )


def matches(item, query):
    text = fold(
        ' '.join(
            str(item.get(k) or '')
            for k in (
                'title',
                'name',
                'artist',
                'album',
                'episodeTitle',
                'country',
                'tags',
            )
        )
    )
    return all(term in text for term in fold(query).split())


def read_json(path, default):
    try:
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('The saved Space catalogue is too large.')
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def rows(path, sql, args=()):
    return list(iter_rows(path, sql, args))


def iter_rows(path, sql, args=()):
    if not path.is_file():
        return
    with closing(
        sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
    ) as db:
        yield from db.execute(sql, args)


def card(kind, item, *, local=False, saved=False, episode=None):
    # Cards are metadata, never provider commands or arbitrary action URLs. Keep
    # the original entity fields needed by its Space, with finite text lengths.
    item = bounded(
        {key: value for key, value in item.items() if key not in ('command', 'actions')}
    )
    space, icon = {
        'movie': ('movies', 'film'),
        'series': ('series', 'tv'),
        'episode': ('series', 'tv'),
        'song': ('music', 'music'),
        'album': ('music', 'music'),
        'artist': ('music', 'user-round'),
        'radio': ('radio', 'boom-box'),
        'tv': ('television', 'antenna'),
        'game': ('games', 'gamepad-2'),
        'youtube': ('streaming', 'video'),
    }[kind]
    identity = str(item.get('id') or item.get('stationuuid') or '')
    if not identity:
        return None
    if kind in ('movie', 'series', 'episode') and item.get('tmdbId'):
        identity = f'tmdb:{item["kind"]}:{item["tmdbId"]}'
    if kind in ('song', 'album', 'artist'):
        identity = ':'.join(
            (
                kind,
                str(item.get('source') or ''),
                str(item.get('account') or ''),
                identity,
            )
        )
    title = str(item.get('title') or item.get('name') or 'Untitled')
    subtitle = [kind.capitalize()]
    subtitle += [
        str(item[k]) for k in ('year', 'artist', 'album', 'country') if item.get(k)
    ]
    payload = {'item': item}
    playable = kind in ('song', 'radio', 'tv', 'youtube', 'movie', 'episode')
    if kind in ('movie', 'series', 'episode'):
        # The Space hydrates its own details. Cast, screenshots and duplicated
        # plot text must not crowd other actionable cards out of a tool result.
        payload = {
            'title': {
                key: item[key]
                for key in (
                    'id',
                    'imdbId',
                    'tmdbId',
                    'malId',
                    'kind',
                    'title',
                    'year',
                    'poster',
                    'backdrop',
                )
                if key in item
            }
        }
    if episode:
        payload['episode'] = episode
        identity += ':' + str(episode['season']) + ':' + str(episode['number'])
        title += ' · S%02dE%02d' % (int(episode['season']), int(episode['number']))
        if episode.get('title'):
            subtitle.insert(0, str(episode['title']))
    if kind == 'game':
        playable = bool(item.get('installedBy'))
    if kind == 'tv':
        playable = bool(item.get('streams'))
    return dict(
        id=space + ':' + identity,
        kind=kind,
        space=space,
        icon=icon,
        artwork=artwork_url(item),
        title=title[:300],
        subtitle=' · '.join(subtitle)[:400],
        availability='Local' if local else 'Saved' if saved else 'Online',
        playable=playable,
        payload=payload,
        metadata={
            'rating_scale': 5 if kind == 'game' else 10,
            **{
                k: item[k]
                for k in (
                    'plot',
                    'overview',
                    'description',
                    'genre',
                    'genres',
                    'rating',
                    'duration',
                    'releaseDate',
                    'year',
                    'votes',
                    'ratingCount',
                    'summary',
                    'genreNames',
                    'platforms',
                    'country',
                    'countries',
                    'languages',
                    'categories',
                    'bitrate',
                    'codec',
                    'artist',
                    'album',
                    'creator',
                    'date',
                    'live',
                    'ownedBy',
                    'installedBy',
                    'favorite',
                    'ownershipKnown',
                    'installationKnown',
                )
                if item.get(k) is not None
            },
            **({'episode': bounded(episode)} if episode else {}),
        },
    )


def artwork_url(item):
    for key in ('poster', 'cover', 'thumbnail', 'image', 'logo', 'favicon'):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get('url')
        if isinstance(value, str) and value.startswith(
            ('https://', 'http://', 'file://', '/')
        ):
            return value
    return ''


def bounded(value, depth=0):
    if depth > 5:
        return None
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, dict):
        return {str(k): bounded(v, depth + 1) for k, v in list(value.items())[:60]}
    if isinstance(value, list):
        return [bounded(item, depth + 1) for item in value[:40]]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def media_local(args):
    kind = args['kind']
    media_kind = 'movie' if kind == 'movie' else 'tv'
    path = (
        root('XDG_DATA_HOME', '.local/share')
        / ('movies' if kind == 'movie' else 'series')
        / 'library.sqlite'
    )
    query = (
        EPISODE.sub('', args['query']).strip() if kind == 'episode' else args['query']
    )
    wanted = EPISODE.search(args['query']) if kind == 'episode' else None
    numbers = None
    if wanted:
        numbers = (int(wanted[1] or wanted[3]), int(wanted[2] or wanted[4]))
    titles, aliases, personal = media_snapshot(path)
    result = []
    for season, episode, filename, payload in rows(
        path,
        'SELECT season,episode,path,title_json FROM local_files WHERE kind=? ORDER BY title_id,season,episode',
        (media_kind,),
    ):
        item = json.loads(payload)
        item = item | titles.get(aliases.get(item.get('id'), item.get('id')), {})
        item['favorite'] = bool(personal.get(item.get('id'), {}).get('favorite'))
        if not Path(filename).is_file() or not matches(item, query):
            continue
        if numbers and numbers != (season, episode):
            continue
        episode_title = item.get('episodeTitle', '')
        item = {
            k: v
            for k, v in item.items()
            if k not in ('season', 'episode', 'episodeTitle')
        }
        item['local'] = True
        result.append(
            card(
                kind,
                item,
                local=True,
                episode=dict(
                    season=season,
                    number=episode,
                    **({'title': episode_title} if episode_title else {}),
                )
                if kind == 'episode'
                else None,
            )
        )
    return result


def media_snapshot(path):
    tables = {
        name
        for (name,) in rows(path, "SELECT name FROM sqlite_master WHERE type='table'")
    }
    titles = (
        {
            item['id']: item
            for (payload,) in rows(
                path, "SELECT value FROM cache WHERE key LIKE 'title:%'"
            )
            for item in [json.loads(payload)]
            if isinstance(item, dict) and item.get('id')
        }
        if 'cache' in tables
        else {}
    )
    aliases = (
        dict(rows(path, 'SELECT alias,id FROM aliases')) if 'aliases' in tables else {}
    )
    personal = (
        {
            identity: json.loads(payload)
            for identity, payload in rows(path, 'SELECT id,value FROM personal')
        }
        if 'personal' in tables
        else {}
    )
    return titles, aliases, personal


def media_saved(args):
    kind = args['kind']
    path = (
        root('XDG_DATA_HOME', '.local/share')
        / ('movies' if kind == 'movie' else 'series')
        / 'library.sqlite'
    )
    if not rows(
        path, "SELECT name FROM sqlite_master WHERE type='table' AND name='cache'"
    ):
        return []
    titles, _aliases, personal = media_snapshot(path)
    titles = {
        identity: item | dict(favorite=bool(personal.get(identity, {}).get('favorite')))
        for identity, item in titles.items()
        if item.get('kind') == ('movie' if kind == 'movie' else 'tv')
    }
    if kind != 'episode':
        return [
            card(kind, item, saved=True)
            for item in titles.values()
            if matches(item, args['query'])
        ]
    wanted = EPISODE.search(args['query'])
    query = EPISODE.sub('', args['query']).strip()
    result = []
    for key, payload in rows(
        path, "SELECT key,value FROM cache WHERE key LIKE 'episodes:%'"
    ):
        identity, season, _page = json.loads(key.partition(':')[2])
        item = titles.get(identity)
        if not item or season is None:
            continue
        for episode in json.loads(payload).get('items', []):
            if wanted and (int(episode['season']), int(episode['number'])) != (
                int(wanted[1] or wanted[3]),
                int(wanted[2] or wanted[4]),
            ):
                continue
            if matches({**item, 'episodeTitle': episode.get('title', '')}, query):
                result.append(card(kind, item, saved=True, episode=episode))
    return result


def music_path():
    # Resolve only the current account; never expose an old account's snapshot.
    from integrations import nextcloud

    account = nextcloud.load_account()
    if not account:
        return None
    account = nextcloud.validate_account(account)
    digest = hashlib.sha256(json.dumps(account, sort_keys=True).encode()).hexdigest()
    base = root('XDG_CACHE_HOME', '.cache') / 'music/nextcloud' / digest
    path = base / 'library.sqlite'
    if not path.is_file():
        path = base / 'catalogue.sqlite'
    return path


def music_local(args):
    path = music_path()
    if path is None:
        return []
    kinds = ('song', 'album', 'artist') if args['kind'] == 'music' else (args['kind'],)
    result = []
    for kind in kinds:
        # Bound the SQLite result before materializing records in Python.
        clauses, params = ['kind=?'], [kind]
        for term in fold(args['query']).split():
            clauses.append('instr(search,?)>0')
            params.append(term)
        sort = args['filters'].get('sort')
        ordering = {
            'newest': "json_extract(payload,'$.releaseDate') DESC",
            'oldest': "json_extract(payload,'$.releaseDate') ASC",
            'shortest': "json_extract(payload,'$.duration') ASC",
            'longest': "json_extract(payload,'$.duration') DESC",
        }.get(sort, 'sort,id')
        accepted = 0
        for (payload,) in iter_rows(
            path,
            'SELECT payload FROM records WHERE '
            + ' AND '.join(clauses)
            + " ORDER BY COALESCE(json_extract(payload,'$.local'),0) DESC,"
            + ordering,
            params,
        ):
            item = json.loads(payload)
            local = bool(
                item.get('local')
                and Path(item.get('localPath') or '/nonexistent').is_file()
            )
            if kind in ('album', 'artist'):
                related_sql = (
                    'album=?'
                    if kind == 'album'
                    else 'id IN (SELECT song FROM artist_songs WHERE artist=?)'
                )
                if args['filters'].get('genre') and not (
                    item.get('genreNames') or item.get('genres')
                ):
                    item['genreNames'] = [
                        name
                        for (name,) in rows(
                            path,
                            "SELECT DISTINCT name FROM genres WHERE kind='song' AND id IN (SELECT id FROM records WHERE kind='song' AND "
                            + related_sql
                            + ')',
                            (item['id'],),
                        )
                    ]
                for (song_payload,) in iter_rows(
                    path,
                    "SELECT payload FROM records WHERE kind='song' AND COALESCE(json_extract(payload,'$.local'),0)=1 AND "
                    + related_sql,
                    (item['id'],),
                ):
                    song = json.loads(song_payload)
                    if Path(song.get('localPath') or '/nonexistent').is_file():
                        local = True
                        break
            candidate = card(kind, item, local=local, saved=True)
            if candidate and Filters.accepts(candidate, args['filters']):
                result.append(candidate)
                accepted += 1
                if accepted >= 36:
                    break
    return result


def local_results(args):
    kind = args['kind']
    data, cache = (
        root('XDG_DATA_HOME', '.local/share'),
        root('XDG_CACHE_HOME', '.cache'),
    )
    if kind in ('movie', 'series', 'episode'):
        return media_local(args) + media_saved(args)
    if kind in ('music', 'song', 'album', 'artist'):
        return music_local(args)
    if kind in ('radio', 'tv'):
        space = 'radio' if kind == 'radio' else 'television'
        items = read_json(data / space / 'favorites.json', [])
        favorite_ids = {
            str(item.get('id') or item.get('stationuuid') or '') for item in items
        }
        if kind == 'tv':
            items += read_json(cache / space / 'catalogue.json', {}).get('channels', [])
        return [
            card(
                kind,
                item
                | {
                    'favorite': str(item.get('id') or item.get('stationuuid') or '')
                    in favorite_ids
                },
                saved=True,
            )
            for item in items
            if isinstance(item, dict) and matches(item, args['query'])
        ]
    if kind == 'youtube':
        downloads = (
            read_json(data / 'streaming/library.json', {}).get('downloads', {}).values()
        )
        return [
            card(kind, saved['video'], local=True)
            for saved in downloads
            if isinstance(saved.get('video'), dict)
            and matches(saved['video'], args['query'])
            and Path(saved.get('path') or '/nonexistent').is_file()
        ]
    if kind == 'game':
        from spaces.games.backend import GamesBackend

        backend = GamesBackend()
        # Legendary's ordinary library refresh can log in to Epic. Local search
        # uses its saved ownership snapshot, plus current Steam manifests only.
        snapshot, _fresh = backend._cache_get('libraries:v1', 0, allow_stale=True)
        empty = dict(
            items=[], ownedIds=[], ownershipKnown=False, installationKnown=False
        )
        backend._library_snapshot = {
            store: (snapshot or {}).get(store, dict(empty))
            for store in ('steam', 'epic', 'gog')
        }
        backend._library_snapshot['steam'] = backend._steam_state(offline=True)
        backend._library_updated = backend._clock()
        result, offset = [], 0
        # Filter before taking the final shortlist, rather than filtering just
        # the first alphabetical page of a larger installed/owned collection.
        for _page in range(10):
            page = backend.library_games({'query': args['query'], 'offset': offset})
            game_knowledge(backend, page['items'])
            result += filtered(
                [
                    card(kind, item, local=bool(item.get('installedBy')), saved=True)
                    for item in page['items']
                ],
                args,
            )
            next_offset = page.get('next')
            if next_offset is None or int(next_offset) <= offset:
                break
            offset = int(next_offset)
        return result
    return []


def game_knowledge(backend, items):
    state = backend._library_state()
    for item in items:
        stores = set(item.get('libraryStores') or []) | {
            ref['store']
            for ref in item.get('storeReferences', [])
            if isinstance(ref, dict) and ref.get('store')
        }
        item['ownershipKnown'] = bool(item.get('ownedBy')) or bool(
            stores
            and all(state.get(store, {}).get('ownershipKnown') for store in stores)
        )
        item['installationKnown'] = bool(item.get('installedBy')) or bool(
            stores
            and all(state.get(store, {}).get('installationKnown') for store in stores)
        )


def resolve_option(options, value, label):
    normal = Filters.genre_key if label == 'genre' else Filters.key
    aliases = {
        'pc': 'pcmicrosoftwindows',
        'windows': 'pcmicrosoftwindows',
        'ps5': 'playstation5',
        'ps4': 'playstation4',
    }
    wanted = (
        aliases.get(normal(value), normal(value))
        if label == 'platform'
        else normal(value)
    )
    for option in options:
        if str(option.get('id')) == value or normal(option.get('name', '')) == wanted:
            return str(option['id']), option['name']
    raise ValueError(
        f'Unknown {label}: {value}. Inspect space_filters for supported values.'
    )


def eligible_online(args):
    filters = args['filters']
    return (
        args['online']
        and filters.get('availability', 'any') == 'any'
        and not any(filters.get(name) for name in ('favorites', 'installed', 'owned'))
    )


def filtered(items, args, trusted=()):
    return [
        item
        for item in items
        if item and Filters.accepts(item, args['filters'], trusted)
    ]


def online_results(args):
    kind, query = args['kind'], args['query']
    filters = args['filters']
    if kind in ('movie', 'series', 'episode'):
        from spaces.movies.backend import Backend

        space = 'movies' if kind == 'movie' else 'series'
        backend = Backend(
            config=root('XDG_CONFIG_HOME', '.config') / space / 'media.json',
            data=root('XDG_DATA_HOME', '.local/share') / space,
        )
        wanted = EPISODE.search(query) if kind == 'episode' else None
        if kind == 'episode' and not wanted:
            return (
                [],
                'For online episodes, include a show and episode, e.g. /episode Severance S01E02.',
            )
        provider_filters = {
            target: filters[source]
            for source, target in (
                ('genre', 'genre'),
                ('min_year', 'minYear'),
                ('max_year', 'maxYear'),
                ('min_rating', 'rating'),
                ('min_votes', 'votes'),
                ('country', 'country'),
                ('sort', 'sort'),
            )
            if source in filters
        }
        # Search endpoints do not supply movie countries. Hydrate only the small
        # returned candidate set before applying that constraint.
        if query:
            provider_filters.pop('country', None)
        items = backend.browse(
            dict(
                kind='movie' if kind == 'movie' else 'tv',
                query=EPISODE.sub('', query).strip() if wanted else query,
                filters=provider_filters,
            )
        )
        candidates = items['items']
        if query and filters.get('country'):
            candidates = [backend.details({'title': item}) for item in candidates[:12]]
        if wanted:
            result = []
            for item in candidates[:2]:
                episodes = backend.episodes(
                    dict(title=item, season=int(wanted[1] or wanted[3]))
                )
                result += [
                    card(kind, item, episode=episode)
                    for episode in episodes['items']
                    if int(episode['number']) == int(wanted[2] or wanted[4])
                ]
            return filtered(result, args), items.get('warning', '')
        cards = [card(kind, item) for item in candidates]
        return filtered(cards, args, ('country',) if not query else ()), items.get(
            'warning', ''
        )
    if kind in ('music', 'song', 'album', 'artist'):
        from spaces.music.backend import (
            search_page,
            load_genres,
            charts,
            chart_items,
            catalog_artist_records,
        )

        kinds = ('song', 'album', 'artist') if kind == 'music' else (kind,)
        results, warnings = [], []
        genre_id, genre_name = '', filters.get('genre', '')
        if genre_name:
            genre_id, genre_name = resolve_option(load_genres(), genre_name, 'genre')
        music_query = query or ' '.join(
            filters[name] for name in ('artist', 'album') if filters.get(name)
        )
        for category in kinds:
            try:
                # Empty discovery uses genre charts, independently of the user's
                # configured landing playlist. Artists can be found by genre text.
                if not music_query:
                    if category == 'artist':
                        songs = chart_items(charts('songs', genre_id), 'songs')[0]
                        items = catalog_artist_records(
                            [
                                identity
                                for song in songs
                                for identity in song.get('artistIds', [])
                            ]
                        )
                    else:
                        items = chart_items(
                            charts(category + 's', genre_id), category + 's'
                        )[0]
                else:
                    items = search_page(
                        dict(
                            query=music_query,
                            category=category + 's',
                            genreId=genre_id,
                            genreName=genre_name,
                        )
                    )['items']
                results += filtered([card(category, item) for item in items], args)
            except SEARCH_ERRORS as error:
                warnings.append(category.capitalize() + ': ' + str(error))
            except SearchDeadline:
                warnings.append(DEADLINE_MESSAGE)
                break
        return results, ' '.join(warnings)
    if kind == 'radio':
        from spaces.radio.api import browse

        country = filters.get('country', '')
        # Directory supports country names on its existing browse path; a code
        # remains a strict local constraint on returned station metadata.
        result = browse(
            dict(
                query=query,
                country=country if len(country) != 2 else '',
                tags=[filters['genre']] if filters.get('genre') else [],
            )
        )
        return filtered(
            [card(kind, item) for item in result['items']], args
        ), result.get('warning', '')
    if kind == 'tv':
        # Television's explicit refresh remains in its Space; search never downloads
        # the entire channel directory just because the launcher was opened.
        return [], ''
    if kind == 'game':
        from spaces.games.backend import GamesBackend

        backend = GamesBackend()
        resolved_filters = dict(filters)
        provider_filters = {
            target: filters[source]
            for source, target in (('min_year', 'fromYear'), ('max_year', 'toYear'))
            if source in filters
        }
        if any(name in filters for name in ('genre', 'platform')):
            options = backend._filter_options()
            for name in ('genre', 'platform'):
                if name in filters:
                    identity, label = resolve_option(
                        options[name + 's'], filters[name], name
                    )
                    provider_filters[name] = identity
                    resolved_filters[name] = label
        provider_filters['sort'] = {
            'rating': '-rating',
            'newest': '-released',
            'oldest': 'released',
            'title': 'name',
        }.get(filters.get('sort'), '-added')
        result = backend.browse(dict(query=query, filters=provider_filters))
        game_knowledge(backend, result['items'])
        return filtered(
            [card(kind, item) for item in result['items']],
            {**args, 'filters': resolved_filters},
        ), result.get('warning', '')
    from spaces.streaming.backend import StreamingBackend

    backend = StreamingBackend()
    try:
        result = backend.browse(dict(tab='search', query=query, page=0))
        candidates, warnings = [], [result.get('warning', '')]
        for item in result['items'][:24]:
            try:
                needs_details = any(
                    name in filters for name in ('live', 'min_year', 'max_year')
                ) or (
                    any(name in filters for name in ('min_duration', 'max_duration'))
                    and not item.get('duration')
                )
                if needs_details:
                    item = backend.details(item['id'])
                candidate = card(kind, item)
                if candidate and Filters.accepts(candidate, filters):
                    candidates.append(candidate)
                if len(candidates) >= args['limit']:
                    break
            except SEARCH_ERRORS as error:
                warnings.append(str(error))
            except SearchDeadline:
                warnings.append(DEADLINE_MESSAGE)
                break
        return candidates, ' '.join(dict.fromkeys(filter(None, warnings)))
    finally:
        backend.commands.close()


def filter_options(args):
    if not isinstance(args, dict) or set(args) - {'op', 'kind', 'online', 'query'}:
        raise ValueError(
            'Filter lookup requires kind, optional online, and optional query.'
        )
    kind, online, query = (
        args.get('kind'),
        args.get('online', False),
        args.get('query', ''),
    )
    if (
        type(online) is not bool
        or not isinstance(query, str)
        or len(query) > 100
        or any(ord(c) < 32 for c in query)
    ):
        raise ValueError('Invalid filter lookup arguments.')
    result = Filters.capabilities(kind)
    options, warnings = {}, []
    cache = root('XDG_CACHE_HOME', '.cache')
    try:
        if kind == 'game':
            from spaces.games.backend import GamesBackend

            backend = GamesBackend()
            options = (
                backend._filter_options()
                if online
                else (
                    backend._cache_get('catalog-filters:igdb:v1', 0, allow_stale=True)[
                        0
                    ]
                    or {}
                )
            )
        elif kind in ('music', 'song', 'album', 'artist'):
            if online:
                from spaces.music.backend import load_genres

                options = {'genres': load_genres()}
            else:
                path = music_path()
                genres = (
                    [
                        dict(name=name)
                        for (name,) in rows(
                            path, 'SELECT DISTINCT name FROM genres ORDER BY name'
                        )
                    ]
                    if path
                    else []
                )
                if genres:
                    options = {'genres': genres}
        elif kind == 'tv':
            options = read_json(cache / 'television/catalogue.json', {}).get(
                'filters', {}
            )
        elif kind == 'radio' and online:
            from spaces.radio.api import list_genres, list_countries

            options = dict(genres=list_genres(), countries=list_countries())
    except SEARCH_ERRORS as error:
        warnings.append(str(error))
    except SearchDeadline:
        warnings.append(DEADLINE_MESSAGE)
    result['options'] = {}
    result['more_options'] = []
    for field, values in options.items():
        if not isinstance(values, list):
            continue
        matching = [
            value
            for value in values
            if not query
            or Filters.key(query)
            in Filters.key(
                value.get('name') or value.get('code') or value.get('id') or ''
            )
        ]
        result['options'][field] = matching[:60]
        if len(matching) > 60:
            result['more_options'].append(field)
    if result['more_options']:
        result['notes'].append(
            'Some option lists were shortened. Pass query to find a specific name.'
        )
    if not online and kind in ('music', 'song', 'album', 'artist', 'game', 'radio'):
        result['notes'].append(
            'Use online=true to load provider filter choices when saved choices are unavailable.'
        )
    result['warning'] = ' '.join(warnings)
    return result


def merge(items, limit, diverse=False, sort='relevance'):
    unique = {}
    for item in items:
        if item:
            unique.setdefault(item['id'], item)
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            {'Local': 0, 'Saved': 1, 'Online': 2}[item['availability']],
            Filters.sort_key(item, sort) if sort != 'relevance' else 0,
        ),
    )
    if diverse:
        balanced = []
        for availability in ('Local', 'Saved', 'Online'):
            groups = (
                [
                    item
                    for item in ordered
                    if item['availability'] == availability and item['kind'] == category
                ]
                for category in ('song', 'album', 'artist')
            )
            for group in zip_longest(*groups):
                balanced.extend(item for item in group if item)
        ordered = balanced
    return ordered[:limit]


def search(args, publish=None):
    args = normalize(args)
    items, warnings = [], []
    try:
        items = merge(
            filtered(local_results(args), args),
            args['limit'],
            args['kind'] == 'music',
            args['filters'].get('sort', 'relevance'),
        )
    except SearchDeadline:
        result = dict(items=[], warning=DEADLINE_MESSAGE, complete=True)
        if publish:
            publish(result)
        return result
    except SEARCH_ERRORS as error:
        warnings.append('Saved results: ' + str(error))
    if publish:
        publish(
            dict(
                items=items,
                warning=' '.join(warnings),
                complete=not eligible_online(args),
                filters=args['filters'],
            )
        )
    if eligible_online(args):
        try:
            remote, warning = online_results(args)
            items = merge(
                items + remote,
                args['limit'],
                args['kind'] == 'music',
                args['filters'].get('sort', 'relevance'),
            )
            if warning:
                warnings.append(warning)
        except SEARCH_ERRORS as error:
            warnings.append('Online search: ' + str(error))
        except SearchDeadline:
            warnings.append(DEADLINE_MESSAGE)
    result = dict(
        items=items, warning=' '.join(warnings), complete=True, filters=args['filters']
    )
    if publish:
        publish(result)
    return result


def main():
    def timeout(_signal, _frame):
        raise SearchDeadline()

    def emit(value):
        print(json.dumps(value, allow_nan=False), flush=True)

    os.umask(0o077)
    # Unwind provider finally blocks before exit; yt-dlp owns a separate process
    # group and must be reaped when a launcher query is replaced or dismissed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(30)
    try:
        args = json.loads(
            sys.argv[1] if len(sys.argv) == 2 else sys.stdin.readline(8192)
        )
        if isinstance(args, dict) and args.get('op') == 'filters':
            emit(filter_options(args))
        elif len(sys.argv) == 2:
            emit(search(args))
        else:
            search(args, emit)
    except SEARCH_ERRORS as error:
        emit(dict(error=str(error), complete=True))
    except SearchDeadline:
        emit(dict(error=DEADLINE_MESSAGE, complete=True))
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
