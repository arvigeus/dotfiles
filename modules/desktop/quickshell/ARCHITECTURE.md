# Desktop shell implementation

Sources live under [desktop/](symlinks/home/.config/quickshell/desktop/).
QML edits reload automatically.
Repository provisioning rules are in [the root architecture](../../../ARCHITECTURE.md).

## Package ownership

This module declares Quickshell, Qt Multimedia, AT-SPI, V4L2 control tooling, cliphist and
wl-clipboard. Hardware modules own
audio, Bluetooth, networking, storage, display tools and battery reporting,
including the external editors launched by drawers. `hardware/battery` declares
UPower and its service for every host; `hardware/power` owns the Zephyrus-only
power policy.
Notifications belong to `desktop/notifications`, Dolphin and its administrator
integration to `files/dolphin`, GTK to `look-and-feel/gtk`, terminal launching to
`base/terminal`, and Python GObject bindings to `dev/languages/python`.
The hardware modules also own suppression of their packages' login applets:
[networking](../../hardware/network/ARCHITECTURE.md) and
[Bluetooth](../../hardware/bluetooth/ARCHITECTURE.md).

## Lifetimes

`DrawerHost` lazily creates one `DrawerPage`. Closing clears `active` immediately;
the page survives only the exit animation. Bind observation to `active`, and keep
operations that must survive dismissal in feature-local services. Header actions
belong to the page and are loaded by the host; the catalogue must not import services.
Headers use a single title, vertically centered beside page-owned actions.

The installed shell uses individual file symlinks. Editing an existing linked
file reloads it, but adding a component or helper also requires installing its
new link before reloading. Regenerating the manifest alone does not publish
links. Publish new links before editing importers or their `qmldir`. If an
already running engine attempted a missing component, edit the top-level
`shell.qml` after publishing to force a fresh configuration engine; a new preview
process cannot detect cached failures in the existing shell. Change the contents
of `shell.qml` to trigger that reload: touching only its timestamp can be ignored
by the file watcher.
Verify component loading through the installed configuration as well as
repository fixtures, which cannot detect missing installed files.

## System tray

The shell root references `Quickshell.Services.SystemTray.SystemTray` for the
whole session so the native StatusNotifierItem watcher/host remains registered
while the drawer is closed. `TrayDrawer.qml` binds directly to `items.values`;
it includes passive items, follows live icon/title/status changes, and retains
no application state or polling worker. Quickshell supplies icon URLs, including
pixmaps and overlays; a missing icon keeps a generic outline and the app's name.
The API exposes no watcher-availability property, so an empty inventory does not
claim a service failure. XEmbed hosting is outside this native service.

`drawers/tray/TrayService.qml` derives the bar count and attention without loading
the drawer or starting a helper. The count includes all registered entries,
including passive ones; the badge hides at zero, caps at `99+` and reserves that
width. Both the bar and drawer rows use native `Status.NeedsAttention` or unseen
notification history belonging to that app. Attention status buttons use the
shared accent fill/border, icon and badge styling.

Notification matching uses case-insensitive exact tray IDs/titles and notification
app names/desktop-entry IDs, stripping `.desktop` and considering reverse-DNS
IDs' final component. It makes no substring, process, title-change or icon-pixel
guesses. Opening the tray itself acknowledges nothing. Primary app activation
marks that app's matching notifications seen through NotificationCenter;
notification acknowledgement/removal also clears the fallback. Native attention
remains until the app changes its status. This fallback means unseen desktop
notifications, not app read receipts: reading a chat elsewhere cannot clear it
without an app signal, and silent/muted unread messages cannot be inferred.
ZapZap's installed tray manager updates icon artwork and Qt's native badge;
its desktop notifications supply the fallback when it does not set SNI urgency.

`shell.qml` starts in `UseQApplication` mode for native platform menus and selects
the declared Adwaita icon theme with `IconTheme`. This resolves GTK symbolic
menu icons such as Blueman's rather than letting the default theme produce
missing-texture squares. These startup pragmas require a shell restart when
changed. Rows share one full-width `ButtonBackground` for hover, keyboard focus
and either pressed action; primary activation and menu controls remain separate
input targets with transparent backgrounds.
Opening the tray retains the host's default close-button focus rather than
preselecting the first app. Tab or keyboard navigation can focus the list.

Primary activation dismisses the drawer before invoking the app. Menu-only
items instead open their menu. Right-click, the menu button and Menu/Shift+F10
use one `QsMenuAnchor`; middle-click forwards secondary activation and wheel
events forward both signed angle-delta axes to SNI Scroll. The native menu owns
submenus, separators, disabled entries, checks and radio state. Its Escape state
is also exposed to the drawer host. Dismissal, item removal or loss of its menu
closes the menu and clears its anchor; ordinary menu closure restores focus to
its invoking control. The page guards all actions against inactive or removed
items. The list supports Up/Down and Enter/Space, and individual controls remain
in the Tab order.

`tests/test_tray_drawer.py` exercises production pointer/keyboard input, hot
removal, inactive guards, status changes and narrow layouts. Its native test
runs a test-only SNI/DBusMenu publisher on a private `dbus-run-session`, covering
closed-drawer registration, menu structure, action/scroll transport and app exit.
It never activates real tray apps. Run it with
`python3 -B -m unittest discover -s tests -p 'test_tray_drawer.py'`.
Native previews use `DISPLAY_PREVIEW_PLATFORM=wayland`; set
`DISPLAY_PREVIEW_DIR` to an existing output directory for captures.
The native icon check covers Blueman's symbolic menu icons. DBusMenu interaction
tests use the offscreen QPA because QTest events carry no Wayland seat serial
for native grabbing menus. Row hover/focus and image rendering also run on Wayland.
The shared desktop interaction test covers opening the tray from its bar button.

