"""Optional, session-owned MP4 wallpapers through mpvpaper."""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from spaces.pictures.mpv import MpvIpc
from spaces.pictures.storage import atomic_write


def requirements():
    missing = [name for name in ("mpvpaper", "ffmpeg") if not shutil.which(name)]
    if missing:
        raise ValueError("Install " + " and ".join(missing) + " to apply video wallpapers.")
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise ValueError("Video wallpapers currently require a Hyprland session.")


def local_video(value):
    path = Path(str(value))
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("The saved video wallpaper is missing. Apply it again.")
    return path


def still_frame(path):
    target = path.with_suffix(".poster.jpg")
    if target.is_file() and target.stat().st_size:
        return target
    temporary = target.with_name("." + target.stem + "-" + uuid.uuid4().hex + ".jpg")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(temporary),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
        )
        if result.returncode or not temporary.is_file() or not temporary.stat().st_size:
            raise ValueError("Could not extract a still image from this video wallpaper.")
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def apply(path, provider):
    from spaces.pictures import wallpaper_engine as engine
    from spaces.pictures.wallpaper import update_lock_background

    requirements()
    path = local_video(path).resolve()
    poster = still_frame(path)
    selection = uuid.uuid4().hex
    with engine.control_lock():
        previous = engine.read_setting()
        atomic_write(
            engine.config_dir() / "wallpaper.json",
            json.dumps(
                {
                    "mode": "video",
                    "video": str(path),
                    "provider": provider,
                    "selection": selection,
                    "image": poster.as_uri(),
                }
            )
            + "\n",
        )
    deadline = time.monotonic() + 45
    error = "Video wallpaper did not start. Ensure the desktop shell is running."
    while time.monotonic() < deadline:
        state = engine.read_state()
        if state.get("selection") == selection:
            if state.get("status") == "ready":
                update_lock_background(poster, engine.config_dir().parent)
                return {
                    "path": str(path),
                    "service": "mpvpaper",
                    "message": "Video wallpaper applied. Lock screen uses a still frame.",
                }
            if state.get("status") == "error":
                error = state.get("error") or error
                break
        if engine.read_setting().get("selection") != selection:
            raise ValueError("Wallpaper selection changed before Apply completed.")
        time.sleep(0.1)
    with engine.control_lock():
        if (
            previous.get("mode") not in {"video", "wallpaper_engine"}
            and engine.read_setting().get("selection") == selection
        ):
            atomic_write(engine.config_dir() / "wallpaper.json", json.dumps(previous) + "\n")
    if previous.get("mode") not in {"video", "wallpaper_engine"}:
        engine.wait_idle()
    raise ValueError(error)


class Player:
    def __init__(self):
        self.process = None
        self.token = None
        self.log = None
        self.socket = None
        self.ipc = MpvIpc("wallpaper")
        self.started = 0
        self.ready = False
        self.paused = False

    def stop(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        if self.socket:
            self.ipc.cleanup(self.socket)
            self.socket = None
        self.token = None
        self.ready = False
        self.paused = False

    def sync(self, runtime, request, setting):
        from spaces.pictures import wallpaper_engine as engine

        requirements()
        path = local_video(setting.get("video", ""))
        token = (setting["selection"], str(path))
        if token != self.token or runtime.daemon:
            runtime.stop()
        monitors = [m for m in request.get("monitors", []) if not m.get("disabled")]
        awake = any(m.get("dpmsStatus") is not False for m in monitors)
        if not self.process:
            if not awake:
                runtime.publish("waiting")
                return {"screens": []}
            layers = engine.hypr_query("layers")
            if any(
                s.get("namespace") == "mpvpaper"
                for m in layers.values()
                for s in m.get("levels", {}).get("0", [])
            ):
                raise ValueError(
                    "A separate mpvpaper session is running. Close it before applying."
                )
            self.socket = self.ipc.directory() / ("mpv-" + uuid.uuid4().hex[:16] + ".sock")
            self.log = (engine.state_file().parent / "video.log").open("w")
            atomic_write(runtime.ownership_file, json.dumps({"owner": runtime.owner}) + "\n")
            options = " ".join(
                [
                    "config=no",
                    "load-scripts=no",
                    "ytdl=no",
                    "input-terminal=no",
                    "audio=no",
                    "loop-file=inf",
                    "hwdec=auto",
                    "panscan=1",
                    "input-ipc-server=" + str(self.socket),
                ]
            )
            self.process = subprocess.Popen(
                ["mpvpaper", "-l", "background", "-o", options, "ALL", str(path)],
                env=dict(os.environ, DESKTOP_WALLPAPER_OWNER=runtime.owner),
                stdin=subprocess.DEVNULL,
                stdout=self.log,
                stderr=self.log,
                start_new_session=True,
                preexec_fn=engine.die_with_worker,
            )
            self.token = token
            self.started = time.monotonic()
            runtime.publish("starting")
        if self.process.poll() is not None:
            raise ValueError(
                "Video wallpaper playback stopped. Check video.log in the wallpaper runtime directory."
            )
        position = self.ipc.property(self.socket, "time-pos")
        if isinstance(position, (int, float)) and position > 0:
            self.ready = True
        layers = engine.hypr_query("layers")
        screens = [
            m["name"]
            for m in monitors
            if any(
                s.get("namespace") == "mpvpaper"
                and s.get("alpha", 1) > 0
                and s.get("w", 0) > 0
                and s.get("h", 0) > 0
                and ("pid" not in s or s["pid"] == self.process.pid)
                for s in layers.get(m["name"], {}).get("levels", {}).get("0", [])
            )
        ]
        if not self.ready or not screens:
            if not awake:
                self.started = time.monotonic()
            if awake and time.monotonic() - self.started > 30:
                raise ValueError("Video wallpaper did not produce visible frames.")
            return {"screens": []}
        # Measure the timeout from the last visible frame, not from launch, so a
        # long-running wallpaper survives a brief output change or hotplug.
        self.started = time.monotonic()
        paused = not awake or engine.visible_fullscreen(monitors, request.get("clients", []))
        if paused != self.paused:
            if not self.ipc.send(self.socket, ["set_property", "pause", paused]):
                raise ValueError("Could not control video wallpaper playback.")
            self.paused = paused
        runtime.publish("ready", screens=screens, paused=paused)
        return {"screens": screens, "paused": paused}
