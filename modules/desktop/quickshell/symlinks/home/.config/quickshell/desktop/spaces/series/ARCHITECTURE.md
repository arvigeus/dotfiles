# TV Series implementation

## Boundaries and presentation

`Main.qml` instantiates the existing Movies `MediaBrowser` with `kind: "tv"`.
The Movies controls, dark/red palette, background gradients, artwork transitions,
rail/grid layout and toolbar are the presentation source of truth. The initial
layout is the same poster rail as Movies; each instance saves its own choice.
Do not import the legacy Series theme or adapt these controls to the shell palette.
See the [Movies architecture](../movies/ARCHITECTURE.md) for the shared UI,
provider features, caches and worker transport.

`SpaceState` registers Series as `series`; `SpaceHost` independently owns its lazy
loader. The drawer derives availability from that registry. Open/hide/restore,
Escape priority, fullscreen geometry, focus and explicit close use the same host
contract as Movies. Related anime can navigate between the two retained instances.
There is no independent Series lifecycle manager.

Series retains discovery/search/filters, anime, favorites, related titles,
cast/filmography, trailers, provider links, local scanning/playback, subtitles,
season/episode torrent search and import monitoring. Episodes use the Movies
controls and per-episode local-file actions. There is no embedded player.
All TV behaviour lives in `MediaBrowser`'s `kind === "tv"` paths; a Series-only
component would have to reach into its selection generations and local state.

## Seasons and episodes

The page's `season` string is the chosen season and the single input to episode
loading, local episode rows and season torrent search; the season picker only
reflects it. `setSeasons()` is the one place seasons are assigned: values become
strings, ordered numerically with TMDB's season 0 last and labelled Specials, so
the default is the first regular season. Local mode lists the local files'
seasons; otherwise the provider list wins, with local seasons standing in until
it arrives. A chosen season survives list changes (imports, deletions, refresh)
while it still exists; otherwise the first season is chosen and an open Episodes
tab reloads, so the rows always match the picker. Qt 6.12 resets a ComboBox
index whenever its model changes, so the picker re-syncs from `season` on model
changes instead of binding `currentIndex`.

Season controls are disabled until seasons exist. Selection and episode generations
reject superseded responses; clearing a title invalidates its episode catalogue.
Refresh title bypasses the cached season list (one hour) and reloads the open
season. Watch online opens Episodes only for a provider whose `series_url` has
`{season}`/`{episode}`; others open their series page. An episode click follows
the chosen watch option: an online provider streams even episodes kept locally,
while Local plays the file or falls back to the title's saved URL, then the
provider. `providerIndex` derives from the watch button's `watchIndex`, so a
request always names the provider the button shows after a selection or Local
availability change. Local episode rows follow the library's season/episode
order, including files indexed under an older TMDB alias.

## Workers and storage

The shared `Worker` passes `QUICKSHELL_MEDIA_SPACE=series` to each Series metadata,
torrent and subtitle process. `movies/paths.py` validates this namespace once per
process. All three backends, including catalogue lookups inside the torrent
backend, use the same Series metadata config/data paths. All Spaces read the
single qBittorrent connection in `integrations/torrents.json`; job records and
tags remain scoped to their owning Space. Movies retains its existing paths.
No worker changes process-global environment from a request. Closing one instance
releases only its owned workers; the qBittorrent client and external players remain
independent. Hidden idle job polling stops; active imports continue intentionally.

User configuration and state:

- `~/.config/quickshell/desktop/spaces/series/media.json`: API keys, region,
  playback providers/player, optional anime adapters and OpenSubtitles account.
- `~/.config/quickshell/desktop/spaces/series/media-ui.ini`: layout preference.
- `~/.local/share/quickshell/desktop/spaces/series/library.sqlite`: favorites,
  aliases, metadata cache, local-file inventory, subtitle records and import jobs.

Metadata cache entries live in the Series database; OpenSubtitles login tokens
stay in memory. The shared qBittorrent connection is declared once as
`~/.config/quickshell/desktop/integrations/torrents.json`; see
[integration ownership](../../integrations/ARCHITECTURE.md#qbittorrent).
Artwork intentionally uses the existing shared `ImageCache` singleton and bounded Movies
artwork directory: overlapping poster/gallery consumers share downloads, and closing
one Space cannot stop the other’s artwork worker. It stops when the final consumer
is destroyed. No credentials or personal records belong to this image cache.

Series uses `series` qBittorrent tags. Imports write `tvshow.nfo` beside the
Season folders and a per-episode `.release.nfo` with `seriesrelease` metadata;
JSON media sidecars belong only to non-video kinds. Provider identifiers and
personal record formats stay stable. Payloads use the XDG Videos `Series` directory.

## Provisioning and recovery

Series uses the existing quickshell, mpv, ffmpeg, qBittorrent and browser/XDG module
dependencies; no additional package is needed. Provider templates need `series_url`.
Remote qBittorrent paths must also exist on this machine. Expired API credentials
or account sessions require renewal in the Series configuration.

## Validation

Use the repository unittest discovery command. `test_series_space.py` uses the real
host, drawer, page and worker transport over isolated cached metadata: drawer open,
seasons, episode switching, compact rating pairs, independent preferences/favorites,
hide/restore, explicit close and fresh reopen. Its season fixtures cover Specials
ordering, a chosen season kept across a refresh that adds a season, local seasons
replacing a loading provider list without stale rows, and watch-option routing
through a worker that rejects every playback request, so nothing is launched.
`test_series_media.py` exercises the Series environment across all three backends,
episode imports, local/provider playback resolution, refresh bypassing cached
seasons/episodes and alias-independent local episode order. Existing
Movies/provider/worker tests cover the reused code.
Real playback/download completion and multi-monitor focus/hotplug require
interactive validation.
