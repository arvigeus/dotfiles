"""Typed discovery constraints shared by Space providers, launcher and assistant."""

from datetime import date
import math
import re
import unicodedata

from spaces.movies.records import TMDB_GENRES

KINDS = (
    'movie',
    'series',
    'episode',
    'music',
    'song',
    'album',
    'artist',
    'radio',
    'tv',
    'game',
    'youtube',
)
COMMON = {'availability', 'sort'}
MEDIA = {
    'genre',
    'min_year',
    'max_year',
    'min_rating',
    'min_votes',
    'country',
    'favorites',
}
MUSIC = {'genre', 'artist', 'min_year', 'max_year'}
FIELDS = {
    'movie': MEDIA,
    'series': MEDIA,
    'episode': MEDIA,
    'music': MUSIC,
    'song': MUSIC | {'album', 'min_duration', 'max_duration'},
    'album': MUSIC,
    'artist': {'genre'},
    'radio': {'genre', 'country', 'language', 'min_bitrate', 'codec', 'favorites'},
    'tv': {'country', 'language', 'category', 'favorites'},
    'game': {
        'genre',
        'platform',
        'min_year',
        'max_year',
        'min_rating',
        'min_votes',
        'owned',
        'installed',
        'favorites',
    },
    'youtube': {
        'channel',
        'min_duration',
        'max_duration',
        'live',
        'min_year',
        'max_year',
    },
}
SORTS = {
    'movie': ('relevance', 'popular', 'rating', 'newest', 'oldest', 'title'),
    'series': ('relevance', 'popular', 'rating', 'newest', 'oldest', 'title'),
    'episode': ('relevance', 'popular', 'rating', 'newest', 'oldest', 'title'),
    'music': ('relevance', 'popular', 'newest', 'oldest', 'title'),
    'song': (
        'relevance',
        'popular',
        'newest',
        'oldest',
        'title',
        'shortest',
        'longest',
    ),
    'album': ('relevance', 'popular', 'newest', 'oldest', 'title'),
    'artist': ('relevance', 'popular', 'title'),
    'radio': ('relevance', 'popular', 'title', 'bitrate'),
    'tv': ('relevance', 'title'),
    'game': ('relevance', 'popular', 'rating', 'newest', 'oldest', 'title'),
    'youtube': (
        'relevance',
        'popular',
        'newest',
        'oldest',
        'title',
        'shortest',
        'longest',
    ),
}
TEXT_FIELDS = {
    'genre',
    'country',
    'language',
    'category',
    'artist',
    'album',
    'channel',
    'platform',
    'codec',
}
BOOL_FIELDS = {'favorites', 'owned', 'installed', 'live'}
BOUNDS = {
    'min_year': (1870, date.today().year + 8),
    'max_year': (1870, date.today().year + 8),
    'min_rating': (0, 10),
    'min_votes': (0, 10**9),
    'min_duration': (0, 86400),
    'max_duration': (0, 86400),
    'min_bitrate': (0, 10000),
}


def key(value):
    text = ''.join(
        c
        for c in unicodedata.normalize('NFKD', str(value)).casefold()
        if not unicodedata.combining(c)
    )
    return ''.join(c for c in text.replace('&', 'and') if c.isalnum())


def genre_key(value):
    value = key(value)
    return {
        'scifi': 'sciencefiction',
        'sf': 'sciencefiction',
        'scifiandfantasy': 'sciencefiction',
        'sciencefictionandfantasy': 'sciencefiction',
        'sciencefictionfantasy': 'sciencefiction',
        'hiphoprap': 'hiphop',
        'randb': 'rnb',
        'randbsoul': 'rnb',
        'rhythmandblues': 'rnb',
        'roleplaying': 'rpg',
        'roleplayingrpg': 'rpg',
        'rpgs': 'rpg',
    }.get(value, value)


def canonical_genre(kind, value):
    if kind in ('movie', 'series', 'episode'):
        if kind != 'movie':
            value = {
                'fantasy': 'Sci-Fi & Fantasy',
                'action': 'Action & Adventure',
                'adventure': 'Action & Adventure',
            }.get(key(value), value)
        options = TMDB_GENRES['movie' if kind == 'movie' else 'tv']
        for name, identity in options.items():
            if genre_key(name) == genre_key(value) or str(identity) == value:
                return name
        raise ValueError('Unknown genre. Choose one of: ' + ', '.join(options))
    return value


def platform_key(value):
    value = key(value)
    return {
        'pc': 'pcmicrosoftwindows',
        'windows': 'pcmicrosoftwindows',
        'ps5': 'playstation5',
        'ps4': 'playstation4',
    }.get(value, value)


