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
focus off the test field and, after success, refocuses it
with a short delay so a cold-started IME can attach. The single-line test field
uses `NetworkField` styling. Test text is page-local, never persisted and cleared
on dismissal. The help popup has separate Telex, Phonetic and shortcut tabs,
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
The module declares `libnotify` and Dunst, whose notification service activates
over D-Bus. Desktop notification policies, including do-not-disturb, apply.
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
