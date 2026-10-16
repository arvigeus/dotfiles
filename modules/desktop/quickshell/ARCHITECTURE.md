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

## Icons

Interface SVGs are copied without modification from Lucide's `icons/` directory,
revision `440a1e1dfb1e712505308da46bead3c28b1f1398`. Add individual SVGs as needed
and retain their license notices. `ui/Icon.qml` tints monochrome interface icons;
application artwork uses `ui/AppIcon.qml` and the system icon theme.
`cloudflare.svg` uses a `currentColor` fill for theme tinting.
