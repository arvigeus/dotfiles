# Desktop shell implementation

Sources live under [desktop/](symlinks/home/.config/quickshell/desktop/).
Provisioning and module conventions are in the [root architecture](../../../ARCHITECTURE.md).

## Package ownership

This module owns Quickshell, Qt Multimedia, cliphist, wl-clipboard, capture tools,
the iCalendar libraries and Mugshot/AccountsService. Hardware modules own audio,
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
exit animation. Page-owned popovers consume Escape first. Bind observation and
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

`Theme` defines logical-pixel sizing and the light/dark palettes. Theme mode is a
user preference in `theme-mode`, defaulting to dark; apply does not seed it.
`IconButton`, `ShellButton`, `ShellChoice` and `ShellMenuItem` share styling.
`HoldButton` cancels on release, focus loss, disabling or dismissal.
`PassiveToolTip` uses passive hover/focus observation without stealing clicks.
`WheelScroll` and `ScrollListView` handle pointer wheels and touchpad scrolling.

Native QObject lists use `ScriptModel`. Plain keyed snapshots use `KeyedModel`,
a dynamic `ListModel` reconciled by `ui/Models.js`. It updates records after moves
while preserving delegates and focus. Quickshell 0.3.2's `ScriptModel.objectProp`
can leave a moved delegate's `modelData` stale. Model roles remain `modelData` so
controls and choices can share them.

## Spaces

The space entries are placeholders. `spaces/profile.py` reads public
AccountsService data, passwd GECOS and standard photo fallbacks on opening.
Photos use an mtime URL suffix and no cache. `ProfileButton` launches Mugshot in
its own unit. The managed Mugshot wrapper uses AccountsService and suppresses its
obsolete sudo/chfn probes; the packaged executable remains unchanged.

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
The shell debounces layout refreshes; bindings send `desktop-layout-changed`
after actions for which Hyprland lacks a native geometry/order event.

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
Actions launch `package-maintenance`, Topgrade and logs in independent terminal
units. Package maintenance and signing repair belong to the package modules.

## Networking

`WifiDrawer` and the bar read `Quickshell.Networking`: radio/hardware block,
connectivity, Wi-Fi networks, saved-network activation, forgetting and Ethernet.
Scanning belongs to the open drawer. Native QObject identity keeps list delegates
stable; sorting uses connected, saved, signal-icon level and name.

`NetworkService` invokes `network/backend.py` for VPN/WireGuard profiles, WARP,
IP details and new user-scoped Wi-Fi profiles. It refreshes every ten seconds only
while observed. Mutations finish after dismissal and take priority over reads.
Passwords use stdin/D-Bus and never argv, status records or diagnostics.
Enterprise/WEP configurations open the connection editor.

`PublicIpService` queries only on opening information, caches for ten minutes and
invalidates on route changes. The speed test follows the current route and is
cancelled on dismissal. Interface transfer counters are distinct from that test.

Ports uses the unprivileged `firewall-ports` client; see
[firewall architecture](../../system/security/firewall/ARCHITECTURE.md).
Openings are runtime IPv4 rich rules scoped to the current source subnet and
local destination address. A network change makes mismatched rules inert; rules
can apply again if the same address/subnet/zone returns. Reload/reboot removes
them. Closing a rule does not terminate established connections.

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
matching application streams.

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

Confirmed changes persist as native `hl.monitor` rules in the user-owned
`~/.config/hypr/displays.lua`, loaded after host defaults. Descriptions are used
only when they uniquely identify a connected output; ambiguous descriptions fall
back to connector names. Atomic writes preserve unrelated/disconnected rules.
Hyprland owns reload/hotplug matching. External-tool changes require Save layout.
If undocking leaves only disabled outputs, the helper temporarily enables one,
preferring the internal panel; it does not persist that emergency fallback.
On redocking, a saved panel-disable rule returns only after verifying a usable
independent external output. This preserves dock-only preferences safely.

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
