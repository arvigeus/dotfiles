"""Credential files in the shared integrations directory: bounded, non-blocking reads."""

import errno
import os
import stat
from pathlib import Path

LIMIT = 64 * 1024


class UnreadableFile(ValueError):
    """The path is not a regular UTF-8 file of at most LIMIT bytes."""


def config_root():
    base = os.environ.get('XDG_CONFIG_HOME') or ''
    root = Path(base) if os.path.isabs(base) else Path.home() / '.config'
    return root / 'quickshell/desktop/integrations'


def read(path, *, follow_symlinks):
    """Return (text, stat) of the opened file; FileNotFoundError passes through.

    O_NONBLOCK keeps a FIFO from blocking the worker. Checks use the opened
    descriptor, so replacing the path cannot change what was validated.
    """
    name = Path(path).name
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
    if not follow_symlinks:
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as error:
        if error.errno == errno.ELOOP and not follow_symlinks:
            raise UnreadableFile(name + ' must not be a symlink.') from error
        raise UnreadableFile(name + ' cannot be opened.') from error
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UnreadableFile(name + ' must be a regular file.')
        try:
            data = source.read(LIMIT + 1)
        except OSError as error:
            raise UnreadableFile(name + ' cannot be read.') from error
    if len(data) > LIMIT:
        raise UnreadableFile(name + ' is larger than 64 KiB.')
    try:
        return data.decode(), info
    except UnicodeError as error:
        raise UnreadableFile(name + ' is not UTF-8 text.') from error


def owner_only(info):
    """True when only the current user can access the file, for example mode 0600."""
    return info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077
