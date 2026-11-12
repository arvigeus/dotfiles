"""Passive Music cache with explicit per-song save, upload and rename actions."""

import configparser
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import closing, contextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from integrations import nextcloud
from spaces.books.jobs import Jobs, check_cancelled, progress
from spaces.movies.local import place, xdg_dir
from spaces.music.records import MusicError
from spaces.music.storage import DATA
from spaces.music.remote_files import RemoteFiles

EXTENSIONS = {
    '.mp3',
    '.flac',
    '.m4a',
    '.aac',
    '.ogg',
    '.opus',
    '.wav',
    '.aiff',
    '.aif',
    '.mka',
    '.wma',
    '.ape',
    '.wv',
}
# The same folder catalogue downloads and Movies' music imports use.
ROOT = xdg_dir('XDG_MUSIC_DIR', 'Music')
JOBS = Jobs(errors=(MusicError, ValueError))
_processes = set()
_partials = set()
_lock = threading.Lock()
_commit = threading.local()


def account_id():
    account = nextcloud.load_account()
    if not account:
        raise MusicError('Restore the shared Nextcloud account first.')
    config = configparser.ConfigParser(interpolation=None)
    config.read(
        Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
        / 'rclone/rclone.conf'
    )
    if not config.has_section('nextcloud'):
        raise MusicError('Restore the private nextcloud rclone remote first.')
    remote = config['nextcloud']
    base = urlsplit(account['url'])
    url = urlsplit(remote.get('url', ''))
    roots = {
        base.path.rstrip('/') + '/remote.php/webdav/',
        base.path.rstrip('/') + '/remote.php/dav/files/' + account['username'] + '/',
    }
    if (
        remote.get('type') != 'webdav'
        or remote.get('vendor') != 'nextcloud'
        or remote.get('user') != account['username']
        or url.scheme != 'https'
        or url.netloc != base.netloc
        or unquote(url.path).rstrip('/') + '/' not in roots
        or url.query
        or url.fragment
        or url.username
        or url.password
    ):
        raise MusicError(
            'The rclone remote and Music must use the same Nextcloud account.'
        )
    return hashlib.sha256(json.dumps(account, sort_keys=True).encode()).hexdigest()


def relative(song):
    value = str(song.get('serverPath') or '')
    parts = value.lstrip('/').split('/')
    if not value or any(
        part in ('', '.', '..') or '\n' in part or '\0' in part for part in parts
    ):
        raise MusicError('This song has no safe Music-relative path.')
    return PurePosixPath(*parts).as_posix()


def local_path(rel):
    parts = rel.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise MusicError('Invalid local Music path.')
    path = ROOT.joinpath(*parts)
    if (
        ROOT.is_symlink()
        or ROOT.is_mount()
        or any(
            parent.is_symlink()
            for parent in (path, *path.parents)
            if parent == ROOT or ROOT in parent.parents
        )
    ):
        raise MusicError('The local Music cache must not contain symbolic links.')
    return path


def checked(song):
    owner = account_id()
    if song.get('account') != owner:
        raise MusicError('Refresh My Library before accessing another account’s files.')
    return owner, relative(song)


def same_song(moved, old_path, song):
    """Whether a pending move describes song. Paths can be reused by another
    song (moves that swap names), so ids decide whenever both have one."""
    if moved.get('id') and song.get('id'):
        return moved['id'] == song['id']
    return str(song.get('serverPath') or '').lstrip('/') in (
        old_path,
        *moved.get('previousPaths', []),
    )


def pending_path(owner, song):
    with db() as connection:
        rows = connection.execute(
            'SELECT old_path,new_path,payload FROM music_pending_moves WHERE account=?',
            (owner,),
        ).fetchall()
    for old_path, new_path, payload in rows:
        if same_song(json.loads(payload), old_path, song):
            return new_path
    return ''


def cached(song):
    _, rel = checked(song)
    path = local_path(rel)
    return path if path.is_file() else None


def signature(path):
    stat = path.stat()
    return [stat.st_ino, stat.st_size, stat.st_mtime_ns]


def token(value):
    """A signature as QML holds it: nanosecond mtimes exceed exact JS numbers."""
    return json.dumps(value)


_CONTENT = {}


