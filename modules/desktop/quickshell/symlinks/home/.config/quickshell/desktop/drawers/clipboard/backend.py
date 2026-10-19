#!/usr/bin/env python3
"""JSON-lines adapter for cliphist and its Wayland capture processes."""
import json
import mimetypes
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

MAX_ITEMS = "50"
MAX_CACHED_IMAGES = 32
paused_path = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")) / "quickshell/desktop/clipboard-paused"
cache_root = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "quickshell/clipboard-preview"
watchers = []
cached_images = []
IMAGE_PREVIEW = re.compile(
    r"^\[\[ binary data (?P<size>\d+(?:\.\d+)?\s+\S+) "
    r"(?P<format>png|jpe?g|gif|webp|bmp|tiff?|svg|avif|heic|ico)"
    r"(?: (?P<dimensions>\d+x\d+))? \]\]$", re.IGNORECASE)


def command(args, *, input_data=None, timeout=5):
    return subprocess.run(["cliphist", "-max-items", MAX_ITEMS, *args], input=input_data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True)


def watcher_args(kind):
    return ["wl-paste", "--type", kind, "--watch", "cliphist", "-max-items", MAX_ITEMS, "store"]


def start_watchers():
    global watchers
    stop_watchers()
    if paused_path.exists():
        return
    if not shutil.which("wl-paste") or not shutil.which("cliphist"):
        return
    for kind in ("text", "image"):
        try:
            watchers.append(subprocess.Popen(watcher_args(kind), stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True))
        except OSError:
            stop_watchers()
            return


def stop_watchers():
    global watchers
    for proc in watchers:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
    watchers = []


def list_records():
    output = command(["list"]).stdout.decode("utf-8", "replace")
    records = []
    for line in output.splitlines():
        item_id, separator, preview = line.partition("\t")
        if not separator:
            continue
        try:
            records.append((int(item_id), line + "\n", preview))
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
    for item_id, _, preview in list_records():
        details = image_details(preview)
        mime = details["mime"] if details else "text/plain;charset=utf-8"
        label = details["preview"] if details else preview
        if needle and needle not in (mime + " " + label + " " + preview).casefold():
            continue
        result.append({"id": item_id, "mime": mime, "preview": label,
                       "image": details is not None})
    return result


def raw_record(item_id):
    for record_id, line, preview in list_records():
        if record_id == item_id:
            return line.encode(), preview
    raise ValueError("Clipboard item no longer exists.")


def handle(request):
    op = request.get("op")
    if op == "status":
        available = bool(shutil.which("cliphist") and shutil.which("wl-paste") and shutil.which("wl-copy"))
        return {"op": op, "available": available, "paused": paused_path.exists(), "entries": []}
    if op == "list":
        return {"op": op, "available": True, "paused": paused_path.exists(), "entries": entries(str(request.get("query", "")))}
    if op == "pause":
        if request.get("value"):
            paused_path.parent.mkdir(parents=True, exist_ok=True)
            paused_path.write_text("paused\n")
        else:
            paused_path.unlink(missing_ok=True)
        start_watchers()
        return {"op": op, "paused": paused_path.exists()}
    if op == "clear":
        command(["wipe"])
        return {"op": op}
    if op == "delete":
        command(["delete"], input_data=raw_record(int(request["id"]))[0])
        return {"op": op}
    if op == "copy":
        item_id = int(request["id"])
        record, preview = raw_record(item_id)
        decoded = command(["decode"], input_data=record, timeout=10).stdout
        details = image_details(preview)
        mime = decoded_mime(decoded, details["mime"] if details else None)
        process = subprocess.Popen(["wl-copy", "--foreground", "--type", mime], stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            process.stdin.write(decoded)
            process.stdin.close()
        except OSError:
            process.kill()
            raise
        try:
            code = process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            # wl-copy stays alive while it owns the clipboard selection.
            pass
        else:
            if code:
                raise RuntimeError("wl-copy could not set the clipboard contents.")
        return {"op": op}
    if op == "thumbnail":
        item_id = int(request["id"])
        record, preview = raw_record(item_id)
        details = image_details(preview)
        if not details:
            raise ValueError("Clipboard item is not an image.")
        decoded = command(["decode"], input_data=record, timeout=10).stdout
        mime = decoded_mime(decoded, details["mime"] if details else None)
        cache_root.mkdir(parents=True, exist_ok=True)
        suffix = mimetypes.guess_extension(mime) or ".img"
        path = cache_root / (str(item_id) + suffix)
        path.write_bytes(decoded)
        if item_id in cached_images:
            cached_images.remove(item_id)
        cached_images.append(item_id)
        expired_images = []
        while len(cached_images) > MAX_CACHED_IMAGES:
            expired = cached_images.pop(0)
            expired_images.append(expired)
            for old in cache_root.glob(str(expired) + ".*"):
                old.unlink(missing_ok=True)
        return {"op": op, "id": item_id, "url": path.as_uri(), "expired": expired_images}
    raise ValueError("Unknown clipboard operation.")


def main():
    os.umask(0o077)
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_root.chmod(0o700)
    # Preview files can contain sensitive clipboard data; keep them private and
    # remove stale preview files whenever this shell session starts.
    for path in cache_root.iterdir():
        if path.is_file():
            path.unlink(missing_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    start_watchers()
    try:
        for line in sys.stdin:
            try:
                result = handle(json.loads(line))
            except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
                result = {"op": "error", "error": str(exc)[:200]}
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        stop_watchers()
        shutil.rmtree(cache_root, ignore_errors=True)


if __name__ == "__main__":
    main()