def normalize(kind, filters):
    if not isinstance(filters, dict):
        raise ValueError('filters must be an object.')
    allowed = COMMON | FIELDS[kind]
    unsupported = set(filters) - allowed
    if unsupported:
        raise ValueError(
            f'{kind} does not support: {", ".join(sorted(unsupported))}. Supported filters: {", ".join(sorted(allowed))}.'
        )
    result = {}
    for name, value in filters.items():
        if name in TEXT_FIELDS:
            if (
                not isinstance(value, str)
                or not 1 <= len(value.strip()) <= 100
                or any(ord(c) < 32 for c in value)
                or not any(c.isalnum() for c in value)
            ):
                raise ValueError(name + ' must contain 1 to 100 characters.')
            result[name] = value.strip()
        elif name in BOOL_FIELDS:
            if type(value) is not bool:
                raise ValueError(name + ' must be boolean.')
            result[name] = value
        elif name in BOUNDS:
            low, high = BOUNDS[name]
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not low <= value <= high
                or (name != 'min_rating' and int(value) != value)
            ):
                raise ValueError(f'{name} must be between {low} and {high}.')
            result[name] = value if name == 'min_rating' else int(value)
        elif name == 'availability':
            if value not in ('any', 'local', 'library'):
                raise ValueError('availability must be any, local, or library.')
            result[name] = value
        elif name == 'sort':
            if value not in SORTS[kind]:
                raise ValueError('sort must be one of: ' + ', '.join(SORTS[kind]))
            result[name] = value
    if 'genre' in result:
        result['genre'] = canonical_genre(kind, result['genre'])
    if kind in ('movie', 'series', 'episode') and 'country' in result:
        if not re.fullmatch(r'[A-Za-z]{2}', result['country']):
            raise ValueError(
                'Movie/series country must be a two-letter country code, such as US or JP.'
            )
        result['country'] = result['country'].upper()
    for low, high in (('min_year', 'max_year'), ('min_duration', 'max_duration')):
        if low in result and high in result and result[low] > result[high]:
            raise ValueError(low + ' must not exceed ' + high + '.')
    return result


def strings(value):
    if isinstance(value, str):
        return [part.strip() for part in value.split(',') if part.strip()]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.extend(
                    str(item[field])
                    for field in ('name', 'code', 'iso_3166_1', 'id')
                    if item.get(field)
                )
            else:
                result.append(str(item))
        return result
    return []


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def item_for(card):
    entity = card['payload'].get('title') or card['payload'].get('item') or {}
    return {**card.get('metadata', {}), **entity}


def year(item):
    match = re.match(
        r'\d{4}',
        str(item.get('year') or item.get('releaseDate') or item.get('date') or ''),
    )
    return int(match[0]) if match else None


def accepts(card, filters, trusted=()):
    """Missing metadata never satisfies a constraint unless its provider applied it."""
    item = item_for(card)
    availability = filters.get('availability', 'any')
    if availability == 'local' and card['availability'] != 'Local':
        return False
    in_library = (
        card['availability'] == 'Local'
        or item.get('favorite')
        or item.get('libraryEntry')
        or item.get('ownedBy')
        or item.get('source') in ('nextcloud', 'music-local')
    )
    if availability == 'library' and not in_library:
        return False
    if filters.get('favorites') and not item.get('favorite'):
        return False
    if 'installed' in filters and bool(item.get('installedBy')) != filters['installed']:
        return False
    if filters.get('installed') is False and not item.get('installationKnown'):
        return False
    if 'owned' in filters and bool(item.get('ownedBy')) != filters['owned']:
        return False
    if filters.get('owned') is False and not item.get('ownershipKnown'):
        return False
    if 'live' in filters and bool(item.get('live')) != filters['live']:
        return False
    groups = {
        'genre': strings(item.get('genres'))
        + strings(item.get('genreNames'))
        + strings(item.get('tags'))
        + strings(item.get('genreIds')),
        'platform': strings(item.get('platforms')) + strings(item.get('platformIds')),
        'country': strings(item.get('countries'))
        + strings(item.get('country'))
        + strings(item.get('countryName'))
        + strings(item.get('countrycode')),
        'language': strings(item.get('languages'))
        + strings(item.get('languageNames'))
        + strings(item.get('language')),
        'category': strings(item.get('categories'))
        + strings(item.get('categoryNames')),
        'codec': strings(item.get('codec')),
    }
    for name, values in groups.items():
        if name not in filters:
            continue
        normalize_value = (
            genre_key
            if name == 'genre'
            else platform_key
            if name == 'platform'
            else key
        )
        if not any(
            normalize_value(value) == normalize_value(filters[name]) for value in values
        ):
            if name not in trusted or values:
                return False
    for name, value in (
        (
            'artist',
            item.get('name') if card['kind'] == 'artist' else item.get('artist'),
        ),
        ('album', item.get('album')),
        (
            'channel',
            ' '.join(
                str(item.get(k) or '')
                for k in ('creator', 'channel', 'channelId', 'channelHandle')
            ),
        ),
    ):
        if name in filters and key(filters[name]) not in key(value or ''):
            return False
    rating = number(item.get('rating'))
    if rating is not None and card['kind'] == 'game':
        rating *= 2  # Games stores IGDB scores on a five-point scale.
    metrics = {
        'min_year': year(item),
        'max_year': year(item),
        'min_rating': rating,
        'min_votes': number(item.get('votes', item.get('ratingCount'))),
        'min_duration': number(item.get('duration')) or None,
        'max_duration': number(item.get('duration')) or None,
        'min_bitrate': number(item.get('bitrate')),
    }
    for name, actual in metrics.items():
        if name in filters and (
            actual is None
            or (
                actual > filters[name]
                if name.startswith('max_')
                else actual < filters[name]
            )
        ):
            if name not in trusted or actual is not None:
                return False
    return True


