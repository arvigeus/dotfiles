# Movies implementation

## Scope and integration

Movies runs in the shared Spaces host; see its
[lifecycle](../../../../../../../ARCHITECTURE.md#spaces). A related anime of the
other kind opens in TV Series (or Movies) only while this page is shown; a lookup
that finishes after the page was hidden is dropped without an error.

Movies retains the established catalogue/detail and rail/grid workflows.
Browser targets
use xdg-open through Apps/UWSM; custom old shell browser commands are not imported.
TV Series reuses this browser and presentation with its own workers and storage;
see [Series architecture](../series/ARCHITECTURE.md). There is no embedded player.
The provider/library implementation retains legacy record formats and aliases;
Provider IDs and record formats remain stable across both applications.

## Presentation contract

Spaces are immersive destinations, with no Spaces navigation button inside an
opened module. Keep the host's top-left hide control reachable over popups.
The page's `backdropTarget` points to the host's edge-to-edge background layer;
only the foreground content uses the host's padding and header allowance.
The page's single toolbar is reparented into `toolbarTarget`, beside the hide
control and a separator, without a duplicate Space title. Bind that toolbar's
visibility to page activation, since its visual parent is the host. Drawer entries
use only their close X to indicate a running instance.
Do not put the backdrop back inside that inset content area.

Catalogue Spaces use underlined `MovieTab` navigation: My Library, Browse and
Favorites where supported. The right-hand actions start with Search, Filters and
Refresh, followed by transfer/activity and layout controls where applicable.
Movies, TV Series and Books use Refresh in My Library to toggle the existing
scan/review panel; scanning remains an explicit action with an optional path.
Its default-path guidance lives in the path input's tooltip and accessible
description. Browse Refresh bypasses the saved catalogue response while retaining
the query and filters; Favorites Refresh rereads saved favorites. Movies and
Series skip the initial snapshot on explicit refresh, retaining their displayed
results until the current request settles; provider failures can still return
the backend's saved catalogue with an offline warning.

Movies deliberately has one cinematic dark appearance in both desktop modes:
near-black surfaces, white text, saturated red primary actions, ghost secondary
controls and red underlines on active tabs. `MovieStyle.qml` owns these colors;
only typography follows the desktop. Local `Movie*` controls apply this palette
to popups, inputs, cards and scrollbars without changing shared shell controls.
Do not reintroduce gray button/tab fills or light/dark variants to match the shell.
Artwork uses full-size cropped images with directional dark gradients for text
legibility. The moderate reading scrim follows the detail column: left in rail
mode, right in grid mode; the artwork remains visible beneath it. `MovieText` adds a subtle dark shadow. Keep the artwork visible
on the opposite side rather than flattening the whole background.
Rating links use the bundled full-color service marks in `ratings/`, including
score-dependent Rotten Tomatoes and audience marks. Logo/score pairs use intrinsic
row widths and a fixed six-pixel gap rather than a stretching layout. Preserve accessible service
names and scores; do not replace the marks with text-only badges or tint them.

`ActivityIndicator.qml` provides the toolbar activity control shared by every
Space. Pages supply keyed pending tasks and their job snapshots; simultaneous
work appears on separate tooltip lines, including job phase and progress. The
red ring animates only while work is pending and the page is active. The
indicator and tooltip disappear completely when idle or hidden; there is no
completion marker or retained last-action text. Completed, failed, cancelled
and reviewable jobs remain in the existing notification/activity panels.
The cached ring repaints after canvas allocation, sizing or visibility changes,
including asynchronous page creation and retained-page restoration.

Every Space reuses this directory's `Movie*` controls, `ScrollArea` and
`Catalogue.js`. `ScrollArea` steps mouse wheels like the shell's drawers and
sizes its content from its single declared child unless the page sets
`contentWidth`/`contentHeight`. `Catalogue.update()` keeps catalogue rows
(`key` plus a JSON `payload`) keyed by identity, so delegates, decoded artwork
and scroll position survive refreshes; appended pages add only unseen keys. It
stays separate from the shell's role-based `ui/Models.js`.

Progress derives directly from pending tasks and job snapshots; the indicator
does not collect operation history. Errors, validation and actions requiring
intervention stay beside their controls.
Music's metadata dialog retains failed/partial saves and unsaved-edit warnings
inline. Embedded download, scan and subtitle panels use `showStatus: false`
instead of rendering a second routine status line. Their standalone presentation
remains self-contained.
Explicit transfer/review panels retain their detailed controls and job rows.

Movies covers catalogue loading, selected-movie metadata, personal state,
local-file inventory, backdrop/logo decoding and the visible tab's requests.
The image gallery uses its own spinner while hiding the toolbar animation.
Activity descriptions appear in the tooltip and accessible name. An extra-request generation prevents
an earlier tab's response from clearing a later tab's loading state or replacing
its content. Selection generations protect personal state and file inventory too.
`resetSelection()` is the one place that abandons a selection's requests, so it
also clears every per-title loading flag. Refresh supersedes only metadata
hydration; pending playback and tab requests still settle.

`tests/test_space_activity.py` exercises concurrent tasks/jobs, live tooltip
updates, progress, hidden/idle disappearance and rendered spinner contrast against
the native UI. The Series integration test captures the actual toolbar ring
during a delayed episode request and after hide/restore, checking red pixels
rather than only its loading flags. Space integration tests cover each toolbar
and verify routine notices no longer consume content rows.

Backdrops allow the previous movie's image a 1 second grace period. A ready
replacement crossfades directly; otherwise the old image yields to the current
movie's poster, cropped to fill the screen. Poster decoding starts during that
grace period, and its buffer resets on URL changes to prevent stale poster reuse.
The real backdrop replaces the poster when ready; failures retain the poster.
Only backdrops opt into this deadline. Logos reset immediately on source changes.
`ProgressiveImage.qml` owns the two cached image layers and preview/full-source
handoff shared by backdrops and the Pictures detail preview. Pictures clears the
previous original immediately on source changes; backdrops retain their bounded
grace period. Both layers decode for the physical surface size.

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

Examples are secret-free and do not get copied over user configuration. Keys remain in Python;
QML sees provider labels and resolved playback targets. Worker stderr is reduced
to one generic diagnostic per two-second burst rather than publishing provider
exceptions or URLs.

All Spaces read one qBittorrent connection from
`~/.config/quickshell/desktop/integrations/torrents.json`. See [shared integration settings](../../integrations/ARCHITECTURE.md#qbittorrent)
for authentication. Torrent jobs, libraries and worker
lifetimes remain independent per Space.

## Validation

Use the repository unittest discovery entry point. `test_movies_media.py`,
`test_movies_torrents.py` and `test_movies_subtitles.py` cover provider failover,
identity, favorites, subtitle operations and movie import/data preservation.
`test_movies_space.py` runs the production page, workers and SpaceHost over an
isolated database and an offscreen native-window substitute. It covers lazy load,
hide/restore identity, popup/input Escape priority, top-left hiding over the image
gallery, drawer close, full-row pointer hover including its independent X,
persisted favorites and fresh reopen. Artwork fixtures verify gallery completion,
worker restart/delegate recreation without repeat downloads, and scaled thumbnail
decoding. `test_movies_cache.py` exercises persistent hits, request coalescing,
retention/LRU limits and interrupted downloads. Delayed worker
responses also exercise tab loading, one visible spinner until inventory and
primary images finish, and stale-response rejection. Backdrop fixtures cover
fast transitions, poster fallback, failed images and superseded downloads.
Native Wayland smoke checks cover real fullscreen geometry and opening/closing
in dark and light modes. `test_movies_worker.py` checks subprocess cleanup while
retaining a detached application, including when the QML `Worker` is destroyed,
strict per-request responses and single stderr diagnostics. `test_movies_import.py`
simulates filesystems without hard links.
Delayed replies check that refresh and empty views leave no request spinning.
Multi-monitor focus/stacking, scaling, hotplug, real playback and real download
completion still require desktop/device interaction.
