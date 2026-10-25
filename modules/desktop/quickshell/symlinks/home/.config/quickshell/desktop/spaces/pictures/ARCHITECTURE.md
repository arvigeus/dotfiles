# Pictures implementation

## Boundaries and presentation

`ui/SpaceState` registers Pictures in the retained fullscreen host used by Movies,
Series and Games. Pictures shares their cinematic presentation: full-screen
selected-artwork backdrop, large title/facts/actions above a scrolling detail
column, an inline toolbar with expandable search and filters, and Movies controls,
artwork cards, scrollbars and gallery. Rail mode places details at the left above
bottom-aligned landscape cards; grid mode uses the same 51% catalogue / 45% detail
split as Movies, separated by a 4% gutter. An uncropped preview remains in the
scrolling overview, and the gallery shows the full image. The preview has no
background panel, fits its source aspect ratio and is capped at 360 logical pixels
high. Both it and the backdrop use Movies' `ProgressiveImage`: show the provider
preview while fetching the original, then crossfade to the original whenever it
is available. They share one Pictures artwork cache, coalescing the two requests
for each URL. Detail images decode for their physical display size; there is no
logical-width heuristic that can leave them on thumbnails. Thumbnails crop to fit. Wallhaven tags/categories/order/period/ratio/minimum-resolution filters,
Bing markets, metadata, favorites and provider identity are retained.

Escape closes gallery or provider/tag menus, then filters, then clears search,
then closes search, then hides the Space. The top-left host X remains accessible throughout.
Hiding retains selection, catalogue, filter drafts and ongoing actions; it stops
pagination, search debounce, tag menus, installation polling and detail rendering.
Closing destroys the browser, artwork cache and provider worker, cancels requests
and kills its owned converter/plugin process groups. Detached Steam/browser
handoffs survive. Other Spaces remain independent.

`WallpaperService` owns the Displays random action. Its on-demand worker executes
`randomSet`, pins Wallhaven/SFW regardless of current Pictures filters, and is
unloaded on completion/failure. Repeated clicks are disabled while pending;
errors and completion remain visible in Displays. One image button with a shuffle
badge performs this action; there is no separate Pictures-launch action.

The session-owned `WallpaperRuntime` intentionally survives browser close. It
loads no controller for ordinary still-image sessions. Only an animated choice
or an ownership journal needing cleanup starts its worker. Background layer
surfaces cover each output without reserving space or taking keyboard focus.
The shell yields an output only after the external renderer supplies frames.

## Storage, backup and restore

The quickshell module declares these `extra.private.files` destinations:

- `home/.config/quickshell/desktop/spaces/pictures/pictures.json`
- `home/.config/quickshell/desktop/spaces/pictures/pictures-ui.json`
- `home/.config/quickshell/desktop/spaces/pictures/wallpaper.json`
- `home/.config/quickshell/desktop/spaces/pictures/providers`
- `home/.local/share/quickshell/desktop/spaces/pictures/favorites.json`

Config contains optional `providers` and `wallpaper_engine` objects. Preferences
save grid/strip, selected provider and per-provider applied filters. Favorites
retain provider IDs, item IDs and safe metadata, never resolver headers/secrets.
Private records are atomically written as 0600 beneath owner-only directories.
Runtime journals/locks are machine/session state, excluded from portable backup.

`$XDG_DATA_HOME/quickshell/desktop/spaces/pictures/current-wallpaper` is the single
ordinary still-image file used by desktop backgrounds and `hyprlock.conf`.
An image Apply downloads first, then publishes the still and settings under the
wallpaper control lock. A failed settings commit restores the previous still.
Animated choices publish their still preview/frame there when ready. Static
background URLs use a revision to invalidate Qt's image cache even when the
provider and stable path stay unchanged. Lock changes take effect on the next
lock; an already-open lock screen is not modified.

The current image is explicitly excluded from backup, per the user's exception.
Restored settings alone do not restore wallpaper payloads; the themed desktop
and solid-color lock background remain available until another Apply. Downloads
and artwork are regenerable under
`$XDG_CACHE_HOME/quickshell/desktop/spaces/pictures/`. Videos and Steam Workshop
payloads also need independent storage/backup. Machine-specific Steam library
paths and Proton overrides must match the fresh machine.

`backup.sh` snapshots declared paths into the verified local
`/home/arvigeus/Projects/dotfiles-private/modules/backup`. The private standalone
`apply.sh` restores copies, creates private parents, preserves modes and renames
collisions beside their destinations. Restore private data in addition to the
public quickshell module; public apply never hydrates secrets. Provider packages
and their env files stay in the private repository, never in public examples.
The Pictures package was copied from the existing private configuration without
replacing nonempty destinations; provider paths are now module-relative. The old
reference checkout is preserved. No migration or legacy fallback hook is installed.
The snapshot must be reviewed, committed and synchronized privately before it can
serve as an off-machine recovery source; this work never pushes private data.

