"""One owned mpv window with native controls, captions, speed and resume support."""
import shutil
import subprocess
import tempfile
import uuid

from spaces.pictures.mpv import MpvIpc
from spaces.streaming.storage import StreamingError
from spaces.streaming.youtube import Commands, command_error, watch_url


class Player:
    def __init__(self, data):
        self.data = data
        self.ipc = MpvIpc("streaming", timeout=0.25)
        self.process = None
        self.path = ""
        self.identity = ""
        self.diagnostic = None

    def start(self, item, local="", audio=False, start=None):
        binary = shutil.which("mpv")
        if not binary:
            raise StreamingError("Install mpv to watch videos.")
        if start is not None and (type(start) not in (int, float) or not 0 <= start <= 7 * 24 * 3600):
            raise StreamingError("Invalid chapter time.")
        self.stop()
        resume = self.data / "resume"
        resume.mkdir(mode=0o700, parents=True, exist_ok=True)
        resume.chmod(0o700)
        self.path = str(self.ipc.directory() / ("mpv-" + uuid.uuid4().hex[:16] + ".sock"))
        command = [binary, "--terminal=yes", "--input-terminal=no", "--msg-level=all=error", "--force-window=" + ("no" if audio else "immediate"),
                   "--keep-open=no", "--idle=no", "--input-ipc-server=" + self.path,
                   "--audio-client-name=Streaming", "--title=Streaming", "--force-media-title=" + item["title"],
                   "--network-timeout=20",
                   "--ytdl-raw-options=ignore-config=,no-plugin-dirs=,no-remote-components=,no-playlist=",
                   "--save-position-on-quit=yes", "--watch-later-directory=" + str(resume)]
        if audio:
            command += ["--vid=no", "--ytdl-format=bestaudio/best"]
        if start is not None:
            command += ["--start=" + str(start)]
        if local:
            command += ["--ytdl=no"]
        try:
            self.diagnostic = tempfile.TemporaryFile()
            self.process = subprocess.Popen([*command, "--", local or watch_url(item["id"])],
                                            stdin=subprocess.DEVNULL, stdout=self.diagnostic, stderr=self.diagnostic, start_new_session=True)
        except OSError:
            self.ipc.cleanup(self.path)
            self.path = ""
            if self.diagnostic:
                self.diagnostic.close(); self.diagnostic = None
            raise StreamingError("Streaming could not start mpv.") from None
        self.identity = item["id"]
        return dict(playing=True, id=self.identity, paused=False, title=item["title"], connecting=True)

    def stop(self):
        if self.process:
            self.ipc.send(self.path, ["quit"])
            try:
                self.process.wait(timeout=0.7)
            except subprocess.TimeoutExpired:
                pass
            Commands.terminate(self.process)
            self.process = None
        if self.path:
            self.ipc.cleanup(self.path)
        if self.diagnostic:
            self.diagnostic.close(); self.diagnostic = None
        self.path = self.identity = ""
        return dict(playing=False, id="", paused=False)

    def status(self):
        if not self.process:
            return dict(playing=False, id="", paused=False)
        code = self.process.poll()
        if code is not None:
            diagnostic = ""
            if self.diagnostic:
                self.diagnostic.seek(0)
                diagnostic = self.diagnostic.read(65536).decode("utf-8", "replace")
            state = self.stop()
            if code:
                state["error"] = str(command_error(diagnostic))
            return state
        paused = self.ipc.property(self.path, "pause")
        position = self.ipc.property(self.path, "time-pos")
        return dict(playing=True, id=self.identity, paused=bool(paused), connecting=position is None,
                    position=position or 0,
                    duration=self.ipc.property(self.path, "duration") or 0)

    def pause(self):
        if not self.ipc.send(self.path, ["cycle", "pause"]):
            raise StreamingError("The player is still connecting. Try again shortly.")
        return self.status()
