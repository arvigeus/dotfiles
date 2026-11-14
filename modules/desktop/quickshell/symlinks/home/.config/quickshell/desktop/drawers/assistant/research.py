"""Read-only web and lyrics tools in a bounded, disposable worker."""

import json
from pathlib import Path
import re
import signal
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ui import space_search as Spaces
import web


class ResearchDeadline(BaseException):
    pass


def integer(args, name, default, low, high):
    value = args.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer between {low} and {high}.')
    return value


def normalize(name, args):
    fields = {
        'web_search': {'query', 'limit'},
        'read_web_page': {'url', 'offset', 'max_chars'},
        'search_lyrics': {'fragment', 'online', 'limit', 'display'},
        'get_song_lyrics': {'ref', 'online', 'offset', 'max_chars'},
    }
    if not isinstance(args, dict) or name not in fields or set(args) - fields[name]:
        raise ValueError('Unsupported research tool arguments.')
    result = dict(args)
    if name in ('web_search', 'search_lyrics'):
        field = 'query' if name == 'web_search' else 'fragment'
        value = args.get(field)
        if (
            not isinstance(value, str)
            or not 3 <= len(value.strip()) <= 500
            or any(ord(c) < 32 and c not in '\n\t' for c in value)
        ):
            raise ValueError(f'{field} requires 3 to 500 characters of text.')
        result[field] = ' '.join(value.split())
        result['limit'] = integer(args, 'limit', 5, 1, 6)
        if name == 'search_lyrics' and len(words(value)) < 5:
            raise ValueError(
                'Use a lyric fragment with at least five letters or numbers.'
            )
    if name in ('search_lyrics', 'get_song_lyrics'):
        if type(args.get('online', True)) is not bool:
            raise ValueError('online must be boolean.')
        result['online'] = args.get('online', True)
    if name == 'search_lyrics':
        if type(args.get('display', True)) is not bool:
            raise ValueError('display must be boolean.')
        result['display'] = args.get('display', True)
    if name in ('read_web_page', 'get_song_lyrics'):
        result['offset'] = integer(args, 'offset', 0, 0, web.MAX_TEXT + 200000)
        result['max_chars'] = integer(args, 'max_chars', 9000, 500, 10000)
    if name == 'read_web_page':
        result['url'] = web.clean_url(args.get('url'))
    if name == 'get_song_lyrics' and (
        not isinstance(args.get('ref'), str)
        or not re.fullmatch(r'space_[a-f0-9]{32}', args['ref'])
    ):
        raise ValueError('Use a song ref returned by search_spaces or search_lyrics.')
    return result


def words(value):
    value = re.sub(r'\[\d{1,3}:\d{2}(?:[.:]\d+)?\]', ' ', value)
    value = Spaces.fold(unicodedata.normalize('NFKC', value))
    return ' '.join(re.findall(r'[^\W_]+', value, re.UNICODE))


def local_file(relative):
    from spaces.music import local_files

    root = local_files.ROOT
    rel = Path(relative)
    if (
        not relative
        or rel.is_absolute()
        or any(part in ('.', '..') or part.startswith('.') for part in rel.parts)
    ):
        return None
    if root.is_symlink() or root.is_mount():
        return None
    path = root
    for part in rel.parts:
        path /= part
        if path.is_symlink():
            return None
    try:
        return (
            path
            if path.is_file() and path.resolve().is_relative_to(root.resolve())
            else None
        )
    except OSError:
        return None


def inventory_rows(path, wanted=None):
    if path is None:
        return
    for relative, signature, payload in Spaces.iter_rows(
        path.parent / 'local.sqlite',
        'SELECT path,signature,payload FROM files LIMIT 10000',
    ):
        if wanted is not None and relative not in wanted:
            continue
        try:
            file = local_file(relative)
            if not file:
                continue
            stat = file.stat()
            if json.loads(signature) != [stat.st_ino, stat.st_size, stat.st_mtime_ns]:
                continue
            details = json.loads(payload)
            if isinstance(details, dict) and isinstance(details.get('tags'), dict):
                yield relative, file, details
        except (OSError, ValueError, TypeError):
            continue


def library_songs(path):
    if path is None:
        return
    for (payload,) in Spaces.iter_rows(
        path, "SELECT payload FROM records WHERE kind='song' LIMIT 20000"
    ):
        try:
            song = json.loads(payload)
            if (
                isinstance(song, dict)
                and song.get('account') == path.parent.name
                and song.get('source') in ('music-local', 'nextcloud')
            ):
                yield song
        except (ValueError, TypeError):
            continue


