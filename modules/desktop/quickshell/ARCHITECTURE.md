# Desktop shell implementation

Sources live under [desktop/](symlinks/home/.config/quickshell/desktop/).
QML edits reload automatically.
Repository provisioning rules are in [the root architecture](../../../ARCHITECTURE.md).

## Lifetimes

`DrawerHost` lazily creates one `DrawerPage`. Closing clears `active` immediately;
the page survives only the exit animation. Bind observation to `active`, and keep
operations that must survive dismissal in feature-local services. Header actions
belong to the page and are loaded by the host; the catalogue must not import services.

The installed shell uses individual file symlinks. Editing an existing linked
file reloads it, but adding a component or helper also requires installing its
new link before reloading. Regenerating the manifest alone does not publish
links. Verify component loading through the installed configuration as well as
repository fixtures, which cannot detect missing installed files.

## Scrolling

`ui/WheelScroll.qml` supplies immediate 120-logical-pixel mouse-wheel steps,
proportional high-resolution wheel deltas, bounds and nested-view propagation.
Touchpad gestures retain native precision and inertia. `ScrollListView.qml` owns
this behavior for lists, including launcher results and display options;
`DrawerColumn.qml` installs it on its internal Flickable for all drawer forms.
Keep wheel behavior in these widgets rather than tuning individual drawers.

## Networking

- `drawers/network/NetworkService.qml` serializes requests to `backend.py` over
  stdin/stdout JSON. The backend uses libnm; passwords never enter argv or status
  snapshots. Mutations survive page dismissal; NetworkManager owns connections.
- Observation runs only while active: status every 5 seconds, scans every 20.
  User actions take priority over queued reads. `Models.js` reconciles keyed rows
  to preserve focus, password input and ordering through refreshes.
- `bar/NetworkStatus.qml` uses native NetworkManager notifications with scanning
  disabled. Keep it independent of the drawer service so bar updates stay cheap.

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
  the device header; every input retains a title/checkmark, status and gain row.
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
  routing targets the current connected port of an exposed sink. `libpulse` provides pactl; pavucontrol is the advanced editor.
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

| Source | Owns |
| --- | --- |
| [Shared labels](../../hardware/audio/symlinks/home/.config/devices/audio/profiles.json) | Plain-language profile names; driver labels remain available on hover |
| [Zephyrus audio](../../hardware/devices/zephyrus/symlinks/home/.config/devices/audio/zephyrus.json) | Laptop speakers, headphone jack and graphics audio connections |
| [Dell S2722DC](../../hardware/peripherals/dell-s2722dc/symlinks/home/.config/devices/audio/dell-s2722dc.json) | Monitor speaker name, overriding generic graphics audio names |

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
      "match": {"device.name": "alsa_card.example", "port.name": "analog-output-headphones"},
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
stays enabled. These safety fallbacks do not overwrite unchanged saved preferences.
Restoration uses the same validation, readback and rollback path as manual changes.
Hyprland `configreloaded` queues a debounced restore rather than saving reset
defaults. Monitor enable/disable events alone do not trigger restoration: they
can be deliberate edits in wdisplays, while `monitors all` distinguishes physical
topology from enabled state. No window/workspace preferences are saved.
There is no primary/default display preference: launcher output selection and
Hyprland's window/workspace placement remain authoritative.
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
`ComfortControls.qml` presents only the Night light toggle. The monitor cog owns
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

## Icons

Interface SVGs are copied without modification from Lucide's `icons/` directory,
revision `440a1e1dfb1e712505308da46bead3c28b1f1398`. Add individual SVGs as needed
and retain their license notices. `ui/Icon.qml` tints monochrome interface icons;
application artwork uses `ui/AppIcon.qml` and the system icon theme.
`cloudflare.svg` uses a `currentColor` fill for theme tinting.
