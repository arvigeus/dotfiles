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
and search plugins. **My Library → Refresh** scans existing episodes under
`Videos/Series` (or your XDG Videos directory) and opens a lightbox for unidentified
files. Hidden folders, samples and trailers are skipped. Select a catalogue match,
check the season and episode (a combined file can use `1-2`), then choose **Import**.
Anime episode numbers without a season default to season 1. Held local deletion removes the
whole season folder; torrent deletion removes the associated torrent and all its
files, including other episodes in a season pack.

Episode files use `S01E01 - Episode title.mkv` inside the series/season folder.
For extra library folders, remove `.example` from
`~/.config/quickshell/desktop/integrations/media-library.json.example` and fill in
the `series` list. These folders stay in place; local deletion removes the selected
file and sidecars.

Local media’s **Subtitles** section can generate `filename.srt` beside the video.
The caption icon uses the Capture menu’s speech model and spoken language;
missing models download on first use. Generation preserves the original language
and existing subtitles, and continues when the Space closes.

X and Escape hide Series. Its X in Spaces closes it; accepted qBittorrent downloads
continue. Movies and Series remember their own layout, favorites and navigation.

Media files and mounts need their
own backup. See [architecture](ARCHITECTURE.md) for storage and recovery details.