def sort_key(card, sort):
    item = item_for(card)
    if sort == 'title':
        return key(card['title'])
    if sort in ('newest', 'oldest'):
        value = year(item)
    elif sort in ('shortest', 'longest'):
        value = number(item.get('duration'))
    elif sort == 'rating':
        value = number(item.get('rating'))
    elif sort == 'bitrate':
        value = number(item.get('bitrate'))
    elif card['kind'] in ('movie', 'series', 'episode'):
        value = number(item.get('popularity'))
    else:
        value = number(
            item.get(
                'votes',
                item.get('ratingCount', item.get('clickcount', item.get('views'))),
            )
        )
    return (value is None, (value or 0) * (1 if sort in ('oldest', 'shortest') else -1))


def capabilities(kind):
    if kind not in KINDS:
        raise ValueError('Choose a supported Space search category.')
    result = dict(
        kind=kind,
        filters=sorted(COMMON | FIELDS[kind]),
        sorts=SORTS[kind],
        availability=['any', 'local', 'library'],
        rating_scale='0–10',
        duration_unit='seconds',
        notes=[
            'Unknown metadata is excluded when filtering. Results are a bounded candidate set; refine filters for more choices.'
        ],
    )
    if kind in ('movie', 'series', 'episode'):
        result['genres'] = list(TMDB_GENRES['movie' if kind == 'movie' else 'tv'])
        result['notes'].append(
            'Online genre discovery without a title requires TMDB. Country uses ISO 3166-1 alpha-2 codes.'
        )
    if kind == 'episode':
        result['notes'].append(
            'Online episode lookup requires show name S01E02. Filters describe the parent series.'
        )
    if kind == 'youtube':
        result['notes'].append(
            'Online video searches need query text; channel and duration filter returned metadata.'
        )
    if kind == 'radio':
        result['notes'].append(
            'Country may be a directory country name or a two-letter code. Bitrate is in kbps.'
        )
    result['notes'].append(
        'library includes local files, owned store games, saved music and favorites; it excludes ordinary provider caches. local requires an available local file or installed game. favorites=true keeps favorites only.'
    )
    if kind in ('music', 'song', 'album', 'artist'):
        result['notes'].append(
            'Genre discovery samples genre charts; year, artist and duration constraints use returned metadata. Exact title/artist queries can find older material absent from current charts.'
        )
    return result


def schema():
    properties = {name: {'type': 'string'} for name in sorted(TEXT_FIELDS)}
    properties.update({name: {'type': 'boolean'} for name in sorted(BOOL_FIELDS)})
    properties.update(
        {
            name: {
                'type': 'number' if name == 'min_rating' else 'integer',
                'minimum': low,
                'maximum': high,
            }
            for name, (low, high) in BOUNDS.items()
        }
    )
    properties.update(
        availability={'type': 'string', 'enum': ['any', 'local', 'library']},
        sort={
            'type': 'string',
            'enum': sorted({value for values in SORTS.values() for value in values}),
        },
    )
    return {
        'type': 'object',
        'description': 'Use space_filters to inspect supported fields and canonical values for this kind. Scores use 0–10; durations use seconds. Unsupported filters fail explicitly.',
        'properties': properties,
        'additionalProperties': False,
    }
