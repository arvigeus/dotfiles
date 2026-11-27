"""Account-scoped metadata snapshot. Audio and file synchronization are not involved."""

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from xml.etree.ElementTree import ParseError

from integrations.nextcloud import NextcloudError
from integrations.subsonic import MusicError
from spaces.music import records

BATCH = 500
PAGE = 200
SCHEMA = 2
REFRESH_INTERVAL = 300
CATALOGUE_RECHECK = 900
LYRICS_BATCH = 12


def fold(text):
    return ''.join(
        c
        for c in unicodedata.normalize('NFKD', str(text)).casefold()
        if not unicodedata.combining(c)
    )


def lyric_texts(result):
    """Return plain text for each version, with unsynced versions first."""
    group = result.get('lyricsList', {})
    values = group.get('structuredLyrics', []) if isinstance(group, dict) else None
    if not isinstance(values, list):
        raise MusicError('The server returned invalid lyrics.')
    texts = []
    for value in sorted(
        (value for value in values if isinstance(value, dict)),
        key=lambda value: bool(value.get('synced')),
    ):
        lines = value.get('line', [])
        if not isinstance(lines, list):
            raise MusicError('The server returned invalid lyrics.')
        text = '\n'.join(
            str(line.get('value') or '') for line in lines if isinstance(line, dict)
        )
        if text.strip():
            texts.append(text)
    return texts


