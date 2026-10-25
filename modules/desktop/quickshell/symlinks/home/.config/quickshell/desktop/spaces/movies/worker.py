"""Bounded JSON-lines workers with read, ordered control, and artwork lanes.

Every accepted request settles, even when superseded. Read traffic leaves room
for controls so a busy catalogue cannot prevent playback or saving favorites.
"""

import json
import logging
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

_LOG = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 1024 * 1024


def own_process_group(cleanup=None):
    """Terminate owned probes/converters on close; detached applications survive."""
    os.setpgid(0, 0)

    def terminate_group(*_):
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.killpg(os.getpid(), signal.SIGTERM)

    def shutdown(*_):
        # Network cleanup must not prevent releasing local processes on close.
        signal.signal(signal.SIGALRM, terminate_group)
        signal.alarm(2)
        try:
            if os.environ.get("QUICKSHELL_MEDIA_SPACE", "movies") in ("movies", "series", "games", "books"):
                from spaces.movies.local import cleanup_transfers
                cleanup_transfers()
            if cleanup:
                cleanup()
        finally:
            terminate_group()

    signal.signal(signal.SIGTERM, shutdown)


def serve(
    handle,
    *,
    errors=(ValueError,),
    latest=(),
    controls=(),
    background=(),
    workers=3,
    stream=None,
    output=None,
    capacity=64,
    scope=None,
):
    stream, output = stream or sys.stdin, output or sys.stdout
    write_lock = threading.Lock()
    state_lock = threading.Lock()
    newest = {}
    scope = scope or (lambda request: request["op"])
    slots = threading.BoundedSemaphore(capacity)
    read_slots = threading.BoundedSemaphore(capacity - min(8, capacity // 4))

    def emit(response):
        with write_lock:
            output.write(json.dumps(response, ensure_ascii=False) + "\n")
            output.flush()

    def execute(request, key, token, is_control):
        try:
            with state_lock:
                superseded = token is not None and newest.get(key) is not token
            if superseded:
                emit({"id": request["id"], "error": "Request superseded."})
                return
            try:
                response = {"id": request["id"], "result": handle(request)}
                # Serialize inside the error boundary: a malformed backend result
                # must settle its callback too, rather than vanish in a Future.
                encoded = json.dumps(response, ensure_ascii=False)
            except errors as error:
                response = {"id": request["id"], "error": str(error)}
                if code := getattr(error, "code", None):
                    response["error_code"] = code
                encoded = json.dumps(response)
            except Exception:
                _LOG.exception("Worker operation %s failed", request["op"])
                encoded = json.dumps(
                    {
                        "id": request["id"],
                        "error": "The request could not be completed. Try again.",
                    }
                )
            with write_lock:
                output.write(encoded + "\n")
                output.flush()
        finally:
            if token is not None:
                with state_lock:
                    if newest.get(key) is token:
                        del newest[key]
            slots.release()
            if not is_control:
                read_slots.release()

    with (
        ThreadPoolExecutor(max_workers=workers, thread_name_prefix="catalogue") as reads,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="control") as writes,
        ThreadPoolExecutor(max_workers=2, thread_name_prefix="artwork") as images,
    ):
        for line in stream:
            request = None
            try:
                if len(line) > MAX_REQUEST_BYTES:
                    raise ValueError()
                request = json.loads(line)
                if (
                    not isinstance(request, dict)
                    or not isinstance(request.get("op"), str)
                    or not request["op"]
                    or type(request.get("id")) not in (int, str)
                ):
                    raise ValueError()
                is_control = request["op"] in controls
                # Mutations are never superseded, even if also listed in latest.
                token = object() if request["op"] in latest and not is_control else None
                key = scope(request) if token is not None else None
                hash(key)
            except (ValueError, TypeError, KeyError):
                identifier = request.get("id") if isinstance(request, dict) else None
                emit(
                    {
                        "id": identifier if type(identifier) in (int, str) else None,
                        "error": "Invalid worker request.",
                    }
                )
                continue
            read_acquired = is_control or read_slots.acquire(blocking=False)
            if not read_acquired or not slots.acquire(blocking=False):
                if read_acquired and not is_control:
                    read_slots.release()
                emit(
                    {"id": request["id"], "error": "Too many pending requests. Try again shortly."}
                )
                continue
            if token is not None:
                with state_lock:
                    newest[key] = token
            executor = writes if is_control else images if request["op"] in background else reads
            executor.submit(execute, request, key, token, is_control)
