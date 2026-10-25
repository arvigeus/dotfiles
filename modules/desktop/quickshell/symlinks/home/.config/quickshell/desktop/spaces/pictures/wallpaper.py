"""Portable still background shared by desktop and lock screen."""
import os
from pathlib import Path
from spaces.pictures.storage import atomic_write


def current_image():
    value = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    root = value if value.is_absolute() else Path.home() / ".local/share"
    return root / "quickshell/desktop/spaces/pictures/current-wallpaper"


def update_lock_background(image, config=None):
    target = current_image()
    image = Path(image).resolve(strict=True)
    if image != target.resolve():
        atomic_write(target, image.read_bytes())
