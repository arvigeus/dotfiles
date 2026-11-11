# Movies implementation

## Scope and integration

Movies uses the shared [Spaces lifecycle](../../../../../../../ARCHITECTURE.md#spaces).
TV Series reuses its browser, controls and workers with independent storage; see
[Series architecture](../series/ARCHITECTURE.md). Related anime may switch Spaces
only while the requesting page is shown. Players/browser targets launch through
Apps/UWSM; there is no embedded player.

## Presentation contract

Spaces use one cinematic dark palette in both desktop modes. `MovieStyle.qml`
owns near-black surfaces, white text and red actions; only typography follows the
shell. Shared `Movie*` controls apply it without restyling shell controls.
The host owns the edge-to-edge backdrop and single toolbar: pages provide
`backdropTarget` / `toolbarTarget`, bind toolbar visibility to activation and keep
the host's hide control reachable over popups. Do not add in-page Spaces links.

Catalogue tabs and toolbar actions share ordering across Spaces. Refresh retains
query/filters and displayed results while replacing metadata; Favorites rereads
saved state. My Library scans immediately, showing `LocalScan` only for unidentified
files. Review is modeless and defers while hidden. Only explicit Import publishes
a chosen match. Provider failures may retain saved catalogues with an offline
warning. Refresh must not cancel pending playback or unrelated tab requests.

Use cropped artwork and directional gradients for legibility without obscuring
the opposite side. Rating links retain full-color service marks, readable scores
and accessible names. `Catalogue.update()` reconciles identity-keyed JSON payloads
to preserve delegates, decoded images and scroll position; appended pages dedupe.
This differs from the role-based shell `ui/Models.js`. `ScrollArea` sizes to its
single child unless content dimensions are explicit.

`ActivityIndicator` derives concurrent tasks/progress from live request and job
snapshots. It animates only while active/pending and disappears while idle/hidden.
Canvas allocation/visibility changes must repaint it. Completed jobs belong to
activity panels; errors and recovery controls stay local. Embedded scan/download/
subtitle panels use `showStatus: false` to avoid duplicate routine notices.
Selection and tab generations prevent older replies from clearing newer loading
state or replacing content; `resetSelection()` clears all per-title requests.

`ProgressiveImage` owns cached preview/full layers. Backdrops retain their old
image for up to one second, then use the current poster until the new backdrop
is ready; failure retains the poster. Buffers reset on source changes. Pictures
previews clear the prior original immediately, and logos reset immediately.
Decode both layers for physical surface size.

## Artwork and response caches

`ImageCache.qml` coalesces duplicate artwork requests through `ArtworkCache.qml`.
Games, Pictures and Books use independent instances of this component with their
own cache namespaces. Movies, Series and Streaming share the default `ImageCache`
instance and its `movies` namespace. The cache lazily owns a Python
worker while image consumers exist. `image_cache.py` downloads to atomic files in
`$XDG_CACHE_HOME/quickshell/desktop/spaces/movies/artwork/` (normally
`~/.local/cache/quickshell/desktop/spaces/movies/artwork` in this configuration). SHA-256 filenames
contain no source URLs. Images are private (0600; directory 0700), limited to
20 MiB each, 256 MiB total and 2,000 files. Files expire after 30 days without a
disk-cache access; startup and downloads prune expired/oldest entries. Shell
restart retains complete cached files. The worker stops once its last image
consumer closes; only that worker's unfinished downloads are removed. Abandoned partial files are
pruned after a day. No personal library state lives in this directory.

`CachedImage.qml` cancels stale listeners when a delegate changes or dies, resolves
remote URLs to local cache files, and exposes a loading state covering both
fetching and decoding. Gallery spinners hide when that state finishes, including
failures. `CrossfadeImage` keeps source identity separate from the local cache URL.
Qt's decoded-image cache stays enabled; cover images decode at their rendered
width and output scale, capped by the component's requested resolution. Grid and
rail cache buffers retain nearby delegates for quick scroll reversals. An evicted
image can still be decoded from disk without another provider download.

`MediaService.fetch()` retains up to 80 successful metadata/detail/tab responses
for 15 minutes and coalesces identical pending reads. Keys use title identity,
so enriching a title record does not defeat the cache. Warm selections bypass the
90 ms hydration debounce used for rapidly browsing unseen titles. Explicit refresh clears
this memory cache and bypasses the backend metadata cache. Mutating operations,
local-file inventory, favorites and playback resolution always reach the worker.
The SQLite cache keeps provider responses across instance/shell restarts. Each
metadata worker start drops responses older than 30 days, except title records
used by a personal row (favorite, note, URL) or a local file: favorites and the
My Library view are built from them. Never clear title records as artwork-cache
maintenance.

## Workers and persistence

Provider logic stays here. `Worker.qml` owns one bounded JSON-lines Python process,
request IDs, startup queuing, deadlines and callbacks. `worker.py` writes each
response as one strict ASCII JSON line: undecodable file names arrive as escaped
surrogates, and NaN or an unserializable result settles only that request as an
error. Otherwise one bad value would stall the request or make QML fail every
pending one. Each backend has its own
process group so close releases ffprobe/ffmpeg children as well as the worker.
Quickshell 0.3.2 SIGKILLs a destroyed `Process`, so by default the backend runs
under `timeout 0 setpriv --pdeathsig TERM`: killing that supervisor on Space
close or shell reload delivers one SIGTERM, and the backend's `own_process_group`
cleanup still runs for every Space using this worker. Only the Pictures wallpaper
runtime sets `gracefulStop: false`, because its renderer handoff expects SIGKILL.
The torrent worker attempts bounded cleanup of only its own remote search jobs.
qBittorrent and user-launched players/browsers have independent lifetimes.
Ordinary imports publish complete files without replacing an existing destination;
cross-filesystem copies keep their source until publication and remove in-flight
temporary files on worker close. `local.publish()` and `place()` use a hard link,
or `renameat2(RENAME_NOREPLACE)` where the filesystem has none (vfat, exFAT);
subtitle writes and Music downloads use the same primitives. Each torrent job's
`torrent-locks/` file serializes imports across workers and is removed once the
job is imported or needs review. Interrupted indexing can be recovered through
My Library's Refresh scanner.
Scan includes the default library, completed downloads and configured extra
library roots, deduplicating overlapping locations before import. Extra roots
retain their existing directories and movie filenames; TV basenames still follow
the episode convention. qBittorrent renames its own files without relocating an
extra collection. Flat movie collections use per-video `.nfo` identities. Local
deletion in extra roots removes only the selected video and associated sidecars.
Scan walks visible folders only and skips samples, `-trailer` files and
Extras/Samples/Trailers folders. `movie.nfo` identifies only its folder's single
feature; `tvshow.nfo` may sit one level above Season folders.
Downloaded torrents belong to qBittorrent; closing Movies stops monitoring and
importing, and opening it resumes from saved job records. Do not stop that shared
client to close a Space.

Metadata requests may finish while hidden. Selection/browse generations reject
stale responses. Hidden views stop pagination, search polling and background
artwork presentation; active torrent imports keep their five-second monitor.
Idle hidden torrent monitoring stops. Favorites, IMDb/TMDB aliases, custom older
notes/URLs, local file records and torrent import records remain in
`$XDG_DATA_HOME/quickshell/desktop/spaces/movies/library.sqlite`. Metadata refresh
preserves personal records.

SQLite uses short transactions and per-request connections.
Cache entries in the database are included with personal records; image caches,
large media, sockets and generated OpenSubtitles sessions are not portable inputs.

## Private configuration and provisioning

Private files are stored alongside their owning Space under the current shell's
XDG namespace:

- `~/.config/quickshell/desktop/spaces/movies/media.json`: metadata API keys, named playback
  templates, region, player argv, optional anime adapters and OpenSubtitles account.
  It may link into a private checkout. `paths.media_config()` reads it through
  `integrations/private.py` (regular file, at most 64 KiB, non-blocking) and,
  like `torrents.json`, refuses it unless owner-only when it holds API keys, the
  OpenSubtitles password or a player command.
- `~/.config/quickshell/desktop/spaces/movies/media-ui.ini`: view preferences.
  `Settings.value()` returns INI booleans as `"true"`/`"false"` strings once read
  from disk, so restore them by comparing with `"true"`.
- `~/.local/share/quickshell/desktop/spaces/movies/library.sqlite`: personal/library state.

`~/.config/quickshell/desktop/integrations/media-library.json` is user-owned and
independent of private provider settings. Only `media-library.json.example` is a
copied `files/home/` asset; the active file is never generated or reconciled by
dotfiles. Its object has `movies` and `series` arrays of existing absolute directory
paths (`~` and `$HOME` expand). For example:

```json
{"movies": ["~/Videos/Ghibli"], "series": []}
```

The workers reread it on scans/imports; missing configuration means no extra roots.
Invalid JSON, invalid list values or unavailable directories fail with a visible
error before scanning. Reads are bounded regular-file reads without symlink
following. No credentials belong here.

Examples are secret-free and do not get copied over user configuration. Keys remain in Python;
QML sees provider labels and resolved playback targets. Worker stderr is reduced
to one generic diagnostic per two-second burst rather than publishing provider
exceptions or URLs.

All Spaces read one qBittorrent connection from
`~/.config/quickshell/desktop/integrations/torrents.json`. See [shared integration settings](../../integrations/ARCHITECTURE.md#qbittorrent)
for authentication. Torrent jobs, libraries and worker
lifetimes remain independent per Space.

## Generated subtitles

The shared `Subtitles.qml` panel includes one caption icon beside the selected
local file, switching to a cancel action while that file's SRT job runs. Tooltips
expose the model/language from Capture preferences. `capture/FileSpeech.qml`
uses the retained capture socket owner; generation does not require an
OpenSubtitles account and continues while browsing another title/episode or after
closing the Space. Other paths cannot cancel the active job. Completion refreshes
the selected inventory, and reopening a title reads any completed sidecar.
The same panel serves Movies and TV Series; episode filenames determine their
own output names. See the shell's [speech architecture](../../../../../../../ARCHITECTURE.md)
for file limits, frozen options, publication and cancellation guarantees.
