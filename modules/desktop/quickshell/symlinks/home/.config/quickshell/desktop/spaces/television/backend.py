"""Television catalogue reads, portable local favorites and an owned mpv window."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spaces.movies.worker import own_process_group, serve
from spaces.television.catalogue import Catalogue, stream_record, text
from spaces.television.player import Player
from spaces.television.storage import TelevisionError, atomic_json, http_url, read_json

ROOT = "quickshell/desktop/spaces/television"


def clean_settings(settings):
    if (not isinstance(settings, dict) or any(not isinstance(settings.get(key, ""), str) for key in ("country", "language", "category"))
            or not isinstance(settings.get("streams", {}), dict)):
        raise TelevisionError("Invalid Television preferences; the existing file was preserved.")
    choices = settings.get("streams", {})
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in choices.items()):
        raise TelevisionError("Invalid stream preferences; the existing file was preserved.")
    return dict(country=text(settings.get("country"), 2), language=text(settings.get("language"), 10),
                category=text(settings.get("category"), 100), streams=dict(list(choices.items())[:1000]))


def clean_channel(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"] or not isinstance(raw.get("name"), str) or not raw["name"].strip():
        raise TelevisionError("An invalid favorite channel was found; existing favorites were preserved.")
    streams = raw.get("streams")
    if not isinstance(streams, list) or not streams or len(streams) > 512:
        raise TelevisionError("A favorite has invalid streams; existing favorites were preserved.")
    cleaned = []
    for value in streams:
        if not isinstance(value, dict): raise TelevisionError("A favorite stream is invalid.")
        item = stream_record(value, {"name": value.get("feed", "")})
        if item is None: raise TelevisionError("A favorite stream must be an HTTP address.")
        cleaned.append(item)
    def strings(key):
        values = raw.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise TelevisionError("A favorite channel has invalid metadata.")
        return values[:100]
    return dict(id=raw["id"][:500], name=raw["name"].strip()[:500], aliases=strings("aliases"),
                country=text(raw.get("country"), 2), countryName=text(raw.get("countryName")),
                languages=strings("languages"), languageNames=strings("languageNames"),
                categories=strings("categories"), categoryNames=strings("categoryNames"),
                website=http_url(raw.get("website")), streams=cleaned)


class TelevisionBackend:
    def __init__(self, config=None, data=None, cache=None, fetch=None):
        self.config = Path(config) if config else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / ROOT
        self.data = Path(data) if data else Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / ROOT
        self.cache = Path(cache) if cache else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / ROOT
        self.catalogue = Catalogue(self.cache, **({"fetch": fetch} if fetch else {}))
        self.player = Player()

    def favorites(self):
        values = read_json(self.data / "favorites.json", [])
        if not isinstance(values, list) or len(values) > 1000:
            raise TelevisionError("Television favorites must be a list of up to 1,000 channels.")
        return [clean_channel(value) for value in values]

    def init(self):
        settings = clean_settings(read_json(self.config / "television-ui.json", {}))
        favorites = self.favorites()
        if not (self.config / "television-ui.json").exists(): atomic_json(self.config / "television-ui.json", settings)
        if not (self.data / "favorites.json").exists(): atomic_json(self.data / "favorites.json", favorites)
        return dict(settings=settings, favorites=favorites, **self.catalogue.summary())

    def handle(self, request):
        op = request["op"]
        if op == "init": return self.init()
        if op == "refresh": return self.catalogue.refresh()
        if op == "browse": return self.catalogue.browse(request, self.favorites())
        if op == "settings-save":
            atomic_json(self.config / "television-ui.json", clean_settings(request.get("settings")))
            return True
        if op == "favorite":
            channel = clean_channel(request.get("channel"))
            favorites = [item for item in self.favorites() if item["id"] != channel["id"]]
            if request.get("value"):
                if len(favorites) >= 1000: raise TelevisionError("Television supports up to 1,000 favorites.")
                favorites.insert(0, channel)
            atomic_json(self.data / "favorites.json", favorites)
            return favorites
        if op == "play":
            identity = request.get("channelId")
            channel = next((row for row in self.catalogue.snapshot.get("channels", []) if row["id"] == identity), None)
            if channel is None: channel = next((row for row in self.favorites() if row["id"] == identity), None)
            if channel is None: raise TelevisionError("This channel is no longer available. Refresh the directory.")
            channel = clean_channel(channel)
            stream = next((value for value in channel["streams"] if value["id"] == request.get("streamId")), None)
            if stream is None: raise TelevisionError("The selected stream changed. Select it again before playing.")
            return self.player.start(channel, stream)
        if op == "status": return self.player.status()
        if op == "stop": return self.player.stop()
        if op == "pause": return self.player.pause()
        raise TelevisionError("Unknown Television operation.")


def main():
    backend = TelevisionBackend()
    own_process_group(backend.player.stop)
    try:
        serve(backend.handle, errors=(TelevisionError, OSError), latest=("browse",),
              controls=("init", "settings-save", "favorite", "play", "status", "pause", "stop"))
    finally: backend.player.stop()


if __name__ == "__main__": main()
