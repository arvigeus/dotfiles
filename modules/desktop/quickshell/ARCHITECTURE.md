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
starts services needed across drawers: notifications (first, as the D-Bus
activation target), calendar warming, display
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
field codes, working directories and terminal entries. UWSM rejects IDs outside
`[A-Za-z0-9_][A-Za-z0-9_.-]*`, which Quickshell still lists (Steam and Wine names
with spaces or `+`); `launcher/entry_path.py` maps those back to the file that won
XDG precedence and UWSM parses it by path. A new search query selects its best
match; favorite and catalogue changes keep the selected application. Enter, the
arrows and Ctrl+D apply a still-debounced query first. Helpers keep their parent
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

Movies, TV Series, Games, Pictures, Books, Radio, Television, Streaming and Music are fullscreen, retained Spaces.
`ui/SpaceState.entries` is the only registry; the Spaces drawer lists it in that order. Space modules use their own immersive
presentation rather than the shell's gray controls or light/dark variants, and omit in-module Spaces links.
See the presentation contract in [Movies architecture](symlinks/home/.config/quickshell/desktop/spaces/movies/ARCHITECTURE.md)
for provider, worker and persistent settings details.

`SpaceState` owns running IDs and the current Space; opening one requires a
connected output. `SpaceHost` owns asynchronous loaders and binds effective page
activation. It uses the shared `InteractionState` / `InteractionWindow` layer
surface with all four anchors, Overlay stacking and ignored exclusion zones,
covering the panel as well as the workspace, with no panel-height allowance or
compositor geometry commands. Qt applies per-output scale; the surface follows
the output selected in Spaces. Unplugging that output, or opening a drawer or
launcher, hides the Space through shared input ownership. Hidden Spaces stay
running. Explicit close unloads only that instance and drops an open payload
still waiting for asynchronous creation. Each page gets a `host` with `hide()`
and `openModule(id, payload)`; both act only while that page is shown, so late
callbacks cannot hide, reopen or switch Spaces, and `openModule` returns `false`
when refused. The top-left hide control is outside the page and its popups.
Escape calls the page's `dismissTransient()` (popup/gallery, then search or
filters) before hiding the Space; native menus can consume Escape through their
normal shortcut override. Focus is restored only after the visible native
surface activates.

