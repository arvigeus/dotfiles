#!/usr/bin/env python3
"""Isolated executable fixtures for the real wallpaper worker and QML actions."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(os.environ["ENGINE_FIXTURE_ROOT"])
command = Path(sys.argv[0]).name
pidfile = root / "pids.json"


def running():
    try:
        pid = json.loads(pidfile.read_text())[0]
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, ValueError, IndexError):
        return False


if command == "wallpiperd":
    # Make the independent-session guard exercise the actual daemon name.
    ctypes.CDLL(None).prctl(15, b"wallpiperd", 0, 0, 0)
    (root / "controller.pid").write_text(str(os.getppid()))
    native_path = Path(os.environ["WALLPIPER_WE_EXE"]).parent / "config.json"
    native = json.loads(native_path.read_text())
    with (root / "native-starts.jsonl").open("a") as stream:
        stream.write(json.dumps(native["steamuser"]["general"]["user"]) + "\n")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True
    )
    pidfile.write_text(json.dumps([os.getpid(), child.pid]))
    with (root / "all-pids.jsonl").open("a") as stream:
        stream.write(json.dumps([os.getpid(), child.pid]) + "\n")
    runtime = Path(os.environ["WALLPIPER_TEMP_DIR"])
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "wallpiper-renderer-pid").write_text(str(child.pid))
    time.sleep(300)
elif command == "hyprctl":
    subject = sys.argv[1]
    if subject == "monitors":
        print(json.dumps([{"name": "TEST", "id": 0, "activeWorkspace": {"id": 1}}]))
    elif subject == "clients":
        print("[]")
    elif subject == "layers":
        print(
            json.dumps(
                {
                    "TEST": {
                        "levels": {
                            "0": [
                                {
                                    "namespace": "wallpiper-portal-hyprland",
                                    "w": 1920,
                                    "h": 1080,
                                    "alpha": 0 if (root / "require-first-set").exists() else 1,
                                    "address": (root / "surface-address").read_text()
                                    if (root / "surface-address").exists()
                                    else "fixture",
                                }
                            ]
                            if running() and not (root / "hide-surfaces").exists()
                            else []
                        }
                    }
                }
            )
        )
elif command == "wallpiperctl":
    if not running():
        sys.exit("fixture daemon has not started")
    with (root / "commands.jsonl").open("a") as stream:
        stream.write(json.dumps({"command": sys.argv[1], "args": sys.argv[2:]}) + "\n")
    if sys.argv[1] == "set":
        (root / "require-first-set").unlink(missing_ok=True)
        project = Path(sys.argv[2])
        metadata = json.loads(project.read_text())
        asset = project.parent / metadata.get("file", "scene.json")
        if metadata.get("type") == "scene":
            asset = asset.with_suffix(".pkg")
        config = Path(os.environ["WALLPIPER_WE_EXE"]).parent / "config.json"
        try:
            native = json.loads(config.read_text())
        except FileNotFoundError:
            native = {}
        slots = (
            native.setdefault("steamuser", {})
            .setdefault("general", {})
            .setdefault("wallpaperconfig", {})
            .setdefault("selectedwallpapers", {})
        )
        slots["Monitor" + sys.argv[3]] = {"file": "Z:" + str(asset)}
        config.write_text(json.dumps(native))
        if os.environ.get("ENGINE_FIXTURE_CRASH"):
            # Crash handlers can leave the tracked process alive with a dialog.
            (config.parent / "wallpaper64_fixture.mdmp").write_bytes(b"crash")
elif command == "steam":
    (root / "steam.json").write_text(json.dumps(sys.argv[1:]))
elif command == "engine-fixture-control":
    if sys.argv[1] == "crash":
        os.kill(int((root / "controller.pid").read_text()), signal.SIGKILL)
    elif sys.argv[1] == "hide":
        (root / "hide-surfaces").touch()
    elif sys.argv[1] == "show":
        (root / "hide-surfaces").unlink()
    else:
        sys.exit("unknown fixture action")
else:
    sys.exit("unknown fixture executable")
