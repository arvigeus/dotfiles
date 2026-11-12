"""Owned state and settings: atomic replacement and private settings reads."""

import json
import os
import tempfile
from pathlib import Path

from integrations import private


def atomic_write(path, content, mode=0o600):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.pictures-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content if isinstance(content, bytes) else content.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_settings(path):
    """Return (parsed JSON, owner-only) for a settings file; missing is ({}, True).

    The file may link into a private checkout; the opened target is checked.
    Settings that run commands or hold credentials are trusted only from a file
    that only its owner can access, as Movies requires for media.json.
    """
    try:
        text, info = private.read(path, follow_symlinks=True)
    except FileNotFoundError:
        return {}, True
    return json.loads(text), private.owner_only(info)
