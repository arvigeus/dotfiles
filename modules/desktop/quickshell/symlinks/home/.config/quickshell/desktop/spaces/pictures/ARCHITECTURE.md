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

`WallpaperService` is the shell's only reader of `wallpaper.json`; backgrounds and
`WallpaperRuntime` follow its `choice`. It also owns the Displays random action.
Its on-demand worker executes `randomSet`, pins Wallhaven/SFW regardless of
current Pictures filters, and is unloaded on completion/failure. Repeated clicks
are disabled while pending; errors and completion remain visible in Displays. One
image button with a shuffle badge performs this action; there is no separate
Pictures-launch action. Apply and random requests wait up to four minutes, longer
than the backend's own download, startup and shutdown deadlines, so the UI never
unlocks while an Apply is still running. Favorites, preferences and Steam handoff
share the ordered control lane, can queue behind an Apply and use the same limit.

The session-owned `WallpaperRuntime` intentionally survives browser close. It
loads no controller for ordinary still-image sessions. Only an animated choice
or an ownership journal needing cleanup (read once at startup) starts its worker.
A failed worker restarts after 1, 2 and 4 seconds; a successful sync restores
that budget. A renderer error latches until the next Apply. Background layer
surfaces cover each output without reserving space or taking keyboard focus.
The shell yields an output only after the external renderer supplies frames.

## Storage

User configuration and state:

- `~/.config/quickshell/desktop/spaces/pictures/pictures.json`
- `~/.config/quickshell/desktop/spaces/pictures/pictures-ui.json`
- `~/.config/quickshell/desktop/spaces/pictures/wallpaper.json`
- `~/.config/quickshell/desktop/spaces/pictures/providers`
- `~/.local/share/quickshell/desktop/spaces/pictures/favorites.json`

Config contains optional `providers` and `wallpaper_engine` objects. Preferences
save grid/strip, selected provider and per-provider applied filters. Favorites
retain provider IDs, item IDs and safe metadata, never resolver headers/secrets.
Private records are atomically written as 0600 beneath owner-only directories.
Runtime journals/locks are machine/session state, excluded from portable backup.

`$XDG_DATA_HOME/quickshell/desktop/spaces/pictures/current-wallpaper` is the single
ordinary still-image file used by desktop backgrounds and `hyprlock.conf`.
hyprlock reads JPEG, PNG and WebP but not GIF or AVIF, so other formats (such as
Wallpaper Engine's GIF previews) are published as a PNG of their first frame
through FFmpeg. Without FFmpeg the original is copied for the desktop.
An image Apply downloads first, then publishes the still and settings under the
wallpaper control lock. A failed settings commit restores the previous still.
The previous still remains while an animated choice starts. Once frames are
visible, the runtime publishes that choice's still (Wallpaper Engine preview or
extracted video frame) under the control lock and rewrites the choice. Every
reload of `wallpaper.json` bumps the background URL revision, invalidating Qt's
image cache although the path stays the same. Lock changes take effect on the
next lock; an already-open lock screen is not modified.

The current image is explicitly excluded from backup, per the user's exception.
Restored settings alone do not restore wallpaper payloads; the themed desktop
and solid-color lock background remain available until another Apply. Downloads
and artwork are regenerable under
`$XDG_CACHE_HOME/quickshell/desktop/spaces/pictures/`. Each successful image or
video Apply prunes `wallpapers/` to the 32 most recently used files within 2 GiB.
The active video, its frame and files from the last hour are always kept;
temporaries abandoned by killed workers are removed after a day. Videos and
Steam Workshop payloads also need independent storage/backup. Machine-specific
Steam library paths and Proton overrides must match the fresh machine.

## Providers and playback

Python owns provider credentials and network calls. The browser uses the shared
bounded JSON-lines worker with ordered mutations, superseded browse/tag/status
reads, request generations and timeouts. Provider failures are shown without
environment values. Downloads validate content type, size, deadline and file
signature (MP4, or JPEG/PNG/WebP/AVIF/GIF), write unique partials and remove
them on failure/close. A cached file that fails the signature check is fetched
again. Only safe provider URLs enter QML. Wallhaven uses its public search API;
Bing uses Microsoft's recent homepage feed. Bing's feed and Wallhaven's HTML
tag suggestions can change independently.

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
Source filter defaults to Workshop when a Steam key is available. The optional
`wallpaper_engine` configuration accepts `library_paths`, `proton_bin` and a
Steam-key override. Otherwise Workshop reads the existing Games private
`../games/games.json`; no Games process starts and no key crosses into QML.
Provider IDs, Workshop IDs, manifest formats and data keys remain stable.

The runtime retains exclusive control leases, PID/start-time/owner markers,
crash journals, native playback-policy restoration, bounded retries, fullscreen
and DPMS suspension, still fallback and exact owned-process cleanup. It queries
Hyprland itself, only while animated and inside its transient-error handling, so
a slow compositor reply recovers without tearing down the renderer. Renderer
children get a parent-death signal tied to the worker's single control thread,
which lives as long as the worker. Video uses mpvpaper and FFmpeg still
extraction.
Steam, Proton and Wallpaper Engine media remain launcher-owned. The module
explicitly declares Python, FFmpeg and mpvpaper for command-provider/video support,
and Wallpiper's Hyprland portal for Wallpaper Engine. Steam remains launcher-owned. No wallpaper daemon is autostarted separately.
[Wallpiper upstream](https://github.com/ejalxndr/wallpiper) describes the supported
runtime setup and its experimental status.

The controller targets Wallpiper 2.1. The AUR Wallpiper/portal 2.0.1 binaries
contain every `wallpiperctl` command (`set <path> <monitor>`, `mute`, `play`,
`pause`), environment variable, the `wallpiper-renderer-pid` file and the
`wallpiper-portal-hyprland` layer namespace it uses, except
`WALLPIPER_FORCE_LINEAR`. 2.0.1 ignores that, so the Hyprland/Mesa striping
workaround needs 2.1; rendering itself is unverified on 2.0.1. Missing Wallpaper
Engine/Proton reports setup requirements rather than starting a renderer.
