#!/usr/bin/env python3
"""Offline command, download server, and renderer fixtures for real Pictures flows."""

import json
import os
import signal
import socket
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = Path(os.environ["PICTURE_FIXTURE_ROOT"])
name = Path(sys.argv[0]).name


def alive():
    try:
        pid = int((root / "player.pid").read_text())
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return pid if state not in {"Z", "X"} else 0
    except (OSError, ValueError):
        return 0


if name == "mpvpaper":
    options = sys.argv[sys.argv.index("-o") + 1].split()
    socket_path = next(
        part.split("=", 1)[1] for part in options if part.startswith("input-ipc-server=")
    )
    (root / "player.pid").write_text(str(os.getpid()))
    with (root / "players.jsonl").open("a") as log:
        log.write(json.dumps({"pid": os.getpid(), "argv": sys.argv[1:]}) + "\n")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen()
    paused = False

    def shutdown(signum, frame):
        server.close()
        Path(socket_path).unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    while True:
        connection, _ = server.accept()
        with connection:
            request = json.loads(connection.makefile("rb").readline())
            command = request["command"]
            data = None
            if command == ["get_property", "time-pos"]:
                data = 1.0
            elif command[:2] == ["set_property", "pause"]:
                paused = command[2]
                with (root / "pause.jsonl").open("a") as log:
                    log.write(json.dumps(paused) + "\n")
            connection.sendall(
                (json.dumps({"request_id": 1, "error": "success", "data": data}) + "\n").encode()
            )
elif name == "hyprctl":
    if sys.argv[1] == "layers":
        pid = alive()
        surfaces = (
            [{"namespace": "mpvpaper", "pid": pid, "w": 1920, "h": 1080, "alpha": 1}] if pid else []
        )
        print(json.dumps({"TEST": {"levels": {"0": surfaces}}}))
    else:
        print("[]")
elif name == "picture-fixture-server":

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    (root / "server.port").write_text(str(server.server_address[1]))
    server.serve_forever()
else:
    request = json.load(sys.stdin)
    base = "http://127.0.0.1:" + (root / "server.port").read_text()
    with (root / "provider-requests.jsonl").open("a") as log:
        log.write(json.dumps(request) + "\n")
    if request.get("query") == "slow":
        time.sleep(10)
    if request.get("op") == "browse":
        page = request.get("page", 1)
        identifier = "second" if page == "opaque-next-page" else "first"
        print(
            json.dumps(
                {
                    "success": True,
                    "next": "opaque-next-page" if identifier == "first" else 0,
                    "items": [
                        {
                            "id": identifier,
                            "title": "Fixture video " + identifier,
                            "kind": "video",
                            "ref": {"id": identifier},
                            "preview": base + "/poster.png",
                            "url": base + "/detail",
                        }
                    ],
                }
            )
        )
    elif request.get("op") == "resolve":
        print(json.dumps({"success": True, "url": base + "/video.mp4"}))
    else:
        print(json.dumps({"success": False, "error": "Unsupported fixture request."}))
