"""Nextcloud library browsing over the shell's shared Subsonic account."""

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations import nextcloud
from integrations.subsonic import MusicError, SubsonicClient
from spaces.music.cloud_index import CatalogueIndex
from spaces.music.storage import atomic_write

PAGE = 50
_INDEXES = {}
_INDEX_LOCK = threading.Lock()
_INVENTORIES = {}
_COVER_LOCKS = [threading.Lock() for _ in range(64)]


def identity(value):
    value = str(value or '')
    if not value or len(value) > 256 or any(c in value for c in '\r\n\0'):
        raise MusicError('The library item has an invalid identity.')
    return value


def record(raw, kind, account):
    if not isinstance(raw, dict):
        raise MusicError('Nextcloud returned an invalid library item.')
    item = dict(
        id=identity(raw.get('id')),
        source='nextcloud',
        account=account,
        kind=kind,
        starred=bool(raw.get('starred')),
        coverArt=str(raw.get('coverArt') or ''),
    )
    if kind == 'artist':
        return item | dict(name=str(raw.get('name') or 'Unknown artist'), genres=[])
    item.update(
        title=str(raw.get('title') or raw.get('name') or 'Untitled'),
        artist=str(raw.get('artist') or 'Unknown artist'),
        artistIds=[str(raw['artistId'])] if raw.get('artistId') else [],
        genreNames=[str(raw['genre'])] if raw.get('genre') else [],
        releaseDate=str(raw.get('year') or ''),
    )
    if kind == 'song':
        item.update(
            album=str(raw.get('album') or ''),
            albumId=str(raw.get('albumId') or ''),
            fileInfo=' · '.join(
                filter(
                    None,
                    [
                        str(raw.get('suffix') or '').upper(),
                        str(raw['bitRate']) + ' kbps' if raw.get('bitRate') else '',
                    ],
                )
            ),
            duration=int(raw.get('duration') or 0),
            discNumber=int(raw.get('discNumber') or 0),
            trackNumber=int(raw.get('track') or 0),
            serverPath=str(raw.get('path') or ''),
            playCount=int(raw['playCount'])
            if raw.get('playCount') is not None
            else None,
        )
    return item


class LibraryClient(SubsonicClient):
    METHODS = {
        'search3',
        'getArtists',
        'getArtist',
        'getAlbum',
        'getSong',
        'getLyricsBySongId',
        'getCoverArt',
        'getPlaylists',
        'getPlaylist',
        'getArtistInfo2',
        'getAlbumList2',
        'getSongsByGenre',
        'getStarred2',
        'getGenres',
        'star',
        'unstar',
        'stream',
    }