Interface references: [SystemTrayItem](https://quickshell.org/docs/v0.3.2/types/Quickshell.Services.SystemTray/SystemTrayItem/),
[QsMenuAnchor](https://quickshell.org/docs/v0.3.2/types/Quickshell/QsMenuAnchor/) and
[StatusNotifierItem](https://specifications.freedesktop.org/status-notifier-item/latest/status-notifier-item.html).

## Bar badges

Window attention binds directly to `HyprlandToplevel.urgent`. `BarButton` gives
urgent windows an amber border and fill, and `WindowList` adds a dot and tooltip.
`WorkspaceList` derives directional indicators from urgent toplevels on the same
monitor's higher/lower workspace IDs. It uses individual window urgency because
`HyprlandWorkspace.urgent` clears when the workspace is focused. Hyprland owns
clearing urgency when a window receives focus; the shell keeps no attention
state, polling timer or focus-stealing policy.

`ui/StatusBadge.qml` supplies the compact bubble used for input language,
battery charge, current weather temperature, tray app count and unseen notifications. Its
`reserveText` measures a fixed slot using the label's font; empty text hides only
the bubble, preserving the slot and surrounding spacing. The visible bubble fits
its current text, with a circular minimum shape. Values use tabular digits
and elide within that slot. `BarEntry.badgeReserveText` opts a status into this
reservation even when empty; `StatusButton` centers the bubble on the icon's
lower-right corner and reserves its full footprint inside the button, before
optional labels such as the clock. Icons keep the same vertical center as
unbadged icons; 14 px bubbles with 10 px text fit beneath that center without
raising the icons. Notification counts cap at `99+`;
their highlighted state uses the theme's accent fill and contrasting foreground.
A trailing badge's reserved overhang replaces the button's normal right padding;
optional text labels retain their usual end padding. The language slot uses the
widest supported code, `BG`.
Weather temperature follows the passive weather snapshot and stays empty when
no finite reading is available. No additional weather request is needed.

## Scrolling

`ui/WheelScroll.qml` supplies immediate 120-logical-pixel mouse-wheel steps,
proportional high-resolution wheel deltas, bounds and nested-view propagation.
Touchpad gestures retain native precision and inertia. `ScrollListView.qml` owns
this behavior for lists, including launcher results and display options;
`DrawerColumn.qml` installs it on its internal Flickable for all drawer forms.
Keep wheel behavior in these widgets rather than tuning individual drawers.

## Clipboard

`drawers/clipboard/ClipboardService.qml` is imported by the shell root so its
capture worker runs for the whole shell session, independently of the drawer's
lazy-loaded page. Its Python JSON-lines backend starts separate `wl-paste`
watchers for text and images and stores entries with cliphist. It serializes
search, preview, restore, deletion and clear requests. Restore sends the saved
MIME type to `wl-copy`, which is required for images.

History stays local and is limited to 50 entries. cliphist keeps its database
in the XDG cache directory by default, where the user or system may clear it.
Pausing is saved in `$XDG_CONFIG_HOME/quickshell/desktop/clipboard-paused` and
stops both watchers across shell restarts. Pause collection before copying
sensitive data. Visible image rows decode on demand into a private session cache;
the cache keeps at most 32 images and is removed when the shell exits. Copy closes
the drawer after restoring content, returning focus to the application.

## Capture

`CaptureDrawer.qml` combines still capture, recording controls and webcam preview under
the `capture` catalogue/bar key. Screenshot and Recording use equal-width
`CaptureButton` split tiles styled like Performance's modes: a large icon/label
action and a separate chevron. The screenshot action always captures immediately;
its compact `InfoPopover` contains paired 3/5/10 second fullscreen/region actions
with clock icons, shared editor/save checkmarks, optional output selector and
separated file navigation. Entry labels align left. Menu widths follow the layout's natural content width
from the rendered, nonwrapping labels, including row/popup padding and a small
margin, constrained only by the overlay width. Row backgrounds explicitly use
hover or keyboard focus: standalone MenuItems do not get a Menu's highlight
management. Checkable entries stay open naturally inside the InfoPopover; no
close/reopen handling is needed.
`CaptureButton` uses one background for hover, focus and press on either target.
Recording's menu holds
system audio, microphone and pointer checkmarks, plus separated folder/last-file
entries with paths in folder tooltips.
Escape closes a popup before the drawer. Both capture menus and webcam settings
are mutually exclusive; popup widths also respect narrow drawer content.

`CaptureService.editorPreference` uses a watched FileView for the user-owned
`$XDG_CONFIG_HOME/quickshell/desktop/screenshot-editor` file (`on`/`off`). Missing
or invalid values default to on, preserving the existing shortcut behavior. The
same file is read by `desktop-screenshot`; explicit helper flags override it.
The watched `screenshot-save` file uses the same on/off contract and defaults to
on. The drawer freezes both preferences and capture mode into each pending
request, passing `--save|--no-save` and `--edit|--no-edit`. With saving off, the
editor menu entry is disabled while retaining its preference for later use.

`capture/CaptureService.qml` owns countdowns, screenshot process and recording status
for the shell lifetime. Capture freezes the selected output and editor choice;
the page closes immediately. Before capture the service emits `hideRequested`,
which dismisses drawers/search again if reopened, and leaves at least 400 ms for
the 200 ms exit animation and compositor frames. A late timer after suspension
still waits for dismissal. Cancel clears the pending operation. Timers run only
during countdowns; pending capture and the last image reset on shell reload. The helper
uses `desktop-screenshot output --output NAME` or `region`, with `--report` and
frozen preference flags. Region selection starts only when the countdown ends;
selection cancellation is successful and leaves the last saved image unchanged.
Report mode returns a saved image path or `clipboard` and lets the editor run
independently when saving. Capture failures remain
visible on reopening.

`capture/recorder.py --serve` runs on demand under `desktop-capture.service`,
independent of the shell process. It owns exactly one GPU Screen Recorder child;
only that child receives stop signals. A shell watcher connects to the private
`$XDG_RUNTIME_DIR/desktop-capture/control.sock` Unix socket and reattaches after
reloads. Commands and watched snapshots are newline JSON. Operations are `start`
(with `source`), `stop`, `pause`, `option` (with `key` and boolean `value`),
`clear-error` and `watch`. Idle state is event driven; while recording, a 250 ms
check detects completion and emits elapsed-time changes once a second.

The main Recording action waits 400 ms after dismissal and starts capture of the
selected output. During a session it becomes Stop. Win+Shift+R dismisses the shell
and uses `slurp -f "%wx%h+%x+%y"` for region selection when idle, or stops the
active session. Cancelling Slurp starts nothing. Starting, recording, paused,
stopping and idle are explicit phases. The first-frame timestamp sidecar marks
actual capture readiness; the service removes it after initialization. The bar timer excludes acknowledged pauses.
Options are locked during a session. Initialization failures and abnormal exits
report the recorder log in the drawer; the full log is kept in the runtime directory.

The recorder uses native `-ipc` `set-paused` acknowledgements and SIGINT to stop
and finalize, including on graphical-session shutdown. The service allows 15 seconds
for finalization within systemd's 20-second stop timeout. Closing drawers or
reloading Quickshell never signals it. A stopped service ends its recording rather
than recovering a detached process. Last-file navigation is published only after a
successful exit and a nonempty output file. The service is not enabled at login;
CaptureService's initial watcher starts it and reconnects on failure.

Preferences are stored atomically in the user-owned
`$XDG_CONFIG_HOME/quickshell/desktop/recording.json`: boolean `systemAudio`
(default true), `microphone` (false) and `pointer` (true). These control recordings
started from either the drawer or shortcut. Audio uses `default_output` and/or
`default_input`; when both are selected they are mixed into one track. Before
recording a microphone,
`pactl` checks that the default input is a real source rather than a speaker
monitor fallback. Audio support is provided by the hardware audio module. Output is
60 fps H.264/AAC MP4 in XDG Videos/Recordings with a timestamped unique filename.
There is no silent CPU-encoding fallback. Quickshell owns gpu-screen-recorder and
slurp dependencies; Hyprland owns screenshot tools and shortcut dispatch.

Qt Multimedia enumerates cameras without starting streams. `WebcamCard.qml`
provides a device heading, settings and Test action per camera. Infrared companion
sensors are omitted when regular cameras are present (identified by IR/infrared
in the reported name); an infrared-only inventory remains accessible.
`WebcamPreview.qml` is loaded only after Test, with that card's QCameraDevice and
a mirrored video output. No audio input, image capture or media recorder is
attached. Dismissal unloads it immediately; reopening never reactivates it.

`WebcamService.qml` reads `webcam.py` every five seconds while the page is active.
V4L2 control enumeration never starts a stream. Mutations are serialized with
per-control coalescing, followed by fresh device readback. Keyed controls retain
their delegates and keyboard focus during polling; sliders commit on release.
Their custom track/handle supply no implicit height, so the slider explicitly
reserves `Theme.controlHeight` for layout and pointer input.
The backend accepts only ordinary supported controls, rechecks device identity,
flags, range, step and menu membership before writing, and rejects replacement
devices and unavailable/automatic controls. Settings stay with the hardware;
there is no startup restoration competing with other apps.

Only cameras exposing V4L2 `privacy` show a capture-enable switch. Its inverse is
displayed, and read-only hardware privacy controls cannot be toggled. Blocking
capture unloads preview too. The backend does not unload kernel drivers, change
device permissions or disable unrelated USB functions. See the kernel's
[privacy-control contract](https://docs.kernel.org/userspace-api/media/v4l/ext-ctrls-camera.html).

`tests/test_capture_drawer.py` covers request freezing, duplicate prevention,
countdown cancellation, late timer dismissal, process completion, responsive
controls, popup dismissal, settings readback and webcam component lifetime.
Slider coverage uses pointer dragging and keyboard input, including a readback
update during dragging and the value committed on release.
`tests/test_webcam_controls.py` checks device replacement and mutation validation.
`tests/test_capture_recorder.py` covers source validation, mixed audio, persistent
options, native pause acknowledgements, failure/completion and reconnecting clients.
Its fake-recorder service integration also verifies graceful shutdown finalization. The QML recording test verifies dismissal
delay, duplicate prevention and completion independently of page lifetime.
`tests/test_screenshots.py` exercises the shared preference, explicit overrides,
named-output/report/editor handoff with stub commands and literal XDG paths.
Desktop interaction coverage checks the merged catalogue and bar entry.

## System

`drawers/SystemDrawer.qml` owns a local `system/SystemService.qml`. Its one-shot
Python reader stays idle until a popover opens. Each request passes `--section`
(`info`, `boot` or `services`) and reads only that section. Direct terminal actions
choose their updater or check maintenance tools only after being clicked. Info
and Services refresh every 30 seconds while their popover remains open. Boot
reads once per opening. Closing a popover or drawer cancels observation. Section
changes serialize readers and discard results from earlier request generations,
including a rapid close/reopen of the same popover. Each observation command has
a three-second deadline, with a 25-second QML watchdog. Last successful data stays
visible during refresh within the same open popover; a new opening shows its own
loading/error status before exposing data. Individual systemd read failures are
shown in their section and never reported as healthy services.
The catalogue and system island import no diagnostic service.

The top actions use full-width `DrawerActionButton` rows. Boot times and Services
open scrollable `InfoPopover` details anchored to their buttons. The header info
button opens the OS/kernel/uptime card. Signing repair and package health are
full-width actions with explanatory `PassiveToolTip`s. All three popovers are
mutually exclusive, close on dismissal, and consume Escape before the drawer. The header uses a
page-owned popup reference because the host instantiates its actions separately.
System is the last entry in the system bar island.

Boot phases come from C-locale
`systemd-analyze time`, and the five slowest activations from `blame`. Parallel
activation times are not additive. Failed units include both system and user
managers; upcoming realtime timers merge both scopes, sort by deadline, and show
five entries. systemctl JSON timestamps are microseconds, converted to milliseconds
for QML. Reboot marker files are authoritative; missing modules for the running
kernel produce only a qualified restart hint.

Updates explicitly launch `xdg-terminal-exec python3 backend.py --action update`.
The helper requires `topgrade` and passes no automatic-confirmation flags or
fallback updater. The package module owns its configuration and pacman hooks;
see [update integration](../../system/package/topgrade/ARCHITECTURE.md).
Authentication and package confirmation remain interactive; no updater, network update check or repair runs during observation.
The terminal waits for Enter after completion or failure. Journal actions use
`journalctl -b -n 200`, scoped to system/user, filtered to warnings or a selected
unit. Arguments stay separate, and unit names are validated before launching.
Journal access follows the user's existing permissions.

Maintenance tools and keyrings are checked by the backend when a direct action
runs; missing requirements are reported in its terminal. These actions need no
preliminary read and remain independent of drawer lifetime. No maintenance
commands run during observation.

Signing repair runs `sudo -- pacman-key --init`, `--populate` (all installed
keyrings), then `--updatedb`, stopping on the first error. It never removes the
keyring directory, imports arbitrary keys, resets local signatures or disables
signature checking. It reloads the installed repository keyring data; newer
keyring package versions still come through Update system. See
[`pacman-key` operations](https://man.archlinux.org/man/pacman-key.8.en).

Package health runs read-only `pacman -Dk` and `pacman -Qkq`, completing both
checks even when one reports problems. It checks local database consistency and
missing files, not content hashes or intentional configuration changes. Quiet
file-check output supplies package/path pairs; install targets must have valid
package names and belong to `pacman -Qnq`'s repository package set. Foreign
packages are reported for manual repair from their original source. See
[`pacman` checks](https://man.archlinux.org/man/pacman.8.en).

When affected repository packages exist, the terminal offers a default-no
reinstall with a full update: `sudo -- pacman -Syu -- <targets>`. Native package
confirmation stays interactive; no overwrite or nonconfirmation flags are used.
Successful repairs run the health checks once more without offering another
repair. Declined, unavailable or failed repairs retain a failure status; failed
diagnostics are never presented as healthy. Terminal actions preserve their exit
status after the existing Enter-to-close prompt.

All icons reuse the bundled Lucide assets and their existing license.

```sh
python3 -m unittest discover -s tests -p test_system_drawer.py
python3 -m unittest discover -s tests -p test_system_cleanup.py
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

Fixtures cover boot parsing, partial failures, timer conversion, literal journal
arguments, updater selection, active observation, terminal handoff, top action
placement, full/narrow layouts, header information and popup dismissal. Maintenance
coverage checks keyring command order and early failure, read-only diagnostics,
conservative repair targeting, declining repair, rechecking and unavailable tools.
No test updates packages or changes the host keyring.

## Buttons

`ui/ShellButton.qml` styles Qt Quick Controls' `Button` for ordinary text actions,
with an optional leading icon, symmetrically centered label and zero vertical
padding. Content height contributes to minimum button height so fonts cannot be
clipped inside the 34 px default. Cleanup, hold confirmation, Reminders/Focus and
the existing `network/NetworkButton.qml` wrapper share this layout. Use it for
new ordinary actions rather than recreating their padding and content layouts.
`DrawerActionButton` supplies the 48 px drawer footer variant, centering the icon
and label together with a 22 px icon and 12 px gap, matching the audio/speed-test
actions. Cleanup, one-time charging and performance recording use this variant;
the recording toggle fills the footer row.
`ShellChoice` shares themed selection controls between drawers, including the
existing `NetworkChoice` wrapper.
`HoldButton` adds gesture/progress handling; specialized icon buttons, multi-line
audio tests and device rows retain their feature-specific layouts. Overriding
`contentItem` makes that component responsible for its own size and alignment.
Reserve hover and pressed styling for actionable controls. Informational icons
and readings retain their tooltips without changing appearance on hover.
`PassiveToolTip` accepts any Item, using a passive HoverHandler for informational
labels/readings and the native hover/press state for buttons.
`ShellSwitch` supplies the compact themed switch used in radio headers. Rebind
`checked` after a user toggle so backend readback remains authoritative; external
updates must never dispatch mutations.

`ui/PlainInputField.qml` is the shared styled `TextField` with no clear action.
`ui/InputField.qml` extends it with a trailing clear action visible whenever
text is present, and emits `cleared` after clearing. Set `clearButtonEnabled`
false when a field should not offer that action. `ui/SearchInput.qml` extends
`InputField` with a configurable
`debounceInterval` (300 ms by default) and emits `searchRequested(query)` after
typing pauses. Clearing emits an empty query immediately. Search fields own no
service logic; their consumers connect the signal to the relevant search.

## Networking

- `drawers/network/NetworkService.qml` serializes requests to `backend.py` over
  stdin/stdout JSON. The backend uses libnm; passwords never enter argv or status
  snapshots. Mutations survive page dismissal; NetworkManager owns connections.
- Observation runs only while active: status every 5 seconds, scans every 20.
  User actions take priority over queued reads. `Models.js` reconciles keyed rows
  to preserve focus, password input and ordering through refreshes.
- `bar/NetworkStatus.qml` uses native NetworkManager notifications with scanning
  disabled. Keep it independent of the drawer service so bar updates stay cheap.
- Wi-Fi information, power, scan and editor actions live in the header.
  Section headings have no leading icons or connection-detail tooltips.

### Connection information and ports

Wi-Fi and Bluetooth use Lucide info buttons and shared `InfoPopover` / `InfoRow`
components. Popovers anchor to their header button, constrain themselves to the
window and scroll long detail lists. Escape and outside clicks dismiss them;
closing restores focus to the trigger. Drawer dismissal and changing the selected
adapter close information. Wi-Fi keeps its information, WARP and port popovers
mutually exclusive. Bluetooth's Escape handler closes information before
cancelling an unfinished pairing operation. Headers have no adapter subtitles.

Wi-Fi information shows connection status, network, interface, local/public IPv4,
MAC, gateway, DNS and available IPv6 details. Bluetooth shows the selected adapter
name, interface and address. `InfoRow` copies the complete value through
`Quickshell.clipboardText`, with brief checkmark feedback. Empty values and
public-IP placeholders cannot be copied. Values remain live while the popover is
open; public-IP completion does not dismiss it. Adapter details are no longer
repeated in the connected-network hover hint.

`PortsControls.qml` follows the Focus editor pattern: cards with TCP port numbers
and × actions, then a full-width Open port button. Its popover has a `NumberField`
(1–65535), six port presets and Open. Presets fill the field without submitting.
Escape closes the popover before the drawer; dismissal and interface changes close
it too. Wi-Fi is preferred while connected, otherwise a connected Ethernet device
is used. The UFW module owns the privileged service; see its
[implementation notes](../../system/security/ufw/ARCHITECTURE.md).

`PortsService.qml` runs the installed D-Bus client separately from network controls.
Status refreshes every five seconds only while the drawer is active. Actions queue
ahead of subsequent reads and finish after dismissal. Unchanged lists retain card
instances and focus. Only confirmed backend state creates or removes cards.
Failed client launches clear the pending request, allowing later refreshes to
recover after the helper is installed.

`PublicIpService.qml` launches curl against `https://api.ipify.org` only when Wi-Fi
information opens. Local IPv4 comes from the selected adapter's
snapshot and needs no lookup. Public lookup has a two-second overall curl deadline,
a three-second process watchdog and a 64-byte response limit; only a valid IPv4
address is displayed. Failures quietly show Unavailable and cache for one minute;
successes cache for ten minutes. No periodic lookup runs. This worker is separate
from network mutations and speed tests.

The public-IP cache key includes active NetworkManager connection paths, stable
IPv4/IPv6 route fields, interface addresses and VPN/WARP state. Traffic counters
are excluded. A changed key discards cached values; an in-flight old-route reply
is ignored. Opening information during that request queues a lookup for the new context. Closing
the drawer allows an already requested lookup to finish and populate the cache.

```sh
python3 -m unittest discover -s tests -p test_network_ports.py
python3 -m unittest discover -s tests -p test_connection_info.py
```

Tests use a fake kernel and service; they never change host firewall rules.

WARP connects by starting `warp-svc.service`; disconnects and failed connection
attempts stop it. It is never enabled at boot. The polkit rule grants active local
sessions only start/stop access to this unit. Registration is explicit; mode and
registration preferences live in `$XDG_CONFIG_HOME/quickshell/desktop/network.ini`.

`SpeedTestService.qml` runs LibreSpeed separately from network mutations and cancels
on dismissal. CLI JSON speeds are **Mb/s**, latency/jitter are **ms**. Footer rates
come from interface byte counters and use **B/s**. Keep speed-button sizing explicit:
nested layout size hints previously caused a Qt polish loop during drawer opening.

## Validation

```sh
python3 -m unittest discover -s tests -p test_wifi_drawer.py
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

The tests mock network mutations. Set `WIFI_PREVIEW_PLATFORM=wayland` and
`WIFI_PREVIEW_DIR=/tmp` for native drawer captures; offscreen rendering cannot verify
icon tinting. Treat layout/polish warnings as failures, including during resizing.

## Bluetooth

`BluetoothDrawer.qml` uses the same device-card, icon-action, text-button and
scrolling components as the audio and keyboard drawers. A keyed model preserves
device delegates across BlueZ updates. Connected, paired and available sections
share one selected adapter; changing adapters releases this drawer's discovery.
The header refresh action toggles discovery and stays highlighted while searching;
the power switch controls the selected adapter; the info popover shows its identity;
the pencil launches `blueman-manager` and dismisses the drawer. The Bluetooth
hardware module declares Blueman as the editor dependency.
Device summaries keep actions beside the identity block at widths of at least
420 logical pixels, with actions below it on narrower drawers. Names stay vertically
centered independently of connection state and battery reporting. A three-pixel
vertical charge bar sits in the card's existing left padding. Its twelve-pixel
hover area remains reserved when unavailable; the tooltip gives the percentage or
says that the level is not reported. Zero charge retains a one-pixel warning fill.
Long names elide and retain a full name/address tooltip. The Connect/Disconnect/Pair
button stays visible and shows the operation text while pending. Its fixed width
accounts for both idle and progress labels, keeping the forget button stationary.
Pair still pairs and then connects.
Section headings and actions communicate normal connection/pairing states. Only
blocked devices retain a status subtitle. Pairing instructions, their response
buttons and errors expand below the stable summary row.
The ghost trash button uses `HoldButton`'s 1.3-second confirmation and progress
underline. Early release, pointer exit, deactivation and device removal cancel
the gesture; it adds no confirmation row. Keyboard Space uses the same hold.
Reported Battery1 percentages distinguish zero from unavailable. Blocked devices
remain visible with connection/pairing disabled; forgetting is still available.

`drawers/bluetooth/BluetoothService.qml` owns a JSON-lines GLib/Gio worker.
Owner registration follows `DrawerPage.active`. The worker reads BlueZ's object
manager and debounces property/interface signals while the drawer is active.
Mutations serialize and validate the live adapter, device address, power, pairing
and blocked state. Connect, disconnect, forget and power changes finish across
dismissal; the helper exits afterwards. The passive bar uses native
`Quickshell.Bluetooth` notifications independently, without starting the helper,
polling or discovery. The hardware Bluetooth module supplies BlueZ; the existing
Quickshell module supplies Python GObject.

Discovery starts only on request, owns one BlueZ client session and ends after
30 seconds, explicit stop, adapter switching, adapter loss or dismissal.
StopDiscovery releases this client's session without stopping another client's
scan. An asynchronous start completing after dismissal is released immediately.
The worker's bus connection also releases its discovery session on process exit.

Pairing registers a KeyboardDisplay Agent1 for this client without requesting the
global default-agent role. Requests must come from BlueZ and match this client's
pending device. Confirmation, authorization, PIN/passkey entry and keyboard code
display remain in the device card. Prompt ids reject expired replies; passkeys
retain six-digit formatting. Input remains on stdin/stdout, never argv or files.
Rejection, CancelPairing, dismissal, device/adapter loss and a 60-second deadline
end the interaction. After successful Pair, the worker transitions to the connection
phase, which survives dismissal. Explicit Connect and completed Pair set that
selected paired device's Trusted property before connecting, allowing future
incoming audio connections without a persistent default agent. The worker revalidates
address, pairing, power and blocked state and confirms trust before Connect.
Observation, discovery, failed/canceled pairing and unrelated devices never grant
trust. Already-trusted devices need no write. Trust failures prevent connecting;
a later connection failure retains the saved trust and pairing and reports that
distinction. Action errors remain beside their device, or at
the top when that device is no longer visible. Forget uses RemoveDevice only
after the hold completes. The worker never changes discoverability or pairability.

BlueZ API references: [Agent](https://bluez.readthedocs.io/en/latest/agent-api/),
[Adapter](https://bluez.readthedocs.io/en/latest/adapter-api/) and
[Device](https://bluez.readthedocs.io/en/latest/device-api/).

```sh
python3 -m unittest discover -s tests -p test_bluetooth_drawer.py
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

Tests mock BlueZ mutations and worker replies. They cover discovery ownership and
start/dismiss races, request validation, agent prompts/replies, rejection and
cancellation, disappearing/off adapters, battery availability, forget confirmation,
input, narrowing and helper shutdown/reopening. Set
`DISPLAY_PREVIEW_PLATFORM=wayland` and `DISPLAY_PREVIEW_DIR=/tmp/bluetooth-preview`
for native captures. Software rendering cannot verify icon tinting.

## Playback

- Sound and Microphone share `drawers/audio/AudioService.qml`. Pages register
  their active owner with `observe()`, so destruction of an old page cannot stop
  its replacement's subscription. The `pactl subscribe` listener and five-second
  recovery refresh stop after the last active owner leaves. Debounced events
  refresh cards, output/input routes, profiles and application streams through
  `backend.py`. The passive bar tracks native PipeWire defaults independently.
- The backend groups ACP profiles by output components. The Sound menu selects a
  playback layout while the resolver preserves input capability and connection.
  Opaque profiles remain distinct; incompatible modes stay in the advanced editor.
- Sound inventory similarly separates `outputDevices` (card/profile/boost scope)
  from `outputs` (independent sinks), each owning its connected alternative routes.
  A single device profile menu controls all its sinks. Device headers can use
  `deviceLabel` rules independently of route/source names.
- MPRIS transports sit beside their application stream only when desktop/app
  identity gives a unique match in both directions. Unmatched or ambiguous
  sessions remain in Playback, so paused players without streams stay usable.
  Multiple sessions are independently controlled; the playerctld proxy is hidden.
  Device profile menus insert their separator/boost footer explicitly after
  construction, keeping it after dynamically created profiles on load and refresh.
- `output-default` and `output-port` are distinct from explicit per-app `move`.
  Neither action forcibly migrates every playback stream. Selecting a connection
  honors its master-volume cap before changing ports and rechecks any restored
  route gain afterwards, without unmuting or changing the default. The session manager retains its default-following/routing policy.
- Boost preferences are device-keyed and committed only after `output-boost`
  succeeds. Disabling boost lowers that device's sinks and current sink-inputs,
  preserving raw channel balance, mute and unrelated devices. Affected gain
  controls pause while a boost action is pending. The old global preference is a
  migration fallback. App gain permission follows its destination device; moving
  to a device without boost lowers only the moved stream's excess gain.
- Sliders expand their display range for externally boosted levels and rebind
  their value when the range changes. The backend permits lowering an existing
  above-limit gain while rejecting further increases. Dragging holds the range
  steady; server gain/mute remain authoritative.
- Microphone inventory separates `inputDevices` (hardware/profile scope) from
  `inputs` (independent sources). Each source owns its connected alternative routes;
  those routes do not get independent sliders. Sources without a physical card
  remain controllable and expose no unsupported hardware-disable action. Device
  groups and source models reconcile by stable keys to preserve slider focus.
- Source gain/mute, `input-port`, `input-default`, and `input-enabled` are distinct
  actions. Default changes never explicitly move all recordings; the session
  manager retains its routing policy. Recording-app moves validate stream serials,
  source existence, and active connection availability, and move only that stream.
- The hardware enable switch applies once per device, including cards exposing
  several sources. It preserves playback family and existing defaults; unsupported
  combinations show an explanation. Disabled devices keep an inert volume
  control without adding a fake source to the inventory. All switches stay in
  the device header; every input retains a title/checkmark and gain row. Source
  subtitles show only active capture ("In use") or unexpected unavailability;
  routine ready, disabled and muted states use the existing controls. Default
  input/output checkmarks retain their selected accent color, with fill and border
  appearing only on hover, press or keyboard focus.
  Device-local presentation history preserves input rows and connection-selector
  space across profile changes. Backend `inputSlots` metadata provides inert
  initial rows for disabled devices, without native endpoint identities. Muted
  input sliders are disabled while their mute icons remain usable. A source can
  be used even when its hardware has no compatible disable profile. Enabling
  creates muted inputs and does not explicitly select a default.
- Profile changes snapshot endpoint levels, mute, ports, defaults and stream
  routes. Recreated endpoints are matched by native name or ALSA device identity;
  live streams are revalidated by serial before moving. Unaffected default outputs
  are preserved too. Failed restoration attempts roll back the previous profile.
  New microphone endpoints start muted; unmuting is a separate source action.
  Connection changes wait for route properties to settle before restoring mute
  and applying output gain limits, including when enabling a microphone.
  Opening the drawer never starts capture or a level monitor. Only the explicit
  microphone test opens a capture stream.
- Backend actions revalidate current devices, ports, card profiles and application
  serials. Profile changes require the previously observed profile. Explicit app
  routing targets the current connected port of an exposed sink. `libpulse` provides pactl; pavucontrol-qt is the advanced editor.
- Actions serialize and survive dismissal. Pending slider changes coalesce; model
  records reconcile by stable keys so refreshes preserve delegate identity/focus.
  Mute and volume are independent. The backend enforces volume ceilings too.
- Audio labels and limits come from module-provided drop-ins described under
  [Audio configuration](#audio-configuration). Runtime boost preferences live
  separately in `quickshell/desktop/audio.ini`; loading configuration never
  mutates hardware.
- `bar/MicrophoneStatus.qml` uses `mic-off` for both muted and unavailable sources.
  Icon color depends only on availability: available sources use `Theme.text`,
  including muted sources, while unavailable sources use `Theme.muted`.
  Reference implementations reviewed: [DankMaterialShell audio](https://github.com/AvengeMedia/DankMaterialShell/blob/master/quickshell/Services/AudioService.qml),
  [Caelestia audio](https://github.com/caelestia-dots/shell/blob/main/services/Audio.qml),
  and Zephyrus's `settings/AudioInventory.qml` and `docs/audio-names.md`.

```sh
python3 -m unittest discover -s tests -p test_audio_drawer.py
python3 -m unittest discover -s tests -p test_audio_probe.py
```

Tests use production QML with mock audio snapshots and a mock worker; host audio
is never changed. Set `AUDIO_PREVIEW_PLATFORM=wayland` for native icon/theme QA and
`AUDIO_PREVIEW_DIR` to select the capture directory. Verify no layout/polish
warnings at normal and narrow widths, and observation stops on dismissal.

## Audio tests

`AudioTestButton.qml` provides one footer control per drawer, using a page-owned
`AudioTestService.qml` and a separate `probe.py` process. Tests do not enter the
mixer action queue. Deactivation, gesture cancellation and explicit stop requests
terminate the worker's audio client; a deadline also bounds the worker lifetime.

Speaker tests snapshot connected, unmuted sinks and visit their native
`channel_map` entries sequentially. Each channel uses an explicitly targeted
`paplay` stream with remixing disabled. Spoken channel labels come from
[alsa-utils](https://github.com/alsa-project/alsa-utils/tree/master/speaker-test/samples);
LFE, height and auxiliary channels use a short generated tone with an on-screen
label. Test streams request unity gain and leave endpoint gain, mute, defaults,
profiles and existing application routes untouched. Devices and connections are
revalidated before each channel and while playback is running.

The microphone test binds to the default source and default sink at press time.
Both must be connected and unmuted; monitor sources are rejected. `parec` records
24 kHz mono PCM into memory, bounded to ten seconds. Reaching the cap stops capture
and waits for release before playback; a thirty-second hold deadline discards an
abandoned recording. Release closes and reaps the recorder before starting
`paplay`, avoiding live feedback. Cancellation and input EOF discard the buffer.
Recordings are never written to disk. Test streams use `application.id` equal to
`dotfiles.audio-test` and are omitted from application mixer rows. Stream restore
properties are disabled so old per-application routing/gain cannot override the test.

Tests substitute audio clients on `PATH` and exercise the real worker, including
release arriving with the initial request, cancellation, capture limits,
disconnection and client cleanup. QML tests cover mouse/Space holds, gesture
cancellation, drawer dismissal, worker errors and restart. No host audio is used.

## Audio configuration

Audio settings are contributed by modules:

| Source                                                                                                        | Owns                                                                  |
| ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [Shared labels](../../hardware/audio/symlinks/home/.config/devices/audio/profiles.json)                       | Plain-language profile names; driver labels remain available on hover |
| [Zephyrus audio](../../hardware/devices/zephyrus/symlinks/home/.config/devices/audio/zephyrus.json)           | Laptop speakers, headphone jack and graphics audio connections        |
| [Dell S2722DC](../../hardware/peripherals/dell-s2722dc/symlinks/home/.config/devices/audio/dell-s2722dc.json) | Monitor speaker name, overriding generic graphics audio names         |

Each module installs its JSON file as a symlink under
`$XDG_CONFIG_HOME/devices/audio/`. The drawer reads every `*.json` file in that
directory, in filename order, whenever it refreshes. Edits to the source files
appear on the next audio event or five-second refresh; adding files requires
regeneration and apply to install their links. Runtime boost preferences stay
in `quickshell/desktop/audio.ini`.

Each file can contribute `rules`, `profiles`, or both. Invalid files are skipped
with a warning naming the file; valid files continue to apply. Conflicting
profile labels also produce a warning rather than silently overriding a label.

Example device file:

```json
{
  "rules": [
    {
      "match": { "device.name": "alsa_card.example", "port.name": "analog-output-headphones" },
      "label": "Desk headphones",
      "icon": "headphones",
      "maxVolume": 100
    }
  ]
}
```

Rules with higher `priority` are checked first (default 0); ties retain filename
and rule order. All `match` fields require exact equality; all `contains` fields
require substrings. Inspect identifiers with `pactl -f json list sinks` and
`pactl -f json list cards`. Match `device.name` for aliases that survive profile changes; `node.name` includes the current
profile. Serial numbers can distinguish otherwise identical hardware.
The Dell rule has priority 10 so it overrides generic graphics audio rules.
`{port}` inserts a readable connection name, distinguishing multiple outputs.
Profile labels are a map of driver profile identifiers to friendly labels;
unlisted profiles keep their driver descriptions.

`icon` accepts `speaker`, `headphones`, `monitor`, `bluetooth`, `volume-2`,
`mic` or `mic-off`.
Optional `deviceLabel` names the device header independently of its output names;
match it using stable card properties such as `device.name`.
Optional `maxVolume` caps that connection's master-volume adjustments at 1–150%
(default 150% with boost, 100% without it). Selecting a connection also lowers its
output gain if needed to honor that cap. Naming and limits never automatically
select hardware or force profiles. Unmatched devices keep their reported descriptions and port names.

## Displays

`DisplaysDrawer.qml` reconciles one card per output by native name. The header
identifies the connection and owns its enable switch; the next rows identify the
physical display and summarize its active settings. Brightness and the settings
cog share a row. The cog is a scrollable, single-level popup with Refresh rate
and Mirroring sections, using the same checkmarked item styling as Sound.
Resolution, scale and rotation are handled in wdisplays. A keyed options model
preserves scroll/focus across changes. Nonnegative popup margins constrain it to
the enclosing window; its height is capped at 560 logical pixels and the available
window height, rather than the drawer body height. Short menus include both top
and bottom padding in their height, avoiding an unnecessary scrollbar. Long mode
lists scroll with a visible scrollbar and an exact
content extent for the mixed heading/separator/option heights. Refresh rate
choices retain the current resolution, scale and transform.

The cog's Use recommended resolution action sends `mode: "preferred"` through
the existing change request. The backend queries `hl.get_monitor().available_modes`
with read-only `hyprctl repl` and matches the preferred flag's dimensions and
unrounded refresh rate to an advertised mode. Missing/unavailable preferred modes
report an error without mutation. The resolved explicit mode uses normal geometry
adjustment, validation, readback, rollback and persistence; scale, transform and
mirroring are retained. Mode-list order is not used to infer the recommendation.

Selections apply immediately and close the popup. Escape, an outside click or a
second cog click dismisses the menu without changing applied settings. The popup
excludes its parent button from outside press dismissal so the button can toggle
it without reopening on release. `DrawerPage.escapeHandler` is forwarded through
`DrawerHost` to the interaction window's Escape shortcut so an open popup closes
before the drawer. The popup also handles Escape directly for standalone rendering.

The header edit action opens `wdisplays` for arrangement. Its output-management
protocol leaves repository monitor/workspace files untouched. Drawer changes add
connector-keyed runtime monitor rules through `hl.monitor`. `Preferences` in
`backend.py` saves confirmed drawer changes immediately and captures external
changes (including wdisplays) after native display-change notifications settle.
Preferences live at `$XDG_CONFIG_HOME/quickshell/desktop/displays.json` (default
`~/.config`), an unmanaged user-owned file, never a provisioning asset. Writes use
a private temporary file, fsync and atomic replacement; malformed existing files
are reported and left untouched. Write failures surface in the drawer too.

The version-1 JSON object contains an `outputs` array with connector `name`,
five-part native `identity`, `enabled`, `mode` (resolution and refresh rate),
`scale`, `transform` (rotation/flip), `x`, `y`, `mirror` and `mirrorIdentity`.
Disconnected outputs stay saved; disabled outputs retain their last usable mode
and geometry. Identities include connector and physical metadata, so replacement
hardware does not inherit settings and reconnecting uses the same connector.

Shell startup and subsequent physical topology changes restore matching outputs.
Unsupported modes are skipped. Missing/replaced mirror sources become
independent temporarily; overlap is resolved by moving conflicting outputs right.
If saved settings would leave no independent output, a usable connected output
stays enabled, preferring the built-in panel when one must be enabled. A disabled
panel retains valid saved mode, scale, transform and position during this temporary
override. Hyprland's invisible `FALLBACK` output is excluded from discovery and
safety checks; legacy saved entries for it are ignored on load. These safety
fallbacks do not overwrite unchanged saved preferences.
Restoration uses the same validation, readback and rollback path as manual changes.
Hyprland `configreloaded` queues a debounced restore rather than saving reset
defaults. Monitor enable/disable events alone do not trigger restoration: they
can be deliberate edits in wdisplays, while `monitors all` distinguishes physical
topology from enabled state. No window/workspace preferences are saved.
There is no primary/default display preference: launcher output selection and
Hyprland's window/workspace placement remain authoritative.
The native workspace policy repairs stranded workspace ownership and wholly
off-screen floating windows after layout changes; see
[workspace recovery](../hyprland/ARCHITECTURE.md).
See [wdisplays](https://github.com/artizirk/wdisplays) for compositor caveats.

`monitors.lua` forwards Hyprland's native `monitor.layout_changed` Lua event as
`desktop-displays-changed` through the existing IPC connection. It covers mode,
refresh rate, scale, transform and position updates, including wdisplays edits.
`shell.qml` also forwards monitor add/remove and config reload IPC events to
`DisplayService.handleEvent()`. A 500 ms one-shot timer combines event bursts;
config reload restoration takes priority over ordinary synchronization. Unrelated
events schedule nothing. Display layout discovery has no repeating timer.

`DisplayService.start()` restores once at shell startup. Opening a drawer reads
status; owner-keyed observation controls brightness discovery/polling. Every
layout request launches a short-lived helper, writes one JSON line and closes
stdin. The helper also exits after that one request without waiting for EOF.
Status, sync, restore and immediate changes serialize, and accepted requests
survive drawer dismissal. A failed helper reports an error and can be retried by
the next relevant event or explicit Refresh; idle time never launches a helper.
The catalogue imports no service and the helper uses one advisory lock per
compositor session while handling a request.

The shell retains an acknowledged `baseline` snapshot and attaches it when each
queued request starts. Replies carry the next baseline, allowing processes to
exit without forgetting which state came from a restore. Read-only status does
not advance it or save external edits. Startup/topology restores acknowledge their
result and seed only unknown outputs. Echo events then compare equal and neither
reapply outputs nor rewrite preferences, preserving temporary safety fallbacks.
Failed restores acknowledge the actual rollback state too, preventing event-driven
retry loops. Save failures retain the prior baseline so a later event can retry.

`test_display_drawer.py` verifies user-file writes and failure handling, restart
and reconnect restoration, physical identity matching, external-edit settling,
disabled-output geometry, safe dock/mirror fallbacks, restore echoes, event burst
coalescing, failure recovery on the next event, idle inactivity, native Lua event
forwarding and short/long popup sizing. Its preferences and compositor state are
isolated. The worker test redirects both XDG configuration and runtime directories
and verifies process exit while its stdin remains open.

The backend reads `hyprctl -j monitors all` and applies `hl.monitor` tables through
`hyprctl eval`. Each change revalidates connector plus physical identity, current
inventory, advertised modes, numeric bounds, whole logical pixels and a surviving
independent output. It changes only the selected output and affected neighbors.
Resizing preserves gaps by shifting outputs to its right/below; enabling or
unmirroring places just that output beside the existing independent displays.
Unresolvable overlaps report an error directing the user to wdisplays.

Mirrors normalize Hyprland IDs to output names. Missing, disabled, self-referential,
chained and cyclic targets are rejected. Sources apply before mirrors; enabled
replacements are verified usable before old outputs are disabled. Lua strings use
byte escapes without shell interpolation. Actual state is reread to reject mode
fallbacks. Unrelated rule fields are omitted. A failed mutation attempts to restore
the state immediately preceding it, including neighbor placement. Restoration
matches physical identities, skips disconnected/replaced devices and preserves a
surviving independent output.
Mirrors with vanished sources become independent. Hardware changes and restoration
errors are reported; window/workspace placement after disabling an output is not
part of a display snapshot. There is no automatic restoration on helper termination.
See the [monitor API](https://wiki.hypr.land/Configuring/Basics/Monitors/)
and [runtime CLI](https://wiki.hypr.land/configuring/core/advanced-configuration/using-hyprctl/).

### Identification and visual tests

The drawer footer identifies enabled outputs for five seconds, with connector,
physical label and a numbered badge. `DisplayTestService.qml` maps records to
current `Quickshell.screens`, skipping disabled or missing outputs. Its singleton
lifetime lets identification finish after dismissal and lets fullscreen tests
outlive the drawer. Repeating Identify hides the labels. Screen removal prunes
identification targets or ends the selected test.

A final Test display section in each cog launches patterns or motion for that
output, closing the drawer only after successful selection. These actions never
call the monitor or brightness helpers. `DisplayTestWindow.qml` is loaded lazily
per target; stopped tests destroy their windows. Identification uses transparent
Overlay-layer panels with an empty input region and no keyboard focus. Tests use
an input-taking fullscreen Overlay panel on the selected screen. Closing destroys
the panel and releases its exclusive keyboard focus. Mirrored outputs reproduce
the source image rather than offering independent image content.

`DisplayTestView.qml` renders black, white, red, green, blue, a grayscale gradient
and a 24-logical-pixel checkerboard. Space/Left/Right cycle patterns, H toggles
controls, and Escape, a background click or Close ends the test. The motion view
moves contrast targets across three backgrounds at 600 logical pixels per second,
using frame time rather than a fixed timer; it stops animating when hidden. The
refresh-rate label describes the configured mode, not a measured refresh rate.
Tests provide visual inspection rather than calibrated color or refresh measurement.

`test_display_tools.py` covers target selection, hotplug, timeout, rendered views,
animation lifetime and native panel input/keyboard behavior. Offscreen controller
tests inject a Qt-only window source; native runs exercise the production panels.

### Physical brightness

`BrightnessControl.qml` reflects a separate `brightness.py` worker. Backlight
values come from sysfs; writes use `brightnessctl` with the exact device and native
range. External displays use `ddcutil` brightness VCP 0x10, including its reported
maximum. Controls permit 1–100% and never change gamma, color/HDR or layout.
Unsupported/ambiguous hardware keeps a disabled slider and an explanatory tooltip.

Matching uses one connected DRM connector with the native output name. A
backlight must be a descendant of that connector. DisplayPort prefers its own
`i2c-*` AUX adapter: AMD's `ddc` link can point to an unused physical I2C bus.
Other connections use that link when unambiguous. Writes revalidate output
identity, enabled state, controller kind/key and range; readback rechecks identity.
The ddcutil package supplies i2c-dev loading and active-session udev access.
DDC/CI must also be enabled by the monitor and supported by the cable/adapter.

Brightness reads run on opening and every five seconds while observed. Writes
serialize independently, coalescing pending values per output and surviving
dismissal. Slow DDC operations do not block layout/menu requests. Brightness
changes apply immediately. No brightness preference is saved or reapplied on
startup/reconnect; retention is owned by the hardware and other system services.

### Night light and Keep awake

`ComfortService.qml` serializes requests to `comfort.py` and observes state every
three seconds. `shell.qml` starts the service once; drawer dismissal leaves it
running. The bar reads the same singleton without starting display discovery.
`ComfortControls.qml` presents global Dark mode and Night light toggles below the
display cards. Dark mode uses `Theme.setMode()` and the existing user-owned
`~/.config/quickshell/desktop/theme-mode` preference; it changes only shell
appearance and remains available independently of display hardware/services.
The monitor cog owns
an indefinite Keep awake checkmark; the bar for that monitor uses `Theme.accent`
while checked. Each bar's `screen.name` determines which output it represents.

Night light uses the packaged `hyprsunset.service`. Enabling runs
`systemctl --user enable --now`; disabling runs `disable --now`, so the choice
survives login without a separate preference file. The helper polls native unit
state, reflecting external starts/stops too. The running process is required to
maintain the color transform even without a schedule. Temperature, gamma and
profiles belong exclusively to `~/.config/hypr/hyprsunset.conf`; the drawer never
parses or rewrites them. One profile without a time warms displays whenever the
service runs. Multiple timed profiles let hyprsunset own scheduling and hotplug.

Keep awake stores connector/physical-identity pairs in session-local leases under
`$XDG_RUNTIME_DIR/hypr/<instance>/desktop-keep-awake/`. Each lease has an advisory
lock held by the helper and a separate atomic JSON snapshot. Only locked leases
whose identities match current enabled outputs affect idle behavior. A crash
releases the lock, making leftover files inert; normal exit removes both files.
Unplugged, replaced or disabled outputs are pruned on the next status check.
Selections survive drawer dismissal and reset on shell exit/reload.

The Hyprland module's `desktop-idle` wrapper runs this same helper for Hypridle.
Its blanking action uses the public per-monitor DPMS dispatcher, skipping protected
outputs. Lock and suspend listeners use supported `condition_cmd` hooks with a
ten-second retry while any protected monitor remains connected. They therefore
resume normal idle behavior after the last checkmark is cleared. Native app
inhibitors remain effective for every listener; no global inhibitor is created
by Keep awake. Explicit locking, sleep and lid actions retain their normal paths.

`test_display_comfort.py` exercises native service commands, stale-action rejection,
locked/crashed leases, physical identity changes, hotplug cleanup, selective DPMS,
idle guards, helper EOF, cog checkmarks, per-bar coloring and the simple toggle.
Host service and display mutations are mocked. `DISPLAY_PREVIEW_DIR` enables a
capture of the simplified drawer.

```sh
python3 -m unittest discover -s tests -p 'test_display*.py'
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

Tests mock monitor mutations, sysfs and brightness clients. Production QML runs
with injected services/workers and never changes host displays or brightness.
Set `DISPLAY_PREVIEW_PLATFORM=wayland` for native icon/menu QA and
`DISPLAY_PREVIEW_DIR=/tmp` for normal, narrow and settings-popup captures. Publish
new component/helper/icon symlinks before checking the installed shell;
configuration generation alone does not install them.

## Keyboard

`drawers/keyboard/InputLanguage.qml` owns confirmed language and secondary-pair
state independently of the transient drawer. The bar reads its EN/BG/VI label.
Requests serialize; repeated status reads coalesce, pending selections take
priority, and selections finish after dismissal. Failed selections retain the
last confirmed state and their error until another explicit selection. Status
refreshes recover separately without hiding a failed action.

`backend.py` reads `$XDG_CONFIG_HOME/quickshell/input-language.json` on each
request and invokes its `command` array directly, without a shell. The existing
[hardware input controller](../../hardware/keyboard/input-method/ARCHITECTURE.md)
owns Fcitx startup/stop, pair selection, Alt+Shift and session persistence.
Missing providers fall back to the configured Hyprland XKB layouts; Vietnamese
stays visible but disabled with an explanation. Reads never launch a daemon.
No login/reboot persistence is added: the provider resets each compositor
instance to English/Bulgarian and preserves changes through config reloads.

Hyprland layout events carry the keyboard that changed, including non-main
keyboards. Config reloads also refresh state. Provider mode changes need a
one-second refresh while the Vietnamese pair is selected. The active drawer
adds a five-second recovery refresh. All bars share this single provider.

Language highlighting identifies active input; the checkmark identifies the
secondary language even while English is active. Choosing a language commits
existing preedit and temporarily replaces the target row's checkmark slot with a
spinner, without adding a status row or moving the language list. The service's
`selectingLanguage` includes queued selections. Choosing a language also moves
focus off the test field and, after success, refocuses it with a short delay so a
cold-started IME can attach. The single-line test field uses
`InputField`. Test text is page-local, never persisted and cleared on
dismissal. The help popup has separate Telex, Phonetic and shortcut tabs,
scrolls at narrow heights and consumes Escape before dismissal.
Tabs use `QtQuick.Templates` with an explicit row, equal widths and an eight-pixel
gap; no platform tab background, inset or underline is retained. The Telex view
groups a two-column diacritics map and named tones with key badges. Popup height
follows content within the window bounds. Outside press, the help button or
Escape dismisses it; there is no separate close control.
The Bulgarian map follows the configured `bg(phonetic)` traditional variant,
not `bg(bas_phonetic)`. Its alphabetic three-column map includes the punctuation
keys used for ч, ш, щ and ю, plus the Shift+X exception for ѝ. Mappings are checked
against the installed xkeyboard-config `symbols/bg` definition.
Patterns reviewed: [Caelestia dashboard tabs](https://github.com/caelestia-dots/shell/blob/main/modules/dashboard/Tabs.qml)
and [DMS shared tab bar](https://github.com/AvengeMedia/dank-qml-common/blob/master/DCommon/Widgets/DTabBar.qml).
Their theme and navigation dependencies stay outside this shell.

The shortcut list mirrors the repository's Hyprland bindings; it is a reference,
not a live introspection of arbitrary external bindings. Telex mappings follow
the [UniKey manual](https://www.unikey.org/support/ukmanual.html).

The pencil launches `fcitx5-configtool`, provided by
`hardware/keyboard/input-method/config.jsonc`. This editor covers input methods;
physical keyboard settings remain owned by Hyprland.

`keyboard/backlight.py` owns a page-scoped worker with independent keyboard
cards, placed immediately after Languages. Cards identify each device by title
and model, with brightness and a capability-filtered settings cog. There is no
input-disable action: zero brightness and the MX backlight Off mode affect only
lighting. Native LED inventory includes only the `kbd_backlight` function;
lock, compose, network and display LEDs are excluded. Brightness writes
revalidate resolved sysfs identity and native maximum, reject wildcard device
names, target brightnessctl's exact LED and read hardware back. Sliders use
integer levels from zero to the native maximum. Unknown/unreadable controls
report their reason rather than silently retargeting another device.

Hardware modules install trusted Python adapters in
`$XDG_CONFIG_HOME/devices/keyboard/backends/*.py` (default `~/.config`). The worker
loads only these installed adapters; no vendor imports or device IDs live in the
shell. Without adapters, native Linux keyboard brightness remains available.
The [Zephyrus module](../../hardware/devices/zephyrus/ARCHITECTURE.md) owns ASUS
Aura integration and dependencies; the
[Logitech module](../../hardware/peripherals/logitech/ARCHITECTURE.md) owns Solaar
integration and dependencies. Module selection determines which adapters ship.

Each adapter exports `Provider` with `snapshot(native)`, `change(row, request)`
and `close()`. `snapshot` receives native LED records and returns additional or
augmented records in the same card schema. Native rows carry `key`, resolved
`identity`, `value`, `maximum`, `available`, and `reason`; adapters can add
`label`, `connection`, `effects` (`id`, `label`, `colors`), active `effect`,
`rgb`, `color`, `lightingPath`, `modes` (`id`, `label`), and active `mode`.
The worker merges by key and records adapter ownership as `provider`; conflicting
adapter claims fail explicitly. Native `set` operations always retain the generic
sysfs validation/write path. Other mutations route to the owning adapter, which
revalidates live identity and capabilities. `close` releases adapter resources.
Adapters neither apply saved preferences during discovery nor add shell-owned
lighting persistence. The swatches are UI presets for RGB-capable effects.

`BacklightService.qml` serializes requests over stdin/stdout JSON to a persistent
worker. Repeated slider updates coalesce per device/action; they cannot discard
an unrelated effect or mode change. Observation polls once per second only while
an owner is active. Adapters may cache device reads and retain handles while
open; their timing and hardware rules live in their module documentation.
First-time wireless discovery can take several seconds and shows a
loading indicator. Reads never change lighting. Queued mutations drain on
dismissal before the worker exits and releases its handles. Keyed models retain
slider and option-button identity through status updates. Only one lighting or
reference popup remains open; Escape dismisses it before the drawer.

```sh
python3 -m unittest discover -s tests -p 'test_keyboard*.py'
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

Tests use mock providers and production QML; they do not change host input.
`DISPLAY_PREVIEW_PLATFORM=wayland DISPLAY_PREVIEW_DIR=/tmp` enables native
captures of language choices, backlight controls, narrow/light layouts and the
three reference tabs. Backlight tests use fake sysfs and clients, including
native/off levels, stale controllers, capability filtering, RGB effect semantics,
Logitech mode selection/rollback, optional adapter discovery/routing, write
failures and queue/observer lifetime. Generation tests check adapter ownership
and host selection. Publish both the shell and selected hardware module symlinks
before reloading the installed shell.
Real Telex composition in third-party clients remains a native acceptance check.

## Disks

`drawers/DisksDrawer.qml` groups volumes under physical-drive cards, using shared
surface, button, field, spinner and scroll controls. `disks/DriveCard.qml` keeps
one representative volume's free-space summary visible (root, another mounted
volume, or the first volume, in that order). Other volumes and mount-point chips
start collapsed behind a chevron. Expansion is disabled without mounted volumes
and collapses after the last unmount. It survives keyed refreshes while the
drawer lives and resets on media-identity changes. Volume names open their first
mount point; the expanded chips open specific locations. `VolumeRow.qml` shares
summary, capacity and icon controls. The summary's single action beside its size
mounts or unmounts that volume without powering off or ejecting the drive, so
it remains available to remount. Locked volumes use that slot for unlock.
Expanded secondary volumes retain individual mount/unmount/unlock controls.
Drive/volume details live in passive tooltips; a heart button opens health details
and checks on the first open without cached results. Unsupported health buttons are disabled. The popup
shows pending/error states and offers an explicit refresh for cached results.
Only one drive menu or editor popup remains open. Mount locations open with
literal `dolphin --` arguments, matching the desktop file-manager shortcut and
avoiding directory MIME handlers that may launch a terminal. Header actions
refresh inventory and launch `partitionmanager` (KDE Partition Manager) for
partition and filesystem operations. The scan action launches `filelight` as a separate
application and dismisses the drawer. Each launch action is unavailable until
its executable is installed.

`disks/backend.py` uses Gio on the system bus with
[UDisks](https://storaged.org/doc/udisks2-api/latest/index.html). Ordinary reads
use `GetManagedObjects` and mounted filesystems' `statvfs`; they issue no SMART,
device-probe, auto-mount or power-management commands. Local UDisks volumes are
in scope; network shares and unrelated virtual filesystems are not inventoried.
Free space uses `f_bavail`, so space reserved for root is not presented as usable.
Failed capacity reads remain unknown. Multiple mount points share one volume's
capacity bar; Btrfs subvolume mount points do not multiply storage totals.

Crypto backing paths and sysfs slave relationships associate encrypted/LVM/RAID
layers with physical drives. A directly unlocked filesystem shares its encrypted
container's row; unlocked containers holding LVM give way to their filesystem
rows. Volumes spanning several drives appear under Other volumes. Mounted
volumes stay visible even with UDisks' ignore hint. Unmounted ignored volumes
and raw partitions without a filesystem are omitted. Empty drives remain visible.

Every action revalidates a fingerprint of the native object and observed media:
block device number, filesystem UUID, size, crypto backing and associated drive
identities; drive identity includes connection/media detection timestamps.
Mount, unlock and unmount target the current native interface. Unlock does not
automatically mount. Passphrases cross the worker's stdin and D-Bus only, never
argv, disk or error text. QML retains startup input only until the pipe is ready;
the input field clears on submission, Escape and dismissal. System mounts (`/`,
`/boot`, `/efi`, `/usr`, `/var`, `/home` and their descendants) cannot be unmounted
through the drawer. Active swap also prevents drive removal.

The backend's explicit eject operation freezes the drive's block inventory, unmounts mounted
filesystems without force, locks encrypted containers, then requests `PowerOff`
or `Eject` according to capability. Each step checks live device identity; newly
appearing mappings or mounts stop removal. Busy LVM/RAID holders are left to
UDisks to reject. No holder teardown or swap disabling is attempted. A power-off
that could affect another drive with the same `SiblingId` is withheld, with an
explanation directing the user to Disks. Failure refreshes inventory so any
completed unmounts are reflected. UDisks' existing polkit rules and the desktop
authentication agent own authorization; this feature adds no permission rules.

Health is an explicit read using `Drive.Ata.SmartUpdate` with `nowakeup=true`, or
`NVMe.Controller.SmartUpdate`. SMART is never enabled automatically. Unsupported
or disabled reporting has no health action. Summaries show provider warnings,
temperature, powered-on hours, ATA bad sectors and the observation time. Results
remain in memory, keyed by drive identity, without automatic health refreshes.
An asleep ATA device reports that refresh would wake it and retains any prior
result. NVMe checks may wake their controller; opening the drawer never requests
one. No self-tests are started.

`disks/DisksService.qml` is a feature-local lazy singleton. It polls only while
a page observes it, serializes explicit actions and coalesces status reads.
Actions finish after dismissal; the worker exits once the last owner leaves and
the current action finishes. Stable keyed models preserve card and volume
controls across refreshes. Action errors remain beside the affected device (or
above the list after disconnect) until another action or dismissal of the error;
successful status reads do not erase them. Unlock consumes Escape before the
drawer and closes if its target disappears or changes identity.

```sh
python3 -m unittest discover -s tests -p test_disks_drawer.py
python3 -m unittest discover -s tests -p test_desktop_interactions.py
```

Tests use fake UDisks inventories/mutations and the production QML. They cover
encrypted/LVM associations, reserved/unknown capacity, stale media, system/swap
protection, shared power, busy and changed inventories during removal, secret
handling, health semantics, compact/expanded keyed refresh, narrow/light layouts,
popup input, unmount/remount continuity and service lifetime. Dedicated analyzer
launches use a fixture executable, so tests never start a real scan.
`DISPLAY_PREVIEW_PLATFORM=wayland DISPLAY_PREVIEW_DIR=/tmp/disks-preview`
enables native captures. Publish the new `disks/` helper and singleton links
before checking the installed shell. Real mount/unlock/eject and polkit dialogs
remain acceptance checks on disposable/removable media.

### System cleanup

`disks/CleanupControl.qml` pins the Clean system action below the drive list.
Its upward popover resets selections on opening, discovers availability without
running package managers, and scrolls independently at narrow/short sizes.
Each option has a short description. Administrator-required options
carry a shield icon with a tooltip. The pinned Select all checkbox supports
partial selection and clearing, skips unavailable choices, and selects All Mise
tools instead of the redundant unused-versions option.
Escape, outside press and drawer deactivation cancel confirmation and close it.
`ui/HoldButton.qml` follows Zephyrus's 1300 ms hold/progress pattern, including
Space-key activation; early release, lost focus, changed choices, disabling and
popup closure cancel the gesture. A hold fires once and clears the selection.

`CleanupService.qml` owns a separate one-shot worker outside the page lifetime;
cleanup continues after dismissal and sends its outcome as a desktop notification.
`cleanup.py` accepts category IDs only, validates the whole selection before any
mutation, sends progress, and continues after individual failures. Native commands
have a ten-minute timeout and literal argv with no shell. Discovery never cleans.
Permission, authorization, timeout and general command failures become short,
human-readable messages; terminal output and Python errno details never appear
in the popover or notifications. The service sends one completion/partial-failure
notification through `notify-send`, even after page destruction. Successful
discovery does not replay results. Notification delivery is replaced in tests.

The fixed catalogue follows the developer/package modules and their environment:
XDG cache/data, `MISE_CACHE_DIR`, `MISE_DATA_DIR`, `CARGO_HOME`, `npm_config_cache`
and `PIP_CACHE_DIR`. Defaults match provisioning: `~/.local/cache` and
`~/.local/share/cargo`. Legacy `~/.cache`, `~/.cargo` and `~/.npm` folders are not
added automatically; explicit environment overrides still apply.
It includes pacman archives (all versions via
`pkexec /usr/bin/paccache --remove --keep 0`), paru package archives only,
mise downloads/cache, npm content cache, pnpm store pruning, Bun cache, pip/uv,
Cargo registry archives, known browser web caches, and thumbnails/Mesa/NVIDIA
shader caches. It never recursively clears the whole XDG cache, browser profiles,
AUR working trees, Downloads, Trash, logs or project directories. Cache traversal
opens all ancestors with `O_NOFOLLOW`; fd-based deletion does not follow symlinks.
Home/config/data roots and their ancestors are refused. Cache directory roots
remain in place. Concurrent applications may refill caches; close browsers first.

Rootless Podman cleanup inspects immutable image IDs, requires `RepoDigests`,
skips images referenced by any running/stopped container (including descendant
images), and removes without force. It never prunes containers, volumes or local
builds, preserving Distrobox state. Removal failures, including multiple tags or
new dependencies, appear in the per-category result. Flatpak uses native
`uninstall --unused --noninteractive` separately for user and default system
installations; applications, data and pinned runtimes remain under Flatpak policy.
Native polkit authentication applies to privileged operations; no new grants.
`pacman-contrib` supplies paccache. Package caches are the offline rollback copies;
removing them does not uninstall packages.

Mise has mutually exclusive choices for `prune --tools --yes` and
`uninstall --all --yes`. Neither edits tool configuration. Pruning relies on
mise's tracked configurations and may remove versions used only by one-off
commands. Removing all versions requires `mise install` before those tools work.
Installed tools start unchecked, as do all other categories.

References: [Syntaxis cleanup UI](https://github.com/katawaredev/syntaxis/blob/master/crates/app-shell/src/home_management.rs),
Zephyrus `widgets/HoldAction.qml`, [mise pruning](https://mise.jdx.dev/cli/prune.html),
[Podman inspection](https://docs.podman.io/en/stable/markdown/podman-image-inspect.1.html),
[Flatpak commands](https://docs.flatpak.org/en/latest/flatpak-command-reference.html),
[pnpm store](https://pnpm.io/cli/store) and [uv caches](https://docs.astral.sh/uv/concepts/cache/).

```sh
python3 -m unittest discover -s tests -p test_system_cleanup.py
```

Tests use temporary caches and mock commands; no real cleanup occurs. They cover
allowlists, environment paths, symlink protection, AUR working tree preservation,
container/image protections, partial failures, hold cancellation/keyboard input,
narrow/light layouts, button geometry, notifications and service survival after
page destruction. Native captures
use `DISPLAY_PREVIEW_PLATFORM=wayland DISPLAY_PREVIEW_DIR=/tmp/cleanup-preview`.

## Battery and performance

`drawers/power/PowerService.qml` is shared by Battery and Performance. Observation
is owner-scoped: Battery polls every ten seconds, Performance every two seconds.
Only Performance requests detailed telemetry. Requests serialize over JSON lines
to `backend.py`; user actions precede refreshes and finish after dismissal. The
last departing owner stops the timer and closes the helper after pending actions.
Power profiles and charge limits remain daemon-owned. The shell persists only
the previous limit for a one-time full charge, not a competing settings copy.
Snapshot updates reconcile cards and profile buttons by key to retain keyboard
focus. Controls display confirmed values rather than predicting action results.

The drawers have no links to each other. Battery has a Batteries section with one
system card, then Device batteries with separate keyed cards. The system card has
percentage, pack
name and estimate at top left, health/cycle/energy/power metrics at top right,
and the full-width charge gauge below, followed by a power-source explanation.
Battery-wear guidance lives in the health tooltip. Multiple packs remain keyed
sections within the metrics block, alongside the aggregate charge summary.
`ChargeGauge.qml` overlays the actual limit as a solid rounded marker without an
outline.
The full track always represents 0–100% charge. Slider padding maps the advertised
minimum/maximum onto that same track, rather than rescaling the battery level.
Drag release and keyboard steps submit integer limits; only dragging previews a
new value. Status refreshes do not replace the slider or its keyboard focus.
`MetricChip.qml` groups icon/value readings with labels and explanations in passive
tooltips. Missing values use a dash. Performance uses three compact profile
choices, hiding captions at narrow widths; warnings remain visible. CPU, memory,
GPU and fan details use the same chips. Sleeping GPUs omit inactive counters.

The battery hardware module declares UPower and its service for all hosts. UPower supplies
system batteries (`Type=Battery`, `PowerSupply`, `IsPresent`),
external power, capacity, health, cycles and energy rate. Its display device
supplies the aggregate percentage/state/estimate, including for multiple packs;
the backend never averages pack percentages or derives its own time estimates.
Zero cycles/rate/percentage are valid; negative cycles, zero time estimates and
missing capacity remain unknown. Fully charged, pending charge and estimating
are distinct. Peripherals have separate rows and never enter the system battery
inventory or its aggregate percentage/runtime. Coarse UPower battery levels are
shown as labels rather than false precision. Device rows use daemon reports;
the shell does not poll Bluetooth hardware.
Remaining-runtime estimates are hidden on external power, including residual
discharge while charge-capped; actual battery flow remains visible.
`bar/BatteryStatus.qml` independently subscribes through Quickshell's native
UPower service; its percentage is a fraction, unlike the D-Bus API's 0–100 value.
The bar loads no detailed helper and polls no hardware.
The Performance bar icon follows native `PowerProfiles` notifications, using the
same profile-to-icon mapping as the drawer without starting its telemetry worker.
System-wide plug/unplug selection belongs to the power module's
`power-source.service`, which selects through PPD; the shell only displays the
confirmed resulting mode. Balanced and Performance preserve mpv quality;
Powersave alone overlays cheaper playback settings.
Keep passive hardware indicators event-driven. Dedicated GPU runtime power status
does not provide ordinary sysfs change notifications, so there is no background
GPU badge or poller. Read GPU telemetry only while the Performance drawer is active.

Profiles use the public `org.freedesktop.UPower.PowerProfiles` API, with the older
`net.hadess.PowerProfiles` interface as fallback. This includes tuned-ppd. Only
advertised standard profiles appear, ordered Powersave, Balanced, Performance,
with degradation, inhibition and application
hold information. Mutations revalidate the daemon's unique bus owner, previously
observed profile and supported choices, then read back the active profile.
The drawer never writes platform profiles, CPU governors or EPP directly.
Existing daemon policy controls profile authorization.

CPU boost belongs to the selected system mode; the shell has no independent
boost action or privileged boost helper. TuneD owns that control on Zephyrus.
Performance shows hardware readback mismatches, while GPU edge, hotspot and memory
temperatures are labelled separately and read only while the device is awake.
See the [power architecture](../../hardware/power/ARCHITECTURE.md) for session,
mpv and temporary panel-refresh policy. The existing display service observes
native profile changes independently of drawer lifetime. Its `powerState`
retains temporary mode overlays across short-lived backend processes; ordinary
display preference saves exclude those overlays.
Refresh restoration stays pending while a panel is blank. Hypridle's wake
notification applies it once awake, without a periodic display probe.

CPU utilization uses `/proc/stat` deltas (excluding the already included guest
counters), with a fresh baseline after long gaps. Frequency averages available
cpufreq policies; CPU temperature is the highest valid sensor on recognized CPU
hwmon providers. Memory uses `MemTotal - MemAvailable`, with swap and PSI `some`
average over ten seconds. These are system measurements, not process attribution.
Missing sensors and a first CPU sample remain unknown rather than showing zero.

DRM inventory uses local sysfs identifiers and the installed PCI name database.
GPU utilization, VRAM and temperature are optional sysfs counters. Runtime-
suspended devices skip sensor reads, including through hwmon. No render node,
NVML or `nvidia-smi` is opened to collect telemetry. Fan RPM uses standard hwmon
attributes, including real zero readings. No raw fan or graphics-mode writes are
offered. The header opens btop through `xdg-terminal-exec` for process inspection.
Per-application GPU launching and whole-system graphics-mode switching are outside
these drawers.

For runtime-managed GPUs, sensor reads are spaced at least eight seconds apart
and longer than the advertised autosuspend delay. Interim snapshots reuse the
last reading with its age; a suspended state immediately clears those readings.
This matters even for an already-active GPU: AMD hwmon reads can reset its idle
timer and prevent it from sleeping. The generic hwmon fan scan excludes AMD GPU
chips so it cannot bypass this pacing. Platform ASUS fan tachometers remain
available independently of dGPU runtime state.

Device-specific extensions are installed Python providers in
`$XDG_CONFIG_HOME/devices/power/backends/*.py`. Each exposes `Provider(bus)`,
`snapshot()` and `change(request)`. Snapshot records carry an identity, actual
`limit` or null, and supported `minimum`/`maximum`/`step`. The
shared controller owns discovery and delegates charge-limit requests; providers
own vendor capabilities, validation, typed D-Bus writes and readback. Reads use
`NO_AUTO_START` and never start daemons. Adapter failures cannot suppress the
generic battery/profile/telemetry sections. Zephyrus's implementation lives with
its [hardware module](../../hardware/devices/zephyrus/ARCHITECTURE.md#battery-care-and-performance).

Interface references: [UPower Device](https://upower.freedesktop.org/docs/Device.html),
[ASUS platform proxy](https://github.com/OpenGamingCollective/asusctl/blob/main/rog-dbus/src/zbus_platform.rs)
and [Linux CPUFreq](https://docs.kernel.org/admin-guide/pm/cpufreq.html).

### Power utilities

Both drawers use a scrolling body and a separate footer. Battery offers one-time
full charging for supported limits below 100% while plugged in; a pending action
replaces it with **Restore charge limit**, also available when restoration needs a
retry. Performance has mode choices and CPU, memory, GPU and fan cards. Its
recording footer toggles between starting and stopping an open-ended workload
recording. Results appear above the controls. Hyprland's Ctrl+Shift+P global
shortcut opens or closes this drawer even over fullscreen applications.

`PowerSession.qml` starts `session.py` once from `shell.qml`, independently of
drawer lifetimes. It subscribes to UPower and login1 events, but only queries
battery daemon properties when a one-time charge is pending or explicitly
requested. Relevant events debounce for 250 ms. Device batteries come from the
ordinary drawer snapshot; no closed-drawer peripheral discovery runs. There is
no background history, notification target, temporary profile or profile-daemon
subscription. No background thermal/fan/CPU/GPU sampling or status timer runs.

An advisory lock prevents overlapping helpers during reload. Quickshell owns a
small idle supervisor; the event helper runs in a separate session with the same
pipes. QProcess destruction kills its direct child immediately, so this separation
lets stdin EOF reach the helper and stop its recorder during reload. The supervisor
only waits for its child and forwards termination signals; it has no timer. The
QML transport retries a stopped helper after five seconds. The ordinary drawer
helper still stops on dismissal. While PowerSession is started, PowerService
routes mutations through it; manual limit changes cancel the one-time intent.
Command completion refreshes an open drawer.

`$XDG_STATE_HOME/quickshell/power/session.json` stores the pending one-time charge
and last recording only. Invalid actions and unknown top-level fields are
discarded on load. Explicit changes save immediately by fsync and atomic
replacement. One-time charging records the previous supported limit before
requesting 100%. Unplugging restores it using fresh provider identity/readback;
a new boot also restores it at startup. Missing controllers retain restoration
for subsequent events or an explicit retry. Externally changed limits are respected.
Actions need the shell running: unplug/replug cycles entirely while stopped cannot
be reconstructed. The ordinary charge-limit slider can end a full-charge override.

Recording is available when `power-study` is installed. It runs until stopped
at two-second intervals, with no child workload or GPU sensor
telemetry. The helper checks completion every two seconds only during recording.
Results live in timestamped directories under the power state directory. The
drawer shows CPU usage, peak memory/temperature and comparable battery discharge,
with interrupted/invalid-run reasons and folder access. A source/policy/display
change invalidates comparison according to power-study's rules. Recording survives
drawer dismissal; shell exit/reload sends SIGTERM, allowing a partial summary,
then bounds shutdown to eight seconds. The last result reloads from disk.

Validation: `python3 -B -m unittest discover -s tests -p 'test_power*.py'` covers
charge restoration/reload, manual overrides, unavailable controllers, malformed
state, recording lifecycle, telemetry, stale mutation rejection, keyboard input
and narrow layouts. Tests mock hardware mutations. Use
`DISPLAY_PREVIEW_PLATFORM=wayland DISPLAY_PREVIEW_DIR=/tmp/power-preview` for native
captures and icon QA. Install new asset links before reloading the shell.

## Icons

Interface SVGs are copied without modification from Lucide's `icons/` directory,
revision `440a1e1dfb1e712505308da46bead3c28b1f1398`. Add individual SVGs as needed
and retain their license notices. `ui/Icon.qml` tints monochrome interface icons;
application artwork uses `ui/AppIcon.qml` and the system icon theme.
`cloudflare.svg` uses a `currentColor` fill for theme tinting.

## Time and weather

`WeatherDrawer.qml` owns a transient `weather/WeatherService.qml`. It never imports
or changes the system island's clock/weather state. The island icon and tooltip
use the first configured place unless `islandLocation` names another location id
in `weather.json`. `bar/WeatherStatus.qml` checks its cache once per minute and
fetches automatically when it reaches 30 minutes, including with the drawer closed.
The icon follows weather code and day/night state; the tooltip also shows the full
system-local date/time. Background work never reads or writes drawer selection.
Failed background fetches retain cached conditions and retry after five minutes.
Other saved locations are never prefetched; they only fetch while selected in
the drawer with an expired cache (or on manual refresh).
There is no clock-format setting, automatic location detection or account/API-key
setup. Browsing remains independent of system settings; the pin is the explicit
system timezone action.

The inventory is an unmanaged, user-owned JSON object at
`$XDG_CONFIG_HOME/quickshell/desktop/weather.json` (default `~/.config`). It contains
a `locations` array; each entry needs a unique string `id`, display `name`, numeric
`latitude` and `longitude`, and an IANA `timezone`. Optional `detail` disambiguates
places in the picker. An empty/missing inventory shows setup guidance; invalid
entries report an error without rewriting the file. Personal places must never
be included in provisioning assets, generated manifests, fixtures or examples.
`islandLocation` is the explicit current/default location id; omission uses the
first entry. The drawer pin applies the selected IANA timezone through
`timedatectl --no-ask-password`, validates readback, then saves that field while
preserving the inventory and unknown fields with atomic mode-0600 replacement.
A failed timezone change leaves the config alone; a failed config save restores
the previous timezone. The current pin can be reapplied to repair a timezone
changed elsewhere. Reading weather or opening the drawer never changes timezone.
`LocationSettings.qml` is a feature-local singleton, so a pending timezone
change/save survives drawer
dismissal/destruction. On success it calls `Date.timeZoneUpdated()` to clear Qt
QML's cached timezone offset, then notifies the bar to refresh its clock and date
immediately. Normal minute updates still come from `SystemClock`.
The bar watches this file and immediately rereads after changes, deferring past
any in-flight response so the old location cannot overwrite the new one.
`50-desktop-timezone.rules` grants only `org.freedesktop.timedate1.set-timezone`
to active, local members of `wheel`. System time, RTC and NTP permissions retain
their existing policies. Install the rule as root (provisioning manages it as a
file asset); polkit reloads it automatically. Runtime calls forbid interactive
authentication, so a missing/denied permission becomes a short drawer error.
Clock synchronization remains with the existing NTP service.

The selected id is saved separately in `weather-selection.json` using atomic
replacement and mode 0600. New or removed selections fall back to the configured
current location. Ordinary selection never changes `islandLocation`.

`weather/backend.py` uses only the Python standard library. Local status reads
supply a ZoneInfo clock even without networking. While active, a cheap QML timer
checks minute boundaries; local reads update the clock and reload configuration
once per minute, including local clocks for every picker row and the main clock.
The closed picker is a bare chevron at the far right of the clock/date row; its popup
retains location names, details, local times and the selected checkmark. The bare
pin sits immediately before the chevron; refresh remains in the drawer header. A separate cancellable process
fetches Open-Meteo over HTTPS with an 18-second timeout. Closing stops both
processes and the timer. Selection clears
the old place immediately; revision tokens discard delayed responses, including
local reads racing a successful forecast refresh. The picker consumes Escape
before drawer dismissal and supports normal keyboard selection.

Forecasts use °C and km/h, current conditions, six upcoming hourly temperatures
and precipitation probabilities (four at narrow widths), and five daily forecasts.
Wind and humidity stack at the right of current conditions; narrow drawers place
them on their own row below the temperature.
Request UNIX timestamps and convert hours through ZoneInfo to handle daylight
saving changes. Daily dates use the API's fixed UTC offset as documented by
Open-Meteo. Missing metrics stay unknown rather than becoming zero.

A short sentence for each forecast day adapts the daily-outlook idea in zephyrus-shell
(`attention/weather.py`): daylight hours determine predominant sky conditions,
all hours contribute wet/fog spells, and at most one secondary event is included.
It requires at least 18 valid local-day hours and daylight coverage; incomplete
days omit the sentence. Today's outlook appears under current conditions without
a date prefix. Each daily row uses the shared passive tooltip to show its own
outlook, falling back to the provider's condition when hourly coverage is incomplete.
These summaries reuse the cached hourly forecast and require no extra requests.
This is a model-based daily outlook and never overrides
the provider's current condition or island icon. Current conditions come from
Open-Meteo's 15-minute model data, rather than a local observation. The requested
point can resolve to a grid cell several kilometres away.

Validated raw forecasts are stored under
`$XDG_CACHE_HOME/quickshell/desktop/weather/` (default `~/.cache`) in private,
atomically replaced files keyed by coordinates and timezone. Cache hits avoid
network requests for 30 minutes and are shared by the island and drawer.
Automatic fetches acquire a per-place file lock and recheck freshness after
locking, avoiding duplicate downloads across outputs or simultaneous drawer reads.
Manual refresh bypasses freshness checks. Drawer failures retry at most every five
minutes while open. Switching places shows cached weather immediately only if
it is younger than 30 minutes; expired data is hidden until fresh weather arrives.
An already displayed forecast remains available if a later refresh fails.
Forecasts older than one hour are marked outdated. Fetch failures preserve the last successful data
and update time, and show a short error. Changed coordinates cannot reuse another
place's weather. Names and coordinates never enter tracked configuration.
The additional weather SVGs are local drawings matching the existing icon style.

Reference implementations reviewed:
[Caelestia weather service](https://github.com/caelestia-dots/shell/blob/main/services/Weather.qml),
[DankMaterialShell weather service](https://github.com/AvengeMedia/DankMaterialShell/blob/master/quickshell/Services/WeatherService.qml),
[Plasma weather improvements](https://blogs.kde.org/2026/10/17/this-week-in-plasma-new-weather-widget-and-on-screen-keyboard/),
and [Open-Meteo API](https://open-meteo.com/en/docs).

```sh
python3 -m unittest discover -s tests -p test_weather_drawer.py
```

Tests cover date rollover, DST, private persistence, cache isolation/freshness,
nullable and malformed responses, failed refresh retention, keyboard selection,
Escape, narrowing, offline clocks and cancellation/delayed-reply handling. They
mock network calls and location inventories. Set `DISPLAY_PREVIEW_PLATFORM=wayland`
and `DISPLAY_PREVIEW_DIR=/tmp/weather-preview` for native captures; offscreen
rendering cannot verify icon tinting. Install links for newly added QML, helpers
and icons before checking the installed configuration.

### Alarms and focus reminders

`weather/ReminderControls.qml` adds Focus and Reminders sections below the
forecast, each with a full-width action and a separate editor. The focus button
shows the active phase's countdown and stops the cycle directly. One-shot
reminders appear below their add button, each with an individual stop action.
Multiple one-shot alarms and one repeating pomodoro can run together.
The pomodoro defaults to 25 minutes of focus and a 5-minute break; both intervals
are editable. Escape closes the editor before the drawer. Each popup matches its
button's actual width and opens below the button.
Opening and confirming use distinct labels (Set up focus / Start and Add reminder
/ Schedule). Popup content omits duplicate titles, timezone and next-time labels.

`ui/NumberField.qml` styles Qt's editable `SpinBox` with compact up/down arrows,
integer bounds and optional two-digit padding. Typed input is committed before
keyboard or pointer steps so arrows operate on the entered number. Focus/break durations
and the separate hour/minute fields share it. Reminder defaults use the next
actual minute. The editor holds that local date and rejects elapsed times instead
of silently scheduling tomorrow; a midnight default rolls onto the next date and
shows only a small Tomorrow hint. An editor-only timer keeps validation current
even without pending reminders. The service revalidates the date on submission.
The message occupies its own row so it remains usable in narrow drawers.

Input controls reviewed:
[Caelestia StyledSpinBox](https://github.com/caelestia-dots/shell/blob/main/components/controls/StyledSpinBox.qml),
[DMS DTimePicker](https://github.com/AvengeMedia/dank-qml-common/blob/master/DCommon/Widgets/DTimePicker.qml),
and [Qt SpinBox](https://doc.qt.io/qt-6/qml-qtquick-controls-spinbox.html).
The numeric editor uses Qt's control rather than importing either shell's UI.

`weather/ReminderService.qml` is a lazily imported QML singleton outside the
transient drawer's lifecycle. Entries exist only in memory, survive drawer
dismissal, and clear on shell exit/reload. A one-second timer runs only while
entries exist. Alarms resolve the next occurrence of an `HH:mm` system-local
time to an absolute deadline at creation; later timezone changes do not move
that deadline. Searching actual minutes handles DST gaps and repeated hours.
The due label follows the current system timezone.

Deadlines use wall-clock milliseconds, so an overdue alarm fires after resume.
An overdue pomodoro sends one notification and starts the next phase from the
current time rather than replaying missed phases. Nothing wakes the computer.
Stopping an entry removes it immediately; there is no background worker or
persisted state.

Delivery uses `notify-send` with literal arguments and escaped body markup.
The notifications module declares `libnotify`; the shell owns the notification
service and can activate over D-Bus. Desktop notification policies, including do-not-disturb, apply.
The alarm icon is from Lucide under the existing icon license.

```sh
python3 -m unittest discover -s tests -p test_reminders.py
```

Tests exercise one-shot delivery, cancellation, DST, sleep/resume, focus/break
transitions, real numeric typing and step arrows, past-time rejection, midnight
defaults and editor expiration, popup input/dismissal, button/field widths and
label centering in full and narrow layouts,
and drawer destruction. The desktop interaction test also opens both editors in
the production drawer host and checks their width and Escape handling. Tests
replace delivery or the `notify-send` executable, so no real notifications fire.

## Events, tasks and notification history

Events/tasks and notifications have separate catalogue/bar entries. CalendarService
warms cached data from the shell root and synchronizes quietly; its writes and
optimistic state survive drawer dismissal. Calendar provider accounts are shared
outside feature folders. NotificationCenter owns native notification delivery,
popups, history and quiet state for the shell lifetime. See [shared accounts](symlinks/home/.config/quickshell/desktop/integrations/ARCHITECTURE.md)
and [calendar lifetimes and protocol](symlinks/home/.config/quickshell/desktop/drawers/events/ARCHITECTURE.md).
Native delivery and migration are documented in
[notification architecture](symlinks/home/.config/quickshell/desktop/drawers/notifications/ARCHITECTURE.md).
