# Radio implementation

## Presentation and lifecycle

Radio registers with the existing `ui/SpaceState` and retained fullscreen host.
It uses Movies' typography, controls, palette, scrollbar and wheel handling on
a solid black background in both desktop theme modes. The Stations label/count,
search and inline filters share the host's top row beside its hide X. The
vertical station list replaces artwork views; rows show country, language,
genres, quality choices, playback, favorites and an optional website action.
Rows reserve the website action's width even when no website is available, keeping
quality selectors aligned. The playback heading remains above the list.
One discovery list pins saved favorites without separate browse tabs. Saved
favorites apply search/country/genre filters locally and remain available offline.

Open lazily creates an instance. Hide preserves list position, search/filter
drafts, selected quality and playback. It stops metadata polling, search debounce,
pagination, spinners and open menus. Pending user playback requests may complete
while hidden; restore reads current player state and applies deferred searches.
Close releases both workers and the player without affecting another Space.
Escape dismisses country/genre/quality menus, filter mode, search text, then search
mode before hiding. The host X always hides. Enter plays the selected row; Space
pauses/resumes, or plays the selected row when stopped.

## Provider and player boundaries

`api.py` retains Radio Browser UUIDs, country keys and genre spelling aliases.
Requests use discovered HTTPS mirrors, bounded response sizes/timeouts and finite
100-record pages. AND genre filters expand spelling alternatives into a bounded
union, deduplicating UUIDs and merging popularity order across pages. The expansion
size is checked before building combinations. Eight worker-local cursor sessions
are retained. See the [provider API](https://docs.radio-browser.info/).

`Stations.js` groups equivalent names by country and source website, keeping
distinct codecs/bitrates as stream choices. The group key algorithm and provider
UUIDs are unchanged from the reference implementation. Favorites retain all
available variants. Cached catalogue/country/genre reads survive provider failure
with a visible offline warning. Offline pages disable pagination because cursor
state belongs to the live worker. Saved HTTP stream URLs provide a resolution
fallback when the directory is unavailable.

`RadioService` uses Movies' current Worker transport and ordered control lane.
Network discovery and resolution run outside the control lane, allowing Stop
and state writes to settle while a provider request is pending. UI generations
reject stale searches, resolutions and status replies. Favorite writes settle
before changing the displayed favorites; failures preserve the previous records.
Malformed saved JSON is reported without replacing the original file.

`backend.py` owns one mpv subprocess. Starting a replacement terminates and reaps
the old player; Stop also removes its IPC socket. mpv runs without user config,
video or terminal output. Pause and ICY/song metadata use mpv IPC; transport is
reused from Pictures without starting Pictures or its runtime. Radio supplies its
own current-shell runtime namespace and validates socket ownership/path. Radio
explicitly loads the module-provisioned `mpv-mpris` plugin even with `--no-config`.
It exposes a native session with identity `Radio`, live metadata and play/pause
controls in Sound while the Space is hidden. The plugin follows mpv's lifetime,
so Stop/close removes the session. Sound narrows otherwise ambiguous matches by
the media identity and audio application label when that pair is unique; two
indistinguishable sessions still remain unassigned. Paused/streamless sessions
retain controls in Sound's Playback section. Polling
runs every 2.5 seconds only while visible and playing. No audio-device settings
are changed. SIGTERM invokes bounded cleanup and the shared worker process-group
shutdown, releasing network threads and owned processes on explicit close or shell
exit. Python, mpv and mpv-mpris are declared by the quickshell module. ffplay is no longer a
fallback because mpv is a provisioned dependency with consistent pause/metadata.
Station images and their download/cache machinery are omitted from the text list.

## Nextcloud favorites and station identity

`favorites.py` owns a separate on-demand Worker with an ordered request lane and
a cross-process advisory lock. Local star/unstar writes still atomically replace
`favorites.json` before starting cloud work. A slow Music request cannot block the
playback worker. Star controls wait for an active sync to finish so a stale UI
snapshot cannot overwrite an import. Open/restore, explicit Refresh and successful
local changes trigger sync; a minute timer runs only while visible. An in-flight
save/sync may finish after hide. Close terminates the favorites helper as well as
the playback helper; durable local changes remain for the next open.

`music.py` uses the shared account and Music-specific key from `integrations/`.
Subsonic requests send credentials in HTTPS POST bodies to the instance's fixed
Music REST endpoint. Redirects are refused, replies are bounded, and errors omit
server bodies and credentials. The existing DAV app password is unchanged.

`sync.json` records the account fingerprint, remote-ID/local-UUID links, pending
creates and confirmed catalogue identities. First sync unions both lists, so an
empty local installation cannot erase server stations. Later local removals delete
only linked server IDs; remote removals remove their linked local favorite.
Unknown remote entries import without deleting other stations. Pending create
intent is checkpointed before POST; readback by stream URL reconciles an accepted
request whose response was lost, including a subsequent unstar. Restored links
preserve deletion intent. A changed account, malformed records or a missing local
file with existing sync state stop reconciliation instead of treating data loss
as an unstar. Subsonic lacks conditional/idempotent writes; readback and identity
checks reduce races, but edits from another client during an in-flight request
are reconciled on the next sync.

`matching.py` matches public stream URLs (including HTTP/HTTPS variants) and keeps
verified Radio Browser UUIDs in sync state. Private authenticated/query stream
addresses are never submitted to the public catalogue. Catalogue names,
country/language/genres, homepage and compatible alternate qualities replace bare
cloud labels after a match. Qualities require the same country, station name and
website; format suffixes such as `(AAC 128)` do not split a station. Matching is
cached for a day, including misses. A network failure retains the local station
and reports a retryable warning. Confirmed identities can repair rotating/obsolete
relay addresses. Corrections update the existing Music ID, with read-before-write
and readback verification. If every catalogue stream is marked broken, metadata
is retained with the original saved stream. Unmatched cloud stations retain a
stable synthetic UUID and `source: nextcloud`; playback uses their saved HTTP URL
directly rather than sending that synthetic UUID to Radio Browser.

## Private state and installation

User configuration and state:

- `~/.config/quickshell/desktop/spaces/radio/radio-ui.json`: country, genre and
  per-station quality preferences.
- `~/.local/share/quickshell/desktop/spaces/radio/favorites.json`: station
  records, stable provider UUIDs and stream variants.
- `~/.local/share/quickshell/desktop/spaces/radio/sync.json`: account-scoped
  remote links, pending writes and verified station matches.

Files use atomic 0600 replacement and their new parent directories use 0700.
Search text and playback state stay in the retained instance. Regenerable API
responses live under `$XDG_CACHE_HOME/quickshell/desktop/spaces/radio/`; sockets
live in an owner-only `quickshell-radio-UID` runtime directory. Neither is backed
up. Nextcloud Music sync also uses the shared `nextcloud.json` and
`nextcloud-music-api-key`, shared by all consumers. They share
the existing Nextcloud integration directory with the DAV app password; Radio has
no separate account configuration.

## Validation

`tests/test_radio.py` covers genre aliases, union paging/deduplication, expansion
bounds, offline snapshots, corruption preservation, file modes, URL validation,
metadata and real subprocess/IPC ownership using an isolated fake mpv. It verifies
pause, replacement, failed streams and worker SIGTERM cleanup. No test changes
host audio devices or plays sound.

`tests/test_radio_space.py` uses production workers and the shared fullscreen host
with fixture APIs/player. It covers toolbar geometry, black background, light
desktop theme, scrolling/pagination, favorites, nested Escape, pause/resume,
hide/restore, navigation, explicit close, fresh-instance restore and a late
resolution arriving after Stop.

`tests/test_radio_sync.py` covers initial union, add/remove in both directions,
remote edits, offline retry, lost create/delete replies, account isolation,
serialized syncs, safe transport and shared credential file checks.
`tests/test_radio_matching.py` covers verified URL/UUID matches, quality metadata,
scheme aliases, private-stream lookup exclusion, cache behavior, unavailable
streams and correction of cloud records without changing their IDs. The QML test
also verifies hidden import completion, suppressed hidden polling, duplicate
catalogue/favorite recognition and responsive playback during slow sync.

`tests/test_radio_mpris.py` uses an isolated D-Bus session, local HTTP/WAV fixture,
real mpv/plugin and null audio output. Production Sound controls pause/resume
Radio, retain its controls after stream removal and stop its session without
affecting a second mpv player. The existing audio drawer suite covers the other
association, device and routing behavior.

Run `python3 -m unittest discover -s tests -p 'test_radio*.py' -v`.
Multi-monitor focus/hotplug and an audible listening session require interactive
validation.
