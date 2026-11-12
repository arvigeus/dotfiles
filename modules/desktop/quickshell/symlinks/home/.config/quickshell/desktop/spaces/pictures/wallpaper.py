"""Portable still background shared by desktop and lock screen."""

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from spaces.pictures.storage import atomic_write


def current_image():
    value = Path(os.environ.get('XDG_DATA_HOME', '~/.local/share')).expanduser()
    root = value if value.is_absolute() else Path.home() / '.local/share'
    return root / 'quickshell/desktop/spaces/pictures/current-wallpaper'


def lock_readable(path):
    """hyprlock decodes JPEG, PNG and WebP, but not GIF or AVIF previews."""
    with path.open('rb') as stream:
        header = stream.read(12)
    return header.startswith((b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n')) or (
        header[:4] == b'RIFF' and header[8:12] == b'WEBP'
    )


def update_lock_background(image):
    target = current_image()
    image = Path(image).resolve(strict=True)
    if image == target.resolve():
        return
    if lock_readable(image) or not shutil.which('ffmpeg'):
        atomic_write(target, image.read_bytes())
        return
    # Publish the first frame as PNG; the desktop can show the original anyway.
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    frame = target.with_name(f'.{target.name}-{uuid.uuid4().hex}.png')
    try:
        result = subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(image)]
            + ['-frames:v', '1', str(frame)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
        )
        if result.returncode or not frame.is_file() or not frame.stat().st_size:
            atomic_write(target, image.read_bytes())
            return
        os.chmod(frame, 0o600)
        os.replace(frame, target)
    except (OSError, subprocess.SubprocessError):
        atomic_write(target, image.read_bytes())
    finally:
        frame.unlink(missing_ok=True)