class CatalogueIndex:
    def __init__(self, client, root, normalize):
        self.client = client
        self.account = client.account_id
        self.root = Path(root)
        self.path = self.root / 'catalogue.sqlite'
        self.lyrics_path = self.root / 'lyrics.sqlite'
        self.normalize = normalize
        self.view_path = None
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.thread = None
        self.temporary = None
        self.running = False
        self.next_refresh = 0
        self.loaded = 0
        self.error = ''
        self.phase = ''
        self.lyrics_error = ''
        self.refresh_requested = False
        self.song_edits = {}

    def connect(self, remote=False):
        path = (
            self.view_path
            if not remote and self.view_path and self.view_path.exists()
            else self.path
        )
        return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)

    def info(self, remote=False):
        try:
            with closing(self.connect(remote)) as db:
                meta = dict(db.execute('SELECT key,value FROM metadata'))
            if (
                meta.get('account') != self.account
                or int(meta.get('schema', 0)) != SCHEMA
            ):
                return {}
            return {
                **{
                    key: int(meta.get(key, 0)) for key in ('songs', 'albums', 'artists')
                },
                'version': meta.get('version', ''),
            }
        except (sqlite3.Error, OSError, ValueError):
            return {}

    def status(self):
        with self.lock:
            info = self.info()
            return dict(
                ready=bool(info),
                indexing=self.running,
                loaded=self.loaded,
                phase=self.phase,
                indexError=self.error,
                lyricsVersion=self.lyrics_revision(),
                lyricsError=self.lyrics_error,
                **info,
            )

    def start(self, force=False):
        with self.lock:
            if self.running:
                if force and self.phase in ('checking', 'lyric-files', 'lyrics'):
                    self.refresh_requested = True
                return
            if not force and time.monotonic() < self.next_refresh:
                return
            self.running = True
            self.loaded = 0
            self.error = ''
            self.lyrics_error = ''
            self.phase = 'checking'
            self.cancelled.clear()
            self.song_edits = {}
            self.thread = threading.Thread(
                target=self._build, args=(force,), daemon=True, name='music-catalogue'
            )
            self.thread.start()

    def stop(self):
        with self.lock:
            self.cancelled.set()
            if self.temporary:
                self.temporary.unlink(missing_ok=True)

    @staticmethod
    def create(db):
        db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE records(kind TEXT,id TEXT,payload TEXT,search TEXT,sort TEXT,album TEXT,disc INTEGER,track INTEGER,PRIMARY KEY(kind,id));
            CREATE TABLE artist_songs(artist TEXT,song TEXT,PRIMARY KEY(artist,song));
            CREATE TABLE album_artists(artist TEXT,album TEXT,PRIMARY KEY(artist,album));
            CREATE TABLE genres(kind TEXT,id TEXT,name TEXT,PRIMARY KEY(kind,id,name));
            CREATE INDEX record_sort ON records(kind,sort,id);
            CREATE INDEX record_album ON records(kind,album,disc,track);
            CREATE INDEX song_artists ON artist_songs(song,artist);
            CREATE INDEX albums_by_artist ON album_artists(artist,album);
            CREATE INDEX genre_names ON genres(name,kind,id);
        """)

    def put(self, db, item):
        kind = item['kind']
        identifier = str(item['id'])
        search = fold(
            ' '.join(
                str(item.get(key) or '') for key in ('name', 'title', 'artist', 'album')
            )
        )
        db.execute(
            'INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?)',
            (
                kind,
                identifier,
                json.dumps(item, ensure_ascii=False),
                search,
                fold(item.get('title') or item.get('name') or ''),
                item.get('albumId', ''),
                int(item.get('discNumber') or 0),
                int(item.get('trackNumber') or 0),
            ),
        )
        db.execute('DELETE FROM genres WHERE kind=? AND id=?', (kind, identifier))
        db.executemany(
            'INSERT OR IGNORE INTO genres VALUES(?,?,?)',
            [(kind, identifier, name) for name in item.get('genreNames', [])],
        )
        if kind == 'song':
            db.execute('DELETE FROM artist_songs WHERE song=?', (identifier,))
            db.executemany(
                'INSERT OR IGNORE INTO artist_songs VALUES(?,?)',
                [(str(artist), identifier) for artist in item.get('artistIds', [])],
            )
        elif kind == 'album':
            db.execute('DELETE FROM album_artists WHERE album=?', (identifier,))
            db.executemany(
                'INSERT OR IGNORE INTO album_artists VALUES(?,?)',
                [(str(artist), identifier) for artist in item.get('artistIds', [])],
            )

    def _build(self, force):
        temporary = None
        try:
            remote = None
            etag = ''
            checkpoint = self.lyrics_checkpoint()
            if hasattr(self.client, 'lyrics_files'):
                try:
                    remote = self.client.lyrics_files()
                    etag = remote.etag('')
                except (NextcloudError, records.MusicError, ParseError):
                    pass
            if self.cancelled.is_set():
                return
            previous = self.info(remote=True)
            with self.lock:
                force |= self.refresh_requested
                self.refresh_requested = False
                if (
                    not force
                    and etag
                    and previous
                    and checkpoint[:2] == (etag, previous['version'])
                    and time.time_ns() - int(previous['version'])
                    < CATALOGUE_RECHECK * 10**9
                ):
                    return
                self.phase = 'metadata'
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(
                prefix='.catalogue-', suffix='.sqlite', dir=self.root
            )
            os.close(fd)
            temporary = Path(name)
            with self.lock:
                self.temporary = temporary
            with closing(sqlite3.connect(temporary)) as db:
                db.execute('PRAGMA journal_mode=OFF')
                self.create(db)
                offsets = {kind: 0 for kind in ('song', 'album', 'artist')}
                active = set(offsets)
                last = {}
                while active:
                    if self.cancelled.is_set():
                        return
                    args = {'query': ''}
                    for kind in offsets:
                        args.update(
                            {
                                kind + 'Count': BATCH if kind in active else 0,
                                kind + 'Offset': offsets[kind],
                            }
                        )
                    result = self.client.request('search3', **args).get('searchResult3')
                    if not isinstance(result, dict):
                        raise ValueError('Invalid catalogue page')
                    for kind in tuple(active):
                        values = result.get(kind, [])
                        if not isinstance(values, list):
                            raise ValueError('Invalid catalogue items')
                        if not values:
                            active.remove(kind)
                            continue
                        ids = tuple(str(item.get('id')) for item in values)
                        if ids == last.get(kind):
                            raise ValueError('Repeated catalogue page')
                        last[kind] = ids
                        for raw in values:
                            self.put(db, self.normalize(raw, kind, self.account))
                        offsets[kind] += len(values)
                    db.commit()
                    with self.lock:
                        self.loaded = offsets['song']
                version = time.time_ns()
                meta = dict(
                    account=self.account, schema=str(SCHEMA), version=str(version)
                )
                for category, kind in (
                    ('songs', 'song'),
                    ('albums', 'album'),
                    ('artists', 'artist'),
                ):
                    meta[category] = str(
                        db.execute(
                            'SELECT count(*) FROM records WHERE kind=?', (kind,)
                        ).fetchone()[0]
                    )
                db.executemany('INSERT INTO metadata VALUES(?,?)', meta.items())
                with self.lock:
                    if self.cancelled.is_set():
                        return
                    for item in self.song_edits.values():
                        self._put_song(db, item)
                    db.commit()
                    os.replace(temporary, self.path)
            if not self.cancelled.is_set() and hasattr(self.client, 'lyrics_files'):
                with self.lock:
                    self.phase = 'lyric-files'
                    self.loaded = 0
                self._refresh_lyrics(remote, etag, str(version), checkpoint, force)
        except Exception:
            with self.lock:
                self.error = 'The library index could not refresh. Your previous cached library is preserved.'
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
            with self.lock:
                self.running = False
                self.temporary = None
                self.next_refresh = time.monotonic() + REFRESH_INTERVAL
                if self.refresh_requested and not self.cancelled.is_set():
                    self.refresh_requested = False
                    self.start(True)

    def lyrics_revision(self):
        try:
            return str(self.lyrics_path.stat().st_mtime_ns)
        except OSError:
            return ''

    def lyrics_checkpoint(self):
        try:
            with closing(
                sqlite3.connect(self.lyrics_path.as_uri() + '?mode=ro', uri=True)
            ) as db:
                return (
                    db.execute(
                        'SELECT etag, catalogue, songs FROM lyric_checks WHERE account=?',
                        (self.account,),
                    ).fetchone()
                    or ()
                )
        except sqlite3.Error:
            return ()

    def open_lyrics(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.lyrics_path.exists():
            os.close(os.open(self.lyrics_path, os.O_WRONLY | os.O_CREAT, 0o600))
        db = sqlite3.connect(self.lyrics_path, timeout=5)
        try:
            if any(
                column[1] == 'display'
                for column in db.execute('PRAGMA table_info(lyrics)')
            ):
                return db
            # Both the catalogue and the properties workers can initialize this cache.
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("""CREATE TABLE IF NOT EXISTS lyrics(
                    account TEXT, id TEXT, path TEXT, version TEXT, text TEXT, display TEXT,
                    PRIMARY KEY(account,id))""")
                if 'display' not in {
                    column[1] for column in db.execute('PRAGMA table_info(lyrics)')
                }:
                    db.execute('ALTER TABLE lyrics ADD COLUMN display TEXT')
            return db
        except sqlite3.Error:
            db.close()
            raise

    def song_lyrics(self, identifier, path):
        previous = None
        if path:
            try:
                with closing(self.open_lyrics()) as db:
                    previous = db.execute(
                        'SELECT path, version, display FROM lyrics WHERE account=? AND id=?',
                        (self.account, identifier),
                    ).fetchone()
                if previous and previous[0] == path and previous[2] is not None:
                    return previous[2]
            except (sqlite3.Error, OSError):
                pass
        texts = lyric_texts(self.client.request('getLyricsBySongId', id=identifier))
        display = next(iter(texts), '')
        if path:
            try:
                with closing(self.open_lyrics()) as db, db:
                    db.execute(
                        """INSERT INTO lyrics(account,id,path,version,text,display)
                        VALUES(?,?,?,?,?,?) ON CONFLICT(account,id) DO UPDATE SET
                        path=excluded.path, version=excluded.version, text=excluded.text, display=excluded.display
                        WHERE lyrics.path IS ? AND lyrics.version IS ? AND lyrics.display IS ?""",
                        (
                            self.account,
                            identifier,
                            path,
                            previous[1] if previous and previous[0] == path else '',
                            fold('\n'.join(texts)),
                            display,
                            *(previous or (None, None, None)),
                        ),
                    )
            except (sqlite3.Error, OSError):
                pass
        return display

    def _refresh_lyrics(self, remote, etag, catalogue_version, checkpoint, force):
        from spaces.music.local_files import relative

        try:
            with closing(self.open_lyrics()) as db:
                with closing(self.connect(remote=True)) as catalogue:
                    songs = {
                        identifier: json.loads(payload)
                        for identifier, payload in catalogue.execute(
                            "SELECT id,payload FROM records WHERE kind='song'"
                        )
                    }
                cached = {
                    identifier: (path, version)
                    for identifier, path, version in db.execute(
                        'SELECT id,path,version FROM lyrics WHERE account=?',
                        (self.account,),
                    )
                }
                remove = set(cached) - songs.keys()
                folders = {}
                for identifier, song in songs.items():
                    try:
                        path = relative(song)
                    except records.MusicError:
                        continue
                    directory, _, name = path.rpartition('/')
                    folders.setdefault(directory, []).append((identifier, path, name))

                signature = hashlib.sha256(
                    json.dumps(
                        sorted(
                            (identifier, path)
                            for tracks in folders.values()
                            for identifier, path, _ in tracks
                        )
                    ).encode()
                ).hexdigest()
                if (
                    not force
                    and etag
                    and checkpoint
                    and (etag, signature) == (checkpoint[0], checkpoint[2])
                ):
                    self.save_lyrics_checkpoint(db, etag, catalogue_version, signature)
                    return
                if checkpoint:
                    with db:
                        db.execute(
                            'DELETE FROM lyric_checks WHERE account=?', (self.account,)
                        )

                remote = remote or (self.client.lyrics_files() if folders else None)
                pending = []
                failed = False
                for directory, versions in self.lyric_file_versions(remote, folders):
                    if self.cancelled.is_set() or self.refresh_requested:
                        return
                    if versions is None:
                        failed = True
                        continue
                    sidecars = {}
                    for name, version in versions.items():
                        if name.casefold().endswith('.lrc'):
                            sidecars.setdefault(name.casefold(), []).append(
                                (name, version)
                            )
                    for identifier, path, name in folders[directory]:
                        if name not in versions:
                            remove.add(identifier)
                            continue
                        audio = versions[name]
                        sidecar_names = {
                            name.casefold() + '.lrc',
                            Path(name).stem.casefold() + '.lrc',
                        }
                        matches = sorted(
                            entry
                            for sidecar in sidecar_names
                            for entry in sidecars.get(sidecar, [])
                        )
                        if not audio or any(not version for _, version in matches):
                            failed = True
                            continue
                        version = json.dumps([audio, matches])
                        previous = cached.get(identifier)
                        if previous != (path, version):
                            if previous and previous != (path, ''):
                                remove.add(identifier)
                            pending.append((identifier, path, version))
                if remove.intersection(cached):
                    db.executemany(
                        'DELETE FROM lyrics WHERE account=? AND id=?',
                        [(self.account, identifier) for identifier in remove],
                    )
                    db.commit()
                consecutive_failures = 0
                if pending:
                    with self.lock:
                        self.phase = 'lyrics'
                with ThreadPoolExecutor(max_workers=3) as pool:
                    for offset in range(0, len(pending), LYRICS_BATCH):
                        if self.cancelled.is_set() or self.refresh_requested:
                            return
                        batch = pending[offset : offset + LYRICS_BATCH]
                        values = [
                            row for row in pool.map(self._read_lyrics, batch) if row
                        ]
                        failed |= len(values) != len(batch)
                        consecutive_failures = 0 if values else consecutive_failures + 1
                        if consecutive_failures == 2:
                            break
                        db.executemany(
                            'INSERT OR REPLACE INTO lyrics(account,id,path,version,text,display) VALUES(?,?,?,?,?,?)',
                            values,
                        )
                        db.commit()
                        self.loaded += len(values)
                if failed:
                    self.lyrics_error = 'Some song lyrics could not be refreshed.'
                elif (
                    etag and not self.cancelled.is_set() and not self.refresh_requested
                ):
                    self.save_lyrics_checkpoint(db, etag, catalogue_version, signature)
        except (NextcloudError, records.MusicError, sqlite3.Error, OSError):
            self.lyrics_error = 'Song lyrics could not be refreshed.'

    def lyric_file_versions(self, remote, folders):
        def listing(directory):
            try:
                return remote.versions(directory)
            except (NextcloudError, records.MusicError, ParseError):
                return None

        directories = list(folders)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for start in range(0, len(directories), 4):
                if self.cancelled.is_set() or self.refresh_requested:
                    return
                batch = directories[start : start + 4]
                yield from zip(batch, pool.map(listing, batch))

    def save_lyrics_checkpoint(self, db, etag, catalogue_version, signature):
        with db:
            db.execute("""CREATE TABLE IF NOT EXISTS lyric_checks(
                account TEXT PRIMARY KEY, etag TEXT, catalogue TEXT, songs TEXT)""")
            db.execute(
                'INSERT OR REPLACE INTO lyric_checks VALUES(?,?,?,?)',
                (self.account, etag, catalogue_version, signature),
            )

    def _read_lyrics(self, entry):
        if self.cancelled.is_set() or self.refresh_requested:
            return None
        identifier, path, version = entry
        try:
            texts = lyric_texts(self.client.request('getLyricsBySongId', id=identifier))
        except MusicError:
            return None
        return (
            self.account,
            identifier,
            path,
            version,
            fold('\n'.join(texts)),
            next(iter(texts), ''),
        )

    def lookup(self, kind, identifier):
        with closing(self.connect()) as db:
            row = db.execute(
                'SELECT payload FROM records WHERE kind=? AND id=?',
                (kind, str(identifier)),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def browse(self, args, *, artist=None, album=None):
        kind = {'songs': 'song', 'albums': 'album', 'artists': 'artist'}.get(
            args.get('category', 'songs')
        )
        if kind is None:
            raise ValueError('Unknown library category')
        page_size = min(100000, max(PAGE, int(args.get('pageSize') or PAGE)))
        offset = max(0, int(args.get('offset') or 0))
        clauses = ['r.kind=?']
        params = [kind]
        terms = fold(args.get('query') or '').split()
        search_lyrics = kind == 'song' and args.get('includeLyrics', True)
        if args.get('pending'):
            clauses.append("json_extract(r.payload,'$.notUploaded')=1")
        genre = args.get('genreName') or ''
        if genre and kind == 'song':
            clauses.append(
                'EXISTS(SELECT 1 FROM genres g WHERE g.kind=r.kind AND g.id=r.id AND g.name=?)'
            )
            params.append(genre)
        elif genre and kind == 'album':
            clauses.append(
                "r.id IN (SELECT s.album FROM records s JOIN genres g ON g.kind='song' AND g.id=s.id WHERE s.kind='song' AND g.name=?)"
            )
            params.append(genre)
        if album:
            clauses.append('r.album=?')
            params.append(str(album))
        if artist:
            if kind == 'song':
                clauses.append(
                    "r.id IN (SELECT song FROM artist_songs WHERE artist=? UNION SELECT s.id FROM records s JOIN album_artists a ON s.album=a.album WHERE s.kind='song' AND a.artist=?)"
                )
                params.extend([str(artist), str(artist)])
            elif kind == 'album':
                clauses.append(
                    "r.id IN (SELECT album FROM album_artists WHERE artist=? UNION SELECT s.album FROM records s JOIN artist_songs a ON s.id=a.song WHERE s.kind='song' AND a.artist=?)"
                )
                params.extend([str(artist), str(artist)])
        order = 'r.disc,r.track,r.sort,r.id' if album else 'r.sort,r.id'
        with closing(self.connect()) as db:
            joins = ''
            join_params = []
            if terms:
                match = ' AND '.join('instr(r.search,?)>0' for _ in terms)
                lyrics = []
                if search_lyrics and self.lyrics_path.exists():
                    db.execute(
                        'ATTACH DATABASE ? AS remote_lyrics',
                        (self.lyrics_path.as_uri() + '?mode=ro',),
                    )
                    if db.execute(
                        "SELECT 1 FROM remote_lyrics.sqlite_schema WHERE name='lyrics'"
                    ).fetchone():
                        joins += """ LEFT JOIN remote_lyrics.lyrics remote ON remote.account=?
                            AND remote.id=r.id AND remote.path=ltrim(json_extract(r.payload,'$.serverPath'),'/')"""
                        join_params.append(self.account)
                        lyrics.append('remote.text')
                if (
                    search_lyrics
                    and db.execute(
                        "SELECT 1 FROM main.sqlite_schema WHERE name='local_lyrics'"
                    ).fetchone()
                ):
                    joins += ' LEFT JOIN local_lyrics local ON local.id=r.id'
                    lyrics.append('local.text')
                params.extend(terms)
                if lyrics:
                    text = lyrics[0]
                    if len(lyrics) == 2:
                        text = """(CASE WHEN json_extract(r.payload,'$.pendingUpload')=1
                            THEN local.text ELSE coalesce(remote.text,local.text) END)"""
                    match += (
                        ' OR ('
                        + ' AND '.join(f'instr({text},?)>0' for _ in terms)
                        + ')'
                    )
                    params.extend(terms)
                clauses.append('(' + match + ')')
            where = ' AND '.join(clauses)
            selection = ' FROM records r' + joins + ' WHERE ' + where
            # A batch may commit while searching. Keep the count and page on one snapshot.
            db.execute('BEGIN')
            total = db.execute(
                'SELECT count(*)' + selection, [*join_params, *params]
            ).fetchone()[0]
            values = db.execute(
                'SELECT r.payload'
                + selection
                + ' ORDER BY '
                + order
                + ' LIMIT ? OFFSET ?',
                [*join_params, *params, page_size, offset],
            ).fetchall()
        return dict(
            items=[json.loads(payload) for (payload,) in values],
            total=total,
            limit=offset + len(values),
            hasMore=offset + len(values) < total,
            cursor='',
            cached=True,
        )

    def genres(self):
        with closing(self.connect()) as db:
            values = db.execute(
                "SELECT DISTINCT name FROM genres WHERE kind='song' ORDER BY name"
            ).fetchall()
        return [dict(id=name, name=name) for (name,) in values]

    def _put_song(self, db, song):
        self.put(db, song)
        if song.get('albumId'):
            old = db.execute(
                "SELECT payload FROM records WHERE kind='album' AND id=?",
                (str(song['albumId']),),
            ).fetchone()
            album = (
                json.loads(old[0])
                if old
                else dict(
                    id=song['albumId'],
                    kind='album',
                    source='nextcloud',
                    account=self.account,
                    artist=song.get('artist', ''),
                    artistIds=song.get('artistIds', []),
                    genreNames=song.get('genreNames', []),
                    releaseDate=song.get('releaseDate', ''),
                )
            )
            self.put(db, album | dict(title=song.get('album', '')))
        for artist in song.get('artistIds', []):
            if not db.execute(
                "SELECT 1 FROM records WHERE kind='artist' AND id=?", (str(artist),)
            ).fetchone():
                self.put(
                    db,
                    dict(
                        id=str(artist),
                        kind='artist',
                        source='nextcloud',
                        account=self.account,
                        name=song.get('artist', ''),
                    ),
                )

    def update_song(self, song):
        with self.lock:
            self.song_edits[str(song['id'])] = song
            if self.info():
                with closing(sqlite3.connect(self.path, timeout=5)) as db:
                    with db:
                        self._put_song(db, song)
