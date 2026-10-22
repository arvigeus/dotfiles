#!/usr/bin/env python3
"""JSON-lines adapter for cliphist; capture runs in the cliphist@ user units."""
import json
import mimetypes
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

MAX_CACHED_IMAGES = 32
WATCHERS = ["cliphist@text.service", "cliphist@image.service"]
cached_images = []
IMAGE_PREVIEW = re.compile(
    r"^\[\[ binary data (?P<size>\d+(?:\.\d+)?\s+\S+) "
    r"(?P<format>png|jpe?g|gif|webp|bmp|tiff?|svg|avif|heic|ico)"
    r"(?: (?P<dimensions>\d+x\d+))? \]\]$", re.IGNORECASE)


def cache_root():
    base = os.environ.get("XDG_CACHE_HOME") or ""
    root = pathlib.Path(base) if os.path.isabs(base) else pathlib.Path.home() / ".cache"
    return root / "quickshell/clipboard-preview"


def command(args, *, input_data=None, timeout=5):
    return subprocess.run(["cliphist", *args], input=input_data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True)


def paused():
    """Collection is paused while neither watcher unit is active."""
    # is-active succeeds when any listed unit is active.
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", *WATCHERS], timeout=5).returncode != 0


def set_paused(value):
    subprocess.run(["systemctl", "--user", "stop" if value else "start", *WATCHERS],
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15, check=True)


def list_records():
    output = command(["list"]).stdout.decode("utf-8", "replace")
    records = []
    for line in output.splitlines():
        item_id, separator, preview = line.partition("\t")
        if not separator:
            continue
        try:
            records.append((int(item_id), preview))
        except ValueError:
            continue
    return records


def image_details(preview):
    match = IMAGE_PREVIEW.match(preview)
    if not match:
        return None
    image_format = match.group("format").lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(
        image_format, "image/" + image_format)
    label = image_format.upper()
    if match.group("dimensions"):
        label += " · " + match.group("dimensions").replace("x", " × ")
    label += " · " + match.group("size")
    return {"mime": mime, "preview": label}


def decoded_mime(data, image_hint=None):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return image_hint or "text/plain;charset=utf-8"


def entries(query=""):
    needle = query.casefold().strip()
    result = []
    for item_id, preview in list_records():
        details = image_details(preview)
        mime = details["mime"] if details else "text/plain;charset=utf-8"
        label = details["preview"] if details else preview
        if needle and needle not in (mime + " " + label + " " + preview).casefold():
            continue
        result.append({"id": item_id, "mime": mime, "preview": label,
                       "image": details is not None})
    return result


def decode(item_id):
    return command(["decode", str(int(item_id))], timeout=10).stdout


def handle(request):
    op = request.get("op")
    if op == "status":
        available = bool(shutil.which("cliphist") and shutil.which("wl-paste") and shutil.which("wl-copy"))
        return {"op": op, "available": available, "paused": paused(), "entries": []}
    if op == "list":
        return {"op": op, "available": True, "paused": paused(), "entries": entries(str(request.get("query", "")))}
    if op == "pause":
        set_paused(bool(request.get("value")))
        return {"op": op, "paused": paused()}
    if op == "clear":
        command(["wipe"])
        return {"op": op}
    if op == "delete":
        command(["delete"], input_data=f"{int(request['id'])}\t\n".encode())
        return {"op": op}
    if op == "copy":
        decoded = decode(request["id"])
        mime = decoded_mime(decoded, request.get("mime") if str(request.get("mime", "")).startswith("image/") else None)
        # wl-copy forks a server that keeps the selection after this call returns.
        subprocess.run(["wl-copy", "--type", mime], input=decoded, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=5, check=True)
        return {"op": op}
    if op == "thumbnail":
        item_id = int(request["id"])
        decoded = decode(item_id)
        mime = decoded_mime(decoded, request.get("mime") if str(request.get("mime", "")).startswith("image/") else None)
        if not mime.startswith("image/"):
            raise ValueError("Clipboard item is not an image.")
        folder = cache_root()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (str(item_id) + (mimetypes.guess_extension(mime) or ".img"))
        path.write_bytes(decoded)
        if item_id in cached_images:
            cached_images.remove(item_id)
        cached_images.append(item_id)
        expired_images = []
        while len(cached_images) > MAX_CACHED_IMAGES:
            expired = cached_images.pop(0)
            expired_images.append(expired)
            for old in folder.glob(str(expired) + ".*"):
                old.unlink(missing_ok=True)
        return {"op": op, "id": item_id, "url": path.as_uri(), "expired": expired_images}
    raise ValueError("Unknown clipboard operation.")


def main():
    os.umask(0o077)
    folder = cache_root()
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    # Preview files can contain sensitive clipboard data; keep them private and
    # remove stale preview files whenever this shell session starts.
    for path in folder.iterdir():
        if path.is_file():
            path.unlink(missing_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    try:
        for line in sys.stdin:
            try:
                result = handle(json.loads(line))
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                result = {"op": "error", "error": str(exc)[:200]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