def local_matches(fragment, limit):
    path = Spaces.music_path()
    by_path = {
        str(song.get('serverPath', '')).lstrip('/'): song
        for song in library_songs(path)
    }
    needle, result = words(fragment), []
    for relative, file, details in inventory_rows(path):
        tags = details['tags']
        lyrics = str(tags.get('lyrics') or '')[:200000]
        normalized = words(lyrics)
        if ' ' + needle + ' ' not in ' ' + normalized + ' ':
            continue
        song = by_path.get(relative) or dict(
            id='local:' + relative,
            source='music-local',
            account=path.parent.name,
            title=tags.get('title') or file.stem,
            artist=tags.get('artist', ''),
            album=tags.get('album', ''),
            serverPath='/' + relative,
            duration=details.get('duration', 0),
        )
        song = {k: v for k, v in song.items() if k != 'lyrics'}
        song.update(local=True, localPath=str(file))
        card = Spaces.card('song', song, local=True, saved=True)
        if card:
            index = normalized.find(needle)
            card['metadata'].update(
                lyrics_source='Embedded library lyrics',
                lyrics_excerpt=normalized[
                    max(0, index - 50) : index + len(needle) + 80
                ][:300],
            )
            result.append(card)
        if len(result) >= limit:
            break
    return result


def search_lyrics(args):
    items = local_matches(args['fragment'], args['limit'])
    result = dict(
        fragment=args['fragment'],
        items=items,
        entries=[],
        display=args.get('display', True),
        local_checked=True,
    )
    if items or not args.get('online', True):
        result['warning'] = (
            ''
            if items
            else 'No match in indexed local lyrics. Open Music to refresh its library; songs without embedded lyrics cannot match here.'
        )
        return result
    try:
        evidence = web.search(
            '"' + args['fragment'].replace('"', '') + '" lyrics', args['limit']
        )
        result.update(
            entries=evidence['entries'],
            provider=evidence['provider'],
            warning=evidence.get('warning', ''),
        )
        result['next_step'] = (
            'These are web leads, not verified song identities. Read promising pages, verify title and artist, then search_spaces(kind=song) and present the matching card. Say when identification is uncertain.'
        )
    except web.WebError as error:
        result['warning'] = 'No indexed local lyric match. ' + str(error)
    return result


def get_lyrics(args):
    # The parent resolves an opaque ref to this entity; the model cannot pass a
    # path, credentials, or arbitrary song object to this worker.
    song = {k: v for k, v in args['song'].items() if k != 'lyrics'}
    path = Spaces.music_path()
    candidates = [
        candidate
        for candidate in library_songs(path)
        if words(str(candidate.get('title', ''))) == words(str(song.get('title', '')))
        and words(str(candidate.get('artist', '')))
        == words(str(song.get('artist', '')))
    ]
    candidates.sort(
        key=lambda candidate: (
            candidate.get('id') != song.get('id'),
            candidate.get('album') != song.get('album'),
            not candidate.get('local'),
        )
    )
    if (
        path
        and song.get('source') in ('nextcloud', 'music-local')
        and song.get('account') == path.parent.name
        and not any(candidate.get('id') == song.get('id') for candidate in candidates)
    ):
        candidates.insert(0, song)
    candidates = candidates[:20]
    wanted = {
        str(candidate.get('serverPath', '')).lstrip('/') for candidate in candidates
    }
    cached = {
        relative: details for relative, _file, details in inventory_rows(path, wanted)
    }
    for candidate in candidates:
        details = cached.get(str(candidate.get('serverPath', '')).lstrip('/'), {})
        lyrics = str(details.get('tags', {}).get('lyrics') or '').strip()
        if lyrics:
            return dict(
                available=True,
                title=candidate.get('title', ''),
                artist=candidate.get('artist', ''),
                provider='Song tags',
                saved=True,
                **web.chunk(
                    lyrics[:200000], args.get('offset', 0), args.get('max_chars', 9000)
                ),
            )
    # Full embedded tags and existing Music/Nextcloud/provider caches are shared
    # with the Music Space. Looking up lyrics never downloads or edits audio.
    from spaces.music.backend import fetch_lyrics

    preferred = candidates[0] if candidates else song
    preferred = {k: v for k, v in preferred.items() if k != 'lyrics'}
    result = fetch_lyrics(dict(song=preferred, online=args.get('online', True)))
    return dict(
        available=result.get('available', False),
        title=preferred.get('title', ''),
        artist=preferred.get('artist', ''),
        provider=result.get('provider', ''),
        saved=result.get('saved', False),
        **web.chunk(
            str(result.get('lyrics') or '')[:200000],
            args.get('offset', 0),
            args.get('max_chars', 9000),
        ),
    )


def execute(name, args):
    if name == 'web_search':
        return web.search(args['query'], args.get('limit', 5))
    if name == 'read_web_page':
        return web.read_page(
            args['url'], args.get('offset', 0), args.get('max_chars', 9000)
        )
    if name == 'search_lyrics':
        return search_lyrics(args)
    if name == 'get_song_lyrics':
        return get_lyrics(args)
    raise ValueError('Unknown research operation.')


def main():
    def expired(_signum, _frame):
        raise ResearchDeadline()

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(28)
    try:
        request = json.loads(sys.argv[1])
        result = execute(request['name'], request['arguments'])
    except ResearchDeadline:
        result = dict(
            error='Research timed out. Try a narrower request or online=false for lyrics.'
        )
    except Spaces.SEARCH_ERRORS as error:
        result = dict(error=str(error)[:500])
    finally:
        signal.alarm(0)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
