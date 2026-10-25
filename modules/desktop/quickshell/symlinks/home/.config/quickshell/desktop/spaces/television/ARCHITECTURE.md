# Television implementation

## Presentation and hosting

Television is a new `television` entry in the existing `SpaceState`/`SpaceHost`
contract, independent of TV Series and Radio. Spaces uses Lucide's `antenna.svg`,
covered by the existing icons license. The browser shares Movies' immersive
palette, typography, controls and scrolling, and Radio's filter popup component.
It has a black background, the Channels label/count and search/filters in the
shared top row, and a virtualized vertical channel list. There is no Radio-style
large now-playing heading and no Nextcloud integration. Channel rows show country, feed languages, categories,
numbered alternate streams/qualities, optional website and favorite actions.
Missing websites reserve the same space so stream selectors stay aligned.

Open lazily creates one retained instance and worker. Hide preserves list position,
filter/search drafts, chosen streams, favorites and playback. Search debounce,
pagination, status polling, spinners and menus stop while hidden; an in-flight
catalogue refresh may finish into the cache. Restore reads current player state
and applies deferred browsing. Close destroys the worker and its owned player
group without disturbing other Spaces. The host X always hides. Escape dismisses
menus, filters, search text and search mode before hiding. Enter watches the
selected channel; Space pauses/resumes an active player or starts the selection.

## Catalogue and availability

`catalogue.py` reads the fixed HTTPS [IPTV-org API](https://github.com/iptv-org/api):
channels, streams, feeds, countries, languages, categories and blocklist. Four
bounded reader threads fetch these lists, each with a 12-second timeout and a
24 MiB response limit. A successful refresh atomically replaces one normalized
snapshot; partial failures and empty results retain the prior snapshot. Initial
open uses cached data immediately and refreshes when older than a day. Later
Refresh is explicit; there is no periodic network refresh while hidden.

Provider channel IDs remain stable. Streams are grouped beneath their channel;
feed names/languages and resolution/availability labels come from the provider.
Unidentified streams use a stable URL/header hash and their supplied title,
with unknown metadata left blank. Unsupported protocols, closed/adult channels
and the provider blocklist are excluded from discovery. Only public HTTP/HTTPS
stream addresses are accepted. Header values reject control characters. Stream
IDs include the URL, User-Agent and Referer so entries requiring different headers
are distinct. Non-geoblocked streams sort before restricted variants, then by
resolution. Labels are informational; no background probing of thousands of
channels is performed and a listed stream is not a playback guarantee.

Search covers names/aliases, countries, languages and categories. Country,
language and category filters combine; results use finite 100-channel pages.
One discovery list pins local favorites without separate browse tabs. Favorites
use current provider data when present and retain their last complete stream
snapshot if the directory is offline or a channel disappears. Private records
are validated before replacement;
invalid records are reported without erasing their file. Anonymous public streams
may lack a country, language or category and consequently do not match those
specific filters. Logos and EPG data are not fetched.

## Desktop mpv playback

`backend.py` uses the existing JSON-lines Worker with separate read and ordered
control lanes. Catalogue refresh cannot block local favorites, Pause or Stop.
UI request generations reject stale browsing/status/launch callbacks. Playback
selects an existing channel/stream ID from the cached catalogue or a saved
favorite, rather than accepting arbitrary command lines from QML. A stale stream
selection fails explicitly.

`player.py` owns a standard standalone mpv window. Embedding an external Wayland
window into the shell's layer surface is avoided; successful Play hides the
browser so the native mpv window is accessible. The instance retains its state
and the drawer can restore it. The player uses the user's existing mpv config,
uosc, hardware decoding, shader and power-profile setup where installed. The
quickshell module already provisions mpv and mpv-mpris; a fresh setup without the
optional mpv module still uses mpv's standard controls. MPRIS uses the normal
installed mpv plugin with identity `Television`, so Sound can control it.

No global streaming profile is installed. Per-launch settings enable network
caching, cap forward/back cache at 64/16 MiB, prefetch up to 20 seconds, wait for
one second of initial/rebuffer data and use a 15-second network timeout. These
are buffering settings, not a promise of low broadcast latency. The stream's
required User-Agent/Referer are passed as validated argv options. Renderer,
decoding and audio-device choices stay with the existing mpv configuration.
See [mpv caching](https://mpv.io/manual/master/#cache).

Each player starts in an owned process group. Replacement, Stop, natural exit
and explicit Space close terminate/reap the player and release script-owned
thumbnail helpers, with bounded TERM/KILL teardown. The instance-private mpv
socket is removed. IPC transport is reused from Pictures without starting its
runtime, under Television's own owner-only runtime directory. Status polling runs
every two seconds only while the browser is visible and the player is running.
Closing mpv directly does not reopen or focus the browser unexpectedly; restore
observes its exit and any generic stream failure. Closing the shell ends playback.

## Portable state and fresh install

The quickshell module owns these `extra.private.files` declarations:

- `home/.config/quickshell/desktop/spaces/television/television-ui.json`: country,
  language/category choices and selected stream IDs by channel ID.
- `home/.local/share/quickshell/desktop/spaces/television/favorites.json`: complete
  favorite channel/stream snapshots, including public provider headers.

Files use atomic 0600 replacement and their leaf directories use 0700. Search
text and active playback remain in the retained instance. The
regenerable catalogue is under `$XDG_CACHE_HOME/quickshell/desktop/spaces/television/`;
mpv sockets are under the owner-only `quickshell-television-UID` runtime directory.
Caches, sockets and streamed video are excluded from private backups. Television
has no account, secret or machine-bound credential to recover.

The verified private checkout is `/home/arvigeus/Projects/dotfiles-private`.
`backup.sh` snapshots the generated declarations into its `modules/backup/` tree.
On a clean system install the public quickshell module, then run the private
checkout's standalone `apply.sh` as the regular user. It creates parents,
restores file modes and preserves existing destinations as `.before-private-*`.
The optional mpv module restores the managed player UI/configuration. The private
snapshot remains uncommitted, so synchronized fresh-install recovery remains
incomplete until its owner commits and synchronizes it. No private commit or
upload is automatic.

## Validation

`tests/test_television.py` covers provider grouping/feeds, exclusions, anonymous
streams, headers, pagination, filters, offline snapshots, favorites, corruption
preservation, stream identity, mpv argv/config inheritance, switching, pause/stop,
worker close and plugin-helper process groups. Fixture tests never play host
audio or mutate audio devices. `test_television_playback.py` generates a local HLS
fixture and uses real mpv with null audio/video outputs; it verifies decoding,
private normal-config inheritance, pause/resume and cleanup.

`test_television_space.py` exercises the shared fullscreen host with production
workers, fixture provider data and a fake native player. It checks the compact
layout, icon, website spacing, paging, nested Escape, favorites, native-player
handoff, hidden timers, restore, independent close and fresh-instance preferences.
`test_television_private.py` verifies backup → temporary Git clone → standalone
restore, all stream fields/preferences, restrictive permissions and collision
preservation, with no account or cached directory required.

Run `python3 -m unittest discover -s tests -p 'test_television*.py' -v`.
The eleven Television checks and fifteen shared-host/Movies/Books/Radio
regressions pass. The actual private snapshot also passes isolated standalone
restore, byte equality, restrictive modes, collision preservation and fresh
offline initialization. Generated configuration passes offline archinstall
validation. Live provider reads and an NHK World-Japan video probe pass. Interactive native
window focus, audible output and multi-monitor hotplug still require live use;
stream availability and regional restrictions vary by channel.