def content_hash(path, observed):
    """SHA-256 for dirty checks, reused while the file keeps its signature.
    Scrolling and folder observation ask repeatedly about the same edited files."""
    key = (str(path), tuple(observed))
    if key not in _CONTENT:
        value = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                value.update(chunk)
        with _lock:
            if len(_CONTENT) >= 256:
                _CONTENT.clear()
            _CONTENT[key] = value.hexdigest()
    return _CONTENT[key]


def hashes(path):
    values = {name: hashlib.new(name) for name in ('sha256', 'sha1', 'md5')}
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancelled()
            for value in values.values():
                value.update(chunk)
    return {name: value.hexdigest() for name, value in values.items()}


@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(sqlite3.connect(DATA / 'library.sqlite', timeout=20)) as connection:
        with connection:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS music_cache(account TEXT,path TEXT,signature TEXT,hashes TEXT,remote TEXT,PRIMARY KEY(account,path))'
            )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS music_pending_index(account TEXT,path TEXT,PRIMARY KEY(account,path))'
            )
            connection.execute(
                'CREATE TABLE IF NOT EXISTS music_pending_moves(account TEXT,old_path TEXT,new_path TEXT,payload TEXT,PRIMARY KEY(account,old_path))'
            )
            yield connection
    (DATA / 'library.sqlite').chmod(0o600)


def baseline(owner, rel):
    with db() as connection:
        row = connection.execute(
            'SELECT signature,hashes,remote FROM music_cache WHERE account=? AND path=?',
            (owner, rel),
        ).fetchone()
    return (
        dict(
            signature=json.loads(row[0]),
            hashes=json.loads(row[1]),
            remote=json.loads(row[2]),
        )
        if row
        else None
    )


def remember(owner, rel, path, remote, values=None, observed=None):
    with db() as connection:
        connection.execute(
            'INSERT OR REPLACE INTO music_cache VALUES(?,?,?,?,?)',
            (
                owner,
                rel,
                json.dumps(observed if observed is not None else signature(path)),
                json.dumps(values or hashes(path)),
                json.dumps(remote),
            ),
        )


def run(command, timeout=1800):
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    with _lock:
        _processes.add(process)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if not getattr(_commit, 'confirmed', False):
                check_cancelled()
            try:
                output, _ = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() > deadline:
                    raise MusicError(
                        'The Nextcloud operation timed out; local files were kept.'
                    ) from None
        return process.returncode, output
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        with _lock:
            _processes.discard(process)


def metadata(rel):
    code, output = run(
        [
            'rclone',
            'lsjson',
            'nextcloud:Music/' + rel,
            '--stat',
            '--hash',
            '--retries',
            '1',
        ],
        60,
    )
    if code in (3, 4):
        return None
    if code:
        raise MusicError(
            'Could not read the Nextcloud file. Check the rclone account and connection.'
        )
    value = json.loads(output)
    if value.get('IsDir'):
        raise MusicError('The server path is a directory.')
    return {key: value.get(key) for key in ('Size', 'ModTime', 'Hashes')} | {
        'ETag': RemoteFiles().etag(rel)
    }


def matches(values, remote):
    remote_hashes = {
        key.lower().replace('-', ''): value
        for key, value in (remote.get('Hashes') or {}).items()
        if value
    }
    return any(
        values.get(key) == value
        for key, value in remote_hashes.items()
        if key in values
    )


def same_remote(previous, current):
    return all(
        previous.get(key) == current.get(key) for key in ('Size', 'ModTime', 'Hashes')
    ) and (not previous.get('ETag') or previous['ETag'] == current.get('ETag'))


def remote_hash(rel):
    code, output = run(
        [
            'rclone',
            'hashsum',
            'SHA-256',
            'nextcloud:Music/' + rel,
            '--download',
            '--retries',
            '1',
        ]
    )
    values = output.decode().split()
    if code or not values:
        raise MusicError(
            'The server song could not be verified. Local files were kept.'
        )
    return values[0]


