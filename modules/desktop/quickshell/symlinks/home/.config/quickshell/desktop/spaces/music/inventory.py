"""Read-only folder observation; publish a merged metadata snapshot without network I/O."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

from spaces.music import local_files as files, tags
from spaces.music.cloud_index import SCHEMA, CatalogueIndex, fold
from spaces.music.records import MusicError

# A catalogue built this long after a move has had time to index it.
MOVE_GRACE = 3600


class Inventory:
    def __init__(self, index):
        self.index = index
        self.lock = threading.Lock()
        self.path = index.root / 'local.sqlite'
        self.view = index.root / 'library.sqlite'
        self.source = None
        self.version = ''
        self.error = ''
        index.view_path = self.view

    @staticmethod
    def audio_files():
        """(relative path, signature JSON) of ordinary audio files in Music.

        Hidden entries and symbolic links are skipped and never followed, so
        every path stays inside the folder without validating each parent.
        """
        pending = [(files.ROOT, '')]
        while pending:
            directory, prefix = pending.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.name.startswith('.') or entry.is_symlink():
                        continue
                    rel = prefix + entry.name
                    if entry.is_dir(follow_symlinks=False):
                        pending.append((entry.path, rel + '/'))
                    elif os.path.splitext(entry.name)[
                        1
                    ].lower() in files.EXTENSIONS and entry.is_file(
                        follow_symlinks=False
                    ):
                        stat = entry.stat(follow_symlinks=False)
                        yield (
                            rel,
                            json.dumps([stat.st_ino, stat.st_size, stat.st_mtime_ns]),
                        )
                except OSError:
                    continue  # Removed while walking.

    def refresh(self, force=False):
        if not self.lock.acquire(blocking=False):
            return dict(changed=False, version=self.version)
        try:
            return self._refresh(force)
        finally:
            self.lock.release()

    def _refresh(self, force=False):
        self.index.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if files.ROOT.is_symlink() or files.ROOT.is_mount():
            raise MusicError('Music must be an ordinary local folder.')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute(
                'CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY,signature TEXT,payload TEXT)'
            )
            # Payloads stay JSON text: an unchanged pass compares strings only.
            old = {
                rel: (sig, payload)
                for rel, sig, payload in db.execute(
                    'SELECT path,signature,payload FROM files'
                )
            }
            current = {}
            unreadable = 0
            for rel, sig in self.audio_files():
                if rel in old and old[rel][0] == sig:
                    current[rel] = old[rel]
                    continue
                try:
                    details = tags.read(files.ROOT / rel, files.run)
                    current[rel] = (sig, json.dumps(details))
                except (MusicError, OSError, ValueError):
                    unreadable += 1
                    if rel in old:
                        current[rel] = old[rel]
            # Server snapshots and local associations (baselines, pending uploads
            # and moves) change rows without changing any audio file. Creating
            # the association tables first keeps that from counting as a change.
            with files.db():
                pass
            source = tuple(
                path.stat().st_mtime_ns if path.exists() else 0
                for path in (self.index.path, files.DATA / 'library.sqlite')
            )
            changed = (
                force
                or current != old
                or self.source != source
                or not self.view.exists()
            )
            if changed:
                # These are regenerable metadata rows. Audio files are never removed.
                self._publish(
                    {
                        rel: (sig, json.loads(payload))
                        for rel, (sig, payload) in current.items()
                    }
                )
                with db:
                    db.execute('DELETE FROM files')
                    db.executemany(
                        'INSERT INTO files VALUES(?,?,?)',
                        [
                            (rel, sig, payload)
                            for rel, (sig, payload) in current.items()
                        ],
                    )
                self.source = source
            self.path.chmod(0o600)
            self.error = (
                f'{unreadable} local audio file(s) could not be read.'
                if unreadable
                else ''
            )
            return dict(changed=changed, version=self.version, warning=self.error)

    def _publish(self, current):
        fd, name = tempfile.mkstemp(
            prefix='.library-', suffix='.sqlite', dir=self.index.root
        )
        os.close(fd)
        temporary = Path(name)
        try:
            with closing(sqlite3.connect(temporary)) as db:
                if self.index.path.exists():
                    with closing(
                        sqlite3.connect(self.index.path.as_uri() + '?mode=ro', uri=True)
                    ) as remote:
                        remote.backup(db)
                else:
                    CatalogueIndex.create(db)
                remote_paths = {
                    str(json.loads(payload).get('serverPath', '')).lstrip(
                        '/'
                    ): json.loads(payload)
                    for (payload,) in db.execute(
                        "SELECT payload FROM records WHERE kind='song'"
                    )
                }
                artists = {
                    sort: identifier
                    for identifier, sort in db.execute(
                        "SELECT id,sort FROM records WHERE kind='artist'"
                    )
                }
                albums = {
                    (
                        fold(item.get('title', '')),
                        fold(item.get('artist', '')),
                    ): identifier
                    for identifier, payload in db.execute(
                        "SELECT id,payload FROM records WHERE kind='album'"
                    )
                    for item in [json.loads(payload)]
                }
                with files.db() as state:
                    moves = state.execute(
                        'SELECT old_path,new_path,payload FROM music_pending_moves WHERE account=?',
                        (self.index.account,),
                    ).fetchall()
                    # Ids decide: moves that swap names reuse another song's path.
                    by_id = {item['id']: item for item in remote_paths.values()}
                    catalogued = set(remote_paths)
                    built = db.execute(
                        "SELECT value FROM metadata WHERE key='version'"
                    ).fetchone()
                    built = int(built[0]) / 1e9 if built else 0
                    for old_path, new_path, payload in moves:
                        moved = json.loads(payload)
                        aliases = [old_path, *moved.get('previousPaths', [])]
                        identifier = moved.get('id')
                        previous = by_id.get(identifier)
                        acknowledged = remote_paths.get(new_path)
                        # Neither the song nor its new path in a catalogue built
                        # well after the move: the server no longer has it.
                        gone = (
                            not previous
                            and new_path not in catalogued
                            and built - moved.get('moved', 0) > MOVE_GRACE
                        )
                        if gone or (
                            acknowledged
                            and (
                                acknowledged['id'] == identifier
                                or not any(path in remote_paths for path in aliases)
                            )
                        ):
                            state.execute(
                                'DELETE FROM music_pending_moves WHERE account=? AND old_path=?',
                                (self.index.account, old_path),
                            )
                            continue
                        if previous:
                            old = previous.get('serverPath', '').lstrip('/')
                            if remote_paths.get(old) is previous:
                                del remote_paths[old]
                            moved = previous | moved | {'id': previous['id']}
                        if moved.get('id'):
                            moved.update(
                                serverPath='/' + new_path,
                                source='nextcloud',
                                kind='song',
                                account=self.index.account,
                            )
                            self.index.put(db, moved)
                            remote_paths[new_path] = moved
                    awaiting = {
                        rel
                        for (rel,) in state.execute(
                            'SELECT path FROM music_pending_index WHERE account=?',
                            (self.index.account,),
                        )
                    }
                    state.executemany(
                        'DELETE FROM music_pending_index WHERE account=? AND path=?',
                        [
                            (self.index.account, rel)
                            for rel in awaiting
                            if rel in remote_paths
                        ],
                    )

                def artist_identity(name):
                    return (
                        artists.get(fold(name))
                        or 'local-artist:'
                        + hashlib.sha256(fold(name).encode()).hexdigest()[:20]
                    )

                def local_artist(identifier, name):
                    if not db.execute(
                        "SELECT 1 FROM records WHERE kind='artist' AND id=?",
                        (identifier,),
                    ).fetchone():
                        self.index.put(
                            db,
                            dict(
                                id=identifier,
                                source='music-local',
                                account=self.index.account,
                                kind='artist',
                                name=name,
                            ),
                        )

                for rel, (sig, details) in current.items():
                    values = details['tags']
                    artist = values.get('artist') or 'Unknown artist'
                    album = values.get('album', '')
                    # Albums group by album artist, so featured artists and
                    # compilations stay one album.
                    album_artist = values.get('album_artist') or artist
                    previous = remote_paths.get(rel)
                    # A cached copy keeps the server's identities while its tags
                    # still name them; only an edited name selects another entity.
                    if (
                        previous
                        and previous.get('artistIds')
                        and fold(previous.get('artist', '')) == fold(artist)
                    ):
                        artist_ids = list(previous['artistIds'])
                    else:
                        artist_ids = [artist_identity(artist)]
                    if (
                        previous
                        and previous.get('albumId')
                        and fold(previous.get('album', '')) == fold(album)
                    ):
                        album_id = previous['albumId']
                    else:
                        album_id = (
                            albums.get((fold(album), fold(album_artist)))
                            or 'local-album:'
                            + hashlib.sha256(
                                (fold(album) + '|' + fold(album_artist)).encode()
                            ).hexdigest()[:20]
                        )
                    base = previous or dict(
                        id='local:' + rel,
                        kind='song',
                        source='music-local',
                        account=self.index.account,
                        serverPath='/' + rel,
                    )
                    baseline = files.baseline(self.index.account, rel)
                    uploaded = previous is not None or rel in awaiting
                    pending = (
                        not uploaded
                        or not baseline
                        or json.loads(sig) != baseline['signature']
                    )
                    if (
                        uploaded
                        and baseline
                        and pending
                        and files.content_hash(files.ROOT / rel, json.loads(sig))
                        == baseline['hashes']['sha256']
                    ):
                        pending = False
                    item = base | dict(
                        fileInfo=details.get('fileInfo') or base.get('fileInfo', ''),
                        coverVersion=sig,
                        local=True,
                        localPath=str(files.ROOT / rel),
                        pendingUpload=pending,
                        notUploaded=not uploaded,
                        awaitingIndex=rel in awaiting and previous is None,
                    )

                    def number(key):
                        try:
                            return int(values.get(key, '0').split('/')[0] or 0)
                        except ValueError:
                            return 0

                    item.update(
                        title=values.get('title') or Path(rel).stem,
                        artist=artist,
                        artistIds=artist_ids,
                        album=album,
                        albumId=album_id if album else '',
                        releaseDate=values.get('date', ''),
                        genreNames=[values['genre']] if values.get('genre') else [],
                        duration=details['duration'],
                        trackNumber=number('track'),
                        discNumber=number('disc'),
                    )
                    self.index.put(db, item)

                    for identifier in artist_ids:
                        local_artist(identifier, artist)
                    if (
                        album
                        and not db.execute(
                            "SELECT 1 FROM records WHERE kind='album' AND id=?",
                            (album_id,),
                        ).fetchone()
                    ):
                        album_artist_id = artist_identity(album_artist)
                        local_artist(album_artist_id, album_artist)
                        self.index.put(
                            db,
                            dict(
                                id=album_id,
                                source='music-local',
                                account=self.index.account,
                                kind='album',
                                title=album,
                                artist=album_artist,
                                artistIds=[album_artist_id],
                            ),
                        )
                self.version = str(time.time_ns())
                meta = dict(
                    account=self.index.account,
                    schema=str(SCHEMA),
                    version=self.version,
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
                db.executemany(
                    'INSERT OR REPLACE INTO metadata VALUES(?,?)', meta.items()
                )
                db.commit()
            os.replace(temporary, self.view)
        finally:
            temporary.unlink(missing_ok=True)
