"""Music-owned private snapshots and scoped player sockets."""

import json
import os
import tempfile
from pathlib import Path

from spaces.music.records import MusicError
from spaces.pictures.mpv import MpvIpc

ROOT = 'quickshell/desktop/spaces/music'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / ROOT
DATA = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / ROOT


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='.music-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        raise MusicError(
            'Music could not read its saved records. The existing file was preserved.'
        ) from None


class MusicIpc(MpvIpc):
    def directory(self):
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())
        path = runtime / ('quickshell-music-' + str(os.getuid()))
        if len(os.fsencode(str(path / ('mpv-' + 'a' * 16 + '.sock')))) >= 100:
            path = Path(tempfile.gettempdir()) / path.name
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise MusicError("Music's player directory is unavailable.")
        path.chmod(0o700)
        return path