def publish(path, create=False):
    owner = account_id()
    path = Path(path)
    rel = path.relative_to(ROOT).as_posix()
    path = local_path(rel)
    if path.suffix.lower() not in EXTENSIONS:
        raise MusicError('Choose an audio file inside Music.')
    before = signature(path)
    values = hashes(path)
    old = baseline(owner, rel)
    remote = metadata(rel)
    if remote is None and not create:
        return dict(
            synced=False,
            path=str(path),
            message='Saved locally; the song is not on Nextcloud.',
        )
    if remote and matches(values, remote):
        remember(owner, rel, path, remote, values, observed=before)
        return dict(synced=True, path=str(path))
    if remote and old and not same_remote(old['remote'], remote):
        if remote_hash(rel) == values['sha256'] and metadata(rel) == remote:
            remember(owner, rel, path, remote, values, observed=before)
            return dict(synced=True, path=str(path))
        raise MusicError(
            'The server song changed. Local edits were kept; compare the copies before replacing it.'
        )
    if remote and not old:
        code, output = run(
            [
                'rclone',
                'hashsum',
                'SHA-256',
                'nextcloud:Music/' + rel,
                '--download',
                '--retries',
                '1',
            ]
        )
        if (
            code
            or not output.decode().split()
            or output.decode().split()[0] != values['sha256']
        ):
            raise MusicError(
                'An unverified server copy exists. Local edits were kept; compare the copies first.'
            )
        remember(owner, rel, path, remote, values, observed=before)
        return dict(synced=True, path=str(path))
    if remote and old and not old['remote'].get('ETag'):
        if remote_hash(rel) != old['hashes']['sha256'] or metadata(rel) != remote:
            raise MusicError(
                'The server song changed. Local edits were kept; reopen its information.'
            )
    if (
        remote
        and old
        and values['sha256'] == old['hashes']['sha256']
        and same_remote(old['remote'], remote)
    ):
        return dict(synced=True, path=str(path))
    fd, name = tempfile.mkstemp(prefix='.music-upload-', suffix=path.suffix)
    os.close(fd)
    snapshot = Path(name)
    with _lock:
        _partials.add(snapshot)
    try:
        import shutil

        shutil.copy2(path, snapshot)
        if signature(path) != before or hashes(snapshot)['sha256'] != values['sha256']:
            raise MusicError('The local song changed while preparing it; save again.')
        history = time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
        expected = remote.get('ETag') if remote else None
        if remote and not expected:
            raise MusicError('The server did not provide a safe update version.')
        committed = RemoteFiles().upload(
            snapshot, rel, expected, history, sha1=values['sha1']
        )
        # Verification finishes after a confirmed commit, even if Cancel arrives.
        _commit.confirmed = True
        try:
            current = metadata(rel)
            verified = (
                current
                and (not committed or current.get('ETag') == committed)
                and (matches(values, current) or remote_hash(rel) == values['sha256'])
            )
            verified = verified and metadata(rel) == current
        finally:
            _commit.confirmed = False
        if not verified:
            raise MusicError(
                'The server update could not be verified. Local edits were kept.'
            )
        if path.exists() and signature(path) == before:
            remember(owner, rel, path, current, values, observed=before)
        return dict(synced=True, path=str(path))
    finally:
        snapshot.unlink(missing_ok=True)
        with _lock:
            _partials.discard(snapshot)


