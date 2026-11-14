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

### Launcher and assistant discovery

`ui/SpaceQuery.js` recognizes explicit slash categories and aliases plus quoted
`field:value` constraints. `year:2000..2025`, open ranges, numeric rating/vote/
bitrate thresholds, duration suffixes and local/library/offline shortcuts become
typed fields. Category-only input shows examples without starting a search;
ordinary app queries never start Space discovery. `SpaceSearch.qml` debounces for 300 ms,
publishes saved results before online results, cancels on replacement/dismissal,
and discards responses by revision. No Space or player loads during search.
The shared `ui/space_search.py` helper validates category/query/limits, reads
existing SQLite/JSON snapshots, then uses the Spaces' provider implementations.
Movies and Series have separate data/config namespaces. Music uses only the
current Nextcloud account's merged inventory or catalogue, without starting an
index rebuild. Game search reads current Steam manifests and saved Epic/GOG
ownership; it never logs in to a store during the local phase. Television reads
the saved directory and favorites, leaving full-directory refresh to its Space.
Online episodes require a show and `S01E02` or `1x2`; plain queries include saved
episode names and local files. Provider failures retain saved results.

`ui/space_filters.py` owns supported fields per category, validation, aliases,
metadata predicates and sorting. Unsupported fields, unknown movie genres,
nonfinite numbers and invalid ranges fail before provider work. Missing metadata
never satisfies a constraint, except where the provider applied a verified
constraint (e.g. TMDB origin-country discovery). Genres normalize `sci-fi` to the
movie or TV taxonomy; game genres/platforms resolve names or IDs from IGDB's
options. IGDB retains those IDs alongside names and supports oldest-first
discovery. Ratings in requests always use 0–10; Games' stored 0–5 scores are
converted for comparison. Durations use seconds.

| Category | Discovery constraints beyond text and availability |
| --- | --- |
| Movies/Series/Episodes | Genre, year range, minimum rating/votes, origin country, favorites |
| Music/Songs/Albums/Artists | Genre; artist/year where meaningful; song album/duration |
| Radio | Genre tags, country, language, minimum bitrate, codec, favorites |
| Television | Country, language, category, favorites |
| Games | Genre, platform, years, minimum rating/votes, installed/owned, favorites |
| YouTube | Channel, duration, years, live status |

Availability/sort filters apply within each category's supported choices. Local
copies still precede saved/online matches; sorting acts within those groups.
`library` means local media, owned store games, account music or favorites, not
arbitrary cached provider metadata. `online=false` independently forbids provider
access while retaining cached discovery. Library-only/favorite/installed/owned
constraints skip online discovery. Local movie records merge current cached
metadata before filtering. Music filters stream the current account's records
before limiting; artists/albums inherit observed genres/local availability from
related songs. Games inspect up to ten library pages before taking the shortlist.
Online providers return bounded candidate pages; music genre discovery samples
genre charts, so post-filtering is not an exhaustive catalogue query. Exact
artist constraints use provider text search instead of unrelated chart results.
YouTube hydrates metadata only when the requested constraints need it; deadlines
retain candidates already found.

Results carry stable identity, category, availability, bounded metadata and an
entity payload. Local copies win deduplication, then saved results, then online
results; each request returns at most twelve cards (six by default for the assistant).
`SpaceResultCard` is shared by launcher rows and assistant tool activities. Cards
use provider posters/covers/thumbnails through the shared bounded artwork cache,
decode at twice the small display size and fall back to bundled icons. Availability
stays in the tooltip/accessibility description. Search does no artwork hydration.
Movie/series cards retain compact identity payloads; their Space hydrates details.
TMDB/IMDb aliases with a shared TMDB identity collapse to one result.
Only user actions call `SpaceState.open` with an explicit `play` boolean.
The registry copies the payload before opening can unload the caller's delegates.
`SpaceOpenRequest` defers payload delivery until the page is active/initialized
and drops undelivered requests on dismissal. Page handlers use their existing
selection/playback paths, retaining their normal ownership and error reporting.

The assistant's read-only `space_filters` tool exposes supported constraints and
static/saved provider choices, fetching current options only with `online=true`.
A query narrows long option lists. `search_spaces` accepts empty text for discovery
and typed filters, returning metadata plus opaque result refs. `display=false`
keeps candidate cards out of the conversation while the model chooses a shortlist.
`present_space_results` accepts up to eight returned refs with short reasons and
renders exactly those cards in the requested order. It resolves payloads from
tool results, never from model-authored actions. At most 96 refs survive in each
backend request; follow-ups restore refs from validated saved discovery tool
transcripts, excluding user/ordinary assistant text. Unknown refs require another
search. A successful nonempty presentation is a valid answer even when the model
finishes without extra prose; the drawer verifies that the cards exist before
accepting that completion. Other empty tool replies retain their error behavior.
Native tool models receive the current local date for relative year
requests. Models without native tools retain ordinary chat.

