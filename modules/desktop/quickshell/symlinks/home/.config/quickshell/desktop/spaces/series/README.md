# TV Series

Open **Spaces → TV Series** for discovery, search, favorites, anime, cast,
trailers, seasons and episodes. It shares Movies’ cinematic appearance and
supports provider playback, local episodes, subtitles and qBittorrent imports.

Configure `~/.config/quickshell/desktop/spaces/series/media.json` using the
[media example](../movies/media.example.json); keep it mode 0600 once it holds
keys, the OpenSubtitles account or a player command, or Series refuses it. It is
separate from the Movies file, so copy the keys you need. A TMDB key enables
discovery; OMDb is an optional search/detail fallback. Playback templates use
`series_url`; with `{season}`/`{episode}`, Watch online opens Episodes to pick
one, otherwise it opens the series page.

For downloads, configure the shared `~/.config/quickshell/desktop/integrations/torrents.json`
using the [qBittorrent example](../../integrations/torrents.example.json) (mode 0600 when it
holds a password or API key). Enable its Web UI
and search plugins. **Local → Scan** organizes existing episodes under
`Videos/Series` (or your XDG Videos directory), skipping hidden folders, samples
and trailers. Held local deletion removes the
whole season folder; torrent deletion removes the associated torrent and all its
files, including other episodes in a season pack.

X and Escape hide Series. Its X in Spaces closes it; accepted qBittorrent downloads
continue. Movies and Series remember their own layout, favorites and navigation.

Media files and mounts need their
own backup. See [architecture](ARCHITECTURE.md) for storage and recovery details.