class CloudLibrary:
    def __init__(self, client=None, cache=None):
        try:
            self.client = client or LibraryClient()
        except nextcloud.NextcloudError as error:
            raise MusicError(str(error)) from None
        self.account = self.client.account_id
        self.cache = (
            Path(cache)
            if cache
            else Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
            / 'quickshell/desktop/spaces/music/nextcloud'
            / self.account
        )
        self.warning = ''
        key = (str(self.cache), self.account)
        with _INDEX_LOCK:
            if key not in _INDEXES:
                _INDEXES[key] = CatalogueIndex(self.client, self.cache, record)
            self.index = _INDEXES[key]
            if not self.index.running:
                self.index.client = self.client

    def request(self, method, refresh=False, **args):
        path = self.cache / (
            hashlib.sha256(
                json.dumps([method, args], sort_keys=True).encode()
            ).hexdigest()
            + '.json'
        )
        try:
            cached = json.loads(path.read_text())
        except (OSError, ValueError):
            cached = {}
        if not isinstance(cached, dict):
            cached = {}
        if not refresh and cached.get('updated', 0) > time.time() - 120:
            return cached['result']
        try:
            result = self.client.request(method, **args)
        except MusicError:
            if 'result' not in cached:
                raise
            self.warning = 'Nextcloud is unavailable. Showing the saved library view.'
            return cached['result']
        atomic_write(path, json.dumps(dict(updated=time.time(), result=result)))
        cached_paths = sorted(
            self.cache.glob('*.json'),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
        for old in cached_paths[256:]:
            old.unlink(missing_ok=True)
        return result

    def rows(self, values, kind):
        if not isinstance(values, list):
            raise MusicError('Nextcloud returned an invalid library list.')
        return [record(value, kind, self.account) for value in values]

    def browse(self, args):
        self.index.start(bool(args.get('refresh')))
        if args.get('category') == 'playlists':
            return self.playlists(args)
        if self.index.info():
            return self.index.browse(args)
        result = self.remote_browse(args)
        status = self.index.status()
        if status['ready']:
            result = self.index.browse(args)
        return result | dict(index=status)

    def remote_browse(self, args):
        category = args.get('category', 'songs')
        if category not in ('songs', 'albums', 'artists'):
            raise MusicError('Choose songs, albums or artists.')
        query = str(args.get('query') or '').strip()
        genre = str(args.get('genreName') or '')
        offset = max(0, int(args.get('offset') or 0))
        refresh = bool(args.get('refresh'))
        kind = {'songs': 'song', 'albums': 'album', 'artists': 'artist'}[category]
        more = False
        if args.get('starred'):
            result = self.request('getStarred2', refresh=refresh).get('starred2', {})
            items = self.rows(result.get(kind, []), kind)
            if query:
                items = [
                    item
                    for item in items
                    if query.casefold()
                    in ' '.join(
                        str(item.get(key) or '')
                        for key in ('name', 'title', 'artist', 'album')
                    ).casefold()
                ]
            if genre:
                items = [item for item in items if genre in item.get('genreNames', [])]
            more = len(items) > offset + PAGE
            items = items[offset : offset + PAGE]
        elif category == 'artists' and not query:
            indexes = (
                self.request('getArtists', refresh=refresh)
                .get('artists', {})
                .get('index', [])
            )
            items = self.rows(
                [artist for index in indexes for artist in index.get('artist', [])],
                'artist',
            )
            more = len(items) > offset + PAGE
            items = items[offset : offset + PAGE]
        elif category == 'songs' and genre and not query:
            values = (
                self.request(
                    'getSongsByGenre',
                    refresh=refresh,
                    genre=genre,
                    count=PAGE,
                    offset=offset,
                )
                .get('songsByGenre', {})
                .get('song', [])
            )
            items = self.rows(values, 'song')
            more = len(values) == PAGE
        elif category == 'albums' and not query:
            values = (
                self.request(
                    'getAlbumList2',
                    refresh=refresh,
                    type='byGenre' if genre else 'alphabeticalByName',
                    size=PAGE,
                    offset=offset,
                    **({'genre': genre} if genre else {}),
                )
                .get('albumList2', {})
                .get('album', [])
            )
            items = self.rows(values, 'album')
            more = len(values) == PAGE
        else:
            params = dict(query=query, artistCount=0, albumCount=0, songCount=0)
            params.update({kind + 'Count': PAGE, kind + 'Offset': offset})
            result = self.request('search3', refresh=refresh, **params).get(
                'searchResult3', {}
            )
            values = result.get(kind, [])
            items = self.rows(values, kind)
            more = len(values) == PAGE
            if genre:
                items = [item for item in items if genre in item.get('genreNames', [])]
        return dict(
            items=items,
            limit=offset + PAGE,
            hasMore=more,
            cursor='',
            warning=self.warning,
        )

    def playlists(self, args):
        items = [
            dict(
                id=identity(raw.get('id')),
                kind='playlist',
                source='nextcloud',
                account=self.account,
                title=str(raw.get('name') or 'Untitled playlist'),
                songCount=int(raw.get('songCount') or 0),
            )
            for raw in self.request('getPlaylists', refresh=bool(args.get('refresh')))
            .get('playlists', {})
            .get('playlist', [])
        ]
        query = str(args.get('query') or '').casefold()
        items = [item for item in items if query in item['title'].casefold()]
        return dict(items=items, total=len(items), limit=len(items), hasMore=False)

    def playlist(self, item, refresh=False):
        raw = self.request('getPlaylist', refresh=refresh, id=self.checked(item)).get(
            'playlist', {}
        )
        return dict(
            playlist=item
            | dict(title=raw.get('name') or item.get('title', 'Playlist')),
            songs=self.rows(raw.get('entry', []), 'song'),
        )

    def local_entity(self, item):
        identifier = self.checked(item)
        entity = self.index.lookup(item['kind'], identifier)
        if not entity:
            raise MusicError('This item is no longer in the library.')
        songs = self.index.browse({'category': 'songs'}, **{item['kind']: identifier})
        albums = (
            self.index.browse({'category': 'albums'}, artist=identifier)
            if item['kind'] == 'artist'
            else {'items': []}
        )
        return {
            item['kind']: entity,
            'songs': songs['items'],
            'albums': albums['items'],
            'songPaging': dict(offset=songs['limit'], hasMore=songs['hasMore']),
        }

    def artist_info(self, item):
        result = self.request('getArtistInfo2', id=self.checked(item)).get(
            'artistInfo2', {}
        )
        return dict(
            artist=item
            | dict(
                biography=str(result.get('biography') or ''),
                cover=str(
                    result.get('largeImageUrl') or result.get('mediumImageUrl') or ''
                ),
            )
        )

    def lyrics(self, item):
        identifier = self.checked(item)
        values = (
            self.request('getLyricsBySongId', id=identifier)
            .get('lyricsList', {})
            .get('structuredLyrics', [])
        )
        if not isinstance(values, list):
            raise MusicError('The server returned invalid lyrics.')
        values = sorted(
            (value for value in values if isinstance(value, dict)),
            key=lambda value: bool(value.get('synced')),
        )
        text = next(
            (
                '\n'.join(
                    str(line.get('value') or '')
                    for line in value.get('line', [])
                    if isinstance(line, dict)
                )
                for value in values
                if value.get('line')
            ),
            '',
        )
        return dict(
            available=bool(text.strip()), lyrics=text, provider='Song tags', saved=True
        )

    def song_info(self, item):
        raw = self.request('getSong', refresh=True, id=self.checked(item)).get('song')
        if not isinstance(raw, dict):
            raise MusicError('The server did not return song information.')
        tags = {
            key: str(raw.get(key) or '')
            for key in (
                'title',
                'artist',
                'album',
                'composer',
                'comment',
                'lyrics',
                'genre',
            )
        }
        tags.update(
            album_artist=str(raw.get('albumArtist') or ''),
            date=str(raw.get('date') or raw.get('year') or ''),
            track=str(raw.get('track') or ''),
            disc=str(raw.get('discNumber') or ''),
        )
        song = record(raw, 'song', self.account)
        from spaces.music.local_files import pending_path

        if path := pending_path(self.account, item):
            song['serverPath'] = '/' + path
        return dict(
            song=song,
            tags=tags,
            relativePath=song['serverPath'].lstrip('/'),
            fileInfo=song['fileInfo'],
        )

    def cover(self, item):
        identifier = self.checked(item)
        key = hashlib.sha256(
            str(item.get('albumId') or identifier).encode()
        ).hexdigest()
        directory = self.cache / 'covers'
        target = directory / (key + '.img')
        missing = directory / (key + '.missing')
        with _COVER_LOCKS[int(key[:4], 16) % len(_COVER_LOCKS)]:
            if target.is_file():
                return target.as_uri()
            if missing.is_file() and time.time() - missing.stat().st_mtime < 86400:
                return ''
            cover = item.get('coverArt')
            if not cover:
                kind = 'Album' if item.get('kind') == 'album' else 'Song'
                cover = (
                    self.client.request('get' + kind, id=identifier)
                    .get(kind.lower(), {})
                    .get('coverArt')
                )
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not cover:
                missing.touch(mode=0o600)
                return ''
            try:
                with self.client.open(
                    'getCoverArt', dict(id=identity(cover), size=128)
                ) as reply:
                    if (
                        not reply.headers.get('Content-Type', '')
                        .lower()
                        .startswith('image/')
                    ):
                        raise MusicError('Cover art is unavailable.')
                    data = reply.read(4 * 1024 * 1024 + 1)
                if not data or len(data) > 4 * 1024 * 1024:
                    raise MusicError('Cover art is unavailable.')
            except (OSError, ValueError):
                raise MusicError('Cover art is unavailable.') from None
            fd, name = tempfile.mkstemp(prefix='.cover-', dir=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)
            return target.as_uri()

    def genres(self):
        if self.index.info():
            return self.index.genres()
        values = self.request('getGenres').get('genres', {}).get('genre', [])
        return [
            dict(
                id=str(value.get('value') or value.get('name') or ''),
                name=str(value.get('value') or value.get('name') or ''),
            )
            for value in values
        ]

    def checked(self, item):
        if item.get('account') != self.account:
            raise MusicError(
                'This item belongs to a different Nextcloud account. Refresh My Library.'
            )
        return identity(item.get('id'))

    def album(self, item, refresh=False):
        identifier = self.checked(item)
        if refresh:
            self.index.start(True)
        if self.index.info():
            album = self.index.lookup('album', identifier)
            if not album:
                raise MusicError(
                    'The album is no longer in the cached library. Refresh My Library.'
                )
            page = self.index.browse({'category': 'songs'}, album=identifier)
            artists = [
                value
                for artist in album.get('artistIds', [])
                if (value := self.index.lookup('artist', artist))
            ]
            return dict(
                album=album,
                songs=page['items'],
                artists=artists,
                songPaging=dict(
                    album=item, offset=page['limit'], hasMore=page['hasMore']
                ),
                cached=True,
            )
        result = self.request('getAlbum', refresh=refresh, id=self.checked(item)).get(
            'album', {}
        )
        album = record(result, 'album', self.account)
        tracks = self.rows(result.get('song', []), 'song')
        return dict(
            album=album,
            songs=tracks,
            artists=[
                dict(
                    id=artist_id,
                    source='nextcloud',
                    account=self.account,
                    kind='artist',
                    name=album['artist'],
                )
                for artist_id in album['artistIds']
            ],
        )

    def artist(self, item, refresh=False):
        identifier = self.checked(item)
        if refresh:
            self.index.start(True)
        if self.index.info():
            artist = self.index.lookup('artist', identifier)
            if not artist:
                raise MusicError(
                    'The artist is no longer in the cached library. Refresh My Library.'
                )
            songs = self.index.browse({'category': 'songs'}, artist=identifier)
            albums = self.index.browse({'category': 'albums'}, artist=identifier)
            return dict(
                artist=artist,
                songs=songs['items'],
                albums=albums['items'],
                songPaging=dict(
                    artist=item, offset=songs['limit'], hasMore=songs['hasMore']
                ),
                albumPaging=dict(
                    artist=item, offset=albums['limit'], hasMore=albums['hasMore']
                ),
                cached=True,
            )
        result = self.request('getArtist', refresh=refresh, id=self.checked(item)).get(
            'artist', {}
        )
        artist = record(result, 'artist', self.account)
        albums = self.rows(result.get('album', []), 'album')
        page = self.artist_songs(dict(artist=item, offset=0))
        return dict(
            artist=artist,
            albums=albums,
            songs=page['items'],
            songPaging=dict(
                artist=item, offset=page['offset'], hasMore=page['hasMore']
            ),
        )

    def artist_songs(self, args):
        if self.index.info():
            self.checked(args['artist'])
            return self.index.browse(
                dict(args, category='songs'), artist=args['artist']['id']
            )
        item = args['artist']
        offset = max(0, int(args.get('offset') or 0))
        albums = (
            self.request('getArtist', id=self.checked(item))
            .get('artist', {})
            .get('album', [])
        )
        batch = albums[offset : offset + 2]

        def tracks(raw):
            return self.album(record(raw, 'album', self.account))['songs']

        with ThreadPoolExecutor(max_workers=2) as pool:
            songs = [song for group in pool.map(tracks, batch) for song in group]
        return dict(
            items=songs,
            offset=offset + len(batch),
            hasMore=offset + len(batch) < len(albums),
        )

    def entity_browse(self, args):
        item = args['entity']
        identifier = self.checked(item)
        if not self.index.info():
            raise MusicError('The library index is still loading.')
        return self.index.browse(
            args,
            artist=identifier if item['kind'] == 'artist' else None,
            album=identifier if item['kind'] == 'album' else None,
        )

    def queue(self, args):
        entity = args.get('entity') or {}
        if entity.get('kind') == 'playlist':
            return dict(items=self.playlist(entity)['songs'])
        scope = {}
        if entity:
            scope[entity['kind']] = self.checked(entity)
        page = self.index.browse(dict(args, category='songs', offset=0), **scope)
        items = page['items']
        while page['hasMore']:
            page = self.index.browse(
                dict(args, category='songs', offset=page['limit']), **scope
            )
            items.extend(page['items'])
        return dict(items=items)

    def refresh_item(self, item, action=''):
        if not self.index.info() or not item or item.get('source') != 'nextcloud':
            self.index.start(True)
            return {}
        identifier = self.checked(item)
        raw = self.client.request('getSong', id=identifier).get('song')
        if not isinstance(raw, dict):
            raise MusicError(
                'The server has not updated this song yet. Refresh My Library shortly.'
            )
        song = record(raw, 'song', self.account)
        if action == 'move':
            # DAV has already confirmed the move; catalogue indexing may lag it.
            song['serverPath'] = item['serverPath']
            self.index.start(True)
        self.index.update_song(song)
        return {}

    def favorite(self, item, value):
        identifier = self.checked(item)
        key = {'song': 'id', 'album': 'albumId', 'artist': 'artistId'}.get(
            item.get('kind')
        )
        if not key:
            raise MusicError('This library item cannot be starred.')
        self.client.request('star' if value else 'unstar', **{key: identifier})
        self.index.set_star(item, value)
        for path in self.cache.glob('*.json'):
            path.unlink(missing_ok=True)
        return dict(item=item | dict(starred=bool(value)))


def handle(args):
    library = CloudLibrary()
    op = args['op']
    if op == 'local-refresh':
        from spaces.music.inventory import Inventory

        with _INDEX_LOCK:
            if library.account not in _INVENTORIES:
                _INVENTORIES[library.account] = Inventory(library.index)
            inventory = _INVENTORIES[library.account]
        return inventory.refresh(bool(args.get('refresh'))) | dict(
            index=library.index.status()
        )
    if op == 'index-status':
        return library.index.status()
    if op == 'refresh-item':
        result = library.refresh_item(args.get('item'), args.get('action', ''))
    elif op == 'entity-browse':
        result = library.entity_browse(args)
    elif op == 'album-songs-page':
        result = library.index.browse(
            dict(args, category='songs'), album=library.checked(args['album'])
        )
    elif op == 'artist-albums-page':
        result = library.index.browse(
            dict(args, category='albums'), artist=library.checked(args['artist'])
        )
    elif op == 'queue':
        result = library.queue(args)
    elif op == 'browse':
        result = library.browse(args)
    elif op == 'genres':
        return library.genres()
    elif op == 'playlist':
        result = library.playlist(args['playlist'], bool(args.get('refresh')))
    elif op == 'artist-info':
        result = library.artist_info(args['artist'])
    elif op == 'album':
        result = (
            library.local_entity(args['album'])
            if args['album'].get('source') == 'music-local'
            else library.album(args['album'], bool(args.get('refresh')))
        )
    elif op == 'artist':
        result = (
            library.local_entity(args['artist'])
            if args['artist'].get('source') == 'music-local'
            else library.artist(args['artist'], bool(args.get('refresh')))
        )
    elif op == 'artist-songs-page':
        result = library.artist_songs(args)
    elif op == 'favorite':
        result = library.favorite(args['item'], args['value'])
    else:
        raise MusicError('Unknown library operation.')
    return dict(warning=library.warning, index=library.index.status()) | result


if __name__ == '__main__':
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from spaces.movies.worker import own_process_group, serve

    def cleanup():
        for index in tuple(_INDEXES.values()):
            index.stop()

    own_process_group(cleanup)
    serve(
        handle,
        errors=(MusicError,),
        latest=(
            'browse',
            'album',
            'artist',
            'playlist',
            'artist-songs-page',
            'entity-browse',
        ),
        controls=('favorite',),
        scope=lambda r: (r['op'], r.get('lane', ''), r.get('category', '')),
    )
