#!/usr/bin/env python3
"""Bounded private artwork cache. URLs/credentials are never stored in filenames."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SPACE = os.environ.get('QUICKSHELL_MEDIA_SPACE', 'movies')
if SPACE not in ('movies', 'series', 'games', 'pictures', 'books', 'music'):
    raise ValueError('Unknown artwork Space.')
CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.local/cache')) / 'quickshell/desktop/spaces' / SPACE / 'artwork'
RETENTION = 30 * 86400
MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 2000
MAX_IMAGE = 20 * 1024 * 1024


class ImageError(ValueError):
    pass


class ArtworkCache:
    def __init__(self, directory=CACHE, *, max_bytes=MAX_BYTES, max_files=MAX_FILES, retention=RETENTION):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.max_bytes, self.max_files, self.retention = max_bytes, max_files, retention
        self._locks = [threading.Lock() for _ in range(64)]
        self._prune_lock = threading.Lock()
        self.prune()

    def prune(self):
        with self._prune_lock:
            now = time.time()
            files = []
            for path in self.directory.iterdir():
                if path.is_symlink():
                    continue
                if re.fullmatch(r'\.download-\d+-.*', path.name):
                    try:
                        if now - path.stat().st_mtime > 86400:
                            path.unlink(missing_ok=True)
                    except FileNotFoundError:
                        pass
                    continue
                if not re.fullmatch(r'[a-f0-9]{64}\.img', path.name):
                    continue
                try:
                    stat = path.stat()
                    if now - stat.st_mtime > self.retention:
                        path.unlink(missing_ok=True)
                    else:
                        files.append((stat.st_mtime, stat.st_size, path))
                except FileNotFoundError:
                    continue
            total, count = sum(size for _, size, _ in files), len(files)
            for _, size, path in sorted(files):
                if count <= self.max_files and total <= self.max_bytes:
                    break
                path.unlink(missing_ok=True)
                total -= size
                count -= 1

    def fetch(self, url, *, refresh=False):
        if not isinstance(url, str) or len(url) > 8192:
            raise ImageError('Invalid artwork URL.')
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ImageError('Invalid artwork URL.')
        key = hashlib.sha256(url.encode()).hexdigest()
        target = self.directory / (key + '.img')
        with self._locks[int(key[:4], 16) % len(self._locks)]:
            if target.is_file() and not target.is_symlink() and not refresh:
                if time.time() - target.stat().st_mtime <= self.retention:
                    os.utime(target, None)
                    return target.as_uri()
            request = urllib.request.Request(url, headers={'User-Agent': 'DesktopMovies/1.0', 'Accept': 'image/*'})
            temporary = None
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    mime = response.headers.get('Content-Type', '').split(';')[0].lower()
                    if not mime.startswith('image/'):
                        raise ImageError('Artwork provider returned an unsupported image.')
                    with tempfile.NamedTemporaryFile(prefix=f'.download-{os.getpid()}-', dir=self.directory, delete=False) as stream:
                        temporary = Path(stream.name)
                        size = 0
                        while chunk := response.read(65536):
                            size += len(chunk)
                            if size > MAX_IMAGE:
                                raise ImageError('Artwork exceeds the cache image size limit.')
                            stream.write(chunk)
                        if not size:
                            raise ImageError('Artwork provider returned an empty image.')
                        stream.flush()
                        os.fsync(stream.fileno())
                temporary.chmod(0o600)
                temporary.replace(target)
                temporary = None
            except (OSError, urllib.error.URLError):
                raise ImageError('Artwork is unavailable. Try again later.') from None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        # A bounded cache is independent of library data and can be removed freely.
        self.prune()
        return target.as_uri()

    def handle(self, request):
        if request.get('op') != 'fetch':
            raise ImageError('Unknown artwork request.')
        return self.fetch(request.get('url'), refresh=bool(request.get('refresh')))


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from spaces.movies.worker import own_process_group, serve
    cache = ArtworkCache()
    # Remove only this process's unfinished downloads on explicit close.
    own_process_group(lambda: [path.unlink(missing_ok=True) for path in cache.directory.glob(f'.download-{os.getpid()}-*')])
    serve(cache.handle, errors=(ImageError,), workers=4)


if __name__ == '__main__':
    main()
