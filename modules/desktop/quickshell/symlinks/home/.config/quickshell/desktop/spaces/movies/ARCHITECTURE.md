# Movies implementation

## Scope and integration

Movies, TV Series and Games are registered. Other Spaces remain placeholders. `ui/SpaceState.qml`
owns the catalogue, running IDs and navigation; `SpaceHost.qml` owns asynchronous
loaders and binds effective page activation. It uses the existing
`InteractionState` / `InteractionWindow` layer surface with all four anchors,
Overlay stacking and ignored exclusion zones, covering the panel as well as the
workspace. Qt applies per-output scale; the surface follows the output selected
in Spaces. Unplugging its output hides it without destroying the instance.
Opening a drawer or launcher hides the Space through shared input ownership.
Hidden Spaces stay running. Explicit close unloads
only the selected instance. A feature host captures its own ID so late callbacks
cannot hide a different Space.

The top-left hide control is outside the page and its popups. Escape dismisses a
page popup/gallery first, then search or filters, then hides the Space. Native
menus can consume Escape through their normal shortcut override. Focus is restored
only after the visible native surface activates. The full-screen host has no
panel-height allowance or compositor geometry commands.

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

One toolbar spinner covers catalogue loading, selected-movie metadata, personal
state, local-file inventory, backdrop/logo decoding and the visible tab's requests.
Embedded panels suppress their own indicators; the image gallery uses its own
spinner while hiding the toolbar indicator. Loading descriptions appear only in
the indicator's tooltip and accessible name. An extra-request generation prevents
an earlier tab's response from clearing a later tab's loading state or replacing
its content. Selection generations protect personal state and file inventory too.

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
Games uses an independent instance of this
component with its own cache namespace. Movies and Series retain their existing
shared artwork instance. The cache lazily owns a Python
worker while image consumers exist. `image_cache.py` downloads to atomic files in
`$XDG_CACHE_HOME/quickshell/desktop/spaces/movies/artwork/` (normally
`~/.local/cache/quickshell/desktop/spaces/movies/artwork` in this configuration). SHA-256 filenames
contain no source URLs. Images are private (0600; directory 0700), limited to
20 MiB each, 256 MiB total and 2,000 files. Files expire after 30 days without a
disk-cache access; startup and downloads prune expired/oldest entries. Shell
restart retains complete cached files. Closing Movies releases its cache worker;
only that worker's unfinished downloads are removed. Abandoned partial files are
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
The existing SQLite cache retains provider metadata across instance/shell restarts;
its title records also support favorites and aliases and must not be cleared as
an artwork-cache maintenance operation.

## Workers and persistence

Provider logic stays here. `Worker.qml` owns one bounded JSON-lines Python process,
request IDs, startup queuing, deadlines and callbacks. Each backend has its own
process group so close releases ffprobe/ffmpeg children as well as the worker.
The torrent worker attempts bounded cleanup of only its own remote search jobs.
qBittorrent and user-launched players/browsers have independent lifetimes.
Ordinary imports publish complete files without replacing an existing destination;
cross-filesystem copies keep their source until publication and remove in-flight
temporary files on worker close. Interrupted indexing can be recovered by Scan.
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

SQLite uses short transactions and per-request connections. The private engine
backs up files, not online SQLite snapshots: close Movies before `backup.sh`.
Cache entries in the database are included with personal records; image caches,
large media, sockets and generated OpenSubtitles sessions are not portable inputs.

## Private configuration and provisioning

Private files are stored alongside their owning Space under the current shell's
XDG namespace. The owning quickshell module declares these portable paths in
`extra.private.files`:

- `home/.config/quickshell/desktop/spaces/movies/media.json`: metadata API keys, named playback
  templates, region, player argv, optional anime adapters and OpenSubtitles account.
- `home/.config/quickshell/desktop/spaces/movies/media-ui.ini`: view preferences.
- `home/.local/share/quickshell/desktop/spaces/movies/library.sqlite`: personal/library state.

Examples are secret-free and do not get copied over user configuration. Keys remain in Python;
QML sees provider labels and resolved playback targets. Worker stderr is reduced
to a generic diagnostic rather than publishing provider exceptions or URLs.

All Spaces read one qBittorrent connection from
`home/.config/quickshell/desktop/integrations/torrents.json`, declared once by the
quickshell module. See [shared integration settings](../../integrations/ARCHITECTURE.md#qbittorrent)
for authentication and backup ownership. Torrent jobs, libraries and worker
lifetimes remain independent per Space.

`backup.sh` uses generated module selection, writes `modules/backup` in the private
checkout, and refreshes its standalone restore engine. Private `apply.sh` restores
copies, creates parents and preserves collisions beside the destination.
Configuration and database files must be user-owned 0600; the private backup
repository retains owner-only directory modes, and restore creates missing
destination parents as 0700. A fresh
system needs the public quickshell, mpv, qBittorrent, ffmpeg and browser/XDG modules
before private restore. `python-guessit` belongs to quickshell; the other runtime
packages belong to their existing modules. Providers may expire keys/accounts;
reauthenticate in media.json or torrents.json when required. Remote qBittorrent
needs the same absolute download paths mounted locally. Media payloads and machine
mounts are outside this configuration backup.

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
retaining a detached application; `test_movies_private.py` checks a synthetic
backup → Git clone → restore with private permissions, favorites and ID aliases.
Multi-monitor focus/stacking, scaling, hotplug, real playback and real download
completion still require desktop/device interaction.