def move(path, newrel, remote_allowed=True, song=None):
    from urllib.parse import quote

    path = Path(path)
    owner = account_id()
    rel = path.relative_to(ROOT).as_posix()
    local_path(rel)
    if (
        not isinstance(newrel, str)
        or newrel.startswith('/')
        or any(c in newrel for c in ('\\', '\n', '\r', '\0'))
        or Path(newrel).suffix.lower() != path.suffix.lower()
    ):
        raise MusicError('Choose a Music-relative path with the same audio extension.')
    target = local_path(newrel)
    if target == path:
        return dict(path=str(path), synced=remote_allowed)
    if target.exists() or target.is_symlink():
        raise MusicError('The new local filename already exists. Nothing was renamed.')
    newrel = target.relative_to(ROOT).as_posix()
    old = baseline(owner, rel)
    remote = metadata(rel) if remote_allowed else None
    if remote and old and not same_remote(old['remote'], remote):
        raise MusicError('The server song changed; refresh before renaming.')
    if remote_allowed and not remote:
        raise MusicError('The server song is no longer available. Refresh My Library.')
    if remote and metadata(newrel):
        raise MusicError('The new server filename already exists. Nothing was renamed.')
    local = path.is_file()
    if not local and not remote:
        raise MusicError('The local song is no longer available.')
    if local:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(path, target)
    try:
        if remote:
            account = nextcloud.load_account()
            dav = nextcloud.DAVClient(
                account,
                scope='remote.php/dav/files/'
                + quote(account['username'], safe='')
                + '/Music/',
            )
            source = dav.home + '/'.join(
                quote(part, safe='') for part in PurePosixPath(rel).parts
            )
            destination = dav.home + '/'.join(
                quote(part, safe='') for part in PurePosixPath(newrel).parts
            )
            body = (
                b'<d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>'
            )
            document, _ = dav.request(
                'PROPFIND',
                source,
                body,
                {'Depth': '0', 'Content-Type': 'application/xml'},
            )
            etag = ET.fromstring(document).findtext('.//{DAV:}getetag')
            if not etag:
                raise MusicError('The server did not provide a safe rename version.')
            if metadata(rel) != remote:
                raise MusicError(
                    'The server song changed before moving. Both copies were kept.'
                )
            for parent in list(PurePosixPath(newrel).parents)[::-1]:
                if str(parent) == '.':
                    continue
                folder = (
                    dav.home
                    + '/'.join(quote(part, safe='') for part in parent.parts)
                    + '/'
                )
                try:
                    dav.request('MKCOL', folder)
                except nextcloud.NextcloudError:
                    dav.request(
                        'PROPFIND',
                        folder,
                        body,
                        {'Depth': '0', 'Content-Type': 'application/xml'},
                    )
            dav.request(
                'MOVE',
                source,
                headers={
                    'Destination': destination,
                    'Overwrite': 'F',
                    'If-Match': etag,
                },
            )
            payload = dict(song or {}, serverPath='/' + newrel, moved=time.time())
            with db() as connection:
                pending = next(
                    (
                        row
                        for row in connection.execute(
                            'SELECT old_path,payload FROM music_pending_moves WHERE account=? AND new_path=?',
                            (owner, rel),
                        )
                        if same_song(
                            json.loads(row[1]), row[0], dict(payload, serverPath=rel)
                        )
                    ),
                    None,
                )
                if pending:
                    previous = json.loads(pending[1])
                    payload['previousPaths'] = list(
                        dict.fromkeys(
                            [pending[0], *previous.get('previousPaths', []), rel]
                        )
                    )
                    connection.execute(
                        'UPDATE music_pending_moves SET new_path=?,payload=? WHERE account=? AND old_path=?',
                        (newrel, json.dumps(payload), owner, pending[0]),
                    )
                else:
                    connection.execute(
                        'INSERT OR REPLACE INTO music_pending_moves VALUES(?,?,?,?)',
                        (owner, rel, newrel, json.dumps(payload)),
                    )
        if local:
            path.unlink()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if old:
        _commit.confirmed = bool(remote)
        try:
            after = metadata(newrel) if remote else old['remote']
        except (MusicError, ValueError, OSError):
            # The MOVE already committed; a failed check must not report failure.
            after = None
        finally:
            _commit.confirmed = False
        confirmed = after or old['remote']
        with db() as connection:
            connection.execute(
                'DELETE FROM music_cache WHERE account=? AND path=?', (owner, rel)
            )
            connection.execute(
                'INSERT OR REPLACE INTO music_cache VALUES(?,?,?,?,?)',
                (
                    owner,
                    newrel,
                    json.dumps(old['signature']),
                    json.dumps(old['hashes']),
                    json.dumps(confirmed),
                ),
            )
    with db() as connection:
        connection.execute(
            'UPDATE music_pending_index SET path=? WHERE account=? AND path=?',
            (newrel, owner, rel),
        )
    return dict(
        path=str(target), local=local, relativePath=newrel, synced=remote is not None
    )


def download(song):
    owner, rel = checked(song)
    path = local_path(rel)
    if path.is_file():
        return path
    if song.get('source') == 'music-local' and song.get('notUploaded', True):
        raise MusicError('The local song is no longer available. Refresh My Library.')
    before = metadata(rel)
    if not before:
        raise MusicError('This song is no longer on Nextcloud.')
    return fetch(owner, rel, path, before)


