"""IPC transport for module-owned mpv players; no process or playback state."""

import json
import os
import re
import socket
import tempfile
from pathlib import Path


class MpvIpc:
    def __init__(self, owner, timeout=0.4):
        if not re.fullmatch(r"[a-z][a-z0-9-]*", owner):
            raise ValueError("Invalid player owner.")
        self.owner = owner
        self.timeout = timeout

    def directory(self):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        suffix = "zs-" + self.owner + "-" + str(os.getuid())
        directory = runtime / suffix
        if len(os.fsencode(str(directory / ("mpv-" + "a" * 16 + ".sock")))) >= 100:
            directory = Path(tempfile.gettempdir()) / suffix
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        return directory

    def validate(self, value):
        path = Path(str(value or "").strip())
        if not re.fullmatch(r"mpv-[a-f0-9]{16}\.sock", path.name):
            return None
        try:
            return path if path.parent.resolve() == self.directory().resolve() else None
        except OSError:
            return None

    def exchange(self, path, command):
        path = self.validate(path)
        if path is None:
            return None
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(self.timeout)
        try:
            client.connect(str(path))
            client.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
            pending = bytearray()
            received = 0
            while received < 65536:
                chunk = client.recv(min(4096, 65536 - received))
                if not chunk:
                    return None
                received += len(chunk)
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, remaining = pending.partition(b"\n")
                    pending = bytearray(remaining)
                    reply = json.loads(line)
                    if not isinstance(reply, dict):
                        return None
                    # mpv can send events before the reply to this command.
                    if reply.get("request_id") == 1:
                        return reply
            return None
        except (OSError, ValueError, TypeError):
            return None
        finally:
            client.close()

    def property(self, path, name):
        reply = self.exchange(path, ["get_property", name])
        return reply.get("data") if reply and reply.get("error") == "success" else None

    def send(self, path, command):
        reply = self.exchange(path, command)
        return bool(reply and reply.get("error") == "success")

    def cleanup(self, value):
        path = self.validate(value)
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return path is not None
