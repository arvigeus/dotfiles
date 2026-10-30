# Games implementation

## Scope and presentation

Games is registered in `ui/SpaceState.qml` and uses the retained fullscreen
`SpaceHost`. It shares the Movies presentation controls, dark cinematic palette,
toolbar placement, edge-to-edge backdrop, poster rail/grid, image gallery and
scrolling primitives. Each instance owns its catalogue, selection, worker,
preferences, artwork cache and optional torrent worker. Other Spaces retain
their independent instances. See the [presentation contract](../movies/ARCHITECTURE.md#presentation-contract).

The facts row presents the IGDB mark/score, the supplied colored ProtonDB tier
badge and a clock with HowLongToBeat's main-story hours. The clock/time form one
link to the matched HLTB page; a passive tooltip shows all three estimates,
stale status and lookup warnings. Without a match, the clock opens the editable
HLTB link/ID dialog instead. The adjacent link icon opens the official website.
Steam/Epic/GOG actions use adjacent blue/black/purple split buttons with white brand marks,
dynamic action labels and menus for store links, matching and uninstall.
Compact favorite and refresh icons follow the store buttons. Menu Escape and
hiding follow the existing page dismissal policy.

The header, facts and actions remain visible above the Overview/Find tabs, matching
Movies/Series. Find uses the selected game's detail area, not the whole Space.
The Movies `ImageStrip` follows the overview text and metadata inside the same
scroll area, without a bottom-pinned gap. It uses the Games artwork cache;
pointer or keyboard activation opens the existing gallery at the selected image.
ProtonDB badges and store SVGs reuse the supplied artwork from the earlier Games
implementation. The IGDB mark comes from
[Simple Icons](https://github.com/simple-icons/simple-icons/blob/develop/icons/igdb.svg),
as does the [GOG.com mark](https://github.com/simple-icons/simple-icons/blob/develop/icons/gogdotcom.svg).

The library, discovery, favorites, genre/platform/year/order filters, exact store
matching, ProtonDB, install/play/uninstall, imported local files and qBittorrent
workflows are retained. Library is the default so installed games work without
IGDB credentials. Local imports are files, not installed launcher entries; they
open in the file manager and never execute automatically. The shared torrent and
local-library implementation uses the Games storage namespace and `game` kind.

[Game Glance](https://github.com/michpalm/game-glance) informed the title-logo,
custom Steam artwork priority, public beat-time estimates, manual match correction,
offline metadata and local playtime/last-played features. The Python HLTB adapter
is an independent implementation of the public site's request protocol; no Decky
or vendored frontend code is included. Steam's friends, achievements, cloud-sync
status, recommendations and wishlist deals rely on client/account APIs not
available here and are not represented as known. Its screensaver and replacement
Steam Home are outside this Space's scope.

## Provider and worker boundaries

`backend.py` retains the earlier game records, UUID identity, provider IDs,
favorites, store overrides, IGDB OAuth/pacing, store-description fallbacks and
ProtonDB cache. Credentials stay in Python. QML uses bounded JSON-lines transport
through the existing Movies `Worker`, with a selectable backend directory.
The worker owns a process group; explicit close releases its request threads and
owned subprocesses. User-launched games and launcher actions run independently
through `uwsm app -t service` when available. Steam supplies its own install and
uninstall prompts; Epic uninstall requires the page confirmation first.

### GOG through Heroic

`gog.py` reads Heroic's `store_cache/gog_library.json` (`games` array) and
`gog_store/installed.json` (`installed` array). Older `gog_store/library.json`
libraries are accepted when the current cache is absent, not when it is corrupt.
Reads are bounded to 16 MiB. Numeric `app_name`/`appName` identify GOG products;
DLC/redist entries are omitted. Installed paths must be absolute existing
directories. Cache metadata supplies descriptions, genre, developer and artwork
before optional IGDB enrichment. Library union, ownership/installation filters,
favorites and exact-title/edition safeguards apply across all three stores.
IGDB's GOG website slugs are matched to cached store URLs when available, otherwise
unique exact titles; explicit numeric product IDs never fall back to another ID.
Manual GOG overrides accept only numeric IDs and use the existing SQLite table.

Native Heroic uses `$XDG_CONFIG_HOME/heroic` (default `~/.config/heroic`); Flatpak
uses `~/.var/app/com.heroicgameslauncher.hgl/config/heroic`. The adapter chooses one
populated available launcher profile, preferring native when both are populated.
It never combines accounts or uses one launcher's cache with another launcher.
When neither matching launcher is available, cached titles remain visible but
cannot launch. Missing/malformed ownership caches remain unknown, not unowned;
malformed install records disable installation actions. A missing install file
uses Heroic's empty-registry default. Cache contents are not proof of a current
authenticated session; Heroic handles authentication and offline availability.

Heroic already bundles GOGdl; Games adds no Python dependency, credential file or
GOG OAuth implementation. It never reads or backs up Heroic's auth tokens.
GOG matches and copied library metadata reuse the already-declared private
`library.sqlite`; there are no additional Games private paths to provision.
The optional existing `gaming/launchers/heroic` module provisions its Flatpak.
The adapter rechecks launcher, ownership and installation records at action time.
Both Play and Install pass `heroic://launch/gog/PRODUCT_ID` as one argument to
the corresponding native executable or `flatpak run com.heroicgameslauncher.hgl`.
Heroic's [protocol handler](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/main/src/backend/protocol.ts)
launches installed games or asks whether to install an uninstalled game.
Games hides, without destroying its retained instance, for these UI handoffs.
There is no supported uninstall protocol: the menu opens Heroic for management
instead of invoking GOGdl directly or deleting files. Existing Steam/Epic actions
and runner/prefix handling remain unchanged. Refreshing Games rereads the cache;
new purchases require refreshing Heroic's own library first.

`hltb.py` uses bounded HTTPS reads, browser-compatible auth headers, one auth/search
lock and an in-memory auth token. It discovers a changed search route from
same-origin scripts on failure and retries once. Numeric Steam IDs or a unique
normalized exact title determine automatic matches; edition words and sequel
numbers remain significant. Ambiguous or conflicting results require a manual
HLTB game URL/ID. A direct match reads that game's public page. Positive durations
are seconds converted to hours; missing durations stay unavailable. These are
population estimates, not evidence of completion. HLTB's undocumented interface
can change independently of this repository.

Successful HLTB results persist for 30 days; failed reads retain stale times with
a warning and a five-minute cooldown. Manual HLTB overrides have their own table
and survive metadata refresh. An independent request generation prevents a late
automatic result from replacing a newer manual match. Browse, selection and
background library-enrichment generations similarly reject stale results.

`presentation.py` reads Steam's most-recent account (or the sole local account)
for custom grid logos/heroes/covers and local playtime. It does not combine stats
from multiple users. Installed Steam library artwork is tried before public CDN
fallbacks. Local artwork URLs include mtimes; title artwork resets immediately
on selection changes and falls back to text when absent. No SteamGridDB API key
is required for artwork already installed in Steam. Downloaded images use a
Games-owned `ArtworkCache`, reusing the Movies bounded cache implementation;
Movies/Series retain their existing shared cache instance.

Hidden pages stop selection debounce, pagination, search and background metadata
hydration. In-flight bounded reads may finish without activating the page.
Backdrops/logos stop presenting; popups close. Active torrent imports keep their
monitor intentionally; idle hidden monitoring stops. Closing releases the Games
workers and interrupts in-flight indexing, while qBittorrent retains accepted
downloads. Saved jobs resume when Games reopens. Escape dismisses download
review/popups, gallery, match/uninstall dialog, pickers, search and filters before
hiding the Space. The selected detail tab survives hiding and switching Spaces;
selecting a different game or creating a fresh instance starts on Overview.
The host's top-left X remains reachable.

## Configuration, private data and provisioning

User configuration and state:

- `~/.config/quickshell/desktop/spaces/games/games.json`
- `~/.config/quickshell/desktop/spaces/games/games-ui.ini`
- `~/.local/share/quickshell/desktop/spaces/games/library.sqlite`

The JSON game's keys are `igdb_client_id`, `igdb_client_secret`, optional
`steam_api_key`, `steam_id` and `proton_path`. qBittorrent connection settings
are shared by all Spaces at `~/.config/quickshell/desktop/integrations/torrents.json`
; see [integration ownership](../../integrations/ARCHITECTURE.md#qbittorrent).
Missing keys disable only the
corresponding provider. The file reloads on mtime changes. Provider failures are
sanitized; keys, sessions and response bodies are not logged to QML. Private
configuration/database files are 0600 and owner directories 0700.

SQLite contains personal favorites, store/HLTB matches, saved metadata, imported
file records and torrent jobs. Portable backups exclude the large game payloads
and `prefixes/egs/`, which can contain Wine saves. Those need a separate backup or
mounts at the same paths. Artwork caches live under
`$XDG_CACHE_HOME/quickshell/desktop/spaces/games/artwork/`; they are regenerable.
Steam installs, account credentials, local custom art and Legendary authentication
stay owned by their launchers. Fresh installs must sign in again and reinstall or
remount games. `proton_path` is machine-specific and must point to an installed
Proton if supplied.

## Validation

`test_games_backend.py` ports the existing 70 parser/provider/store-action tests.
`test_games_extras.py` covers HLTB auth, route discovery, exact/ambiguous matching,
direct links, stale/offline responses, custom local art, account selection. `test_games_space.py` drives the production worker and
fullscreen host with isolated providers: opening, rail/grid preference,
badge assets, HLTB hover/link/manual-match behavior, inline Find tabs, compact
favorite/refresh/website actions, branded store action changes, image-strip
gallery activation, gallery/dialog/picker/menu Escape, top-left hide, restore identity, drawer close,
fresh reopen and independence from Movies. Fixtures do not launch real games or
contact accounts. Native validation restores `ui/InteractionWindow.qml` in the
fixture to use a Wayland layer surface. For native tooltip hover, move the real
compositor pointer to the control's window coordinates plus its output offset,
then restore the pointer afterward; Qt's simulated move does not reliably reach
an offset output. Movies/Series UI/cache tests cover the shared changes.
The targeted native GOG smoke checks branding, adjacent buttons, manual matching,
the management handoff and retained state; it excludes tooltip hover, which is
covered by the full offscreen suite.
`test_games_gog.py` covers current/legacy native/Flatpak caches, profile isolation,
malformed/missing/bounded reads, metadata, safe IDs/URLs, three-store library union,
filters, favorites, saved matches and action-time revalidation. Launcher calls are
mocked; UI fixtures check the GOG logo, menu, labels and retained launcher handoff.

Live public HLTB search and direct-page reads both resolved Portal 2 (Steam 620)
to HLTB 7231. Actual store launch/install/uninstall, download completion and
multi-monitor scaling/focus/hotplug need interactive validation.
