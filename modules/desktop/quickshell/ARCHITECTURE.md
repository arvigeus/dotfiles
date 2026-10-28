# Desktop shell implementation

Sources live under [desktop/](symlinks/home/.config/quickshell/desktop/).
Provisioning and module conventions are in the [root architecture](../../../ARCHITECTURE.md).

Pictures owns session wallpaper surfaces, animated playback and the Displays
random action; see [Pictures architecture](symlinks/home/.config/quickshell/desktop/spaces/pictures/ARCHITECTURE.md).

## Package ownership

This module owns Quickshell, Qt Multimedia, cliphist, wl-clipboard, capture tools,
the iCalendar libraries, PySide6, Python GObject, AccountsService, mpvpaper and
the Wallpiper Hyprland portal. Hardware
modules own audio,
Bluetooth, networking, storage, display tools and battery reporting. UPower is
shared by hosts; `hardware/power` owns the Zephyrus power policy. Notifications
activation belongs to `desktop/notifications`; GTK, Dolphin and terminal settings
belong to their respective modules.

## Lifetimes

`desktop-shell.service` belongs to `graphical-session.target`. The shell root
starts services needed across drawers: notifications, calendar warming, display
comfort/layout policy, clipboard control, power utilities and capture state.
Other helpers run only while observed or while completing an action.

`InteractionState` owns one interactive surface across all outputs.
`InteractionWindow` handles focus, keyboard ownership, backdrop clicks and Escape.
`DrawerHost` owns the catalogue, shortcut registrations, sliding card and one lazy
`DrawerPage`. Dismissal clears `active` immediately; the page remains during its
exit animation. Entrance waits for the lazy page to become ready (or fail), so
cold module/device initialization cannot stop the card halfway through its slide.
Page-owned popovers consume Escape first. Bind observation and
cancellable work to `active`; put operations that must survive dismissal in a
feature service. Header actions belong to the page.

Installed QML files are individual symlinks into this checkout. Existing-file
edits reload automatically. Adding a component requires regeneration and apply
to publish its link before any importer reloads. Restart the service after
publishing when the running engine has cached a missing type.

`Apps.launch()` uses `uwsm app -t service` to put user-facing applications in their own
units. The launcher uses service mode with the desktop entry ID so UWSM handles
field codes, working directories and terminal entries. Helpers keep their parent
service's lifetime. Shell restart therefore releases temporary controls while
applications launched through UWSM remain running.
The shell service uses `UMask=0077` for private history and helper output;
applications in their own service units use the user manager's ordinary mask.

## Buttons and models

`Theme` defines logical-pixel sizing and reads the shared light/dark palette.
Theme mode is a user preference in `theme-mode`, defaulting to dark; apply does
not seed it. Production starts synchronization through `Theme.start()`;
see [appearance integration](../../look-and-feel/ARCHITECTURE.md).
`IconButton`, `ShellButton`, `ShellChoice` and `ShellMenuItem` share styling.
`ShellChoice` uses the same checked menu rows as Cloudflare settings in a bounded,
scrollable popup, retaining native ComboBox keyboard and model-role behavior.
`Card` centralizes static card appearance: the surface fill, one-pixel border
and control corner radius. Battery/power, disks, displays, keyboard backlights,
audio devices/applications, Bluetooth, webcams and weather summary/hourly/forecast
cards use it. Static containers do
not gain a hover action; their nested controls remain independent. Performance
and keyboard language choices use `ButtonBackground` with the same surface and
idle border, retaining their selected-state tint.
`HoldButton` cancels on release, focus loss, disabling or dismissal; a held
key's auto-repeat remains one hold.
`PassiveToolTip` appears after a delay on hover or keyboard focus, without
taking clicks or focus. Pointer and programmatic focus show no tip.
`WheelScroll` and `ScrollListView` handle pointer wheels and touchpad scrolling.
`DrawerColumn`, `ScrollListView` and the Spaces' `ScrollArea` scroll keyboard and
programmatic focus into view once layouts settle; pointer focus never scrolls.
`wheelInput.reveal(item)` shows any other item.

