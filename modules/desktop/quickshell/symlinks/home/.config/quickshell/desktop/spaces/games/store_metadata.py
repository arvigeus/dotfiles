"""Descriptive store data, independent of catalogue identity and ownership."""

import html
import re
import urllib.parse

FIELDS = (
    'summary',
    'cover',
    'artwork',
    'screenshots',
    'genres',
    'platforms',
    'developers',
    'publishers',
    'releaseDate',
    'officialWebsite',
)


def plain_text(value):
    if not isinstance(value, str):
        return ''
    value = html.unescape(value[:40000])
    value = re.sub(
        r'</?(?:p|div|br|li|h[1-6])\b[^>]*>', ' ', value, flags=re.IGNORECASE
    )
    value = re.sub(r'<[^>]*>', '', value)
    return ' '.join(value.split())[:12000]


def image(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme == 'https'
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        ):
            return {'url': value}
    except ValueError:
        pass
    return None


def fill_missing(primary, fallback):
    result = dict(primary)
    for field in FIELDS:
        if not result.get(field) and fallback.get(field):
            result[field] = fallback[field]
    return result


def steam_artwork(app_id):
    if not re.fullmatch(r'[1-9][0-9]{0,9}', str(app_id)):
        return {}
    base = f'https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/'
    return {
        'cover': image(base + 'library_600x900.jpg'),
        'artwork': [image(base + 'header.jpg')],
    }


def steam_details(raw, app_id):
    entry = raw.get(str(app_id)) if isinstance(raw, dict) else None
    data = (
        entry.get('data') if isinstance(entry, dict) and entry.get('success') else None
    )
    # Never accept a different product returned by the store.
    if not isinstance(data, dict) or str(data.get('steam_appid')) != str(app_id):
        return {}
    result = {
        'summary': plain_text(
            data.get('short_description') or data.get('about_the_game')
        ),
        'cover': image(data.get('header_image')),
        'artwork': [art]
        if (art := image(data.get('background_raw') or data.get('background')))
        else [],
        'screenshots': [
            art
            for shot in (data.get('screenshots') or [])[:32]
            if isinstance(shot, dict) and (art := image(shot.get('path_full')))
        ],
        'genres': [
            plain_text(row['description'])
            for row in (data.get('genres') or [])
            if isinstance(row, dict) and row.get('description')
        ],
        'platforms': [
            name
            for key, name in (
                ('windows', 'Windows'),
                ('mac', 'macOS'),
                ('linux', 'Linux'),
            )
            if (data.get('platforms') or {}).get(key)
        ],
        'developers': [plain_text(name) for name in (data.get('developers') or [])],
        'publishers': [plain_text(name) for name in (data.get('publishers') or [])],
    }
    website = image(data.get('website'))
    if website:
        result['officialWebsite'] = website['url']
    # Steam release strings are localized and may say "Coming soon"; don't
    # turn these into a fabricated ISO date.
    return result


def epic_details(record):
    data = record.get('metadata')
    if not isinstance(data, dict):
        return {}
    images = {}
    for row in (data.get('keyImages') or [])[:32]:
        if isinstance(row, dict) and (art := image(row.get('url'))):
            images.setdefault(row.get('type'), art)
    cover = next(
        (
            images[kind]
            for kind in (
                'DieselGameBoxTall',
                'OfferImageTall',
                'Thumbnail',
                'DieselGameBox',
                'OfferImageWide',
            )
            if kind in images
        ),
        None,
    )
    backdrop = next(
        (
            images[kind]
            for kind in ('DieselGameBox', 'OfferImageWide', 'Screenshot')
            if kind in images
        ),
        None,
    )
    result = {
        'summary': plain_text(data.get('description')),
        'cover': cover,
        'artwork': [backdrop] if backdrop else [],
    }
    if data.get('developer'):
        result['developers'] = [plain_text(data['developer'])]
    release = str(data.get('releaseDate') or '')[:10]
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', release):
        result['releaseDate'] = release
    return result


def gog_details(record):
    extra = record.get('extra') if isinstance(record.get('extra'), dict) else {}
    about = extra.get('about') if isinstance(extra.get('about'), dict) else {}
    artwork = image(record.get('art_background'))
    result = {
        'summary': plain_text(
            about.get('description') or about.get('shortDescription')
        ),
        'cover': image(record.get('art_square')) or image(record.get('art_cover')),
        'artwork': [artwork] if artwork else [],
        'developers': [plain_text(record['developer'])]
        if record.get('developer')
        else [],
        'genres': [
            plain_text(value)
            for value in extra.get('genres', [])
            if isinstance(value, str)
        ]
        if isinstance(extra.get('genres'), list)
        else [],
        'platforms': [
            name
            for key, name in (('is_linux_native', 'Linux'), ('is_mac_native', 'macOS'))
            if record.get(key) is True
        ],
    }
    return result