Inference prompts omit UI action payloads while saved tool transcripts retain them
for validated follow-up refs. Before each round, the backend checks the loaded
runtime's slot size (not its advertised model capacity). Local llama.cpp backends
provide the full chat template and tokenizer; other/unloaded backends use a byte
estimate. The budget reserves reply space, removes whole older turns, then bounds
tool results without splitting call/result exchanges or truncating the current
user request. A server context rejection updates the estimate and retries that
inference once, without rerunning tools. `test_assistant_budget.py` covers runtime
limits, complete exchanges, follow-up payload retention and rejection recovery.

Search runs through the assistant's bounded process runner;
the helper has a thirty-second deadline and unwinds provider cleanup on signals,
including yt-dlp's separate process group. Tool output keeps the existing 16 KiB
budget; excess cards/options are dropped with `truncated=true`. Tests in
`test_space_search.py`, `test_space_discovery.py` and `test_launcher_navigation.py`
cover ordering, real provider-filter routing, invalid/unknown metadata, account
scope, offline boundaries, recommendation tool rounds, follow-up refs, stale
queries and explicit card actions.

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
The protocol follows [Lemonade's Chat Completions API](https://lemonade-server.ai/docs/api/openai/).

`ModelPicker` filters the local catalogue immediately and searches Hugging Face
and ModelScope through `/v1/registry/search` after a 350 ms debounce and three
characters. Downloaded models precede active downloads, followed by the rest of
the catalogue; native alias and catalogue ordering is preserved within each group.
Download ordering follows concrete targets and updates with managed job state.
The two `RegistryModels` sections own independent `RegistryRequest`
helpers, loading/error states and retries. Searches do not hold the singleton's
control lock; query changes, dismissal and going offline cancel metadata helpers.
Request revisions discard late replies. No discovery polling or eager per-result
file inspection runs. Opening a repository requests `/v1/pull/variants`; only
standalone llama.cpp GGUF chat models with valid files are installable. Vision
context still requires a vision model. The quantization chooser prefers Q4_K_M.
Collapsed result loaders are hidden as well as unloaded, so the column excludes
their retained geometry.

An explicit download uses the singleton's serialized control path and rechecks
the repository's files before `/v1/pull`. Main, vision-projector and optional
draft checkpoints and the selected registry come from this validation. Matching
existing definitions are reused without changing their options; new `user.*`
names include a source/checkpoint digest to avoid collisions, and conflicting
definitions are refused. Lemonade owns the download (`stream: true`,
`subscribe: false`); its normal jobs, pause/resume and deletion remain in use.
Successful registration selects/reveals the model without changing the chat or
draft. Registry errors stay in their own sections; unsupported server search
APIs are reported there. Registry requests use the same loopback connection and
server-managed credentials as the catalogue, never direct provider requests.
`test_assistant_registry.py` covers provider routing, file validation, source
preservation, existing-definition reuse, collisions, per-provider failures,
quantization choice, row collapse, native download controls and stale/cancelled searches.

Tool calling is enabled only when Lemonade's model labels include
`tool-calling`; other models receive the existing ordinary chat request. The
backend sends native OpenAI `tools` and `tool_choice: auto` fields and reassembles
streamed argument fragments by call index. Tool-capable aliases use their
catalogue labels. Argument fragments are bounded and calls execute only after
`finish_reason: tool_calls` and the SSE completion marker. Truncated calls never
execute. Missing/repeated call IDs are normalized before returning results. A
rejected, malformed, or unknown call becomes a tool result so the model can
continue without the operation; malformed stream structure ends the request.

Read-only tools cover fixed system inspections (machine, disks, memory, process
list, failed services, Bluetooth, a named service or its logs), bounded text-file
reads, directory listings, and `rg` filename/content searches. Fixed inspection
uses system binaries, validates unit names and disables pagers. Search ignores
ripgrep config, including executable preprocessors. Directory sorting retains at
most 201 entries in memory. General commands and file writes always wait for
approval over the running backend process's stdin. Each execution receives a
fresh approval ID independent of model call IDs; duplicate/stale UI decisions
cannot approve another operation. Command previews include the exact script,
working directory and deadline.

Writes are limited to 64 KiB user-owned regular files; symlinks and special files
are refused. The backend snapshots file identity, mode and content before
approval, rechecks before commit, and atomically replaces the file while retaining
its mode. The directory descriptor is pinned and checked against the snapshot,
so replacing a parent with a symlink cannot redirect an approved write. New-file
creation refuses an intervening file. These checks guard pending approvals; they
are not a filesystem transaction across concurrent writers. The backend never
adds privilege wrappers. An approved shell command has the current user's
ordinary access; this is an approval boundary, not an OS sandbox.

Tool activity is stored with the assistant message and rendered in the drawer as
compact disclosure rows shared with thinking: indicator, label and an adjacent
spinner that becomes a chevron when idle. The whole row toggles details; status
and batch position stay in the label rather than separate right-hand controls.
Spinners run only while the drawer is active. Inspection labels use regex
replacement because the installed QML JavaScript engine lacks `String.replaceAll`.
Approval previews start open while awaiting a choice and can be folded;
stdout, stderr, exit status and other details expand on demand. Calls returned in
one model batch are run in their original order, one approval at a time, with a
batch position shown in the row. Completed tool transcripts stay in the in-memory
conversation for follow-up turns, including after interruption, disconnect or
loop limits. Unexecuted calls receive explicit results; interrupted executions
warn of uncertain side effects. Switching to a model without tools retains the
transcript as untrusted text in an ordinary assistant message. Saved transcripts
must have matched call/result pairs and a terminal assistant message. Tool output
is wrapped as untrusted data before it returns to Lemonade.

Inference retains the existing per-request deadline (ten minutes for a downloaded
model, one hour for its first native download/load). An approval expires after
five minutes; tool argument preparation and file snapshots have a ten-second
deadline. Fixed inspection commands time out after ten seconds, searches after
eight seconds, and arbitrary shell commands after thirty seconds. Every tool also
has a 45-second wall-clock deadline covering filesystem work and grouped
inspections. Inference uses an alarm as well as a socket timeout, so heartbeats or
an unfinished SSE line cannot extend it indefinitely. Commands run without shell
profiles, startup environment scripts or exported functions, with stdin closed,
in their own process group. Cancellation/timeout terminates and reaps the group,
including descendants that inherit pipes after their leader exits. This does not
contain intentionally daemonized processes from an approved arbitrary script.
Captured stdout/stderr are capped at 16 KiB each, then each tool result is bounded
to 16 KiB combined. Tool transcript size is capped at 128 KiB, SSE events at
256 KiB, and generated text/reasoning across all rounds at 160,000/64,000
characters. Agent workflows stop after eight model rounds or 24 tool calls.

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
partial text; retry replaces the last answer. Completion marks an empty final
answer separately from earlier tool prefaces, so a preface cannot disguise a
missing answer. The UI reports the missing answer while retaining tool results;
retries remain explicit. A reply is cut at 160,000
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

New chat clears conversation context, draft and attachments while retaining the
loaded model. The independent header memory action unloads only the selected idle
model and keeps the conversation; a later Send loads it again.

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
keyed by text range/segment or activity ID, preserving earlier code blocks,
thinking/tool expansion and focus as replies grow. Text, thinking and tool
activity interleave at their original body offsets; a shared insertion order
resolves ties when several activities precede the next text. Thinking metadata
stores ranges into the existing bounded reasoning string, not duplicate traces.
The backend batches adjacent tokens of one kind while preserving reasoning/text
transitions, including transitions inside a single provider chunk. Display hard
breaks are added outside code. Links open
only on activation.

The compact composer holds model selection and options; their popups open upward.
Assistant messages use a small identity row and flat body, while user messages
retain the accent surface. User messages share the account photo from the read-only
`spaces/profile.py` helper, refreshed on drawer open with a generic-icon fallback
for missing or unreadable images. The photo is presentation only, outside the
conversation sent to the model. Reasoning and tool output are collapsed by default.
Each thinking phase has its own expandable row at its position in the reply. Text
or a tool call finishes the phase; further reasoning creates a new phase without
restarting or modifying earlier ones. Completion, cancellation and disconnect
close any remaining phase. Progress stays in that row without a duplicate footer
spinner. These patterns draw on T3 Code's
[work log](https://github.com/pingdotgg/t3code/blob/main/apps/web/src/components/chat/WorkLog.tsx),
[activity rows](https://github.com/pingdotgg/t3code/blob/main/apps/web/src/components/chat/TimelineWorkEntryRow.tsx)
and [follow behavior](https://github.com/pingdotgg/t3code/blob/main/apps/web/src/components/chat/useTimelineFollow.ts),
using the shell's existing controls, palette and type scale.

`test_assistant_agent.py` covers adversarial streams, ID reuse, approval expiry,
context closure, output/loop/deadline bounds, startup/config execution injection,
file/directory replacement and real process-group cancellation. Native drawer
fixtures cover approval decisions, stable expansion, interleaving, cancellation
context, code copying, scroll following, model controls and attachment regressions.
Run the assistant suite with the isolated environment from
[tests/ARCHITECTURE.md](../../../tests/ARCHITECTURE.md) and
`python3 -B -m unittest discover -s tests -p 'test_assistant*.py' -v`. Real-model
smoke checks should use an already-downloaded tool model, read-only inspection,
exact approved commands, and disposable files for modifications.

### Web and lyrics research

Four read-only native tools run in `drawers/assistant/research.py` through the
bounded process runner (28-second worker deadline, 32-second parent deadline):
`web_search`, `read_web_page`, `search_lyrics`, and `get_song_lyrics`. The model
receives explicit instructions to verify web leads, cite their URLs and resolve
identified titles/artists through `search_spaces` before presenting cards.
Web search returns evidence rather than model-authored Space action payloads.
Source buttons launch the browser only on a user click. Both web text and lyrics
remain untrusted tool results in native transcripts.

`web.py` searches DuckDuckGo's Lite endpoint with HTML fallback, recognizing
verification challenges separately from no matches. These public endpoints may
rate-limit or change markup. Optional private
`$XDG_CONFIG_HOME/quickshell/desktop/assistant-web.json` selects a public SearXNG
JSON search endpoint instead:

```json
{"provider": "searxng", "url": "https://search.example/search"}
```

Omit the file, or set `provider` to `auto`/`duckduckgo`, for the default. No browser
cookies, session state, proxy environment, external scripts or subresources are
used. HTTP(S) URLs must have no credentials; local names, private addresses and
mixed public/private DNS answers are refused on every redirect. Connections pin
the validated IP while preserving Host and TLS certificate/hostname validation.
Responses are limited to 2 MiB with identity encoding, four redirect hops and
ten-second socket timeouts. The reader extracts visible HTML text and safe source
links, or plain text/JSON; it does not extract PDFs or render JavaScript. Text is
bounded to 160,000 characters. Page and lyrics chunks include character offsets,
`next_offset`, `total_chars` and `has_more`; UTF-8 byte truncation adjusts the
continuation offset so multibyte text is not skipped.

`search_lyrics` first scans up to 10,000 rows of the current Nextcloud account's
Music `local.sqlite` inventory. Matching ignores case, accents, punctuation and
LRC timestamps. Each match requires an ordinary file under the Music directory
with the inventory's current inode/size/mtime signature; stale rows, symlinks and
other accounts are excluded. It produces ordinary song cards with a bounded
matching excerpt, using the merged library identity where available. Local
matches suppress web transmission of the fragment. Otherwise, `online=true`
searches for the quoted fragment and returns unverified web leads. LRCLIB's
[search endpoint](https://lrclib.net/docs) searches track metadata, so it is not
used as a lyric-text search. An empty local result does not mean every library
song has been checked: only indexed embedded lyrics can match, and Music owns
inventory refresh.

`get_song_lyrics` accepts only a returned song ref, never a model-authored song
object or filesystem path. The parent resolves the entity, and the worker seeks
an exact title/artist match in the current account's library, preferring the same
identity and album. Validated inventory lyrics are read in full rather than from
the bounded card payload. Fallback uses Music's existing embedded-tag reader,
Nextcloud lyrics API, configured audio-tools providers and lyrics cache. The
`online=false` option preserves local/cache access while skipping cloud/provider
requests. No audio is downloaded, no tags are changed, and provider configuration
is shared with Music and Audio Tools. `search_lyrics` refs participate in the same
96-ref registry and validated follow-up restoration as Space discovery results.

`test_assistant_research.py` covers public-address and redirect validation, pinned
TLS connections, page/search parsing, challenge fallback, Unicode continuation,
library-first lyrics, stale signatures/account switches, the actual worker,
native tool/card rounds and offscreen source/provenance/card rendering.
`test_music_enrichment.py` also covers offline cache reuse without network calls.

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
controls attach only to uniquely matching streams/application identities. The
Playback section reads artwork only from MPRIS `mpris:artUrl`; transport buttons
follow the player's `CanGoPrevious` and `CanGoNext` capabilities. Music exports
its QML-owned queue through an MPRIS Player interface because it runs one mpv
process per track.

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
modes retain their source and report errors. Hyprland applies live rule changes on
the next rendered frame, so after a start whose layout disabled every connected
output, recovery replaces `displays.lua` with host defaults to force a reload. Powersave caps only enabled internal
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