All Space headers use the shared activity indicator for concurrent work and
progress. The host's page-opening indicator is a 28-pixel `BusySpinner` in the
headers' red; `ui/` does not import Space modules. Idle headers have no status marker or history tooltip; completed jobs
remain in notification/activity panels. Page-level status avoids repeating outcomes
already announced by desktop notifications; task-specific errors stay with their
recovery controls.
For Games providers, artwork and beat times, see the
[Games architecture](symlinks/home/.config/quickshell/desktop/spaces/games/ARCHITECTURE.md).
For Books metadata, private providers and local reading, see the
[Books architecture](symlinks/home/.config/quickshell/desktop/spaces/books/ARCHITECTURE.md).
For Music catalogue/providers, queue playback and persistent settings, see
[Music architecture](symlinks/home/.config/quickshell/desktop/spaces/music/ARCHITECTURE.md).
For YouTube feeds, native playback, Gemini analysis and downloads, see
[Streaming architecture](symlinks/home/.config/quickshell/desktop/spaces/streaming/ARCHITECTURE.md).
`spaces/profile.py` reads public
AccountsService data, passwd GECOS and standard photo fallbacks on opening.
Photos use an mtime URL suffix and no cache. `ProfileButton` launches Account tools in
its own unit. See [account editor](#account-editor) for its data and write boundaries.

`SessionService` makes on-demand capability/status/action requests to
`spaces/backend.py`. Systemd owns shutdown scheduling; capabilities and any
pending shutdown come from logind's `Can*` methods and `ScheduledShutdown`
property, and the popover formats that time in the shell locale. Supported delays are
15/30/60/90/120/180/240/300 minutes. `gaming` and `reload` call `session-mode`;
see [session ownership](../hyprland/ARCHITECTURE.md#session-ownership).
Destructive actions require a two-second hold. Popovers are mutually exclusive
and close on dismissal. Sleep/locking pauses delegate to `ComfortService` and
last only for the shell lifetime.

## System tray and bar badges

`SystemTray` remains registered while the drawer is closed. Tray delegates retain
native items and their application-owned menus. Activation, secondary activation,
scrolling and context menus use the native APIs; XEmbed is unsupported.
Attention combines item status with unseen matching notifications; ordinary
unread application state cannot be inferred without a notification or attention
request. See [tray architecture](symlinks/home/.config/quickshell/desktop/drawers/tray/ARCHITECTURE.md)
for naming, sender matching, acknowledgement and menu lifecycle.

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
compositor view. Selecting a tab runs focus, layout `center` and the
`desktop-layout-changed` event in one Lua callback, matching Alt+Tab's column
centering without changing Win+Left/Right focus navigation.
Edge markers count tabs not wholly in view; clicking one
reveals the nearest hidden window needing attention, otherwise scrolls a page.
A marker's width includes its fade, so revealed tabs stay clear of both.
`tests/test_desktop_workspaces.py` runs the bar against a fake Hyprland IPC.

## Clipboard

Two `cliphist@text/image.service` instances run `wl-paste --watch cliphist store`
for the graphical session. The cliphist config sets retention to 50 items.
They survive shell reload and are stopped with the graphical session.
`clipboard/backend.py` controls the units and adapts list/copy/delete/wipe and
image preview operations; pausing stops both units and is not persisted.

History remains in cliphist's database. Preview files are private and never
outlive their history entry: delete and wipe remove theirs, and each listing
removes those of entries trimmed or deleted elsewhere. At most 32 are cached, and
the helper clears them at start/exit. Copies decode by ID and pass bytes
to wl-copy through stdin, never shell interpolation. Closing the drawer drops
queued previews; rows request them again when it reopens. Clipboard collection
is independent of the drawer.

## Assistant

`drawers/assistant/AssistantService.qml` is instantiated by the first Assistant
drawer or external attachment request.
It owns one in-memory conversation and draft across drawer destruction, plus a
separate streaming process that continues while hidden. Shell exit/reload drops
them and terminates the request; Lemonade remains independently managed by
systemd. The bar entry contains metadata only and performs no background checks.
Opening the drawer requests read-only Status; it never starts Lemonade. Connect
is requested by opening the model picker, Send/Retry while offline, Open Lemonade
or the power button. It reuses an existing listener or starts the packaged service.
Offline drawers do not poll after that initial check. Status polls every five
seconds while observed and online, or every second while a model download is
active. Generation suspends polling once the selected
model is downloaded; while awaiting a first-use download, polling continues even
with the drawer closed. Control actions and attachment preparation suspend polling.
Lemonade's `models_generation` avoids fetching an unchanged catalogue. The backend
is an on-demand Python standard-library client.

Start/Stop use the packaged `lemond.service` user unit without enabling it. An
already-active system unit takes precedence and its controls use normal systemd
authorization. No competing service or daemon launcher is installed. The endpoint
is loopback on the port in `~/.config/lemonade/config.json` (or
`/var/lib/lemonade/config.json` for the system unit), defaulting to 13305.
Runtime port overrides must match that configuration. An optional
`LEMONADE_API_KEY` must be available in the shell service environment. There is one
Open action, in the header; it connects before launching the packaged
`lemonade-web-app` via UWSM. The singleton owns this launch so dismissal during
startup cannot lose it. Start/Stop is the header power button. It refuses active
requests and running downloads, including work started by other clients. The
`ai/lemonade` module owns the package.

Closing the drawer does not stop the shared server. There is no atomic
idle-and-shutdown operation or client lease; a health snapshot cannot prove that
another client will not start work, and native chat auto-downloads are absent from
the managed download-job list. The drawer does not maintain server ownership or
schedule automatic shutdown based on its visibility.

The backend uses `/v1/health`, `/v1/models?show_all=true` and streaming
`/v1/chat/completions`. `ModelPicker` combines downloaded and available models in
one list, downloaded first. It searches IDs/capabilities and shows catalogue sizes,
loaded state and progress. Each entire row is a keyboard-accessible selection
button with a metadata tooltip. The separate trash button deletes a downloaded
model without selecting its row or dismissing the picker. Undownloaded entries
have a passive download indicator; managed jobs retain pause/resume buttons.
Selecting an undownloaded model saves the choice without starting a download.
Send uses the native chat endpoint's download-and-load behavior, with the prompt,
settings and attachment snapshots captured in the ordinary generation request.
There is no separate client download/send queue. Its HTTP timeout is one hour
for an undownloaded model, otherwise ten minutes. In Lemonade 2026.45.3,
`ModelLoader::ensure_loaded` fetches missing models directly without a progress
callback or request cancellation token. It creates no `/v1/downloads` job; the UI
shows an indeterminate waiting status and polls to detect download completion.
Stop terminates the chat request; the server can continue fetching/loading.
`/v1/downloads` supplies progress for managed jobs started through the Web App or
explicit Pull, restored after dismissal/reload. Pause uses
`/v1/downloads/control`; resume uses `/v1/pull` with
`stream: true, subscribe: false`. Closing/reloading never cancels a download.
Explicit model deletion calls `/v1/delete`, with a 60-second timeout, and refreshes
the full catalogue afterward. Both UI and backend refuse deletion of a busy or
pinned model or one with a running download. Lemonade owns unloading and removing
files; no filesystem deletion is performed by the client. Built-in catalogue
entries become undownloaded and remain selectable; native `user.*` deletion also
removes the registration. Existing chat and draft stay in memory. A deleted saved
choice stays selected if still catalogued, otherwise normal model fallback applies.
Failures leave the server-reported catalogue intact and appear inside the picker.

Memory release calls `/v1/unload` for only the selected model. Both UI and backend
check that it is loaded, idle and unpinned; other loaded models remain in place.
Chat models must carry the `chat` label and use a standalone local recipe;
availability is rechecked before each send. Cloud entries, collections/routers and
non-chat deployment types are omitted. The drawer inherits the server catalogue;
it performs no independent RAM/VRAM capacity calculation.
Pending or historical images narrow the chooser to `vision` models; Send and
retry refuse a non-vision model until the images are removed or a new chat starts.
Installed models sort first, then aliases, Lemonade's `suggested` flag and names.
Chat may download only the selected local catalogue model; configured cloud
models are excluded. HTTP bypasses proxies and redirects.
SSE handles Unicode, comments, multiline events, reasoning indicators,
stream errors and premature EOF. Cancellation terminates only the request process
and retains partial text. Retry replaces the last answer using the existing user
turn. Reasoning text is retained separately in memory (at most 64,000 characters
per reply), shown behind an expander and omitted from later request context.
Reply length controls only the system instruction. The client omits token caps
because they budget reasoning and the final answer together; Lemonade's model
and context limits apply. A server-reported output limit is shown on the reply.
Thinking-only replies preserve the separate reasoning text and offer guidance
to turn thinking off or adjust Lemonade's limits.

Preferences in `~/.config/quickshell/desktop/assistant.json` contain `model`,
`length`, `style` and `thinking` (model/alias IDs mapped to `auto`/`on`/`off`).
Thinking is offered for all selected chat models: catalogue labels are descriptive
and can omit `reasoning` for models that support it.
`auto` omits the request field; On/Off send Lemonade's `enable_thinking` extension.
Style Default omits temperature; Precise/Creative send 0.2/0.9. Neither option
changes Lemonade's saved model configuration. The model determines whether it
supports thinking control. An undownloaded saved model stays
selected while it remains in the catalogue. Missing/removed preferences fall
back to a loaded/installed model. Chat content is never written by the drawer.
Context is bounded to 80 messages, after which New chat is required. Sending
while offline connects before submitting the frozen prompt. A saved model ID is
usable before the first catalogue fetch; the refreshed catalogue must still
contain that exact choice before Send or Retry proceeds. Missing choices report an
error and keep the draft/files instead of sending to a fallback model. No catalogue
is persisted on disk. Failed startup preserves the draft, and further typing
during startup is kept separately.
Both speakers render as selectable Qt Markdown with inline images disabled;
HTTP(S) links open only on activation. `assistant/Markdown.js` adds presentation
hard breaks to ordinary lines, preserving code line breaks. The existing media
filter applies to the entire source before that transformation. History, request
context and restored edits retain raw Markdown.
Copy uses the native selection clipboard. Scrolling up stops following streamed
text. The composer has a full-width, height-bounded editor above an action row;
Enter sends and Shift+Enter inserts a newline.

### Native model choices

`/internal/aliases` supplies Lemonade's native alias-to-model mapping. The picker
places aliases above concrete models within each download state, with a separator,
and shows each alias's target. Alias changes are checked alongside health: they can change independently
of `models_generation`, so either change refreshes the catalogue. If the optional
administrative endpoint is unavailable (including separate admin authentication),
the public catalogue and inference still work; aliases appear as ordinary model
entries without grouping or concrete-target decoration.

The server resolves the selected alias for inference. `chat_models` follows the
reported mapping only to match concrete loaded-model state and download jobs,
including canonical `builtin.`/`user.`/`extra.` targets and alias chains. Download,
pause, memory-release and delete operations recheck that mapping before acting on
its concrete target. The delete tooltip names that target and explains the shared
effect for aliases. Alias rows inherit their target's capabilities and receive the
same local-chat filtering as concrete rows. Retargeting refreshes the chooser and
capabilities while preserving the selected alias, conversation and draft.

Lemonade owns alias persistence and editing (`lemonade alias add NAME MODEL_ID`).
There is no drawer task registry or persona prompt. The only client-supplied
system instruction controls reply length; task-specific requests go in the chat.
Collections remain outside this drawer's standalone-chat scope. Omni's native
server orchestration buffers planner replies in the installed 2026.45.3 version,
while this client preserves direct model streaming. See
[model aliases](https://lemonade-server.ai/docs/guide/configuration/custom-models/#model-aliases-aliasesjson)
and the [collection orchestrator](https://github.com/lemonade-sdk/lemonade/blob/v2026.45.3/src/cpp/server/collection_orchestrator.cpp).

The drawer relies on Lemonade's device/memory compatibility filtering and does
not maintain a separate suitability score or performance history. Filtering can
be disabled in Lemonade; a listed model is not proof of comfortable speed or
memory headroom at every context size. Its `suggested` flag is a general
recommendation. Reliable performance comparisons would need model/quantization,
backend, context, hardware and power-mode details. Lemonade's own app already
shows request throughput and time to first token. Per-request final SSE `timings`
and `usage`, when provided by the backend, belong to that request; `/v1/stats`
describes the latest request globally and may belong to another client.
See [compatibility guidance](https://lemonade-server.ai/docs/guide/faq/#3-how-do-i-know-what-size-model-will-work-with-my-setup)
and [telemetry API](https://lemonade-server.ai/docs/api/lemonade/).

### Attachments

`attachments.py` prepares files in a separate process. The paperclip uses an
embedded multi-file `FileDialog` (`DontUseNativeDialog`, `Popup.Item`) so the
picker stays on the shell's input layer. The drawer also accepts local file URLs
through `DropArea`. Ctrl+V requests clipboard MIME types through `wl-paste`,
preferring file URLs and images before text. Plain text is inserted at the frozen
selection; later typing is preserved. Shift+Ctrl+V keeps native plain-text paste.
Requests are queued and preparations survive drawer dismissal.

#### Dolphin context action

This module supplies a scripted KDE Purpose `Export` provider in
`~/.local/share/kpackage/Purpose/desktop-assistant-context` and the
`~/.local/bin/desktop-assistant-context` helper. Dolphin's native Share plugin
discovers the provider's metadata; its executable `contents/code/main.sh` forwards
Purpose's arguments to the helper. There is no compiled plugin or resident
sharing process. The provider requires the helper on PATH; the `purpose` package
is an explicit dependency. Purpose caches provider discovery within each process,
so already-running Dolphin instances may need restarting after installation.
It belongs to this module so an installation without Assistant does not expose
the action. The shell root registers `AssistantInbox` even while the drawer is
closed; its handler accesses the singleton on demand.
See KDE's [scripted provider protocol](https://github.com/KDE/purpose/blob/v6.31.0/README.md#separate-process)
and [process job implementation](https://github.com/KDE/purpose/blob/v6.31.0/src/externalprocess/processjob.cpp).

The helper's `--server` mode connects to Purpose's per-job local socket, reads
its length-prefixed CBOR input using PySide6's `QCborValue`, then reports JSON
output/error fields using the native protocol. The existing PySide6 dependency is
imported only in Share mode. The payload is bounded to 96 KiB and six local regular
files. Purpose's metadata constraints cannot filter URL protocols or mixed local
file selections; the helper rejects remote URLs, folders and special files at
invocation and returns errors through Dolphin. An empty output avoids opening a
URL after success. The helper also remains callable directly with local paths.

The helper converts paths to file URLs and calls the exact desktop shell config's
`assistant.addFiles` IPC method. An object containing `files` keeps Quickshell's
CLI from expanding a bracketed JSON array into separate arguments. Both sides
bound the request to six local paths and 96 KiB; all filenames travel as data,
never shell syntax or file contents. Unavailable shells and rejected requests
report through `notify-send` for direct invocations or Purpose for Share requests.
Accepted requests use the existing importer and
attachment limits. Completion notifications report actual additions, duplicates
and partial failures after preparation; file contents are frozen at that point.
The action preserves draft/history, leaves the drawer closed and does not connect
to Lemonade. Pending context has the same in-memory lifetime as other attachments.

`tests/test_assistant_context.py` runs the real launcher and Quickshell IPC in a
private config, with fake notifications and inference backend. It covers repeated
selections, unusual filenames, snapshots, limits, errors, drawer opening and
reload cleanup. The helper's error paths, Share protocol and argument encoding
have isolated checks. A native KIO/Purpose menu fixture checks provider discovery
and execution with unusual multi-file selections and a fake shell command; it
requires the KDE development files and a C++ compiler.

Snapshots have a content/name hash ID, basename, kind, size and either text or an
image data URL. They live only in memory, including inside the message model's
`filesJson` role. There are no attachment caches or persisted conversations.
Send freezes these snapshots for streaming, retry and offline startup; later
file edits do not affect the chat. Editing the last question restores its frozen
files and removes that question/answer, and requires an empty draft. Changing
models keeps unsent attachments. New chat and shell exit drop them.

Inputs must be regular local files, at most 16 MiB each and six per message.
Nonblocking open/fstat checks refuse pipes/devices. Image preparation uses
PySide6/QImageReader with a 128 MiB allocation cap and 40 MP source bound. Images
are auto-oriented, scaled to a 2048-pixel maximum edge and re-encoded as PNG (JPEG
if needed to stay under 4 MiB). Animated inputs use their first frame. Previews
and thumbnails use these data URLs, never the original mutable file.

Text/code accepts UTF-8 or BOM-marked UTF-16 and rejects binary data. PDF text uses
Poppler's `pdftotext` through stdin with a 15-second timeout and bounded temporary
stdout. DOCX/ODT read bounded document XML from the ZIP container and extract
paragraph text, refusing DTD/entities. Empty/scanned documents require explicit
OCR or page images elsewhere. Extraction refuses more than 64,000 characters per
document. The context has a 160,000-character text cap and 24 MiB encoded-message
cap; oversized requests fail visibly rather than silently dropping file content.

Text attachments become named text parts in chat-completion content arrays;
images become inline `image_url` data URLs. The backend revalidates kinds, image
URLs/size and model vision support. It never reads a path during chat generation
or fetches a remote attachment URL. Standard chat messages stay strings. Document
and reasoning previews are selectable plain text; generated answer Markdown keeps
images disabled and follows HTTP(S) links only on activation.

The drawer currently connects only to Lemonade. Subscription-provider adapters
would need their own official authentication, capability and session lifetimes;
they are not treated as another URL behind the local-model chooser.

`tests/test_assistant_attachments.py` covers real image normalization, PDF/office
extraction, frozen text, limits, special-file rejection and a stub clipboard.
`tests/test_assistant_drawer.py` covers model filtering, service scope, configured
ports, request validation, SSE completion/failure, retained conversation state,
cancel/retry, model preferences, native alias grouping/retargeting and concrete
operations, native first-send downloads with hidden status polling and stop/retry,
unified downloaded-first model ordering, full-row pointer selection and tooltips,
separate native deletion with busy/download guards and error readback,
server-owned pause/resume, Markdown/newline rendering, composer keyboard
input, thinking/style payloads, thinking-only cutoff feedback and unlabeled-model
controls, multimodal content,
previews, paste, image capability checks, last-message editing, scoped memory
release, passive opening, demand-driven startup, cold Send/Retry and startup failure, and
narrow layouts with a fake backend. `DISPLAY_PREVIEW_DIR` saves drawer previews; normal checks use offscreen
surfaces and never contact Lemonade or download models.

## Capture

Screenshots use `desktop-screenshot` (grim/slurp); see
[Hyprland capture integration](../hyprland/ARCHITECTURE.md#desktop-integration).
`CaptureService` freezes the selected options for countdowns and dismisses the
drawer before capture, again if a surface opens in the last 400 ms; a reopened
drawer offers Cancel. `screenshot-editor`
and `screenshot-save` are user-owned on/off preferences shared with shortcuts.
Clipboard-only capture overrides editing and produces no file or notification.
Screenshot and recording-region processes explicitly close stdin after each
spawn. Slurp reads non-terminal stdin for suggested boxes before showing its
overlay; an open, unused Qt pipe otherwise leaves selection waiting indefinitely.

Recording belongs to socket-activated `desktop-capture.service`, independent of
shell reloads. `desktop-capture.socket` exposes a private runtime Unix socket at
`desktop-capture/control.sock`; QML connects directly and sends newline JSON.
Each command gets one state line tagged `reply`; untagged lines report later
changes. QML counts only replies as answered commands, holds the connection while
a session or command is pending, and sends Stop without waiting for earlier
replies. A slow client is never dropped or sent part of a line: changes coalesce
while its output is backlogged, and it receives the newest state once drained.
The service exits after 30 seconds with no recording/client, leaving systemd to
reactivate it. Change the tag protocol service-first: QML that expects tags
cannot release a connection to a service started from older code.

`capture/recorder.py` owns only its GPU Screen Recorder child; `KillMode=mixed`
lets it save that child before systemd kills the rest of the unit.
Start/stop/pause/resume and preference changes use the socket; stopping the
session finalizes the MP4 before bounded teardown. A recorder without a first
frame after 20 seconds is stopped; one still running 15 seconds after SIGINT is
killed, its file is left in place and the log tail is reported. Recordings use
XDG Videos under `Recordings`, H.264/AAC, with remembered
system-audio/microphone/pointer choices in `recording.json`. Region selection
uses Slurp; its pre-selection delay restarts and dismisses again when another
surface opens. A shell reconnect recovers the existing recording state rather
than starting one.

Speech uses selectable local multilingual Whisper models, defaulting to `small`.
`whisper-cpp` provides the `whisper-cli` inference command; `voxtype-bin` provides
model acquisition and its
JSON download progress protocol. Both update as normal packages through Topgrade.
The downloaded model is a fixed release under
`$XDG_DATA_HOME/voxtype/models/ggml-<model>.bin`, with the ordinary XDG fallback.
`capture/dictation.toml` configures that downloader; each setup passes the selected
model explicitly without activating Voxtype's own daemon. Tiny, Base, Small,
Medium, Large v3 and Large v3 Turbo have download-size labels and installed marks.
Selection persists without downloading; a later explicit setup/transcription
action acquires missing weights. Installed models remain cached when switching.
Model, language, audio-only and auto-paste preferences live in `speech.json`.
The menu presents one Action choice: Transcribe to clipboard, Transcribe and
paste or Record audio. The labels stand alone without explanatory text below. A
`speech-output` command updates the stored mode/paste pair atomically. Audio mode
hides transcription-only controls. `SearchableChoice` keeps language search above
its scrolling results, matches names/codes without regard to case and emits the
original model index; the caller retains ownership of selection.

`language_catalog()` reads the installed `libwhisper` C API through ctypes
(`whisper_lang_max_id`, `whisper_lang_str`, `whisper_lang_str_full`), without
loading weights or recording audio. The UI uses this catalogue instead of a
separate language list. Each checkpoint limits it to the vocabulary it supports:
99 languages for original models, 100 including Cantonese for v3/turbo. Switching
to a model that cannot handle the chosen language selects Auto. The engine
package remains necessary for transcription, while audio-only/setup can run
without its language catalogue.

`capture/speech.py` owns one speech job inside `desktop-capture.service` and
publishes its state under the recording snapshot's `speech` field. Requests use
`speech-*` operations on the existing socket/reply protocol. QML retains the
connection while speech is active; reconnecting restores the job after a shell
reload. Screen and speech capture can run independently. Each job freezes its
options. Preference changes are refused while busy; the backend validates values
again and saves them atomically. `DictationService` adapts these states and waits
400 ms after dismissing surfaces before microphone start/stop. The global
`desktop:dictation` toggle follows the selected speech mode and preserves AltGr.

The first transcription action downloads the model and stops at ready: setup
never opens the microphone. Downloads run with Capture dismissed and update one
replaceable transient desktop notification, with progress at most once per second,
using the standard integer `value` progress hint. Completion, cancellation and
failure replace that notification. `SpeechNotification` also reports saved audio,
copied/pasted transcripts, empty recognition and errors. Finished notifications
are non-transient so they remain in notification history. They contain no
transcript text. `notify-send` runs asynchronously with a timeout; notification
failure does not stop the job. The service stays alive until pending notifications
finish. Audio-only recording needs no
model. PipeWire records
16 kHz mono PCM WAV from the default microphone, with a two-minute dictation
limit and a 30-minute audio-only limit. Explicit stop publishes audio-only files
in XDG Music/Recordings with exclusive timestamped names; discard removes only
temporary data. Session shutdown saves an audio-only recording and discards
unfinished transcription. The existing microphone drawer owns device selection.
Before microphone capture, the backend checks the default input and its mute
state. Muted/unavailable inputs wait in `microphone-muted`/`microphone-unavailable`
without opening an audio stream. `SpeechNotification` waits up to thirty seconds
for its native action; cancellation interrupts notify-send to withdraw the prompt.
An unmute action moves to `microphone-approved`; retained `DictationService`
dismisses shell surfaces and waits 400 ms before `speech-resume`. Approval expires
after ten seconds and cannot follow a changed default source. The job retains
its original options and paste target throughout the prompt.

The approved operation snapshots the source name, Pulse index, PipeWire object
serial and device serial, then unmutes only that source and verifies the result.
The recording targets that name explicitly. Only a mute changed by this job is
restored, as soon as Stop is requested and before inference; unexpected recorder
exit, failed startup, discard and orderly service shutdown also restore it.
Restoration looks up the original name and verifies identity, so it neither
follows a changed default nor changes a replacement with a reused name/index.
An unavailable device is left alone. A failed restoration keeps an actionable
warning even after transcript delivery. The controls action sets an acknowledged,
bounded `openMicrophoneControls` request, which the shell routes to the existing
Microphone drawer. It does not enable device profiles or bypass hardware mute.

`pw-record` handles SIGINT and can finalize a recording while returning status 1.
The stopping phase accepts that status only without diagnostics, then verifies
the WAV format and declared sample data before transcription or saving. Other
nonzero exits remain errors. The fake recorder uses the same stop status so
ordinary transcription checks exercise this path.

File transcription uses the same owner through `speech-file`; the Capture drawer
handles microphone input only. File requests accept an absolute local path,
`output` (`clipboard` or `srt`), an opaque `jobId`, and optional model/language
overrides. Overrides are validated and frozen without changing microphone
preferences. A missing model downloads before the file is decoded, within the
same cancellable job. Model setup alone still stops at ready.

FFmpeg decodes the first audio stream as mono 16 kHz PCM WAV, reading at most six
hours plus one second; longer media is rejected without publishing truncated
results. Microphone recording limits remain independent. File decode/inference
have a 24-hour deadline per phase; microphone inference has fifteen minutes and
model downloads thirty minutes. Discard kills the owned process group, including
download children. Private job data and logs are removed on completion or cancel.
Input media is never modified. Recognition quality still needs real-media testing.

SRT jobs use Whisper's timed `-osrt` output without translation. A nonempty result
stages mode-0600 data in a private adjacent directory and publishes `stem.srt`
with an atomic hard link. Both existing files (including dangling symlinks) and
concurrent output creation are refused. Source device/inode/size/mtime must still
match before publication. Empty recognition, failure and cancellation leave no
sidecar. SRT output never changes the clipboard. File jobs expose their identifier,
source, output and final result metadata in snapshots, without recognized text.
A cancel carrying an outdated job identifier has no effect. Command rejection
uses per-reply `requestError`/`requestJobId`, so it cannot corrupt an active job's
result. Jobs survive client disconnection and shell reloads.

`capture/FileSpeech.qml` adapts this protocol for the shared Movies/Series
subtitle panel. It follows jobs for the selected path, refreshes inventory on
completion, and permits cancellation of that job while navigation remains usable.
`media/tools/transcription` owns the native Qt client used by Audio/Video tools;
see its [architecture](../../media/tools/transcription/ARCHITECTURE.md).

Successful transcription starts a `wl-copy --foreground` provider from the text
file. The capture service stays alive while that provider owns the selection,
so systemd cannot kill the clipboard when its ordinary idle timer expires. It
releases the provider on clipboard replacement/session shutdown. Errors and
empty transcripts preserve the previous selection. Text is not included in
socket snapshots, notifications or the journal. The drawer shows only live
progress and cancellation; results never reopen it. Backend notifications survive
shell reloads without replaying old results. File-chooser failures notify directly
from `DictationService`. Existing clipboard-history collection still applies.

Auto-paste is opt-in for microphone transcription. QML reports whether a shell
surface owns input; the backend defaults to blocking paste until that context
arrives. Delivery also compares the original Hyprland window address/class with
the focused application and uses the native `hl.dsp.send_shortcut` dispatcher
(Ctrl+Shift+V for known terminals, Ctrl+V otherwise). It never activates another
window or sends Return. Changed focus, an open shell surface or dispatcher failure
leaves the transcript on the clipboard. Imported-file transcripts always copy.

`tests/test_dictation.py` covers worker lifecycle, persistence, native paste
arguments, Unicode paths, clipboard ownership and the three-button drawer through
fake tools/private sockets. It must not capture host audio or alter its clipboard.

`WebcamService` enumerates through V4L2; `WebcamControls` reflects supported types,
ranges and writability. Mutations validate device identity/control support.
Preview belongs to the drawer and stops on dismissal or device loss. Privacy is
available only when the camera exposes it; other apps may change camera settings.

Temporary workaround: with its default hardware-device lists, Qt 6.12's FFmpeg
backend creates VDPAU, VAAPI, QSV and Vulkan devices on the GUI thread whenever
`MediaDevices` lists cameras. VDPAU opens `$DISPLAY`, which starts Xwayland or
blocks the shell when Xwayland is not accepting. `desktop-shell.service` sets
`QT_FFMPEG_DECODING_HW_DEVICE_TYPES` and `QT_FFMPEG_ENCODING_HW_DEVICE_TYPES` to
empty; both are required, and explicit lists create no devices while listing. The
webcam preview is the shell's only Qt video, so it decodes in software.
`FfmpegX11ProbeTests` in `tests/test_capture_drawer.py` fails once Qt stops opening
`$DISPLAY` without the variables. Then remove the variables, that test and this
note.

## System

`system/backend.py` reads Arch/systemd information on demand, one section per open
popover: OS, kernel and uptime; boot phases and slowest units; failed units and
the next timers of both scopes. Reads are unprivileged, use the C locale and a
three-second limit per command. A failed read is shown beside the other results,
never as a healthy empty one. A missing `/usr/lib/modules/<running kernel>`
signals a newer installed kernel; Arch has no reboot-required flag.

Actions run `backend.py --action` through `xdg-terminal-exec` in their own UWSM
unit, with the user's locale (under `LC_ALL=C` the journal pager escapes
non-ASCII text). Update runs `system-update`, falling back to Topgrade; the
[Topgrade module](../../system/package/topgrade/ARCHITECTURE.md) owns the
post-update review. Logs open `journalctl -b` for a validated unit name or at
warning priority. Sudo is passwordless, so the backend asks before every root
command and prints it.

Signing repair runs `pacman-key --init`, `--populate` and `--updatedb`, which keep
custom keys and local signatures. Package health runs `pacman -Dk` and quiet
`pacman -Qkq` as the user. Quiet output is untranslated `package path` lines for
every file pacman cannot `lstat`, including permission errors, so the backend
checks each path again. Files in root-only directories (`/boot`, `/var/named`) are
unverified rather than missing and do not fail the check. An opt-in
`sudo pacman -Qkq -- <packages>` checks them, and the recheck after a repair
reuses that answer. Only missing files of repository packages (`pacman -Qnq`) are
offered for reinstall, through `sudo pacman -Syu -- <packages>`, so a reinstall is
never a partial upgrade. `tests/test_system_drawer.py` stubs pacman and sudo.

## Networking

`WifiDrawer` and the bar read `Quickshell.Networking`: radio/hardware block,
connectivity, Wi-Fi networks, saved-network activation and Ethernet. Saved-network
deletion belongs to NetworkManager's connection editor, not the Wireless rows.
Scanning belongs to the open drawer. Native QObject identity keeps list delegates
stable; sorting uses connected, saved, signal-icon level and name.

`NetworkService` invokes `network/backend.py` for VPN/WireGuard profiles, WARP,
IP details and new user-scoped Wi-Fi profiles. It refreshes every ten seconds only
while observed. Mutations finish after dismissal and take priority over reads.
Each request runs in its own session, so a shell reload's SIGKILL of the helper
cannot abandon a started change or its cleanup.
Passwords use stdin/D-Bus and never argv, status records or diagnostics.
NetworkManager saves a joined network's profile before activating it; a join that
fails or times out deletes the profile it created, as nmcli does, so a wrong
password never becomes a saved, autoconnecting network. A retry from the drawer
keeps the typed password. Enterprise/WEP configurations open the connection editor.
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
Each status read starts the helper and queries firewalld, so `PortsService`
does not poll. `PortsControls` refreshes on opening and when the drawer's network
context (selected interface and its IPv4 addresses) changes; open/close replies
carry the complete state. Refreshes requested during a request run once after it,
and only while observed. Changes made outside the drawer appear on the next
opening or context change.

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
no periodic discovery runs. Nmap gets a parent-death signal, so it also stops
when cancellation's SIGTERM or a shell reload's SIGKILL ends the helper. Nmap
belongs to `hardware/network`, not the shell or Dolphin. Public/unsupported
networks fail without a scan. Results remain across dismissal until refreshed or
the network context changes; the context does not depend on the page being active.

## Bluetooth

The drawer reads native `Quickshell.Bluetooth` adapters/devices and issues native
power, connect, disconnect and forget operations. Connecting explicitly trusts a
device for future reconnection; observation never does. BlueZ asks only a default
agent to authorize incoming services and none runs (the Blueman applet is masked),
so an untrusted device cannot reconnect by itself. Native failures expose no
reason text, so the service watches each connect/disconnect until its device
settles and reports a generic failure on that device.

`BluetoothService` owns discovery started from the drawer. It ends after 30
seconds, when pairing starts or on dismissal. BlueZ lets only the client that
started discovery stop it, so another application's search is shown but cannot be
stopped here. Quickshell sends Start/StopDiscovery only when its cached
`Discovering` disagrees, and BlueZ refuses to stop a start still in flight, so a
stop requested before discovery is reported is applied once it is. The service
holds that state because the page is destroyed after dismissal.

Only pairing uses `bluetooth/backend.py`: it registers an Agent1 on a private
D-Bus connection and makes Pair() itself so BlueZ routes prompts to that agent.
It checks BlueZ sender/device identity, validates PIN/passkey responses, and
cancels after 60 seconds, on drawer dismissal or when its stdin closes. A cancel
reports its own reason rather than the error BlueZ then returns. Once Pair()
succeeds, trust and connect finish even if a cancel arrives late. The work runs in
a forked child in its own session: a shell reload SIGKILLs the helper and closes
its pipes, which cancels an unfinished pairing but lets a paired device finish.
Helper stderr goes to the shell log.

`tests/test_bluetooth_drawer.py` runs the drawer, service and real helper against
a fake BlueZ (`tests/fixtures/bluez_service.py`) on a private bus that serves as
both system and session bus. It covers discovery ownership and delayed starts,
agent prompts, rejection, dismissal, reload, failed connects and vanished devices.

## Playback

`AudioService` uses native PipeWire nodes, audio controls and link groups for
volume, mute, default devices, routing display and app streams. `PwObjectTracker`
binds detailed objects only while a drawer observes. Levels use the loudest
channel (`ui/AudioIcons.js`), in the drawers and the bar alike; native
`PwNodeAudio.volume` is the channel average. Changing level preserves channel
balance. Link state distinguishes recording from paused capture. Captures linked
from a sink (its monitor) or a playback stream record output audio, so they are
not listed as microphone use. MPRIS controls associate only with uniquely
matching application streams. When several streams match the same desktop
application, a unique media identity/application label pair can distinguish them
(for example Radio and a separate mpv player); otherwise controls stay in the
Playback section.

`audio/backend.py watch` supplies labels, cards, ports, profiles and input
availability. It subscribes to Pulse card/sink/source events, debounces reads and
publishes only changed inventory. Endpoint change events are needed for external
port switches, even though they can also be native volume/mute changes. The
subscription dies with its watcher. Exits requested by dismissal or refresh are
not failures; when observation resumes first, as when switching between Sound
and Microphone, Quickshell restarts the watcher after it exits. One-shot helper
operations cover card profiles, output/input ports, hardware input enablement
and stream moves. Each runs in a forked child in its own session: Quickshell
SIGKILLs a helper whose `Process` is destroyed (a shell reload), and the child
still finishes a started transition while the parent only relays its result.
Nodes belong to a card by `device.name`: a Pulse card index is an object serial,
unrelated to a node's `device.id`.

Boost is a per-device `boostDevices` map in `audio.ini`. Disabling it caps that
device and its streams immediately. Moving playback to a device without boost
caps that stream to 100%. Route changes enforce the route ceiling, preserve mute
and recheck identity/availability. Default changes do not move existing streams.
Hardware input enablement is separate from mute and preserves playback profiles.
WirePlumber restores each route's remembered volume and mute asynchronously. Live
inputs are muted before hardware disablement, so the route is remembered muted.
Capture endpoints that a profile change creates are muted as soon as they appear,
before playback routes are restored. While a route settles, an endpoint that must
stay muted is muted again on the first poll that shows it unmuted.

## Audio configuration

Hardware modules install JSON drop-ins in `$XDG_CONFIG_HOME/devices/audio/`.
Files contain `rules` and an optional `profiles` map of native profile IDs to
labels. A rule needs a nonempty `label`, plus `match` (exact property values) or
`contains` (substrings); both combine with AND. Node/port properties also expose
`node.name`, `node.description`, `port.name` and `port.description`.
Optional fields are `deviceLabel`, `maxVolume` (1–150, default 150) and numeric
`priority` (default 0). The first matching rule wins after descending priority
sort; ties keep file/rule order. `{port}` in a label inserts the connection name.
Malformed files and conflicting profile labels are skipped with warnings; valid
files remain usable.

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

`displays.lua` is the generated active profile, loaded after host defaults and
reconstructed on startup/hotplug. It contains native `hl.monitor` rules for only
the current set; other profiles stay in JSON. Rule selectors use descriptions
only when unique by Hyprland's prefix matching, otherwise connectors. Both writers
use atomic replacement; persistence failure restores the source/cache and live
layout. The app and shell helpers serialize through a session-local flock,
including snapshots, so independent instances cannot interleave writes.
Hyprland's watch treats the replaced file's `IN_IGNORED` event as a change, so
every changed `displays.lua` reloads the whole configuration. It re-applies the
saved rules; in Powersave that briefly restores the panel's configured refresh
until `configreloaded` reapplies the cap.

An unseen set starts enabled, independent and side by side without creating a
saved profile. Startup/hotplug select saved preferences; native rules handle
ordinary reloads. Dark panels defer restoration until the wake event. If
undocking leaves only disabled outputs, emergency recovery enables one, preferring
the internal panel, even when a saved profile is invalid. Replacements are verified
before a saved panel-disable choice is applied. Unsupported saved modes report an
actionable error and leave the source intact. Hyprland itself moves workspaces
off outputs a layout disables; the [Hyprland workspace policy](../hyprland/ARCHITECTURE.md#desktop-integration)
then fits floating windows left outside every output.

Powersave caps enabled internal panels to an available mode at or below 60 Hz in
live rules only; leaving Powersave restores their configured mode. Explicit
refresh changes override the cap until the next profile change. Blank panels are
not awakened for policy; wake events retry deferred work. The saved rules retain
the uncapped choice.

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
locking/suspend for active leases, and respect application inhibitors. Only a
live Keep awake lease makes these checks read the outputs; otherwise blanking is
one global DPMS dispatch. The helper exits 0 to allow and 2 on error, and defers
by exiting 1 and printing `defer`, since a Python crash also exits 1. Locking
proceeds on any other result; suspend stays blocked. Manual lock and
before-sleep locking are unconditional.

## Keyboard

`InputLanguage` runs the controller command that `input-method` declares in
`$XDG_CONFIG_HOME/quickshell/input-language.json`; that module owns layouts, Fcitx
and persistence, and the shell keeps no other language state. Requests run one at
a time; a failure shows the controller's first stderr line and keeps the last
confirmed state. Native keyboard events update the bar. Fcitx mode changes emit
none, so status is read every second while Vietnamese is the secondary language.
The drawer only selects languages, a secondary language and reference text;
typing clears on close.

Lighting providers live in `$XDG_CONFIG_HOME/devices/keyboard/backends/` and are
installed by hardware modules. `BacklightService` validates provider/device
identity and serializes writes. A queued brightness level is shown at once, and
snapshots returned while later changes are queued are discarded so they cannot
move the slider back. Brightness zero means off, not disabled input.
Colors/effects/modes appear only when supported. The Logitech backend owns its
manual/automatic mode transitions and rollback; see the peripheral architecture.

The Keyboard drawer's header info button sits beside input-method settings and
opens the reference with Shortcuts first, followed by Telex and Phonetic maps.
The Shortcuts search stays above the scrolling list and filters keys and action
descriptions locally, matching every whitespace-separated term without regard
to case. Opening the popup clears and focuses the search.
The shortcut tab reads `hyprctl -j binds` when opened, again every five seconds
while visible, and after Hyprland config reloads. The helper excludes mouse
button and wheel binds, formats modifier masks and submaps, and uses each bind
description as its label. Without one, a Lua dispatcher shows its name (its
reported argument is an opaque handle) and a Lua callback shows as a custom action. This lists compositor binds; portal-assigned Quickshell global
shortcuts are managed separately.

## Disks and system cleanup

`DisksService` reads UDisks2, groups physical drives and exposes mount, unmount,
unlock and health operations. It never powers off or ejects a drive. System mounts
cannot be unmounted. Passwords use stdin/D-Bus. Each action revalidates an identity
token for the device and its media. Unmounting an unlocked LUKS container also locks it,
as Dolphin and GNOME do. Containers listed in crypttab stay unlocked because they
may be boot-managed or keyfile-only. A failed lock reports that the volume is
unmounted but still unlocked. Health reads do not wake sleeping ATA hardware.
Filelight, Dolphin and the partition editor launch in independent units.

The helper answers one JSON line per request, in order. Status reads run every
five seconds while a page observes the service. They are not "busy": an action
requested during one waits behind it rather than being disabled or dropped. Actions survive
dismissal. A shell reload or restart kills the helper, but the UDisks call in
flight still completes in udisksd. A D-Bus timeout, such as a slow authentication
answer, reads "refresh to check" because UDisks may still finish. A helper that
fails to start emits no `exited`; both services also finish on `running` turning
false and never retry a lost action. `tests/test_disks_drawer.py` covers
targeting, identity, locking, secrets and the request queue with mocked UDisks objects.

`CleanupService` scans recoverable caches and selected tool/container resources.
The scan reports only category availability, checked with the same no-follow walk
that removal uses. The held action sends category IDs. The helper re-resolves each
category's targets when it runs, under that owner's lock, and never takes paths from
the request. Categories run in catalog order and fail independently, keeping the other
results. There is no cancel or dry run. A reload or shell restart kills the helper
mid-run, and that run's notification is lost. Removal is per entry, so an
interrupted category leaves a partial cache, and spawned tools such as pkexec
finish on their own. Cleanup uses npm/pip/mise's own commands and one Podman
inventory query. Package cleanup may authenticate. It does not remove personal
files, active tools or containers through guesses about directory names.

Path categories open every component without following symlinks. They refuse `$HOME`,
the XDG config/data/state/cache roots and their ancestors. AUR cleanup removes only
built archives directly inside paru's `clone/<pkgbase>/`. Sources, edits and the
makepkg `src/` and `pkg/` trees stay; makepkg leaves `pkg/` at mode 0111.

Configuration & maintenance adds public apply recovery backups and ignored
checkout development caches. Backup cleanup keeps 30 days and the newest batch;
the root-owned `dotfiles-backup-cleanup` helper accepts no path/UID arguments,
derives the caller from PKEXEC_UID and holds the same lock as apply. It only
removes UUID-named backup batches in that caller's state directory. Cache cleanup
uses Git's ignored/untracked directory list, restricted to Python/lint cache
names; tracked files, installation logs and other ignored
files stay untouched.

The same helper recognizes optional private apply backups and system-agent state
through their existing XDG namespaces and locks. It does not execute private
project code. Private backup cleanup holds operation.lock and keeps the same thirty-day
and newest-copy recovery window. Public/private development caches are found in
their source checkouts; private module payload trees remain excluded.

Agent history keeps the newest successful run, failed run and update log,
unfinished/unknown runs, pending update logs, and evidence referenced by learned
knowledge, findings, proposals or the latest report. A reference is any mention of
`runs/<timestamp>` or `updates/<timestamp>`, absolute, relative or `~`-based.
Cache cleanup removes only
known HTTP downloads and abandoned retrieval scratch directories. Control state,
knowledge, proposals and lock inodes are retained. Both hold agent.lock; cache
cleanup also holds http.lock. Busy operations fail promptly with a retry message.
No cleanup category accepts request-supplied paths, executables or retention flags.

`tests/test_system_cleanup.py` covers retention/caller boundaries, symlink safety,
pending/reference pinning, owner locks, cache targeting and offscreen hold/notification flows.
Every deleting test runs under a temporary HOME/XDG tree. Check root refusal through
`refuse_personal_root`. Never call a deleting function on real paths, even to
prove that a test fails.

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

`weather/backend.py` reads user-owned `weather.json` and caches forecasts by
place for 30 minutes. `WeatherStatus` (the bar) refreshes the current place and
runs the helper only when its forecast expires, five minutes after a failed
refresh, when `weather.json` changes or after the drawer fetches that place; its
per-minute wall-clock check catches up after suspend and never restarts a run in
progress. The drawer's `WeatherService` reads every minute while open and fetches
other places only while selected and stale. It hides an expired forecast while
the first refresh for a place is pending and shows it with its age once that
refresh fails. Failed/offline reads retain saved data and timestamps. Public
weather requests contain coordinates and use bounded timeouts. Only
`weather.json` problems are reported as configuration errors.

`weather.json` contains `locations` and optional `islandLocation` (the selected ID):

```json
{"islandLocation":"saigon","locations":[{"id":"saigon","name":"Ho Chi Minh City","detail":"Vietnam","latitude":10.82,"longitude":106.63,"timezone":"Asia/Ho_Chi_Minh"}]}
```

IDs must be unique, coordinates finite/in range, and `detail` is optional. The current
place controls the bar; browsing does not change system time. Pinning sets the
current place and uses the desktop timezone polkit rule. `weather/backend.py`
validates the format and IANA timezone names.

Alarms and focus/break reminders belong to the login session. `ReminderService`
saves them atomically to `$XDG_RUNTIME_DIR/desktop-shell/reminders.json`, so
shell reloads, restarts and crashes keep them and logout clears them.
`WeatherStatus` instantiates the service at shell start, so restored reminders
run without opening the drawer. Restored entries are validated field by field;
an overdue alarm fires once and an overdue focus cycle sends one prompt and
starts its next phase. Alarms are sent as critical, so Do Not Disturb still
shows them until dismissed; focus/break prompts are normal. Alarms keep their
local date and time when the system timezone changes, whether pinned or
external: each records the UTC offset at its deadline and is re-resolved when
that offset changes, so DST transitions before it do not move it. One already
passed in the new zone fires at once. Timers send desktop notifications and
cannot wake a sleeping machine. Reminder popovers own their focus and dismiss
before drawers. The timezone test relinks `/etc/localtime` inside a private user
and mount namespace and skips where unprivileged namespaces are unavailable.

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
a Wayland backend. `tests/support.py` holds shared QML fixtures; session-service
tests own a bus from `support.private_bus`. Run the suite under `dbus-run-session`,
so any remaining helper cannot reach the user's bus, and with `PIPEWIRE_REMOTE` set
to an unavailable test remote. Offscreen runs drop `WAYLAND_DISPLAY` and
`DISPLAY`, so no Qt client reaches the session's X server (see the camera-listing
workaround under Capture). Tests must never start real recordings or mutate host
radio/audio/power state.

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
are profile metadata, not mail-client or session configuration. AccountsService
rejects commas in SetRealName and keeps the remaining GECOS fields, so the editor
does not duplicate those rules.

QProcess runs the helper outside the UI thread. Requests accept only the four
editable string keys and always target the caller's UID. Writes are sequential;
partial success is reported per field, and failed changes remain editable.
Unavailable AccountsService still permits local account/group inspection.
Photo selection normalizes a bounded image to a PNG no larger than 512×512;
temporary images remain alive until the dialog closes so draft/discard cycles
work. SetIconFile copies the file as the caller (at most 1 MiB) before replying,
so AccountsService owns the saved copy; drafts live in `/tmp`, which the packaged
`accounts-daemon.service` shares (`PrivateTmp=false`). Saving prevents closing
until the request finishes; refresh and close confirm discarding unsaved edits.

`tests/test_account_tools.py` runs the real helper and an offscreen dialog against
a fake AccountsService (`tests/fixtures/accounts_service.py`) on a private bus
that serves as both system and session bus. It covers current-user targeting,
validation, partial failures, unavailable services, groups, drafts, photo cleanup
and asynchronous requests. In-process tests block the real adapter, so tests
never modify an account.
