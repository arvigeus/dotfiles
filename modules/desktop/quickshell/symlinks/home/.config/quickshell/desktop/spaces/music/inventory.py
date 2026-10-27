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
from spaces.music.cloud_index import CatalogueIndex, fold
from spaces.music.records import MusicError


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
            old = {
                rel: (sig, json.loads(payload))
                for rel, sig, payload in db.execute('SELECT * FROM files')
            }
            current = {}
            unreadable = 0
            for directory, dirs, names in os.walk(files.ROOT, followlinks=False):
                dirs[:] = [
                    name
                    for name in dirs
                    if not name.startswith('.')
                    and not (Path(directory) / name).is_symlink()
                ]
                for name in names:
                    path = Path(directory) / name
                    if (
                        name.startswith('.')
                        or path.suffix.lower() not in files.EXTENSIONS
                        or path.is_symlink()
                        or not path.is_file()
                    ):
                        continue
                    rel = path.relative_to(files.ROOT).as_posix()
                    try:
                        files.local_path(rel)
                        sig = json.dumps(files.signature(path))
                        if rel in old and old[rel][0] == sig:
                            details = old[rel][1]
                        else:
                            details = tags.read(path, files.run)
                        current[rel] = (sig, details)
                    except (MusicError, OSError, ValueError):
                        unreadable += 1
                        if rel in old:
                            current[rel] = old[rel]
            source = (
                self.index.path.stat().st_mtime_ns if self.index.path.exists() else 0
            )
            changed = (
                force
                or current != old
                or self.source != source
                or not self.view.exists()
            )
            if changed:
                # These are regenerable metadata rows. Audio files are never removed.
                self._publish(current)
                with db:
                    db.execute('DELETE FROM files')
                    db.executemany(
                        'INSERT INTO files VALUES(?,?,?)',
                        [
                            (rel, sig, json.dumps(payload))
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
                    for old_path, new_path, payload in moves:
                        moved = json.loads(payload)
                        aliases = [old_path, *moved.get('previousPaths', [])]
                        previous = next(
                            (
                                remote_paths[path]
                                for path in aliases
                                if path in remote_paths
                            ),
                            None,
                        )
                        identifier = moved.get('id')
                        if not previous and identifier:
                            previous = next(
                                (
                                    item
                                    for item in remote_paths.values()
                                    if item['id'] == identifier
                                ),
                                None,
                            )
                        if new_path in remote_paths and not any(
                            path in remote_paths for path in aliases
                        ):
                            state.execute(
                                'DELETE FROM music_pending_moves WHERE account=? AND old_path=?',
                                (self.index.account, old_path),
                            )
                            continue
                        if previous:
                            remote_paths.pop(
                                previous.get('serverPath', '').lstrip('/'), None
                            )
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
                for rel, (sig, details) in current.items():
                    values = details['tags']
                    artist = values.get('artist') or 'Unknown artist'
                    album = values.get('album', '')
                    artist_id = (
                        artists.get(fold(artist))
                        or 'local-artist:'
                        + hashlib.sha256(fold(artist).encode()).hexdigest()[:20]
                    )
                    album_id = (
                        albums.get((fold(album), fold(artist)))
                        or 'local-album:'
                        + hashlib.sha256(
                            (fold(album) + '|' + fold(artist)).encode()
                        ).hexdigest()[:20]
                    )
                    previous = remote_paths.get(rel)
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
                        and files.hashes(files.local_path(rel))['sha256']
                        == baseline['hashes']['sha256']
                    ):
                        pending = False
                    item = base | dict(
                        fileInfo=details.get('fileInfo') or base.get('fileInfo', ''),
                        coverVersion=sig,
                        local=True,
                        localPath=str(files.local_path(rel)),
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
                        artistIds=[artist_id],
                        album=album,
                        albumId=album_id if album else '',
                        releaseDate=values.get('date', ''),
                        genreNames=[values['genre']] if values.get('genre') else [],
                        duration=details['duration'],
                        trackNumber=number('track'),
                        discNumber=number('disc'),
                    )
                    self.index.put(db, item)
                    if not db.execute(
                        "SELECT 1 FROM records WHERE kind='artist' AND id=?",
                        (artist_id,),
                    ).fetchone():
                        self.index.put(
                            db,
                            dict(
                                id=artist_id,
                                source='music-local',
                                account=self.index.account,
                                kind='artist',
                                name=artist,
                            ),
                        )
                    if (
                        album
                        and not db.execute(
                            "SELECT 1 FROM records WHERE kind='album' AND id=?",
                            (album_id,),
                        ).fetchone()
                    ):
                        self.index.put(
                            db,
                            dict(
                                id=album_id,
                                source='music-local',
                                account=self.index.account,
                                kind='album',
                                title=album,
                                artist=artist,
                                artistIds=[artist_id],
                            ),
                        )
                self.version = str(time.time_ns())
                meta = dict(
                    account=self.index.account, schema='1', version=self.version
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