Native QObject lists use `ScriptModel`. Plain keyed snapshots use `KeyedModel`,
a dynamic `ListModel` reconciled by `ui/Models.js`. It updates records after moves
while preserving delegates and focus. Quickshell 0.3.2's `ScriptModel.objectProp`
can leave a moved delegate's `modelData` stale. Model roles remain `modelData` so
controls and choices can share them.

## Spaces

Movies, TV Series, Games, Pictures, Books, Radio, Television, Streaming and Music are fullscreen, retained Spaces;
remaining entries are placeholders. Space modules use their own immersive
presentation rather than the shell's gray controls or light/dark variants, and omit in-module Spaces links.
See the presentation contract in [Movies architecture](symlinks/home/.config/quickshell/desktop/spaces/movies/ARCHITECTURE.md)
for lifecycle, provider, worker and private restoration details.
All Space headers use the shared activity indicator for concurrent work and
progress. The host's page-opening indicator is a 28-pixel `BusySpinner` in the
headers' red; `ui/` does not import Space modules. Idle headers have no status marker or history tooltip; completed jobs
remain in notification/activity panels. Actionable errors remain inline.
For Games providers, artwork and beat times, see the
[Games architecture](symlinks/home/.config/quickshell/desktop/spaces/games/ARCHITECTURE.md).
For Books metadata, private providers and local reading, see the
[Books architecture](symlinks/home/.config/quickshell/desktop/spaces/books/ARCHITECTURE.md).
For Music catalogue/providers, queue playback and private restoration, see
[Music architecture](symlinks/home/.config/quickshell/desktop/spaces/music/ARCHITECTURE.md).
For YouTube feeds, native playback, Gemini analysis and downloads, see
[Streaming architecture](symlinks/home/.config/quickshell/desktop/spaces/streaming/ARCHITECTURE.md).
`spaces/profile.py` reads public
AccountsService data, passwd GECOS and standard photo fallbacks on opening.
Photos use an mtime URL suffix and no cache. `ProfileButton` launches Account tools in
its own unit. See [account editor](#account-editor) for its data and write boundaries.

`SessionService` makes on-demand capability/status/action requests to
`spaces/backend.py`. Systemd owns shutdown scheduling. Supported delays are
15/30/60/90/120/180/240/300 minutes. `gaming` and `reload` call `session-mode`;
see [session ownership](../hyprland/ARCHITECTURE.md#session-ownership).
Destructive actions require a two-second hold. Popovers are mutually exclusive
and close on dismissal. Sleep/locking pauses delegate to `ComfortService` and
last only for the shell lifetime.

## System tray and bar badges

`SystemTray` remains registered while the drawer is closed. Tray delegates retain
native items and their application-owned menus. Activation, secondary activation,
scrolling and context menus use the native APIs; XEmbed is unsupported.
Attention combines item status with unseen matching notifications. Activation
acknowledges matching notification history. App matching must be unambiguous;
ordinary unread application state cannot be inferred without a notification or
attention request.

Badges and status widgets read native services. Detailed telemetry belongs to
open drawers. Window/workspace navigation uses the shared Hyprland Lua policy.
Window order follows client positions, refreshed 180 ms after the first event of
a burst; a steady stream such as focused-window title changes cannot postpone
it. Bindings send `desktop-layout-changed` after actions for which Hyprland
lacks a native geometry/order event.

Each bar records attention from Hyprland's `urgent`, `activewindowv2` and
`closewindow` events, so a request lasts until that window gains focus.
Quickshell 0.3.2 instead clears every window once its workspace gains focus.
Records start empty after a reload and on a newly attached output.

Window tabs share the strip down to 96 px before it scrolls; shrunk tabs show
their close button only on hover. The strip follows the focused window like the
compositor view. Edge markers count tabs not wholly in view; clicking one
reveals the nearest hidden window needing attention, otherwise scrolls a page.
A marker's width includes its fade, so revealed tabs stay clear of both.
`tests/test_desktop_workspaces.py` runs the bar against a fake Hyprland IPC.

## Clipboard

Two `cliphist@text/image.service` instances run `wl-paste --watch cliphist store`
for the graphical session. The cliphist config sets retention to 50 items.
They survive shell reload and are stopped with the graphical session.
`clipboard/backend.py` controls the units and adapts list/copy/delete/wipe and
image preview operations; pausing stops both units and is not persisted.

History remains in cliphist's database. Preview files are private, limited to 32
cached images and removed on helper exit/start. Copies decode by ID and pass bytes
to wl-copy through stdin, never shell interpolation. Closing the drawer cancels
preview work; clipboard collection is independent of the drawer.

## Capture

Screenshots use `desktop-screenshot` (grim/slurp); see
[Hyprland capture integration](../hyprland/ARCHITECTURE.md#desktop-integration).
`CaptureService` freezes the selected options for countdowns, dismisses the drawer
before capture and cancels a countdown when Capture reopens. `screenshot-editor`
and `screenshot-save` are user-owned on/off preferences shared with shortcuts.
Clipboard-only capture overrides editing and produces no file or notification.
Screenshot and recording-region processes explicitly close stdin after each
spawn. Slurp reads non-terminal stdin for suggested boxes before showing its
overlay; an open, unused Qt pipe otherwise leaves selection waiting indefinitely.

Recording belongs to socket-activated `desktop-capture.service`, independent of
shell reloads. `desktop-capture.socket` exposes a private runtime Unix socket at
`desktop-capture/control.sock`; QML connects directly and sends newline JSON.
Each client receives state after requests and changes. The service exits after
30 seconds with no recording/client, leaving systemd to reactivate it.

`capture/recorder.py` owns only its GPU Screen Recorder child and process group.
Start/stop/pause/resume and preference changes use the socket; stopping the
session finalizes the MP4 before bounded teardown. Recordings use XDG Videos under
`Recordings`, H.264/AAC, with remembered system-audio/microphone/pointer choices in
`recording.json`. Region selection uses Slurp and is cancelled on conflicting UI.
A shell reconnect recovers the existing recording state rather than starting one.

`WebcamService` enumerates through V4L2; `WebcamControls` reflects supported types,
ranges and writability. Mutations validate device identity/control support.
Preview belongs to the drawer and stops on dismissal or device loss. Privacy is
available only when the camera exposes it; other apps may change camera settings.

## System

`system/backend.py` reads Arch/systemd information on demand: boot phases, slow
units, failed services and timers. It does not use Debian's reboot-required flag.
Actions launch `package-maintenance`, `system-update` (with a Topgrade fallback),
and logs in independent terminal
units. Package maintenance and signing repair belong to the package modules.

## Networking

`WifiDrawer` and the bar read `Quickshell.Networking`: radio/hardware block,
connectivity, Wi-Fi networks, saved-network activation and Ethernet. Saved-network
deletion belongs to NetworkManager's connection editor, not the Wireless rows.
Scanning belongs to the open drawer. Native QObject identity keeps list delegates
stable; sorting uses connected, saved, signal-icon level and name.

`NetworkService` invokes `network/backend.py` for VPN/WireGuard profiles, WARP,
IP details and new user-scoped Wi-Fi profiles. It refreshes every ten seconds only
while observed. Mutations finish after dismissal and take priority over reads.
Passwords use stdin/D-Bus and never argv, status records or diagnostics.
Enterprise/WEP configurations open the connection editor.
WARP starts on demand, reuses registration or creates it only when missing, and
stops on disconnect or setup failure. Its menu selects operating mode; registration
requires no separate switch. See the [WARP lifecycle](../../internet/cloudflare/ARCHITECTURE.md).
Wi-Fi, Ethernet and VPN/WARP rows share the keyboard language choices' active
style: connected rows have an accent-tinted fill and normal text/icons; inactive
rows are transparent and muted. Hover/focus adds the shared accent border/icon.
Cloudflare's toggle and settings cog share one background for connected,
hover/focus, pressed and open-menu states; their click actions remain separate.

The VPN heading's add menu launches `network/backend.py --import-wireguard`
through `Apps`, in its own application unit. Zenity owns the `.conf` picker,
independent of the shell's layer surface and drawer dismissal. Acceptance opens
`nm-connection-editor --type wireguard --import` for review and saving;
cancellation creates nothing. Only the local filename is passed in argv, never
config contents. The shell module owns the Zenity dependency.
The existing profile refresh discovers saved imports; importing does not activate
the tunnel.

`PublicIpService` queries only on opening information, caches for ten minutes and
invalidates on route changes. The speed test follows the current route and is
cancelled on dismissal. Interface transfer counters are distinct from that test.

Ports uses the unprivileged `firewall-ports` client; see
[firewall architecture](../../system/security/firewall/ARCHITECTURE.md).
Openings are runtime IPv4 rich rules scoped to the current source subnet and
local destination address. A network change makes mismatched rules inert; rules
can apply again if the same address/subnet/zone returns. Reload/reboot removes
them. Closing a rule does not terminate established connections.

`DeviceDiscoveryService` starts when the collapsed Devices heading is clicked.
The heading fills the available width with no separate refresh control. The body
stays collapsed with a scanning summary until discovery finishes, then opens the
results, empty-result message or error. The idle summary shows the discovered
device count. A repeated click during scanning leaves the pending request intact;
collapsing finished results and clicking again starts a fresh scan. Dismissal or
an interface change discards pending expansion so late results cannot reopen it.
`NetworkSection.toggle()` supplies the normal immediate toggle; Devices overrides
it to defer expansion until the service has finished and published its result.
Default section icons sit inside the heading button, sharing its hover highlight
and click target.
The separate `network/discovery.py` helper derives scope from the selected connected
interface's private IPv4 address, limits a broad subnet to its local /24, and runs
unprivileged Nmap host discovery without port scanning or reverse DNS. It retains
reachable IPv4 addresses and reported response times. Device tooltips identify
local addresses and the gateway from the selected interface's existing connection
details, and show response time when available. Device rows are informational.
Dismissal, route/interface changes and cancellation stop the owned scanner;
no periodic discovery runs. Nmap belongs to
`hardware/network`, not the shell or Dolphin. Public/unsupported networks fail
without a scan. Results remain until refreshed or the connection context changes.

## Bluetooth

The drawer reads native `Quickshell.Bluetooth` adapters/devices and issues native
power, connect, disconnect and forget operations. Connecting explicitly trusts a
device for future reconnection; observation never does. Native failures expose no
reason text, so the service reports a generic connection failure.

Only pairing uses `bluetooth/backend.py`: it registers an Agent1 on a private
D-Bus connection and makes Pair() itself so BlueZ routes prompts to that agent.
It checks BlueZ sender/device identity, validates PIN/passkey responses, and
cancels after 60 seconds or drawer dismissal. After Pair() succeeds, trust/connect
finishes independently of dismissal. Searching stops after 30 seconds or dismissal
and only releases discovery owned by this drawer.

## Playback

`AudioService` uses native PipeWire nodes, audio controls and link groups for
volume, mute, default devices, routing display and app streams. `PwObjectTracker`
binds detailed objects only while a drawer observes. Levels use the loudest
channel; changing level preserves channel balance. Link state distinguishes
recording from paused capture. MPRIS controls associate only with uniquely
matching application streams. When several streams match the same desktop
application, a unique media identity/application label pair can distinguish them
(for example Radio and a separate mpv player); otherwise controls stay in the
Playback section.

`audio/backend.py watch` supplies labels, cards, ports, profiles and input
availability. It subscribes to Pulse card/sink/source events, debounces reads and
publishes only changed inventory. Endpoint change events are needed for external
port switches, even though they can also be native volume/mute changes. The
subscription dies with its watcher. One-shot helper operations cover card
profiles, output/input ports, hardware input enablement and stream moves.

Boost is a per-device `boostDevices` map in `audio.ini`. Disabling it caps that
device and its streams immediately. Moving playback to a device without boost
caps that stream to 100%. Route changes enforce the route ceiling, preserve mute
and recheck identity/availability. Default changes do not move existing streams.
Hardware input enablement is separate from mute and preserves playback profiles.

## Audio configuration

Hardware modules install JSON drop-ins in `$XDG_CONFIG_HOME/devices/audio/`.
Files contain `rules` and an optional `profiles` map of native profile IDs to
labels. A rule needs a nonempty `label`, plus `match` (exact property values) or
`contains` (substrings); both combine with AND. Node/port properties also expose
`node.name`, `node.description`, `port.name` and `port.description`.
Optional fields are `deviceLabel`, `icon`, `maxVolume` (1–150, default 150) and
numeric `priority` (default 0). The first matching rule wins after descending
priority sort; ties keep file/rule order. `{port}` in a label inserts the
connection name. Icons are volume-2, headphones, monitor, bluetooth, speaker,
mic or mic-off. Malformed files and conflicting profile labels are skipped with
warnings; valid files remain usable.

`AudioTestService` runs `audio/probe.py` only during a test. Playback visits native
channels; microphone capture is bounded and requires a live unmuted input.
Release stops capture before playback, while cancellation discards it. Test
streams have a dedicated application ID and never appear in the app mixer.

## Displays

`DisplayService` serializes one-shot display/brightness helpers. Hyprland monitor
and config events are debounced; no repeating display-layout reader runs while
closed. Brightness refreshes while observed. Snapshot tokens and hardware
identities reject stale edits; fallback outputs never count as usable displays.
Controls validate modes, scaling, transforms, mirrors, overlap and at least one
independent enabled output. Replacements are verified before disabling the old
screen; failures attempt to restore the previous connected setup.

The monitor cog is a persistent form popover for resolution, refresh, scale,
orientation and mirroring; each edit applies and saves without closing the form.
Resolution changes retain the nearest refresh and reset scale to 100% only when
the old scale cannot produce whole logical pixels. Geometry changes preserve
gaps to neighboring outputs before overlap validation.

`display-tools` is an independent PySide6 arrangement app. Its desktop entry and
the drawer header launch it through the normal application lifetime. It calls
the same helper with QProcess, never blocks the UI, and subscribes to Hyprland's
event socket for debounced updates. Its scene uses logical pixels after rotation
and scale; dragging snaps edges within twelve view pixels (Shift disables it).
Arrow keys move one logical pixel; Shift+arrows move ten. Coordinates are staged
until Apply arrangement, which verifies and saves in one request. Unapplied edits
survive external changes but cannot apply until reloaded; close/reload confirms
discarding them. The Close button, window controls and Escape share that guard;
a confirmed close completes the dialog through the base rejection path.
The helper validates the complete snapshot token and accepts
only coordinates from the arrangement app.

User preferences live in `~/.config/hypr/display-profiles.json`, version 1, with
a `profiles` object keyed by a hash of the sorted connected hardware identities.
Every profile maps device keys to enabled/mode/scale/transform/x/y/mirror values;
mirror sources are hardware keys, resolved to current connectors on restoration.
Serial/make/model identify hardware across ports; unique descriptions are the
fallback. Ambiguous or anonymous devices require the connector and therefore
cannot reliably follow a port change. Disabled but connected devices belong to
the set. Profiles match exact sets, never subsets. Only explicit settings edits
or Apply arrangement update the source; hotplug, wake and Powersave never do.
The private backup declaration covers this source file.

`displays.lua` is the generated active profile, loaded after host defaults and
reconstructed on startup/hotplug. It contains native `hl.monitor` rules for only
the current set; other profiles stay in JSON. Rule selectors use descriptions
only when unique by Hyprland's prefix matching, otherwise connectors. Both writers
use atomic replacement; persistence failure restores the source/cache and live
layout. The app and shell helpers serialize through a session-local flock,
including snapshots, so independent instances cannot interleave writes.

An unseen set starts enabled, independent and side by side without creating a
saved profile. Startup/hotplug select saved preferences; native rules handle
ordinary reloads. Dark panels defer restoration until the wake event. If
undocking leaves only disabled outputs, emergency recovery enables one, preferring
the internal panel, even when a saved profile is invalid. Replacements are verified
before a saved panel-disable choice is applied. Unsupported saved modes report an
actionable error and leave the source intact.

Powersave caps enabled internal panels to an available mode at or below 60 Hz in
live rules only; leaving Powersave restores their configured mode. Explicit
refresh changes override the cap until the next profile change. Blank panels are
not awakened for policy; wake events retry deferred work. The saved rules retain
the uncapped choice. Display recovery also uses the Hyprland workspace policy.

Physical brightness uses backlight/DDC providers and validates identity before
writing. It is not restored from the layout. Identify/test-pattern windows are
session-owned and bounded; Escape/click closes them. Webcam/display tests are
separate from screenshot/recording ownership.

### Night light and Keep awake

`ComfortService` owns a persistent request helper for temporary leases. Night
light enables/disables the packaged `hyprsunset.service` with `--now`; enablement
remembers the choice. Managed `hyprsunset.conf` supplies filter settings.

Keep awake records connector plus hardware identity under the current Hyprland
runtime directory. Each lease has an advisory lock and atomic JSON; dead locks
are ignored. Disconnect/replacement prunes leases. Session sleep/locking pauses
use separate leases. All end on shell exit/reload.

Hypridle calls `desktop-idle`: blank only unprotected displays, defer automatic
locking/suspend for active leases, and respect application inhibitors. Helper
exit codes are 0 allow, 1 defer, 2 error. Locking proceeds on helper failure;
suspend stays blocked. Manual lock and before-sleep locking are unconditional.

## Keyboard

`InputLanguage` talks to the `input-method` controller; that module owns layouts,
Fcitx and persistence. Native keyboard events update the bar. The drawer only
selects languages, a secondary language and reference text; typing clears on close.

Lighting providers live in `$XDG_CONFIG_HOME/devices/keyboard/backends/` and are
installed by hardware modules. `BacklightService` validates provider/device
identity and serializes writes. Brightness zero means off, not disabled input.
Colors/effects/modes appear only when supported. The Logitech backend owns its
manual/automatic mode transitions and rollback; see the peripheral architecture.

The Keyboard drawer's header info button sits beside input-method settings and
opens the reference with Shortcuts first, followed by Telex and Phonetic maps.
The shortcut tab reads `hyprctl -j binds` when opened, again every five seconds
while visible, and after Hyprland config reloads. The helper excludes mouse
binds, formats modifier masks and submaps, and uses each bind description or its
dispatcher and arguments as a fallback. Lua callbacks without descriptions show
as custom actions. This lists compositor binds; portal-assigned Quickshell global
shortcuts are managed separately.

## Disks and system cleanup

`DisksService` reads UDisks2, groups physical drives and exposes mount, unmount,
unlock and health operations. System mounts cannot be unmounted. Passwords use
stdin/D-Bus. Actions survive dismissal; health reads do not wake sleeping ATA
hardware. Filelight, Dolphin and the partition editor launch in independent units.

`CleanupService` scans recoverable caches and selected tool/container resources.
The preview freezes a plan before confirmation; a held action applies it with
bounded diagnostics. Cleanup uses npm/pip/mise's own commands and one Podman
inventory query. Package cleanup may authenticate. It does not remove personal
files, active tools or containers through guesses about directory names.

## Battery and performance

Battery packs/peripherals and aggregate state come from native UPower. Profiles,
performance availability, degradation and holds come from native PowerProfiles.
`PowerService` reads charge providers every ten seconds while observed; detailed
telemetry/policy warnings every two seconds only in Performance. Sleeping GPUs
remain asleep. GPU/fan snapshots use keyed models so new readings update rows.

`PowerSession` runs `power/session.py` for one-time full charging and workload
recordings. It forwards UPower's battery state (null without a ready system
battery). Charge-once saves the prior limit, requires AC, restores on unplug,
manual request or reboot, and retains unfinished restoration state in
`session.json`. An unplug/replug while the shell is absent cannot be detected.
Manual limit changes cancel the saved restoration.

`power-study` records the current workload until stopped, writing samples and a
summary. The session helper owns its exact child and signals; shell exit/reload
ends recording. The power module owns profile definitions, AC/DC policy and
mpv's live profile updates; see [power architecture](../../hardware/power/ARCHITECTURE.md).

## Time and weather

`WeatherService` reads user-owned `weather.json`, caches forecasts by place and
refreshes the current place every 30 minutes. Other places fetch only while
selected and stale. Failed/offline reads retain saved data and timestamps.
Public weather requests contain coordinates and use bounded timeouts.

`weather.json` contains `locations` and optional `islandLocation` (the selected ID):

```json
{"islandLocation":"saigon","locations":[{"id":"saigon","name":"Ho Chi Minh City","detail":"Vietnam","latitude":10.82,"longitude":106.63,"timezone":"Asia/Ho_Chi_Minh"}]}
```

IDs must be unique, coordinates finite/in range, and `detail` is optional. The current
place controls the bar; browsing does not change system time. Pinning sets the
current place and uses the desktop timezone polkit rule. `weather/backend.py`
validates the format and IANA timezone names.

Alarms and focus/break reminders belong to the shell lifetime, continue with the
drawer closed and clear on exit/reload. Alarms use local system time; a timezone
change follows that wall clock. Timers send desktop notifications and cannot wake
a sleeping machine. Reminder popovers own their focus and dismiss before drawers.

## Events, tasks and notification history

Calendar uses `icalendar` for parsing/serialization, `recurring-ical-events` for
event expansion and dateutil for task recurrence advancement. ETags and scoped
DAV transport protect writes. Cached views work offline; writes require a
connection. See [calendar architecture](symlinks/home/.config/quickshell/desktop/drawers/events/ARCHITECTURE.md)
and [Nextcloud account ownership](symlinks/home/.config/quickshell/desktop/integrations/ARCHITECTURE.md).

`NotificationCenter` owns the native NotificationServer and writes bounded,
normalized history through an atomic `FileView`. It loads before accepting
notifications, retains plain text and safe local icon references, and strips live
images/actions from saved state. A short debounce batches writes. Do Not Disturb
is saved; transient notifications are not retained. Popups have bounded count,
hover-paused expiry and application-owned actions. Opening history acknowledges
unseen items. See [notification lifecycle](symlinks/home/.config/quickshell/desktop/drawers/notifications/ARCHITECTURE.md).

## Validation

Run `python3 -m unittest discover -s tests -v`. QML tests use offscreen surfaces,
private config/runtime/state and fake hardware/helpers; native panel checks need
a Wayland backend. `tests/support.py` holds shared QML fixtures. Run the suite
under `dbus-run-session` for notification tests and with `PIPEWIRE_REMOTE` set to
an unavailable test remote. Tests must never start real recordings or mutate
host radio/audio/power state.

Validate generated configuration and run ShellCheck with `--shell=bash` for
sourced fragments. After apply, verify installed links as well as repository
sources, Hyprland config errors, service state and journal warnings. Hardware
lock/suspend, hotplug, pairing, captures and a DRM/Steam round trip still need
actual device interaction; isolated fixtures do not prove those paths.

## Account editor

`account-tools` is a PySide6 application installed with this module. Its desktop
entry is available in the launcher and the Spaces profile button launches it.

`account_core.py` reads only the current UID via passwd/NSS and AccountsService.
Group membership comes from `getgrouplist`, including the primary group, rather
than the launching process's possibly stale supplementary groups. UID/GID, home,
shell, groups and available account/login flags are read-only. Full name, email,
location and photo use the native SetRealName/SetEmail/SetLocation/SetIconFile
methods with interactive PolicyKit authorization; no direct account-file writes,
sudo, group administration or password handling is implemented. Email/location
are profile metadata, not mail-client or session configuration.

QProcess runs the helper outside the UI thread. Requests accept only the four
editable string keys and always target the caller's UID. Writes are sequential;
partial success is reported per field, and failed changes remain editable.
Unavailable AccountsService still permits local account/group inspection.
Photo selection normalizes a bounded image to a PNG no larger than 512×512;
temporary images remain alive until the dialog closes so draft/discard cycles
work, while AccountsService owns the saved copy. Saving prevents closing until
the request finishes; refresh and close confirm discarding unsaved edits.

`tests/test_account_tools.py` uses fake services and an offscreen dialog to cover
current-user targeting, validation, partial failures, unavailable services,
groups, drafts and asynchronous request dispatch. Tests never modify an account.