## Providers and playback

Python owns provider credentials and network calls. The browser uses the shared
bounded JSON-lines worker with ordered mutations, superseded browse/tag/status
reads, request generations and timeouts. Provider failures are shown without
environment values. Downloads validate content type, size and deadline, write
unique partials and remove them on failure/close. Only safe provider URLs enter
QML. Wallhaven uses its public search API; Bing uses Microsoft's recent homepage
feed. Bing's feed and Wallhaven's HTML tag suggestions can change independently.

A private command provider entry is `{id, name, plugin, env?, env_file?}`, where
`plugin` points to a directory beneath `providers/` relative to `pictures.json`.
Its `manifest.json` has `api_version: 1` and an argv `command` supporting
`{plugin_dir}` substitution. Direct argv commands are supported too. No shell
expansion occurs. Commands accept one JSON request and return one JSON object
with `success: true` or `success: false, error`. Browse returns `items`, optional
opaque `next` and `total`; resolve returns a temporary `url` and optional HTTP
headers. Image/video IDs and opaque refs persist; resolver URLs/headers do not.
Configured commands are trusted user code and are never executed by discovery.
Selecting a provider clears the previous provider's catalogue/selection before
requesting its first page. A named loading state and errors prevent an unreachable
provider from appearing to keep the old selection. All custom discovery and
transport remain private; the public shell knows only the command protocol.

Wallpaper Engine retains installed/Workshop catalogues, Steam handoff, setup
warnings, additional still previews and experimental Wallpiper playback. Its
optional `wallpaper_engine` configuration accepts `library_paths`, `proton_bin`
and a Steam-key override. Otherwise Workshop reads the existing Games private
`../games/games.json`; no Games process starts and no key crosses into QML.
Provider IDs, Workshop IDs, manifest formats and data keys remain stable.

The runtime retains exclusive control leases, PID/start-time/owner markers,
crash journals, native playback-policy restoration, bounded retries, fullscreen
and DPMS suspension, still fallback and exact owned-process cleanup. It reads
Hyprland state only while animated. Video uses mpvpaper and FFmpeg still extraction.
Steam, Proton and Wallpaper Engine media remain launcher-owned. The module
explicitly declares Python, FFmpeg and mpvpaper for command-provider/video support,
and Wallpiper's Hyprland portal for Wallpaper Engine. Steam remains launcher-owned. No wallpaper daemon is autostarted separately.
[Wallpiper upstream](https://github.com/ejalxndr/wallpiper) describes the supported
runtime setup and its experimental status.

## Validation

`test_pictures.py` covers SFW filtering, pagination, downloads/deadlines, stable
shared still publication, failed-write preservation, random Apply and preferences.
`test_picture_providers.py` exercises plugin identity, opaque pagination, resolve
headers, redacted failures, command timeout/shutdown and video fallback.
`test_wallpaper_engine.py` checks 43 ownership, recovery, pause, Steam discovery,
Workshop, crash and shutdown cases with executable fixtures. It starts no real
Steam/Proton renderer. `test_pictures_space.py` drives the production host and
workers with isolated providers, checking cinematic backdrop/toolbar, rail/grid geometry, filters/search Escape,
favorites, hidden action completion, retained identity, independent Movies close,
fresh instances and saved grid preference, plus the shared random action.
`test_pictures_worker.py` exercises the production protocol and owned converter
group shutdown without terminating detached applications.
`test_pictures_private.py` checks backup → synthetic commit → clone → standalone
restore, private modes and destination collision preservation, excluding images.
The restored generic command package is discovered and browsed through the real
Pictures worker. UI fixtures drive provider-choice activation, empty loading state,
private video results and a failed provider without exposing any real private code.

Live Wallhaven downloads, native surfaces and lock configuration are checked
separately. Actual locking, animation/decoding quality, multiple monitor scales,
hotplug and native fullscreen/DPMS behavior still need interactive validation.

Live checks on 2026-10-25 passed Wallhaven download/Apply, Bing's 15-item feed,
native dark/light host lifecycle and decoded previews, active wallpaper layer
surfaces, the managed lock-image path and offline configuration validation.
The actual private snapshot restored eight Pictures files with matching contents
and owner-only modes, excluding images. Its new changes are uncommitted.
mpvpaper and AUR Wallpiper/portal 2.0.1 are installed. The inherited controller
protocol was developed against Wallpiper 2.1; native compatibility of the current
AUR packages is unverified. Wallpaper Engine and the configured Proton are absent
on this machine, so Pictures reports setup requirements until installed/configured.

`test_progressive_image.py` delays the original behind a small preview and verifies
the original replaces it, decoding meets display width and backdrop/detail make
only one request per source. The Displays header fixture verifies the image/shuffle
badge, single action, busy state and absence of a Pictures-launch button.
