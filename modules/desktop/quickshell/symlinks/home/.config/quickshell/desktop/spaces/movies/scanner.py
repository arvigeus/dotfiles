"""Reviewable discovery of completed qBittorrent and filesystem media."""

import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from spaces.movies.local import EXTENSIONS, episode_numbers, media_sidecar_paths

try:
    from guessit import guessit
except ImportError:
    guessit = None

EXTRA_FOLDERS = ('extras', 'samples', 'trailers')


def extra(path, base):
    """A sample, local trailer or bonus video rather than the feature itself."""
    stem = path.stem.casefold()
    relative = path.relative_to(base) if path.is_relative_to(base) else path
    return (
        'sample' in stem
        or re.search(r'(?:^|[-._ ])trailer$', stem) is not None
        or any(part.casefold() in EXTRA_FOLDERS for part in relative.parts[:-1])
    )


def visible_files(root, extensions):
    """Files below root with these suffixes, skipping hidden entries and links.

    Hidden folders hold application data (games, caches, other Spaces), whose
    videos must never be organized into a library.
    """
    found = []
    for directory, folders, files in os.walk(root):
        folders[:] = [name for name in folders if not name.startswith('.')]
        found.extend(
            Path(directory, name)
            for name in files
            if not name.startswith('.') and Path(name).suffix.lower() in extensions
        )
    return sorted(found)


def settled(torrent):
    """Complete and not being moved or rechecked by qBittorrent."""
    return float(torrent.get('progress') or 0) >= 1 and torrent.get('state') not in (
        'moving',
        'checkingUP',
        'checkingDL',
        'checkingResumeData',
    )


