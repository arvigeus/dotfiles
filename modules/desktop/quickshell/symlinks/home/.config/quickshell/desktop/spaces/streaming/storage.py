"""Private portable Streaming state; media and replaceable caches live separately."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading


class StreamingError(ValueError):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (OSError, ValueError):
        raise StreamingError("Streaming could not read its saved settings. The existing file was preserved.") from None


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix=".streaming-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Library:
    def __init__(self, directory):
        self.path = directory / "library.json"
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            value = read_json(self.path, {})
            if not isinstance(value, dict) or any(not isinstance(value.get(key, {}), dict) for key in ("downloads", "summaries")):
                raise StreamingError("Streaming's library is invalid. The existing file was preserved.")
            return {key: value.get(key, {}) for key in ("downloads", "summaries")}

    def put(self, collection, identity, value):
        with self.lock:
            state = self.read()
            target = state[collection]
            target.pop(identity, None)
            if value is not None:
                target[identity] = value
            # Retain download associations; generated text evicts its oldest entry.
            limit = 1000 if collection == "summaries" else 10000
            if len(target) > limit:
                if collection == "downloads":
                    raise StreamingError("Streaming's library is full.")
                target.pop(next(iter(target)))
            atomic_json(self.path, state)

    def items(self, collection):
        return list(reversed(list(self.read()[collection].values())))
