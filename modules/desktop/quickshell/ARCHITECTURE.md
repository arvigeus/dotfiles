# Desktop shell implementation

Sources live under [desktop/](symlinks/home/.config/quickshell/desktop/).
See the [root architecture](../../../ARCHITECTURE.md) for provisioning and
[tests/ARCHITECTURE.md](../../../tests/ARCHITECTURE.md) for isolated checks.

## Ownership and lifetimes

`desktop-shell.service` belongs to `graphical-session.target` and uses
`UMask=0077`. The shell root starts notifications first (it is their D-Bus
activation target), calendar warming, display policy, clipboard control, power
utilities and capture clients. Other helpers run while observed or completing
an action. Hardware modules own device providers; this module owns the shell and
its Qt/Python, clipboard and capture dependencies.

`InteractionState` owns one interactive surface across outputs.
`InteractionWindow` handles focus, keyboard ownership, backdrop clicks and Escape.
`DrawerHost` owns the registry, shortcuts and one lazy `DrawerPage`. Dismissal
clears `active` immediately but retains the page for its exit animation. Entrance
waits for page creation to settle. Bind observation/cancellable work to `active`;
put work that must survive dismissal in a feature service. Page popovers consume
Escape before the host.

Installed QML files are individual symlinks into the checkout. Existing-file edits
reload automatically; adding a component requires regeneration and apply before
importers reload. Restart after publication if the engine cached a missing type.

`Apps.launch()` uses `uwsm app -t service`, giving applications independent units
and the user manager's ordinary umask. Helpers retain their parent's lifetime.
The launcher passes desktop entry IDs to UWSM for field-code/working-directory
handling. For IDs outside `[A-Za-z0-9_][A-Za-z0-9_.-]*`, `launcher/entry_path.py`
resolves the winning XDG entry and passes its path. Enter/arrows/Ctrl+D flush a
pending debounced query; catalogue/favorite changes preserve selection.

## Shared UI

`Theme` reads the shared palette and user-owned `theme-mode` preference (dark by
default); production synchronization starts through `Theme.start()`. See
[appearance integration](../../look-and-feel/ARCHITECTURE.md).
`Card` and the `Shell*` controls centralize appearance. `HoldButton` cancels on
release, focus loss, disablement or dismissal; key repeat remains one hold.
`PassiveToolTip` never takes input. Scroll containers reveal keyboard/programmatic
focus after layout settles; pointer focus does not scroll.

Native QObject lists use `ScriptModel`. Keyed snapshots use `KeyedModel` and
`ui/Models.js`, preserving delegates/focus while updating moved records.
Quickshell 0.3.2's `ScriptModel.objectProp` can leave moved `modelData` stale.

## Spaces

`ui/SpaceState.entries` is the registry. `SpaceState` owns running IDs/current
Space; `SpaceHost` owns async loaders and effective activation. It uses the shared
interaction surface, anchored on all edges above the panel with ignored exclusion
zones. Qt handles output scale. Output loss or another interactive surface hides
the Space without unloading it; explicit close unloads it and drops pending open
payloads. Page `host.hide()` / `openModule(id, payload)` act only while shown,
preventing late callbacks from reopening or switching Spaces. Escape first calls
`dismissTransient()`; the host hide control stays above page popups.

