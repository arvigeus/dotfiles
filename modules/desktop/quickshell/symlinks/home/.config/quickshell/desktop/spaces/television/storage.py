"""Private Television preferences/records and replaceable catalogue snapshots."""

import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


class TelevisionError(ValueError):
    pass


def http_url(value):
    if not isinstance(value, str) or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        return ''
    try:
        parsed = urlsplit(value.strip())
        return (
            value.strip()
            if parsed.scheme in ('http', 'https')
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            else ''
        )
    except ValueError:
        return ''


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        raise TelevisionError(
            'Television could not read its saved records. The existing file was preserved.'
        ) from None


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='.television-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