def refresh_stale(owner, rel, path):
    """Replace a cached copy without local edits when Nextcloud has a newer
    version (edited elsewhere). Returns whether the copy was replaced."""
    old = baseline(owner, rel)
    if not old or not old['remote'].get('ETag'):
        return False
    observed = signature(path)
    if (
        observed != old['signature']
        and content_hash(path, observed) != old['hashes']['sha256']
    ):
        return False  # Local edits: publishing reports the conflict instead.
    remote = metadata(rel)
    if not remote or same_remote(old['remote'], remote):
        return False
    fetch(owner, rel, path, remote, replace=observed)
    return True


def fetch(owner, rel, path, before, replace=None):
    """Download the server version described by before. A new copy never
    replaces a file; replace names the only local version it may overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix='.nextcloud-download-', suffix='.part', dir=path.parent
    )
    os.close(fd)
    temporary = Path(name)
    with _lock:
        _partials.add(temporary)
    try:
        progress(detail='Downloading local copy…')
        code, _ = run(
            [
                'rclone',
                'copyto',
                'nextcloud:Music/' + rel,
                str(temporary),
                # The target is already private; rclone's own partial file would
                # outlive a cancelled (killed) download.
                '--inplace',
                '--checksum',
                '--retries',
                '1',
                '--log-level',
                'ERROR',
            ]
        )
        if code:
            raise MusicError(
                'The song could not be downloaded; existing local files were kept.'
            )
        remote = metadata(rel)
        values = hashes(temporary)
        if (
            not remote
            or remote != before
            or remote.get('Size') != temporary.stat().st_size
        ):
            raise MusicError(
                'The server song changed during download. No local file was replaced.'
            )
        if remote.get('Hashes') and not matches(values, remote):
            raise MusicError(
                'Downloaded bytes could not be verified against Nextcloud.'
            )
        check_cancelled()
        if replace is None:
            try:
                place(temporary, path)
            except FileExistsError:
                return path
        elif signature(path) != replace:
            raise MusicError(
                'The local song changed while updating it from Nextcloud. It was kept.'
            )
        else:
            os.replace(temporary, path)
        remember(owner, rel, path, remote, values, observed=signature(path))
        return path
    finally:
        temporary.unlink(missing_ok=True)
        with _lock:
            _partials.discard(temporary)


def states(items):
    output = []
    for song in items:
        if song.get('source') not in ('nextcloud', 'music-local') or not song.get(
            'serverPath'
        ):
            continue
        try:
            owner, rel = checked(song)
            path = local_path(rel)
            old = baseline(owner, rel)
            local = path.is_file()
            observed = signature(path) if local else None
            dirty = local and (
                not old
                or (
                    observed != old['signature']
                    and content_hash(path, observed) != old['hashes']['sha256']
                )
            )
            output.append(
                dict(
                    id=song['id'],
                    kind='song',
                    source=song['source'],
                    local=local,
                    localPath=str(path) if local else '',
                    pendingUpload=bool(dirty),
                )
            )
        except (MusicError, OSError):
            continue
    return output


def register(path):
    with _lock:
        _partials.add(path)


def unregister(path):
    with _lock:
        _partials.discard(path)


def file_job(args):
    from spaces.music import tags

    action = args['action']
    song = args.get('song', {})
    if action == 'cache-collection':
        count = 0
        errors = []
        for item in args.get('songs', []):
            check_cancelled()
            try:
                download(item)
                count += 1
            except (MusicError, ValueError, OSError, sqlite3.Error, ET.ParseError):
                errors.append(item.get('title') or 'Song')
        if errors:
            raise MusicError(
                str(count)
                + ' songs cached; '
                + str(len(errors))
                + ' failed. Completed files were kept.'
            )
        return dict(action=action, count=count)
    owner, rel = checked(song)
    if action == 'move':
        return dict(
            action=action,
            **move(
                local_path(rel),
                args.get('relativePath'),
                remote_allowed=not song.get(
                    'notUploaded', song.get('source') == 'music-local'
                ),
                song=song,
            ),
        )
    if action == 'download':
        return dict(action=action, path=str(download(song)))
    if action != 'save':
        raise MusicError('Unknown Music file action.')

    def unchanged_server():
        current = metadata(rel)
        if not current or current.get('ETag') != expected:
            raise MusicError(
                'The server song changed since editing began. Your draft was kept; reload its metadata before saving.'
            )

    expected = args.get('remoteVersion')
    if expected:
        unchanged_server()
    path = download(song)
    # Capture a comparison baseline before edits.
    if song.get('source') == 'nextcloud' and baseline(owner, rel) is None:
        remote = metadata(rel)
        if remote:
            code, output = run(
                [
                    'rclone',
                    'hashsum',
                    'SHA-256',
                    'nextcloud:Music/' + rel,
                    '--download',
                    '--retries',
                    '1',
                ]
            )
            values = output.decode().split()
            if code or not values or metadata(rel) != remote:
                raise MusicError(
                    'The server song changed while opening it. Please retry.'
                )
            remember(owner, rel, path, remote, {'sha256': values[0]}, observed=[])
    if (
        song.get('source') == 'nextcloud'
        and refresh_stale(owner, rel, path)
        and args.get('signature')
    ):
        raise MusicError(
            'Nextcloud had a newer version of this song, so the local copy was '
            'updated. Reopen its information to edit it.'
        )
    if expected:
        unchanged_server()
    if args.get('signature') and token(signature(path)) != args['signature']:
        raise MusicError('The local song changed. Reopen information before saving.')
    changes = args.get('tags')
    if isinstance(changes, dict):
        current_tags = tags.read(path, run)['tags']
        changes = {
            key: value
            for key, value in changes.items()
            if current_tags.get(key) != value
        }
    if changes or args.get('artwork'):
        tags.write(
            path,
            changes,
            run,
            signature,
            register,
            unregister,
            artwork=args.get('artwork'),
        )
    details = tags.read(path, run)
    observed = signature(path)
    try:
        result = publish(
            path,
            create=bool(song.get('notUploaded', song.get('source') == 'music-local')),
        )
    except (MusicError, ValueError, OSError, sqlite3.Error, ET.ParseError) as error:
        return dict(
            action=action,
            path=str(path),
            relativePath=rel,
            synced=False,
            error=str(error),
            localSaved=True,
            signature=token(observed),
            **details,
        )
    if result.get('synced'):
        with db() as connection:
            connection.execute(
                'INSERT OR IGNORE INTO music_pending_index VALUES(?,?)',
                (owner, rel),
            )
    return dict(
        action=action, relativePath=rel, signature=token(observed), **details, **result
    )


_COVER_MISSING = set()


def cover(song):
    owner, rel = checked(song)
    path = local_path(rel)
    if not path.is_file():
        return ''
    key = hashlib.sha256(json.dumps([owner, rel, signature(path)]).encode()).hexdigest()
    directory = (
        Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
        / 'quickshell/desktop/spaces/music/artwork/local'
    )
    target = directory / (key + '.img')
    if target.is_file():
        return target.as_uri()
    if key in _COVER_MISSING:
        return ''
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.cover-', suffix='.jpg', dir=directory)
    os.close(fd)
    temporary = Path(name)
    register(temporary)
    try:
        code, _ = run(
            [
                'ffmpeg',
                '-v',
                'error',
                '-nostdin',
                '-y',
                '-i',
                str(path),
                '-map',
                '0:v:0',
                '-an',
                '-frames:v',
                '1',
                '-vf',
                'scale=128:128:force_original_aspect_ratio=decrease',
                str(temporary),
            ],
            20,
        )
        if code or not temporary.stat().st_size:
            if len(_COVER_MISSING) > 512:
                _COVER_MISSING.clear()
            _COVER_MISSING.add(key)
            return ''
        os.replace(temporary, target)
        return target.as_uri()
    finally:
        temporary.unlink(missing_ok=True)
        unregister(temporary)


def shutdown():
    JOBS.stop()
    with _lock:
        processes = list(_processes)
        partials = list(_partials)
    for process in processes:
        if process.poll() is None:
            process.kill()
    for path in partials:
        path.unlink(missing_ok=True)


def handle(args):
    op = args['op']
    if op == 'states':
        return states(args.get('items', []))
    if op == 'file-job':
        return JOBS.start(args.get('title') or 'Music files', lambda: file_job(args))
    if op == 'jobs':
        return JOBS.snapshots()
    if op == 'cancel_job':
        return JOBS.cancel(args['job_id'])
    raise MusicError('Unknown Music file operation.')


if __name__ == '__main__':
    from spaces.movies.worker import own_process_group, serve

    own_process_group(shutdown)
    serve(
        handle,
        errors=(MusicError, nextcloud.NextcloudError, ValueError, OSError),
        controls=('file-job', 'cancel_job'),
        latest=('states',),
    )
