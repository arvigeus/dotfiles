"""Private Radio records use atomic snapshots and bounded, explicit reads."""

import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from spaces.radio import api


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix='.radio-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
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
        raise api.RadioError(
            'Radio could not read its saved records. The existing file was preserved.'
        ) from None


def http_url(value):
    value = str(value or '').strip()
    parsed = urlsplit(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc else ''