def sidecar_identity(path, kind):
    for sidecar in media_sidecar_paths(path):
        if not sidecar.is_file() or sidecar.is_symlink():
            continue
        try:
            value = json.loads(sidecar.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get('kind') and value.get('id'):
            return value
    if kind == 'movie':
        # movie.nfo describes its folder's one feature; trailers, extras and
        # other movies beside or below it are different files.
        try:
            videos = [
                item.name
                for item in path.parent.iterdir()
                if item.suffix.lower() in EXTENSIONS['movie']
                and not item.name.startswith('.')
                and item.is_file()
                and not extra(item, path.parent)
            ]
        except OSError:
            return {}
        folders = (path.parent,) if videos == [path.name] else ()
    elif kind == 'tv':
        # A show's NFO sits in its folder, one level above Season folders.
        folders = (path.parent, path.parent.parent)
    else:
        return {}
    for folder in folders:
        nfo = folder / ('movie.nfo' if kind == 'movie' else 'tvshow.nfo')
        try:
            root = ET.parse(nfo).getroot()
        except (OSError, ET.ParseError):
            continue
        title = {
            'kind': kind,
            'title': root.findtext('title') or '',
            'year': root.findtext('year') or '',
        }
        for item in root.findall('uniqueid'):
            if item.get('type') == 'imdb' and item.text:
                title['id'] = title['imdbId'] = item.text
            elif item.get('type') == 'tmdb' and item.text:
                title['tmdbId'] = item.text
                title.setdefault('id', f'tmdb:{kind}:{item.text}')
        return title if title.get('id') and title.get('title') else {}
    return {}


def audio_tags(path):
    try:
        result = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format_tags=title,artist,album,date',
                '-of',
                'json',
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        tags = json.loads(result.stdout).get('format', {}).get('tags', {})
        tags = {key.casefold(): value for key, value in tags.items()}
        return {key: tags.get(key, '') for key in ('title', 'artist', 'album', 'date')}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def guess(path, kind):
    if kind in ('movie', 'tv') and guessit:
        try:
            data = guessit(
                str(path) if kind == 'tv' else path.name,
                options={'type': 'episode' if kind == 'tv' else 'movie'},
            )
        except (ValueError, TypeError):
            data = {}
        title = str(data.get('title') or path.parent.name)
        year = data.get('year')
        output = {'title': title, 'year': str(year or '')}
        if kind == 'tv':
            output['episodeTitle'] = str(data.get('episode_title') or '')
            season, episode = data.get('season'), data.get('episode')
            if not isinstance(season, int):
                match = re.search(r'(?i)\bSeason[ ._-]*(\d{1,2})\b', path.parent.name)
                if match:
                    season = int(match[1])
                    output['title'] = path.parent.parent.name.split(' (')[0]
            if not isinstance(episode, int):
                match = re.search(r'(?i)\b(?:E|Episode)[ ._-]*(\d{1,3})\b', path.stem)
                if match:
                    episode = int(match[1])
            if isinstance(season, int) and isinstance(episode, int):
                output.update(season=season, episode=episode)
        return output
    if kind == 'music':
        tags = audio_tags(path)
        return {
            'title': tags.get('title') or path.stem,
            'artist': tags.get('artist') or '',
            'album': tags.get('album') or '',
            'releaseDate': tags.get('date') or '',
        }
    return {'title': path.stem}


def catalogue_match(catalogue, kind, parsed):
    if (
        kind not in ('movie', 'tv')
        or not parsed.get('title')
        or (kind == 'movie' and not parsed.get('year'))
    ):
        return None
    try:
        items = catalogue.browse(
            {'kind': kind, 'query': parsed['title'], 'filters': {}}
        )['items']
    except Exception:
        return None

    def normalize(value):
        return re.sub(r'\W+', '', str(value or '').casefold())

    matches = {
        str(item['id']): item
        for item in items
        if normalize(item.get('title')) == normalize(parsed['title'])
        and (
            not parsed.get('year')
            or str(item.get('year') or '')[:4] == str(parsed['year'])[:4]
        )
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def candidates(kind, root, qbit, managed_staging=(), torrents=None, managed_hashes=()):
    """Yield qBittorrent sources first, then ordinary files, with no mutation."""
    seen = set()
    # Remember every torrent payload so incomplete and tracked files cannot be
    # mistaken for ordinary completed videos during the filesystem pass.
    excluded = set()
    for torrent in torrents if torrents is not None else qbit.call('torrents/info'):
        save = Path(torrent.get('save_path') or '').resolve()
        if not save.is_dir():
            continue
        managed = str(torrent.get('hash') or '') in managed_hashes
        complete = settled(torrent)
        for file in qbit.call('torrents/files?hash=' + str(torrent['hash'])):
            relative = Path(file.get('name') or '')
            raw = save / relative
            path = raw.resolve()
            if (
                not relative.is_absolute()
                and '..' not in relative.parts
                and path.is_relative_to(save)
            ):
                excluded.add(path)
                excluded.add(path.with_name(path.name + '.!qB'))
            episodic = bool(
                episode_numbers(path.name)
                or re.search(r'(?i)\b\d{1,2}(?:E|x)\d{1,3}\b', path.name)
            )
            if (
                relative.is_absolute()
                or managed
                or not complete
                or '..' in relative.parts
                or not path.is_relative_to(save)
                or not path.is_file()
                or raw.is_symlink()
                or path.suffix.lower() not in EXTENSIONS[kind]
                or (kind == 'movie' and episodic)
                or (kind == 'tv' and not episodic)
                or (kind in ('movie', 'tv') and extra(path, save))
                or int(file.get('priority', 1)) == 0
            ):
                continue
            seen.add(path)
            yield {
                'path': str(path),
                'torrent_hash': str(torrent['hash']),
                'source': 'qBittorrent',
            }
    root = Path(root).expanduser().resolve()
    paths = (
        [root]
        if root.is_file()
        else visible_files(root, EXTENSIONS[kind])
        if root.is_dir()
        else []
    )
    staging = [Path(folder).resolve() for folder in managed_staging]
    for path in paths:
        if (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in EXTENSIONS[kind]
            and path not in seen
            and path not in excluded
            and not (kind in ('movie', 'tv') and path != root and extra(path, root))
            and not any(path.is_relative_to(folder) for folder in staging)
        ):
            yield {'path': str(path), 'torrent_hash': '', 'source': 'Folder'}
