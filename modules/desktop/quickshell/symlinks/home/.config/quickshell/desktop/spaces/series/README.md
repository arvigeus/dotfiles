# TV Series

Open **Spaces → TV Series** for discovery, search, favorites, anime, cast,
trailers, seasons and episodes. It shares Movies’ cinematic appearance and
supports provider playback, local episodes, subtitles and qBittorrent imports.

Configure `~/.config/quickshell/desktop/spaces/series/media.json` using the
[media example](../movies/media.example.json). A TMDB key enables discovery;
OMDb is an optional search/detail fallback. Playback templates use `series_url`
and can include `{season}` and `{episode}`.

For downloads, configure the shared `~/.config/quickshell/desktop/integrations/torrents.json`
using the [qBittorrent example](../../integrations/torrents.example.json). Enable its Web UI
and search plugins. **Local → Scan** organizes existing episodes under
`Videos/Series` (or your XDG Videos directory). Held local deletion removes the
whole season folder; torrent deletion removes the associated torrent and all its
files, including other episodes in a season pack.

X and Escape hide Series. Its X in Spaces closes it; accepted qBittorrent downloads
continue. Movies and Series remember their own layout, favorites and navigation.

Media files and mounts need their
own backup. See [architecture](ARCHITECTURE.md) for storage and recovery details.
