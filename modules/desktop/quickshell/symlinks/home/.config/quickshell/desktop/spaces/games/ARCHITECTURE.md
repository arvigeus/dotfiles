# Games implementation

## Scope and presentation

Games is registered in `ui/SpaceState.qml` and uses the retained fullscreen
`SpaceHost`. It shares the Movies presentation controls, dark cinematic palette,
toolbar placement, edge-to-edge backdrop, poster rail/grid, image gallery and
scrolling primitives. Each instance owns its catalogue, selection, worker,
preferences, artwork cache and optional torrent worker. Other Spaces retain
their independent instances. See the [presentation contract](../movies/ARCHITECTURE.md#presentation-contract).

The facts row presents the IGDB mark/score, the supplied colored ProtonDB tier
badge (the native badge when Steam's store platforms list a Linux build, falling
back to the client cache's `oslist`, which can still list discontinued ports; the
first lookup fills platforms for the owned library in batched reads) and a clock with HowLongToBeat's main-story hours. The clock/time form one
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

The top-level tabs are My Library, Browse and Favorites. Library is the default
so installed games work without IGDB credentials. Genre/platform/year/order
filters, exact store matching, ProtonDB, install/play/uninstall, imported local
files and qBittorrent workflows are available from these views. Local imports
are files, not installed launcher entries; each game's folder button opens them
in the file manager and never executes them automatically. The shared torrent and
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
uninstall prompts; Epic uninstall requires the page confirmation first. Launcher
snapshots are reused for 60 seconds, except that any action other than Play marks
them stale and Refresh game rescans snapshots older than five seconds. After an
uninstall, the page rechecks the selected game's store state after 3, 10 and 30
seconds while visible, stopping when its installation changes.

Legendary's `list` always logs in and refreshes Epic assets over the network
(2–9 seconds), so Epic ownership is cached as `epic-owned:v1` for six hours, five
minutes after a failure; rescans run only the local `list-installed`. Library
Refresh and install completion re-read ownership. When Epic is unreachable, the
saved ownership stays in use with a notice. Only Legendary's credential messages
mean signed out; its "Logging in…" log line appears on every run.

### Epic installation progress

Epic installs run a detached `backend.py --epic-install` supervisor through the
same UWSM application lifetime as launcher actions. It drains Legendary's output
and saves only percentage, download speed, ETA and terminal status. Raw output
and account/session data are never stored or sent to QML. Progress is best effort
against Legendary's log format; an unknown format retains the indeterminate
install state until the process exits.

Atomic private JSON snapshots in `epic-installs/` under the Games data directory
retain one attempt per Epic app. A start lock serializes requests and a running
flock identifies the supervisor without trusting reusable PIDs. A UUID rejects
late supervisors from older attempts; launch has a 30-second grace period before
an absent supervisor counts as interrupted. Failed/interrupted attempts can be
retried with Install, allowing Legendary to resume its partial download. These
machine-local snapshots are not part of the portable library backup.

Games reads snapshots when it opens or is shown and after starting an install,
then every 1.5 seconds while one is running. The Epic button disables during installation and shows percentage;
inline status adds speed/ETA and retains failures. The Downloads panel lists Epic
jobs across selections, alongside the current game's torrent jobs. Completion
refreshes launcher state and the selected action to Play, deferring visible
catalogue updates while hidden. Closing Games releases its worker but preserves
the independent supervisor; reopening recovers progress from disk.

Install jobs also appear in the shared header activity indicator. Snapshot-only
polls do not create a loading indicator. Content classification uses a separate
two-thread enrichment lane, leaving foreground details, launcher reads and
ordered actions available.

Library listings use only saved and launcher data; there is no background
per-game hydration. Launchers and the Steam CDN supply a poster for every library
row (Steam's portrait `library_600x900` asset; the landscape `appdetails` header
is never a poster). Descriptions, screenshots and the IGDB match load through
`details` for the selected game only. A found IGDB match is reused for 30 days and
Steam descriptions for seven; both stay usable when stale. Selecting a game costs
at most one IGDB search and one `appdetails` read, and nothing once cached.

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

### Native content filtering

`content.py` reads only native classifications: Steam `content_descriptors` 3
(Adult Only Sexual Content) and 4 (Frequent Nudity or Sexual Content), as defined by
[Valve](https://partner.steamgames.com/doc/api/ISteamUGC#EUGCContentDescriptorID),
and GOG's [NSFW store tag](https://www.gog.com/en/games?tags=nsfw).
Missing/malformed labels and unknown descriptor IDs remain unknown; titles,
descriptions, maturity/age ratings, and third-party classifications never
substitute for them. These storefront endpoints are not versioned contracts for
third-party clients and may change independently.

Steam labels come first from the installed client's PICS cache,
`appcache/appinfo.vdf` under each Steam root. It holds `common/content_descriptors`
for owned and viewed apps, and omits the section when an app declares none, as the
store does; for 300 owned games both agreed on every label. Only format v29 (magic
`0x07564429`, string-table keys) is read, bounded to 128 MiB. The app index is
rebuilt when the file's mtime or size changes, and each app's key/values are
parsed on first use. Other apps, an app without `common` data, another format or a
malformed file use `IStoreBrowseService/GetItems` on `api.steampowered.com`:
`content_descriptorids` and `platforms` for up to 100 apps per request, without a
key. Items must identify the requested app; other `success` values (unknown or
region-restricted) stay unknown. Descriptions still come from `appdetails` on
`store.steampowered.com`, so either host can be unreachable without affecting the
other.

GOG labels come from one pass over `GET https://catalog.gog.com/v1/catalog` with
`tags=is:nsfw` (about 1,000 products, 11 pages of 100), without account
credentials; Heroic's caches carry no store tags. The pass is stored as
`gog-nsfw:v1` and a product is NSFW when its ID is listed, so the request count
does not grow with the library. Every listed product must carry the `nsfw` tag
slug: a page that ignored the filter, a malformed page or more than 50 pages fails
the pass, which keeps the previous set. The listing omits secret products (Agony,
for example, is secret and tagged NSFW on its product page), so those count as not
tagged; this is an accepted trade-off for not reading each product. The set renews
after seven days, and library Refresh renews a set older than a day. Until the
first pass completes, GOG games await classification.

Exact store IDs and centralized library matches determine classification,
including manual overrides and GOG slugs resolved against Heroic's product records.
Unresolved slugs, Epic-only games and local files have no supported classification.
A merged game is NSFW when any supported store labels it so, and labelled safe only
when every supported store has a known negative label. This is a store-label filter,
not a claim that unlabelled content is safe.

Each label result carries `pending` (a lookup is due) and `awaiting` (due and never
attempted). With NSFW hidden, QML hides known NSFW games and awaiting ones, so a
new title cannot flash before its first lookup. A label that stays unknown after
an attempt (provider outage, missing product, malformed data) is shown. The game
being viewed is not hidden by an awaiting label, for example after editing its
store link; hiding NSFW removes it as it does a known NSFW selection, and closes
its gallery and dialogs.

`native-content:v1:steam:ID` and `steam-platforms:v1:ID` entries in the existing
SQLite cache last 30 days; stale labels and a stale GOG set still apply while a
refresh is due. Failure markers (`KEY:retry`) store their cooldown: five minutes
after an outage, one day when Steam answers without usable data for that app
(item `success` other than 1). A transport/provider
failure pauses that provider across products, including forced reads:
`steam-store-items` (labels/platforms), `steam-appdetails` (descriptions) and
`gog-content`. Consecutive failures double the pause up to an hour, and a success
clears it, so a long outage costs one probe per hour instead of an 8-second timeout
every five minutes. Products skipped during a pause are recorded as attempted. The
library Refresh action clears the pauses and per-product cooldowns; known labels
are not re-read before they expire.

Listing reads cached and local labels without network locks, through one SQLite
connection per listing; the library computes labels only for the returned page.
`content_rating` takes up to 100 `gameIds` and returns `items`; QML sends up to 25
queued games per request with two requests in flight while visible with filtering
enabled. Each request makes at most one Steam store read per 100 apps; fetches
coalesce through source locks. Changing the NSFW toggle only
refilters the current pages and schedules due labels; it does not refresh launcher
libraries or invalidate saved metadata. Browse generations reject late callbacks
after search or view changes. Hiding stops queued reads; closing terminates the
owned worker as usual.

QML keeps the returned page separately from its visible catalogue and patches rows
in place unless a game's visibility changes. The Filters button opens the
inline header group used by Movies and Books. The All games/Installed/Owned
dropdown is part of that group in Library. NSFW is available there in Library,
Browse and Favorites without catalogue credentials; genre, platform, sort and year
fields with Apply/Reset appear only in configured Browse. The inverse toggle value
persists as `catalogue/hideNsfw` in `games-ui.ini`. The toggle's tooltip counts
games hidden by labels, awaiting classification and shown without labels.
Pagination retains the provider's raw offset, waits for the current
classification queue and advances through wholly hidden pages.
Games backdrops use the shared one-second retention period: the previous image
stays visible while the new backdrop loads, then yields to the selected game's
poster if loading is still in progress.

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
hydration generations similarly reject stale results.

`presentation.py` reads Steam's most-recent account (or the sole local account)
for custom grid logos/heroes/covers and local playtime. It does not combine stats
from multiple users. Installed Steam library artwork is tried before public CDN
fallbacks. Local artwork URLs include mtimes; title artwork resets immediately
on selection changes and falls back to text when absent. No SteamGridDB API key
is required for artwork already installed in Steam. Downloaded images use a
Games-owned `ArtworkCache`, reusing the Movies bounded cache implementation;
Movies/Series retain their existing shared cache instance.

Refreshing a game, finishing an install or saving a store match re-hydrates the
selected game; a hydration generation alongside the selection generation lets only
the newest responses apply. Saving a store match keeps the selection, and a
refreshed listing keeps a retained selection in view instead of scrolling back to
the start.

Hidden pages stop selection debounce, pagination, search and content
classification. In-flight bounded reads may finish without activating the page.
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

`test_games_backend.py` covers parsers, providers and store actions.
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
`test_games_content.py` covers native tag/descriptor parsing, synthetic v29
Steam client caches (labels, fallback, rewrites, other formats, truncation),
batched Steam store items, the bulk GOG NSFW listing (paging, weekly/daily
renewal, untagged pages, secret products), an unreachable description host,
unknown/malformed data, exact identity/override handling, combined stores, cache
reuse/restart, awaiting versus attempted labels, outage pauses and back-off,
one-day cooldowns for missing Steam apps, refresh and single-connection listings. `test_games_backend.py`
also covers the native badge, cached Epic ownership while offline and rescans for
Refresh game. The Games UI fixture checks header placement, hiding labelled and
never-classified artwork, showing unavailable labels, tooltip counts, selection
clearing, Favorites, persisted toggles, scrolling a paged 120-game library with
batched classification and no per-game requests, newest-hydration ordering, match edits that keep the selection, in-place row patches, the native
badge, uninstall rechecks and no polling while idle. UI fixtures stub Steam roots
and storefront HTTP. Threaded backend regressions check nonblocking listing;
`test_movies_worker.py` checks that blocked enrichment leaves foreground, launcher
and control lanes available.

Live public HLTB search and direct-page reads both resolved Portal 2 (Steam 620)
to HLTB 7231. Actual store launch/install/uninstall, download completion and
multi-monitor scaling/focus/hotplug need interactive validation.
Epic install fixtures exercise real detached supervisors with a fake Legendary
executable: telemetry, duplicate requests, backend restart, completion, failure,
interruption and sanitized errors. The UI regression clicks Install, checks
percentage/speed/ETA, the activity indicator and Downloads, closes/reopens Games
during installation and verifies Play on completion. It never contacts an account
or downloads a real game.
