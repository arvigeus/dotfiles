"""Storage namespace selected once by each owned media worker."""
import os
from pathlib import Path

SPACE = os.environ.get("QUICKSHELL_MEDIA_SPACE", "movies")
if SPACE not in ("movies", "series", "games"):
    raise ValueError("Unknown media Space.")
ROOT = "quickshell/desktop/spaces/" + SPACE
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / ROOT
DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / ROOT
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / ROOT
