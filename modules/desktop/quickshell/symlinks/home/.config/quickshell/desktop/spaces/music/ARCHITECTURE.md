# Music implementation

## Presentation and ownership

`Main.qml` is a retained `SpaceState`/`SpaceHost` page with the same black immersive
surface and controls as Radio. A fresh instance opens My Library, all songs, with
no filters. Tabs preserve in-memory queries, navigation, results and scroll.
The general search filters songs; `MusicPicker.qml` owns searchable, virtualized
artist/album/playlist menus, grouped with Genres behind My Library’s filter button. Library pickers read indexed metadata immediately;
Discover pickers wait for two query characters and search Apple dynamically.
Artist pages enrich their header independently of song reads, first from
Subsonic `getArtistInfo2`, then Apple when needed. Enrichment never changes the
library identity or playback source. Songs and Albums remain separate views.

`MusicInfo.qml` has separate read-only and editing states. Opening it requests
`song-info`: existing local files supply FFprobe tags; otherwise Subsonic `getSong`
supplies the server metadata and Music-relative path. This never downloads audio
or starts a lyric lookup. All tag fields remain visible, with placeholders for
missing values. Format/rate/bit-depth details reflect whatever the source exposes.
A missing server path disables editing and moving rather than guessing a filename.
The title and file-detail subtitle share the header with the editing controls:
Edit metadata becomes Cancel while editing, with Save beside it.

Edit metadata starts one owned `info` file job to prepare a local copy and capture
its authoritative tags/signature. Only then do fields and the cover pencil become
editable. The cover image itself has no click action. The pencil opens a Qt Quick
file picker with `DontUseNativeDialog` and `Popup.Item`, keeping it inside the
shell's overlay window. Escape rejects the picker before cancelling editing or
closing Info. Hiding Music closes the picker and Info while retaining drafts.
The chooser inherits the window palette, so temporary per-role bindings apply
Music's palette while it is visible and restore the previous values on closing.

Fetch lyrics is explicit in both states. It reads existing local/server lyrics
first, then configured providers when necessary. Fetched text stays read-only in
viewing mode and can be carried into an editing draft when the local file has no
saved lyrics. A lookup never writes tags. Results use the bounded lyrics cache;
an explicit fetch refreshes it. Song generations reject stale replies, and closing
an unfinished preview permits it to retry on reopening.
Nextcloud Music's [Subsonic interface](https://github.com/nc-music/music/blob/master/lib/Controller/SubsonicController.php)
provides lyric reads but no lyric/tag write endpoint. Fetch therefore remains a
read operation; persistence uses metadata editing and the conditional DAV upload.

Save writes the local tags/cover and explicitly uploads the resulting file,
including new local songs. Successful saves return to viewing mode. An upload
failure retains the locally saved version and enables an explicit retry. Cancel
editing discards unsaved drafts. Info owns its file-job ID, so background jobs
cannot settle its operation; worker exit settles accepted jobs before clearing
state. No automatic lyrics, tag writes, uploads or retries occur while viewing.

The path field and Move button stay at the bottom, outside the metadata editor.
A path draft disables Edit metadata; editing disables the path and Move. Move jobs
carry no tag/cover edits and never prepare or download audio. No delete action or
automatic media eviction exists; adding deletion requires an explicit interface
action with hold-to-confirm.

The `ListView` instantiates visible delegates and reads metadata pages ahead of
its lower edge. Small cover thumbnails load only for visible rows and the Info header.
`artwork.py` isolates thumbnail requests from browsing and file jobs. It prefers
embedded art in cached files, uses authenticated Subsonic POST requests for remote
art, and reuses the shared image cache for public catalogue art. Album/account
identity coalesces server reads; local signatures invalidate extracted thumbnails.
Only local image URLs reach QML for Nextcloud art. Download and upload-indicator
slots remain reserved on every song row so caching does not move adjacent columns. Placeholder dimensions stay
fixed when art is absent or loading. Paging/search/network/file
work stays in Python workers, outside the QML render thread. Popup requests and
page requests have separate cancellation scopes. Escape dismisses popups, filters,
search and entity history before hiding. Hide stops visual polling and folder
observation. Close destroys the page and its workers/player.

