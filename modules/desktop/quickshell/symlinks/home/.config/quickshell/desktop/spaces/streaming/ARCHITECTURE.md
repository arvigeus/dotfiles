# Streaming implementation

## Presentation and lifecycle

`Main.qml` is a retained `SpaceState` / `SpaceHost` page using the immersive
`MovieStyle` palette and existing controls. `VideoCard.qml` presents virtualized
16:9 thumbnails. The toolbar is reparented into the host. The default layout puts
details at the left over a cinematic backdrop, with a horizontal bottom rail.
The alternate layout puts a grid at the left and details at the right; narrow
outputs stack them. The same `MovieBackdrop` and directional scrims as Movies
cover the whole Space. `StreamingDetails.qml` owns Overview, Summary, Chapters
and Downloads tabs and a plain Watch action. mpv owns playback quality. Discover
and Posts retain queries, results, selections, detail tabs and scroll positions
in memory. The toolbar's right-side search queries YouTube
from Discover and filters Posts in its own view.
Escape dismisses channels/operations, detail tabs and search before hiding.

The video rail/grid and Posts list request the next page near their visible end
through one debounced page-owned timer. Short or membership-filtered pages fill
the viewport automatically. One accepted browse owns loading state; hiding,
search debounce, open panels, errors and source exhaustion suspend prefetch.
Appending retains delegates/scroll. Page fingerprints stop provider replays;
video fingerprints include raw IDs before membership filtering so distinct
hidden-only pages still advance. Posts fingerprints include hashed cursor progress.
View restoration uses an owned timer so closing the page cancels deferred work.

The page owns one JSON-lines `Worker` running `backend.py`. Catalogue reads have
their own bounded lane; mutations/player commands are ordered through the shared
worker's control lane. Browse/detail generations discard stale responses. Hidden
pages stop player polling and visual work, while accepted jobs continue polling
to deliver completion/error notifications. Video handoff hides the Space using
its owner-scoped host only once mpv reports a playback position, so failed opens
leave the error visible. Audio playback leaves it visible. Close terminates this
worker's commands, transfer staging directories and mpv process group.

## YouTube and playback

`youtube.py` runs the installed yt-dlp with configuration, plugins and remote
components disabled. Arguments are arrays; input never passes through a shell.
Input URLs require HTTPS and an exact YouTube hostname. Video IDs and channel
paths are validated and canonicalized. Search strings become bounded `ytsearch`
requests. Search pages contain 24 items. A channel page reads 12 items per channel
with at most four concurrent reads and 40 followed channels. Unavailable channels
produce a partial-feed notice. Filtering applies to the currently requested feed
page; subsequent automatic pages search further uploads. Channel pages sort by upload date when
the extractor supplies it; flat results may have no date.

`backend.py` stores at most 200 regenerable feed/search snapshots under
`$XDG_CACHE_HOME/quickshell/desktop/spaces/streaming`. Snapshots are fresh for five
minutes; Refresh bypasses freshness. A failed read can return its last snapshot
with an offline notice and pagination disabled. Normalized metadata contains no
resolved media capabilities. Full video details have a 300-item in-memory cache.
Provider stderr and signed stream addresses stay out of QML and notifications.
Members-only and Premium-only video rows are filtered before every response,
including cached reads. A late metadata discovery also removes
the row from the visible model. Flat channel/search reads expose membership badges
without resolving every video's media. Pagination follows the source page size,
so filtering does not hide the ability to read later public uploads.
Metadata extraction allows missing formats, preserving descriptions and access
status for restricted videos. Membership, private, sign-in, region, format and
network errors map to fixed, actionable messages. Cached catalogue records supply
Watch independently of detail extraction; metadata failure never
prevents mpv from trying a public video. Native playback does not import browser
cookies. Open on YouTube launches the browser through Apps/UWSM for account access.

Backdrops use YouTube's public `sd2.jpg` sampled video still (typically tens of
kilobytes), with the catalogue thumbnail as fallback. No stream resolution,
video download, frame decoding or AI call is needed to obtain the backdrop.
The shared bounded image cache owns those image downloads. yt-dlp's upstream
YouTube extractor lists these sampled stills separately from custom thumbnails.

`player.py` owns a native mpv window using the user's video configuration. Remote
playback passes the canonical video URL to mpv's yt-dlp hook; downloaded media is
preferred. Video playback retains mpv's configured format selection; the shell
does not pass a quality override. Listen selects audio-only playback. Chapters provide
explicit start offsets. mpv owns captions, speed and position persistence in the
private `resume` directory. The private temporary player diagnostic captures
errors for classification, is never sent to QML, and closes with the player.
Stop requests mpv Quit to save position, then releases
its process group and IPC socket.

