# Movies

Open **Spaces → Movies** for discovery, search, favorites, anime, cast, trailers,
provider playback, local files, subtitles and qBittorrent search/import.

Configure `~/.config/quickshell/desktop/spaces/movies/media.json` using
[media.example.json](media.example.json); keep it mode 0600 once it holds keys,
the OpenSubtitles account or a player command, or Movies refuses it. A TMDB key
enables discovery; OMDb is an optional search/detail fallback. Playback providers
and OpenSubtitles are optional.
Player/browser windows run independently.

For downloads, enable qBittorrent’s Web UI and search plugins; configure its
shared connection in `~/.config/quickshell/desktop/integrations/torrents.json` using
[torrents.example.json](../../integrations/torrents.example.json); keep it mode 0600 when it
holds a password or API key. Downloads use `Videos/Movies`
(or your XDG Videos directory). **My Library → Refresh** scans existing files and opens a lightbox for unidentified titles.
Hidden folders, samples and trailers are skipped. Held deletion permanently removes
the movie folder, or the associated torrent and all its downloaded files.

For additional collections, remove `.example` from
`~/.config/quickshell/desktop/integrations/media-library.json.example` and fill in
the `movies` list. These files stay in their existing folders; local deletion
removes the selected file and sidecars rather than the collection.

Local media’s **Subtitles** section can generate `filename.srt` beside the video.
The caption icon uses the Capture menu’s speech model and spoken language;
missing models download on first use. Generation preserves the original language
and existing subtitles, and continues when the Space closes.

X and Escape hide Movies; the X beside its running entry in Spaces closes it.
Downloads accepted by qBittorrent continue; reopening Movies resumes indexing.

Media files themselves need a separate backup or mount at their original paths.
See [architecture](ARCHITECTURE.md) for configuration and storage details.