## Catalogue snapshots and local observation

`cloud.py` uses the shared `integrations/subsonic.py` authenticated POST transport.
`cloud_index.py` builds a complete account-scoped SQLite catalogue in 500-item
batches, then atomically publishes it. Queries return 200-item pages with folded
Unicode search, indexed order and artist/album relationships. Refresh runs in a
background thread while the previous snapshot stays readable. Library playback
queues read the complete matching collection, independently of displayed pages.
Playlists use cached `getPlaylists` and `getPlaylist` reads; entry order is retained.
Provider caches are account-scoped, bounded and usable offline after a successful
read. Authentication errors never select another account's cache.

`inventory.py` observes ordinary files in `~/Music` on opening/restoring My Library,
after file jobs, and every five seconds while visible. The observer performs no
network requests or file mutations. Symlinks, hidden files/directories and unknown
extensions are skipped. It caches FFprobe metadata by inode/size/nanosecond mtime,
so unchanged songs are not reprobed. Unreadable files produce a notice.

The regenerable `local.sqlite` inventory and `library.sqlite` merged snapshot live
beside the remote `catalogue.sqlite` in the account's cache directory. A changed
inventory or remote snapshot builds a new merged database, then publishes it
atomically. Failure preserves the previous readable view and permits retry.
Server-relative paths identify cache copies, avoiding duplicate rows. Cached file tags
override stale server metadata in search, including while the server indexes a save. Local-only artists/albums join
existing names or receive stable local identities. Missing cache bytes remove
only local availability; the remote record remains. Media payloads are never
removed. The observer operates independently of the background remote index build.

## File operations and tag editing

`local_files.py` owns path validation, downloads, local-first playback and file
jobs. Subsonic paths are relative to the server Music root despite a leading
slash. They map to `~/Music/<relative path>`. Traversal, symbolic links and
extension-changing moves are rejected. Account/rclone identities must agree.
Downloads verify stable server metadata, byte count and advertised checksums,
then publish atomically without replacing existing local files.

The private data database's `music_cache` table records account/path, synchronized
hashes, local signatures and server fingerprints, including DAV ETags.
`music_pending_index` records explicit uploads until the catalogue acknowledges
their paths. `music_pending_moves` records the old/new paths and song identity,
including intermediate paths for repeated moves. Inventory applies those moves
to the merged snapshot before joining local files, then drops associations once
the server catalogue acknowledges them. Metadata previews resolve pending paths
through the same association, avoiding duplicates and false upload indicators.

`remote_files.py` performs conditional DAV writes. Existing files are copied to a
unique `Music-history` destination with `If-Match`, then updated in place with the
same version precondition. New files use `If-None-Match: *`. The source remains in
place during backup so the final PUT can reject concurrent changes atomically.
Uploads stream from a private snapshot with byte progress and cooperative
cancellation. Once PUT is confirmed, verification finishes even if Cancel arrives;
a committed update wins over late cancellation. Stable metadata and hashes verify
the result. An identical server copy can be adopted after a lost upload response
without uploading twice. Conflicts retain local edits and never schedule retries.
Rclone provides downloads, file metadata and checksum reads; its remote must
identify the same account root as DAV. Missing local files never trigger remote
deletion or synchronization, and missing unuploaded files cannot adopt unrelated
server files with colliding names.

`tags.py` belongs to Music and uses the existing FFmpeg/FFprobe dependencies.
Edits stream-copy audio, preserve other streams/metadata, verify requested tags
and source signature, then atomically replace the cache file. MP3/FLAC/M4A cover replacement removes only existing attached-picture streams,
embeds the selected image, verifies its presence and checks both source versions.
Local signatures invalidate thumbnails after cover changes. Temporary files
are registered for cancellation/close cleanup. Saving a server copy captures its
baseline before editing. A failed upload returns a local-saved result to the
same dialog, allowing an explicit retry without losing the draft or file.
Local-only information, saves and moves can finish without network access.

