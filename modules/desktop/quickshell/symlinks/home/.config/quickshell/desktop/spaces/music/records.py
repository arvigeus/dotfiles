"""Catalogue record normalization, identity validation, and playback matching.

These functions do not fetch data, start players, or read configuration.
"""

import html
import math
import re
import unicodedata
import urllib.parse


class MusicError(Exception):
    pass


def clean_artist_biography(value):
    text = html.unescape(str(value or ''))
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:p|div|h[1-6]|li)\s*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text)
    return text.strip()


def safe_catalog_id(value):
    value = str(value or '').strip()
    if not re.fullmatch(r'[0-9]{1,32}', value):
        raise MusicError('The selected catalog item has an invalid ID.')
    return value


def parse_playlist_id(value):
    if value is None or value == '':
        return ''
    if not isinstance(value, str):
        raise MusicError('default_playlist must be an Apple Music playlist ID or URL.')
    value = value.strip()
    if not value:
        return ''
    if '://' in value:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != 'https' or parsed.netloc != 'music.apple.com':
            raise MusicError(
                'default_playlist must be an Apple Music playlist ID or URL.'
            )
        parts = parsed.path.strip('/').split('/')
        value = parts[-1] if parts else ''
    if not re.fullmatch(r'pl\.[A-Za-z0-9._-]{1,120}', value):
        raise MusicError('default_playlist must be an Apple Music playlist ID or URL.')
    return value


def safe_playlist_id(value):
    value = str(value or '').strip()
    if not re.fullmatch(r'pl\.[A-Za-z0-9._-]{1,120}', value):
        raise MusicError('The configured Apple Music playlist ID is invalid.')
    return value


def safe_stream_id(value):
    value = str(value or '').strip()
    if not value or len(value) > 256 or any(char in value for char in '\r\n\x00'):
        raise MusicError('The playback provider returned an invalid track ID.')
    return value


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    value = re.sub(r'\b(feat|featuring|ft)\.?\s+.*$', '', value)
    value = ''.join(char if char.isalnum() else ' ' for char in value)
    return ' '.join(value.split())


def clean_duration(value, *, milliseconds=False):
    try:
        duration = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(duration):
        return 0
    if milliseconds:
        duration /= 1000
    return max(0, int(round(duration)))


def raw_artists(item):
    names = item.get('artistNames')
    if isinstance(names, list) and names:
        return [str(name).strip() for name in names if str(name).strip()]
    artists = item.get('artists')
    if isinstance(artists, list):
        return [
            str(artist.get('name') or artist.get('displayName') or '').strip()
            for artist in artists
            if isinstance(artist, dict)
            and (artist.get('name') or artist.get('displayName'))
        ]
    artist = item.get('artistName') or item.get('artist')
    return [str(artist).strip()] if artist else []


def apple_cover(attributes):
    url = (attributes.get('artwork') or {}).get('url') or ''
    return str(url).replace('{w}', '640').replace('{h}', '640').replace('{f}', 'jpg')


def normalize_apple(item, kind):
    """Convert one Apple catalog resource of `kind` (songs, albums, artists) to a record."""
    if not isinstance(item, dict) or kind not in ('songs', 'albums', 'artists'):
        return None
    attributes = item.get('attributes') or {}
    relationships = item.get('relationships') or {}

    def related(name):
        data = (relationships.get(name) or {}).get('data') or []
        return [
            str(value['id'])
            for value in data
            if isinstance(value, dict) and value.get('id')
        ]

    record = {
        'id': str(item.get('id') or ''),
        'source': 'apple',
        'cover': apple_cover(attributes),
    }
    if kind == 'artists':
        notes = attributes.get('editorialNotes')
        notes = notes if isinstance(notes, dict) else {}
        return record | {
            'kind': 'artist',
            'name': str(attributes.get('name') or 'Unknown Artist'),
            'genres': [
                str(name) for name in attributes.get('genreNames') or [] if name
            ],
            'biography': '',
            'editorialNotes': {
                field: text
                for field in ('name', 'tagline', 'short', 'standard')
                if (text := clean_artist_biography(notes.get(field)))
            },
            'url': str(attributes.get('url') or ''),
        }
    artist = str(attributes.get('artistName') or '').strip()
    record |= {
        'artist': artist or 'Unknown Artist',
        'artists': [artist] if artist else [],
        'artistIds': related('artists'),
        'releaseDate': str(attributes.get('releaseDate') or ''),
        'genreNames': [
            str(name) for name in attributes.get('genreNames') or [] if name
        ],
    }
    if kind == 'albums':
        return record | {
            'kind': 'album',
            'title': str(attributes.get('name') or 'Unknown Album'),
        }
    albums = related('albums')
    return record | {
        'kind': 'song',
        'title': str(attributes.get('name') or 'Unknown Title'),
        'album': str(attributes.get('albumName') or 'Unknown Album'),
        'albumId': albums[0] if albums else '',
        'duration': clean_duration(
            attributes.get('durationInMillis'), milliseconds=True
        ),
        'isrc': str(attributes.get('isrc') or ''),
    }


def score_candidate(wanted, candidate):
    wanted_isrc = str(wanted.get('isrc') or '').strip().casefold()
    candidate_isrc = str(candidate.get('isrc') or '').strip().casefold()
    if wanted_isrc and candidate_isrc == wanted_isrc:
        return 1000
    wanted_title = normalized(wanted.get('title'))
    candidate_title = normalized(candidate.get('title'))
    if not wanted_title or not candidate_title:
        return 0
    if wanted_title == candidate_title:
        score = 100
    elif wanted_title in candidate_title or candidate_title in wanted_title:
        score = 60
    else:
        return 0
    artist = normalized(wanted.get('artist'))
    candidate_artists = [normalized(value) for value in raw_artists(candidate)]
    if artist and artist in candidate_artists:
        score += 80
    elif artist and any(
        artist in value or value in artist for value in candidate_artists
    ):
        score += 35
    return score