The YouTube module owns yt-dlp and Deno; Quickshell owns FFmpeg and mpv.
Arch's yt-dlp package provides yt-dlp-ejs. See the upstream
[yt-dlp dependencies and options](https://github.com/yt-dlp/yt-dlp#dependencies).

## Transfers and Music

`downloads.py` uses Books' bounded two-thread `Jobs` manager. Cancellation checks
run between command-output polls, off the render thread. Each child has its own
process group; cancellation/close terminates that group. Staging directories are
registered with the command owner so close can remove partials while jobs settle.
Live/upcoming videos cannot be downloaded.

Each download has a private staging directory on its destination filesystem.
Video selects the best available stream, merges/remuxes into MKV, embeds
available English subtitles and preserves metadata/chapters. Audio selects the
best audio-only stream among Opus and AAC using yt-dlp's quality/codec ordering;
there is no fixed codec preference ahead of source quality and no unsupported
format or video fallback. Audio extraction/conversion postprocessors are omitted.
FFmpeg copies audio packets unchanged into Ogg Opus (`.opus`) or M4A (`.m4a`),
with normalized title/artist/album/date/source tags. Thumbnail conversion only
affects the image. AAC cover art is attached with FFmpeg; Opus cover art uses
Mutagen's standard Vorbis `METADATA_BLOCK_PICTURE` comment. FFprobe verifies the
original codec/sample rate/channel count and resulting audio tags/cover before
publication. Hard-link publication is atomic
and refuses existing names; collisions get a numbered suffix. A committed file
wins over late cancellation.

Audio is saved directly in `~/Music` as
`Title - Artist - Album (YYYY-MM-DD).opus` or `.m4a`; videos use
`~/Videos/Streaming/Title [video-id].mkv`. Missing music-specific metadata falls
back to the uploader and album `YouTube`. Music's existing inventory observes the
completed file and owns metadata editing, conditional DAV upload and indexing.
Uploads remain explicit. These codec/container pairs are listed in
[Nextcloud Music's supported formats](https://github.com/nc-music/music#supported-formats);
audio-only WebM is not published into Music. Existing downloads are left intact.

## Creator Posts and subscriptions

`posts.py` reads the anonymous `/posts?hl=en` page, decodes its `ytInitialData`
and `INNERTUBE_CONTEXT` JSON without executing scripts, and restricts parsing to
the selected Posts tab. It reads text, up to four image attachments, poll choices
and attached videos from post threads. Members-only posts and nested reply
cursors are excluded. Image URLs require HTTPS and YouTube's image hosts,
including the avatar host `yt3.googleusercontent.com`. Protocol-relative URLs
are normalized to HTTPS before validation. The largest supplied author thumbnail
is used; its card shows the creator's initial if the image is missing or fails.
Posts snapshots include a parser-version namespace so older normalized records
do not conceal corrected avatar URLs.
Text stays plain/selectable in `PostsFeed.qml`; voting and comments use Open post
on YouTube. Shared-video actions use the normal video search/open path.

Continuations use the fixed read-only Innertube browse endpoint with the public
page's client context. Per-channel cursor files live in the regenerable Posts
cache, with private modes, per-channel locks and at most 100 cursor files. Each
channel retains its initial cursor and 31 recent cursors, allowing continued
forward paging without unbounded cursor history. Repeated server cursors end
that creator's feed; legitimate recent-page replay remains available. Responses have
12 MiB limits, bounded timeouts, 30-post pages and 8,000-character text limits.
At most four creator reads run concurrently. Results merge by post ID and sort
by approximate relative publication time; the original relative label is shown.
Partial failures retain successful creators. Normal catalogue snapshot caching
also supplies offline Posts results. No Gemini key, browser cookies or write
endpoint is used. The page/continuation renderer shapes are YouTube internals
and can change; parser failures are surfaced without discarding prior snapshots.
The [upstream YouTube tab extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_tab.py)
also uses these thread and continuation renderer families.

Followed channels retain canonical channel IDs and validated URL aliases in
private settings. Feed reads learn the ID and display name from channel metadata.
Video records carry both the canonical channel and uploader handle; feed/post
records also carry their source subscription URL. Subscribe/Unsubscribe resolves
those identities to the configured entry, preventing handle/ID duplicates.
Settings mutations and metadata enrichment share one reentrant lock. Unfollowing
refreshes Discover/Posts while preserving downloaded media.

## Gemini and portable state

`streaming.json` is private configuration under
`~/.config/quickshell/desktop/spaces/streaming`:

```json
{
  "channels": [{"url": "https://www.youtube.com/@example", "name": "Example", "id": "", "aliases": []}],
  "grid_mode": false,
  "gemini_model": "gemini-3.8-flash"
}
```

The credential is a separate 0600 file at
`~/.config/quickshell/desktop/integrations/gemini-api-key`. It is read inside
`insights.py` and sent in the `x-goog-api-key` header to the fixed Gemini endpoint.
Redirects are disabled. Gemini requests are explicit jobs and use the actual
public YouTube video. Responses omit thought parts, handle empty/blocked answers
and expose sanitized quota/auth/model failures. Cancelling a request suppresses
its result; an already submitted API request can still consume quota until its
bounded network read ends. See [Gemini video input](https://ai.google.dev/gemini-api/docs/video-understanding)
and [generateContent](https://ai.google.dev/api/generate-content).

`storage.py` serializes portable library updates with a reentrant lock and atomic,
fsynced JSON replacement. Invalid existing JSON is preserved and reported.
`library.json` under `$XDG_DATA_HOME/quickshell/desktop/spaces/streaming` contains
completed download associations and up to 1,000 answers keyed by
video/model/question. Download associations have a 10,000-record ceiling, support
local-first playback and keep the most recent file per video and type.
Older collision-preserved copies remain on disk.

The key, settings, library and resume directory use 0600 files with
0700 leaf directories. Credentials, portable state, runtime sockets, active jobs,
caches and media payloads stay outside source assets. Media payloads and caches
require independent storage. Removing local files updates availability
without changing Nextcloud.

## Validation

Run `python3 -m unittest discover -s tests -p 'test_streaming*.py' -v` with local
socket access. Tests cover URL validation, feed/search paging and offline reads,
serialized state, API redaction/cache behavior, explicit analysis, cancellation
and partial cleanup, owned player IPC, real FFmpeg tags/cover, Music's tag reader,
and the retained Quickshell page with both
layouts, toolbar search, Posts parsing/pagination and avatars, automatic rail/grid/
Posts loading, scroll retention, hidden/error/exhausted/repeated-page guards,
canonical subscriptions,
members-only filtering, metadata-independent playback, hidden-job
completion and stale-detail protection. Fixtures keep real media, credentials
and server uploads untouched. Live provider checks should use small temporary
samples and never print keys or resolved media URLs.