Moves reject local/server destination collisions. DAV creates required parent
folders, obtains a source ETag, and uses `MOVE` with `Overwrite: F` and `If-Match`.
A cached file changes its local name as part of the action; an uncached song moves
on the server without downloading. Baselines and pending catalogue associations
follow the move. Filesystem changes never infer remote moves or deletes.

## Discover providers and playback

`backend.py` owns Apple catalogue searches, artist/album expansion, lyrics,
provider matching, downloads and player IPC. `records.py` normalizes provider
identities and requires confident ISRC or artist/title matches. Public metadata
reads use the bounded SQLite cache in `cache.py`; tokens/stream URLs are excluded.

`music.json` accepts `catalog_token` or a token endpoint, two-letter `storefront`,
optional `default_playlist` and `providers`. Lyrics providers use the shared
`~/.config/audio-tools/lyrics.json` and `/usr/local/lib/audio-tools/audio_lyrics.py`
owned by [Audio tools](../../../../../../../../../media/tools/audio/ARCHITECTURE.md#lyrics).
Providers specify `search_url`, `stream_url`, optional headers/result mappings,
and `download.track`/`download.album` URL templates or `stream`. Templates escape
metadata. Secrets remain in private configuration and sanitized worker errors.
Catalogue access does not supply subscription authentication or downloadable
full tracks. Stream downloads encode decoded audio losslessly as tagged FLAC,
use the collection's title/artist/album/full-date filename convention, preserve
collisions with numbered names, and register finished files locally. This does
not imply the original stream was lossless. Album jobs report partial failures.

`MusicPlayback.qml` owns one mpv process, MPRIS identity, queue and IPC socket.
Local Music is preferred. Uncached Nextcloud songs and configured Discover
providers use `cloud_stream.py`'s owned loopback gateway. Only temporary track
capabilities reach QML, mpv and FFmpeg. Nextcloud uses authenticated POST/range
requests with redirects disabled. Provider headers and signed URLs remain in
Python; HLS references and DASH bases/templates are rewritten into the same
revocable session, retaining authentication for media segments. Media suffixes
remain on opaque reference paths for demuxer compatibility. Playlists are bounded
to 4 MiB and 16,384 references. Cleanup revokes every child reference and closes
upstream responses, including requests that were still opening when revoked.

Process completion advances the queue while hidden; visual position polling only
runs while visible. File/transfer polling continues while hidden until active jobs
finish so completion notifications arrive on time.
Music sends completion/error notifications through `notify-send` to the shell’s
normal notification server. The Notifications bell retains progress/cancel/retry
controls, with routine Info reads excluded from both the panel and delivery. Generations discard stale play
resolutions after Stop. Close cancels owned jobs and keeps completed media files.

## State and validation

Portable files are declared in the desktop module's `extra.private.files`:
`music.json`, `music-ui.json`, and the data `library.sqlite` with local associations
and cache baselines. Favorites controls are absent from both tabs. Shared
Nextcloud credentials and private `rclone.conf` are declared by their owning
modules. All private snapshots use 0600 files and 0700 leaf directories. Metadata
caches, runtime sockets, active playback and large audio payloads are excluded
from dotfiles backups. New, unuploaded music needs a separate media backup.

Run `python3 -m unittest discover -s tests -p 'test_music*.py' -v`.
Fixtures cover complete/offline indexes, Unicode search, merging and deduplication,
local removal isolation, failed snapshot publication, complete queues, explicit
uploads, file collisions/moves, source-version conflicts, real FFmpeg tag edits,
provider downloads, secure stream proxying, private restore, retained QML views,
the information dialog and real mpv pause/seek/hidden queue completion.
Loopback HTTP/IPC tests need socket access. Fixture tests do not mutate real media
or upload/delete real server songs. Newly added QML/Python/icon files need their
individual source links installed before reloading the live shell.
