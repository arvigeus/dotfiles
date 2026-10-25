"""One owned desktop mpv window, using the user's normal video configuration."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import uuid

from spaces.pictures.mpv import MpvIpc
from spaces.television.storage import TelevisionError, http_url


class TelevisionIpc(MpvIpc):
    def directory(self):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
        path = runtime / ("quickshell-television-" + str(os.getuid()))
        if len(os.fsencode(str(path / ("mpv-" + "a" * 16 + ".sock")))) >= 100:
            path = Path(tempfile.gettempdir()) / path.name
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise TelevisionError("Television's player directory is unavailable.")
        path.chmod(0o700)
        return path


class Player:
    def __init__(self):
        self.process = None
        self.ipc = TelevisionIpc("television", timeout=0.25)
        self.path = ""
        self.channel_id = ""
        self.stream_id = ""

    def start(self, channel, stream):
        mpv = shutil.which("mpv")
        if not mpv: raise TelevisionError("Install mpv to watch Television.")
        if not http_url(stream.get("url")): raise TelevisionError("This channel has no playable HTTP stream.")
        self.stop()
        self.path = str(self.ipc.directory() / ("mpv-" + uuid.uuid4().hex[:16] + ".sock"))
        command = [mpv, "--no-terminal", "--really-quiet", "--force-window=immediate",
            "--keep-open=no", "--idle=no", "--input-ipc-server=" + self.path,
            "--audio-client-name=Television", "--title=Television",
            "--force-media-title=" + channel["name"], "--cache=yes", "--cache-secs=20",
            "--demuxer-max-bytes=64MiB", "--demuxer-max-back-bytes=16MiB",
            "--cache-pause-initial=yes", "--cache-pause-wait=1", "--network-timeout=15"]
        if stream.get("user_agent"): command.append("--user-agent=" + stream["user_agent"])
        if stream.get("referrer"): command.append("--referrer=" + stream["referrer"])
        command.extend(["--", stream["url"]])
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            self.ipc.cleanup(self.path); self.path = ""
            raise TelevisionError("Television could not start mpv.") from None
        self.channel_id, self.stream_id = channel["id"], stream["id"]
        return dict(playing=True, channelId=self.channel_id, streamId=self.stream_id, paused=False, connecting=True)

    def stop(self):
        if self.process:
            # Standard mpv scripts can own thumbnail helpers. Release the entire
            # player group on replacement/close, including after its window exits.
            try: os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired: pass
            try: os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            self.process.wait(timeout=0.5)
            self.process = None
        if self.path: self.ipc.cleanup(self.path)
        self.path = self.channel_id = self.stream_id = ""
        return dict(playing=False, channelId="", streamId="", paused=False)

    def status(self):
        if not self.process: return self.stop()
        code = self.process.poll()
        if code is not None:
            state = self.stop()
            if code:
                state["error"] = "The channel could not be played or the stream ended. Try another stream; it may be unavailable or restricted in your region."
            return state
        paused = self.ipc.property(self.path, "pause")
        return dict(playing=True, channelId=self.channel_id, streamId=self.stream_id, paused=bool(paused),
                    connecting=paused is None or bool(self.ipc.property(self.path, "paused-for-cache")))

    def pause(self):
        if not self.process or not self.ipc.send(self.path, ["cycle", "pause"]):
            raise TelevisionError("The player is still connecting. Try again shortly.")
        return self.status()
