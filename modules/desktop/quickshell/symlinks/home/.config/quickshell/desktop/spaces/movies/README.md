# Movies

Open **Spaces → Movies** for discovery, search, favorites, anime, cast, trailers,
provider playback, local files, subtitles and qBittorrent search/import.

Configure `~/.config/quickshell/desktop/spaces/movies/media.json` using
[media.example.json](media.example.json). A TMDB key enables discovery; OMDb is an
optional search/detail fallback. Playback providers and OpenSubtitles are optional.
Player/browser windows run independently.

For downloads, enable qBittorrent’s Web UI and search plugins; configure its
shared connection in `~/.config/quickshell/desktop/integrations/torrents.json` using
[torrents.example.json](../../integrations/torrents.example.json). Downloads use `Videos/Movies`
(or your XDG Videos directory). **Local → Scan** can organize existing files;
review uncertain matches before importing. Held deletion permanently removes the
movie folder, or the associated torrent and all its downloaded files.

X and Escape hide Movies; the X beside its running entry in Spaces closes it.
Downloads accepted by qBittorrent continue; reopening Movies resumes indexing.

Media files themselves need a separate backup or mount at their original paths.
See [architecture](ARCHITECTURE.md) for configuration and storage details.