Spaces share cinematic controls, keyed catalogue updates and activity indication;
see the [presentation contract](symlinks/home/.config/quickshell/desktop/spaces/movies/ARCHITECTURE.md#presentation-contract).
Provider, persistence and worker details belong to each Space:

- [Movies](symlinks/home/.config/quickshell/desktop/spaces/movies/ARCHITECTURE.md)
  and [Series](symlinks/home/.config/quickshell/desktop/spaces/series/ARCHITECTURE.md)
- [Games](symlinks/home/.config/quickshell/desktop/spaces/games/ARCHITECTURE.md),
  [Books](symlinks/home/.config/quickshell/desktop/spaces/books/ARCHITECTURE.md)
  and [Pictures](symlinks/home/.config/quickshell/desktop/spaces/pictures/ARCHITECTURE.md)
- [Music](symlinks/home/.config/quickshell/desktop/spaces/music/ARCHITECTURE.md),
  [Radio](symlinks/home/.config/quickshell/desktop/spaces/radio/ARCHITECTURE.md),
  [Television](symlinks/home/.config/quickshell/desktop/spaces/television/ARCHITECTURE.md)
  and [Streaming](symlinks/home/.config/quickshell/desktop/spaces/streaming/ARCHITECTURE.md)

`SessionService` reads logind capabilities and `ScheduledShutdown` on demand.
Systemd owns shutdown timers. Gaming/reload delegate to `session-mode`; see
[session ownership](../hyprland/ARCHITECTURE.md#session-ownership). Temporary
sleep/locking pauses use `ComfortService` leases.

## System tray and bar badges

The native tray stays registered while closed. Attention combines item status
with unseen matching notifications, not inferred application unread state. See
[tray matching and menu lifecycle](symlinks/home/.config/quickshell/desktop/drawers/tray/ARCHITECTURE.md).

Window order follows client positions, refreshed 180 ms after the first event in
a burst so title-event streams cannot postpone it. Lua bindings emit
`desktop-layout-changed` for actions without native order/geometry events.
Each bar records `urgent` until `activewindowv2` or `closewindow`; Quickshell
0.3.2 clears native urgency too early when a workspace gains focus. Records are
session-local. Tab selection focuses and centers through one Lua callback;
workspace policy belongs to [Hyprland](../hyprland/ARCHITECTURE.md).

## Clipboard

`cliphist@text/image.service` run for the graphical session, independently of the
shell, with 50-item retention. `clipboard/backend.py` adapts history operations and
pauses both watchers. Pause survives shell reload but not the login session.
History stays in cliphist's database. Private preview files are removed when
entries disappear, capped at 32 and cleared at helper start/exit. Copy decodes
by ID into wl-copy's stdin. Dismissal drops queued previews.

## Assistant

`AssistantService` is created by the first drawer or external attachment request.
It retains conversation/draft and a streaming process across dismissal; shell
exit drops them. Lemonade is independent. Opening requests read-only Status;
Send/Retry, model selection and Open Lemonade connect on demand. Status polls only
while observed/online or awaiting a model download; generation and control work
suspend redundant polling. `models_generation` and native alias changes refresh
the catalogue independently. A helper that cannot start, or exits unanswered,
ends its request with an error; `Process` emits no `exited` for a failed start.

Start/Stop use the packaged user `lemond.service`, without enabling it; an active
system unit takes precedence. Start awaits the HTTP listener, also for a unit that
is already starting. The loopback port comes from the instance's `config.json`
under its XDG config directory (default 13305); the system instance's is private
to its user, so an unreadable file means the default. Optional `LEMONADE_API_KEY`
and `LEMONADE_ADMIN_API_KEY` (preferred for `/internal/`) come from the shell's
environment, then from the user unit's `lemonade/lemond.conf`. The system unit's
`/etc/default/lemond` is root-only: its key must reach the shell's environment.
HTTP bypasses proxies/redirects. Stop refuses known active
requests and downloads. There is no server ownership lease or
atomic idle shutdown: drawer visibility must never drive automatic server stop.
The singleton completes Open Lemonade even after dismissal, then launches the
packaged app through UWSM.

The backend uses health, models and streaming chat-completion APIs. Only local,
standalone chat models are eligible; image context additionally requires vision.
No independent memory-fit estimate is maintained. Native aliases are resolved
again before concrete download/delete/unload operations. An unavailable optional
`/internal/aliases` endpoint leaves public inference usable without alias grouping.

First Send uses Lemonade's native download/load behavior, not a client download
queue. In 2026.45.3 that path creates no managed download job and cannot cancel
its server-side fetch: the client shows indeterminate status and detects completion
by polling. Managed jobs from the Web App expose progress and pause/resume through
`/v1/downloads`, `/v1/downloads/control` and `/v1/pull`; a stopped job (paused,
failed or cancelled) stays listed and restarts with another pull. Deletion/unload recheck
busy/pinned/download state and let Lemonade own files. Deleting `user.*` also
removes its registration. Alias operations affect their concrete target.
Deletion is a `HoldButton`, like the shell's other destructive actions.

SSE parsing handles Unicode, multiline events, errors and premature EOF; text
received before a failure is kept. Cancel terminates the request and retains
partial text; retry replaces the last answer. A reply is cut at 160,000
characters, the context limit it could never be sent back under. Consecutive
turns of one role, left by a failed reply, are sent as one turn because many chat
templates require alternation. Reasoning is bounded separately to 64,000
characters and excluded from future context. Reply length changes the system
instruction, not token caps that would also consume the reasoning budget.
`thinking` sends Lemonade's `enable_thinking` only for explicit on/off; style sets
temperature only for Precise/Creative. A reply that ends while no drawer observes
the service sends a notification.

`assistant.json` stores `model`, `length`, `style` and per-model/alias `thinking`.
Chat stays in memory, bounded to 80 messages. Offline Send freezes prompt/settings/
attachments; after connecting, that exact model must still exist. A missing model
or failed startup preserves the draft, including later typing.

History, requests, editing and Copy keep the raw Markdown; `Markdown.js` is
presentation only. Qt's Markdown renderer fetches images and raw-HTML
backgrounds (`background=`, CSS `background-image`) from any URL, so a reply
could otherwise make the shell contact a host of its choosing. Top-level fenced
blocks therefore become exact plain-text segments with sideways scrolling. The
rest is prose: image syntax becomes a link, every raw HTML tag is escaped
(`<br>` becomes a space), and only single-line code spans are left untouched.
That pass is per line and ignores block structure, because a block this file
read as code but the renderer read as HTML would load its URL. The cost is that
HTML inside multi-line spans and quoted or nested fences shows as `&lt;`.
`tests/test_assistant_drawer.py` renders the known vectors against a loopback
canary; extend `REMOTE_CONTENT` when changing the pass. Segment delegates are
keyed by count, so a streaming reply re-renders only its last segment. Display
hard breaks are added outside code. Links open only on activation.

### Attachments and Dolphin sharing

`attachments.py` prepares immutable in-memory snapshots in a separate process.
The embedded file dialog, DropArea and clipboard all use this importer. Clipboard
requests freeze the selection and preserve later typing; preparations queue and
survive dismissal. Pasted text above 64,000 characters is refused, not inserted. Send/retry/edit use frozen snapshots rather than rereading paths.
New chat/shell exit drops them; there is no disk attachment cache.

Inputs must be regular local files: six per message, 16 MiB each. Nonblocking
open/fstat rejects special files. QImageReader bounds source images to 40 MP /
128 MiB allocation, auto-orients, scales to 2048 pixels and re-encodes within
4 MiB. Text accepts UTF-8/BOM UTF-16. PDF uses bounded, timed `pdftotext` via stdin;
DOCX/ODT use bounded UTF-8 XML extraction without DTD/entities. Extraction refuses more
than 64,000 characters/document; context caps are 160,000 text characters and
24 MiB encoded. Oversize input fails visibly. Generation revalidates snapshots
and vision support; it never reads paths or fetches attachment URLs.

The KDE Purpose scripted Export provider and `desktop-assistant-context` helper
belong to this module. Purpose discovers metadata per process; Dolphin may need
restarting. `--server` reads bounded length-prefixed CBOR with PySide6 and replies
using Purpose's JSON protocol. Direct invocation accepts local paths. Both routes
reject remote URLs/folders/special files and call the exact shell configuration's
`assistant.addFiles` IPC with an object containing `files` (a bare array would
expand into CLI arguments). Requests cap at six paths/96 KiB. `AssistantInbox`
exists while the drawer is closed; accepted preparation preserves the draft and
never connects to Lemonade. Completion notifications describe actual additions
and partial errors. See [Purpose's protocol](https://github.com/KDE/purpose/blob/v6.31.0/README.md#separate-process).

## Capture

Screenshots use `desktop-screenshot`; see [Hyprland capture integration](../hyprland/ARCHITECTURE.md#desktop-integration).
`CaptureService` freezes options and dismisses surfaces before the countdown ends.
`screenshot-editor` / `screenshot-save` are user-owned preferences shared with
shortcuts. Slurp processes must have stdin closed: it reads non-terminal stdin
for suggested boxes and otherwise waits indefinitely on Qt's unused pipe.

Socket-activated `desktop-capture.service` owns recording and speech independently
of shell reloads. Its private runtime socket uses newline JSON; command replies
carry `reply`, state changes do not. Clients count only replies, allow Stop ahead
of pending replies and retain the connection while busy. Slow-client updates
coalesce without partial lines. Upgrade this protocol service-first. The service
exits after 30 seconds without clients/jobs, except while owning the clipboard.

`capture/recorder.py` owns GPU Screen Recorder; `KillMode=mixed` permits MP4
finalization before teardown. No first frame within 20 seconds stops capture;
failure to exit within 15 seconds of SIGINT kills it, retains the file and reports
the log tail. Preferences are in `recording.json`; output is XDG Videos/Recordings.

`capture/speech.py` freezes each job's model/language/output/paste target and
publishes the `speech` snapshot through `speech-*` commands. Whisper CLI performs
local inference; Voxtype acquires selected weights into `$XDG_DATA_HOME/voxtype/models`
without its daemon. `speech.json` stores preferences. Languages come from the
installed libwhisper C API, limited by the selected checkpoint's vocabulary.
Setup downloads then stops at ready, without opening a microphone. Downloads use
one replaceable progress notification; final notices contain no transcript text.

Microphone input is 16 kHz mono WAV, limited to two minutes for dictation or
30 minutes for saved audio. Muted/unavailable inputs wait for explicit approval.
Approval expires after ten seconds and cannot follow a default-device change.
The job snapshots source/Pulse/PipeWire/device identity, records that exact source
and restores only a mute it changed, before inference and on failure/cancellation.
A replacement device never inherits that restoration; restoration failure remains
an actionable warning. `pw-record` may finalize on SIGINT with exit 1: accept it
only without diagnostics and after WAV/sample-length validation.

File requests use `speech-file` with an absolute path, `output` (`clipboard` or
`srt`), `jobId` and optional frozen model/language overrides. FFmpeg decodes at most
six hours plus one second and rejects overlong media. Decode/inference deadlines
are 24 hours/file phase, fifteen minutes/microphone inference and thirty minutes/
download. Cancellation kills owned process groups and removes private job files.
SRT stages private adjacent output, checks source identity and publishes without
replacement; existing/concurrent sidecars are refused. Stale job cancellation is
ignored. Rejections use per-reply `requestError`/`requestJobId`, preserving an active
job's result. `FileSpeech.qml` adapts this for Movies/Series; the
[native transcription client](../../media/tools/transcription/ARCHITECTURE.md)
serves Audio/Video tools.

Successful text delivery owns a `wl-copy --foreground` provider; service idle exit
must not kill it. Failure/empty results preserve the prior clipboard. Text never
enters socket snapshots, notifications or journal. Auto-paste requires the original
Hyprland window, no shell input surface and an acknowledged focus context; it
uses native `send_shortcut`, never activation or Return. Imported text only copies.
Session shutdown saves audio-only capture and discards unfinished transcription.

`WebcamService` uses V4L2 and revalidates device/control identity before writing.
Preview stops on dismissal/device loss. Qt 6.12's FFmpeg camera enumeration opens
X11 on the GUI thread and can block startup. The service sets both
`QT_FFMPEG_DECODING_HW_DEVICE_TYPES` and `QT_FFMPEG_ENCODING_HW_DEVICE_TYPES` empty;
webcam video decodes in software. `FfmpegX11ProbeTests` detects when upstream no
longer needs this workaround; then remove the variables, test and this note.

## System

`system/backend.py` reads only the requested section, unprivileged, in C locale,
with bounded commands. Failed reads remain errors. Interactive actions use the
user's locale in independent UWSM terminals. Update delegates to
[Topgrade](../../system/package/topgrade/ARCHITECTURE.md); signing repair preserves
custom keyring data. Root commands require explicit confirmation.

Package health distinguishes missing files from unreadable root-only paths;
`pacman -Qkq` reports both, so paths need a second check. Opt-in privileged checks
resolve unreadable entries. Reinstall offers only affected repository packages
through a full `pacman -Syu`, avoiding partial upgrades. Missing running-kernel
modules indicate that an installed kernel needs rebooting.

## Networking

Native Quickshell Networking supplies radio, connectivity, saved networks and
Ethernet. Scanning belongs to the open drawer. `NetworkService` adds VPN/WARP,
IP details and user-scoped Wi-Fi joins via `network/backend.py`, polling only while
observed. Mutations outrank reads and finish after dismissal; request children
run in independent sessions so shell SIGKILL cannot abandon a started change.
Passwords travel through stdin/D-Bus. Failed joins delete only their newly created
profile. WARP registration/start/cleanup belongs to the
[Cloudflare lifecycle](../../internet/cloudflare/ARCHITECTURE.md).
WireGuard import launches Zenity/editor in an application unit and passes only the
filename; cancellation creates nothing, saving does not activate a tunnel.

Public IP lookup is lazy, caches ten minutes and invalidates on route changes.
Speed tests cancel on dismissal. Ports controls do not poll: opening/context
changes read runtime firewalld state, mutations return full state and concurrent
refresh requests coalesce. See [firewall ownership](../../system/security/firewall/ARCHITECTURE.md).

`network/discovery.py` scans only the selected connected private IPv4 network,
limited to its local /24, using unprivileged Nmap host discovery without ports or
reverse DNS. It is demand-driven; dismissal/context changes cancel it, and a
parent-death signal handles shell SIGKILL. Results survive dismissal until refreshed
or context changes. Late results cannot reopen a collapsed/dismissed section.

## Bluetooth

Native BlueZ controls manage power/connect/disconnect/forget. Only explicit
Connect/pair trusts devices. `BluetoothService` owns its discovery, ending it on
pairing, dismissal or after 30 seconds; it cannot stop another client's search.
A stop requested before BlueZ reports a pending start is deferred until reported.
Native failures provide no reason text, so operations watch for settled state.

Only pairing uses `bluetooth/backend.py`: a private Agent1 connection verifies
sender/device and validates PIN/passkeys. Pairing cancels on timeout, dismissal
or stdin closure. Once Pair succeeds, trust/connect finish despite late cancel.
A forked session child lets a paired device finish after shell SIGKILL while
unfinished pairing cancels on pipe closure. The Blueman agent is masked; no
default agent authorizes incoming services from untrusted devices.

## Playback

`AudioService` uses native PipeWire nodes/link groups. Detailed trackers run only
while observed. Levels use the loudest channel, not `PwNodeAudio.volume`'s average;
changes preserve balance. Sink-monitor captures are not microphone use. MPRIS
controls attach only to uniquely matching streams/application identities.

`audio/backend.py watch` debounces Pulse card/sink/source events and publishes
changed inventory. Watchers stop on dismissal and restart if observation resumes
during exit. One-shot mutations run in forked session children to finish after
shell SIGKILL. Cards match nodes by `device.name`, not incompatible Pulse indices
and PipeWire IDs.

`audio.ini` stores per-device `boostDevices`. Disabling boost caps the device and
streams; routing to an unboosted device caps the stream while preserving mute.
Changing defaults does not move existing streams. Hardware input disablement
mutes before profile changes; newly exposed captures mute before playback-route
restoration. Recheck mute while WirePlumber asynchronously restores route state.

## Audio configuration

Hardware modules publish JSON drop-ins in `$XDG_CONFIG_HOME/devices/audio/` with
`rules` and optional native-ID-to-label `profiles`. Rules require `label` plus
exact `match` or substring `contains` properties (combined with AND). Endpoint
properties include node/port name/description. Optional fields: `deviceLabel`,
`maxVolume` (1–150; default 150), `priority` (default 0). Descending priority then
file/rule order determines the first match; `{port}` expands the connection name.
Malformed drop-ins/conflicting profile labels warn without disabling valid files.
`AudioTestService` owns bounded channel/microphone probes; release stops recording
before playback and cancel discards it. Probe streams never enter the app mixer.

## Displays

`DisplayService` serializes display/brightness helpers, debounces compositor
events and reads brightness only while observed. Snapshot tokens and hardware
identities reject stale edits. Validate the whole layout, including overlap and
an independent enabled output; verify replacements before disabling old screens
and attempt rollback on failure. `display-tools` uses the same helper asynchronously,
subscribes to events and accepts only coordinate edits against the complete token.

`~/.config/hypr/display-profiles.json` version 1 stores exact connected-hardware
sets, including disabled outputs. Hardware keys use serial/make/model, then unique
descriptions, otherwise connectors. Mirrors reference hardware keys. Only explicit
edits save preferences: hotplug/wake/Powersave must not learn transient layouts.
`displays.lua` is the generated active set, loaded after host defaults; selectors
use descriptions only when uniquely matched by Hyprland. Atomic writers share a
session flock, including reads; persistence failure restores source/cache/layout.
Replacing Lua triggers a complete config reload, so Powersave reapplies its cap.

Unknown sets start side by side without being saved. Wake retries dark outputs.
Emergency undock recovery enables one output, preferring the panel; invalid saved
modes retain their source and report errors. Powersave caps only enabled internal
panels to an available mode at/below 60 Hz in live rules, retaining the uncapped
preference. Explicit refresh changes override it until the next mode change.
Brightness is independent. Identify/test windows are bounded session-owned work.

### Night light and Keep awake

`ComfortService` enables/disables packaged `hyprsunset.service` with `--now`.
Keep awake and sleep/locking pauses use separate runtime leases with flock and
atomic JSON. Display leases include hardware identity; dead/disconnected/replaced
leases are ignored/pruned. All end with the shell.
`desktop-idle` respects application inhibitors, blanks only unprotected outputs
and defers automatic locking/suspend. Exit 1 plus `defer` means a valid deferral;
other failures allow locking but block suspend. Manual/before-sleep locks are
unconditional. Without a live display lease, blanking is one global DPMS dispatch.

## Keyboard

`InputLanguage` invokes the controller declared by `input-method` in
`$XDG_CONFIG_HOME/quickshell/input-language.json`; that module owns persistence.
Requests serialize and retain the last confirmed state on failure. Native events
update the bar; Vietnamese additionally polls because Fcitx mode changes emit none.
Hardware modules install providers in `$XDG_CONFIG_HOME/devices/keyboard/backends/`.
`BacklightService` validates identity and serializes writes, discarding snapshots
older than queued slider changes. Logitech owns its mode transitions/rollback.
Shortcut reference reads native compositor binds while visible; portal-assigned
Quickshell shortcuts are separate. Lua dispatcher arguments can be opaque handles,
so undescribed actions display their dispatcher name rather than the handle.

## Disks and system cleanup

`DisksService` uses UDisks2 with fresh device/media identity tokens. Secrets use
stdin/D-Bus. It never powers off/ejects drives or unmounts system mounts. Unmount
also locks LUKS unless crypttab owns it; a failed lock reports the partial result.
Health checks preserve sleeping ATA drives. Reads run while observed; queued actions
survive dismissal. UDisks operations may finish after helper death/timeout, so lost
replies say to refresh and never trigger automatic retries. Failed helper startup
must settle on `running=false`, since no `exited` signal is guaranteed.

`CleanupService` accepts category IDs, never request-supplied paths/commands.
Availability and deletion use the same no-follow walk. Targets are re-resolved
under owner locks; categories run in catalogue order and fail independently.
There is no rollback/cancel. Shell death can leave partial caches and lose that
run's notification; launched native tools finish independently.

Path cleanup rejects HOME, XDG roots and ancestors. AUR cleanup deletes only
built archives directly in Paru clone directories, preserving sources and makepkg
trees. Development caches come from Git's ignored/untracked directories restricted
to cache names, never tracked data or payloads. Backup cleanup keeps thirty days
and the newest batch; `dotfiles-backup-cleanup` derives the caller from PKEXEC_UID,
accepts no path/UID and holds apply's lock. Only UUID backup batches are eligible.
Private backups use their own operation lock and the same retention window.

Agent cleanup keeps newest success/failure/update logs, unfinished/unknown runs,
pending updates and referenced evidence (`runs/TIMESTAMP` / `updates/TIMESTAMP`
mentions in knowledge/findings/proposals/reports). Cache cleanup removes only
known downloads and abandoned retrieval scratch data. Control state and lock
inodes remain. Both hold agent.lock; downloads also hold http.lock. Busy owners
fail promptly. Deletion tests must use temporary HOME/XDG trees, even when testing
root/path refusal.

## Battery and performance

Native UPower/PowerProfiles own battery and mode state. Detailed telemetry runs
only in Performance and must not wake sleeping GPUs. See the
[power drawer](symlinks/home/.config/quickshell/desktop/drawers/power/ARCHITECTURE.md)
and [hardware policy](../../hardware/power/ARCHITECTURE.md).

## Time and weather

`weather.json` is user-owned, with `locations` and optional `islandLocation`:

```json
{"islandLocation":"saigon","locations":[{"id":"saigon","name":"Ho Chi Minh City","detail":"Vietnam","latitude":10.82,"longitude":106.63,"timezone":"Asia/Ho_Chi_Minh"}]}
```

IDs are unique; coordinates are finite/in range and timezone names are validated.
`detail` is optional. Browsing does not change system time; Pin uses the timezone
polkit rule and saves the current place only after confirmed timezone change.
Failures attempt rollback and preserve private configuration.

Forecasts cache per place for thirty minutes. The bar refreshes on expiry/config
change/current-place drawer fetch and retries failed refreshes after five minutes.
Minute wall-clock checks catch up after suspend without restarting active reads.
The drawer fetches only selected stale places. Failed reads retain data/timestamps;
expired data becomes visible with age after the refresh fails.

`ReminderService` saves validated state atomically in
`$XDG_RUNTIME_DIR/desktop-shell/reminders.json`. Startup restores it without opening
a drawer; shell reload/crash retains it and logout clears it. Overdue alarms fire
once; overdue focus cycles send one prompt then advance. Alarms are critical,
focus/break prompts normal. Local dates/times are re-resolved on timezone/offset
changes, including DST, rather than treating a saved UTC deadline as permanent.
Timers cannot wake a sleeping machine.

## Events, tasks and notification history

Calendar parsing/recurrence use icalendar, recurring-ical-events and dateutil.
ETags and scoped DAV transport protect writes; cached views work offline.
See [calendar architecture](symlinks/home/.config/quickshell/desktop/drawers/events/ARCHITECTURE.md)
and [shared account ownership](symlinks/home/.config/quickshell/desktop/integrations/ARCHITECTURE.md).
`NotificationCenter` loads private bounded history before accepting notifications,
batches atomic writes and strips live images/actions from saved state. See
[notification lifecycle](symlinks/home/.config/quickshell/desktop/drawers/notifications/ARCHITECTURE.md).

## Account editor

`account-tools` is a separate PySide6 app. `account_core.py` targets only the caller's
UID through NSS/AccountsService; groups use `getgrouplist`, not stale process groups.
Only name/email/location/photo are writable, through native methods and interactive
PolicyKit. QProcess keeps requests off the UI thread. Writes serialize and report
partial success per field; failed edits remain drafts. NSS inspection still works
without AccountsService.

Photos normalize to bounded 512×512 PNGs. Drafts stay alive until close; SetIconFile
copies them as the caller before replying (at most 1 MiB). The packaged daemon's
`PrivateTmp=false` makes `/tmp` drafts visible. Saving prevents close until the
request settles; refresh/close guard unsaved edits. `spaces/profile.py` uses public
account fields and standard photo fallbacks, with mtime URL suffixes for refresh.
