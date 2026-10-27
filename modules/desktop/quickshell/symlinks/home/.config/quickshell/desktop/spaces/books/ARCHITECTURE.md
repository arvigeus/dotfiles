# Books implementation

## Presentation and lifecycle

`ui/SpaceState` registers Books with the shared retained fullscreen host. Books
uses Movies' toolbar controls, artwork cards, scrolling and activity panel on a
solid black background. The overview contains synopsis and metadata without a
second copy of the catalogue cover. Rail mode keeps title, facts and actions
above a cover strip;
grid mode uses the shared 51% catalogue / 45% detail split with a 4% gutter.
Covers retain their aspect ratio. The grid uses Movies' 155-pixel target
cell size; whole-pixel cell widths prevent fractional viewport rounding from
leaving a missing column. One toolbar spinner covers catalogue, details, provider,
author, edition, Find and scan requests; nested spinners are disabled. Author
profiles and editions remain separate views. The presentation
uses the same immersive palette in both desktop theme modes.

Open restores one lazy instance. Hide retains selections, search/filter drafts,
layout and jobs. It stops search debounce, pagination, delayed detail loads and
idle torrent polling. Background transfers keep polling until settled. Hidden
provider resolution cannot launch a browser or steal focus. Restore applies any
pending search/library change and resumes appropriate focus. Close destroys both
workers and the instance-owned artwork cache; downloaded books remain on disk.
The top-left host X always hides. Escape dismisses activity, provider/sort menus,
Find interactions, filters, search text, search mode, then the current secondary
view before hiding Books.

## Providers, workers and local files

`backend.py` owns Open Library normalization, caches, favorites, optional command
provider offers and direct downloads. Work IDs and private provider names/opaque
refs retain their meanings. Requests are paced at 1.02 seconds anonymously and
0.36 seconds with contact identification; identified requests include User-Agent
and email headers. Searches, details, author works and editions use finite pages.
Cached pages and saved favorites remain available offline with explicit warnings.

`BooksService` uses the current bounded JSON-lines Worker transport and its
ordered mutation lane. `jobs.py` is Books-owned, with two transfer slots, a bounded
queue, cancellation, progress and retries. Direct downloads validate status,
content type, file suffix and length, reject HTML and existing destinations, and
have a 30-minute transfer deadline plus per-read socket timeouts. Temporary files
are registered for close cleanup. SIGTERM cancels jobs, kills owned command
process groups, removes partials and imposes a two-second exit bound on blocked
network threads. Completed external reader/browser handoffs use the shell's
application launcher and survive hide/close.

The generic manifest/command transport currently lives in
`spaces/pictures/{provider_plugins,command_provider}.py`; Books reuses it without
starting Pictures. Provider commands are trusted private argv, never shell text.
Each request reads env files anew; configured values and URLs are redacted from
errors. Commands and children die on timeout or close. Resolved URLs are neither
cached nor written to the portable library.

Configured entries contain `name` and either `command: [argv...]` or
`plugin: "providers/package"`. Optional `env_file` is relative to the package (or
books.json for direct commands); optional `env` overrides it. A package manifest
has `api_version: 1` and `command`, with `{plugin_dir}` substitution. Search accepts
`{op:"search",query,page:0,limit:10}` and returns
`{success:true,results:[{title,authors:[],ref,...}]}`. Resolve accepts
`{op:"resolve",ref,purpose:"read"|"download"}` and returns `{success:true,url}`.
Failures return `{success:false,error}`. Offers can include format, ISBNs,
size_bytes, language, publisher, pages, cover_url and page_url. Read offers match
edition ISBNs, or exact title/author when ISBNs are absent; unrelated downloads
keep their own identity. The public module contains no private provider code.

LocalLibrary and TorrentService reuse Movies' current import/search boundary,
with `spaceId: books` and `kind: book`. Favorites, local associations and torrent
jobs share Books' database, independently of other Spaces. Scanning uses private
review tokens and explicit Open Library matching for unassociated files; it never
guesses book identity from a filename alone. Imports preserve existing files.
Documents/Books stores actual payloads; module state stores only their identity
and path. qBittorrent credentials remain in the single shared integration.
qBittorrent owns queued torrents and can continue them after the Space closes;
closing releases Books' searches, polling and import worker.

The quickshell module declares Python and python-requests (required by the
existing private package). The ebook-reader module declares Okular and ebook-tools;
qBittorrent remains owned by its internet module. Browser borrowing may require
an Open Library account; this shell neither stores nor backs up browser sessions.

## Storage and fresh-install restore

Portable `extra.private.files` entries owned by the quickshell module:

- `home/.config/quickshell/desktop/spaces/books/books.json`
- `home/.config/quickshell/desktop/spaces/books/books-ui.ini`
- `home/.config/quickshell/desktop/spaces/books/providers`
- `home/.local/share/quickshell/desktop/spaces/books/library.sqlite`

The library contains favorites and cached metadata, local file associations and
Books torrent job records. Settings/provider packages and database files use
owner-only permissions. Response/artwork caches live under
`$XDG_CACHE_HOME/quickshell/desktop/spaces/books/` and are regenerable. No ebook
payloads, temporary downloads, artwork, sockets or browser account sessions enter
private backups. Database backup requires quiescent writes; `backup.sh` is a file
snapshot rather than an application-consistent SQLite backup.

`backup.sh` snapshots the selected module declarations to `modules/backup` with
permissions. On a clean machine, install the public quickshell/ebook-reader/
qBittorrent modules and run the private checkout's standalone `apply.sh` as the
regular user. It creates parents, restores restrictive modes and preserves
collisions under `.before-private-*`. Restore media separately and ensure saved
local paths/mounts exist. Browser borrowing accounts require ordinary sign-in.

## Validation

`test_books.py` exercises normalized IDs, search filters/rate policy, caching,
offline favorites, editions/authors, local matching and imports.
`test_book_providers.py` exercises ISBN matching, packages/env files, safe URLs,
redacted errors, downloads, collisions, cancellation and owned child shutdown.
`test_books_space.py` drives the production host and workers for toolbar/grid/rail,
search/filter Escape, author/edition/scan views, hide/restore, hidden transfer
completion, independent Movies close, fresh instances and saved layout.
`test_books_private.py` performs backup → synthetic commit → clone → standalone
restore, checks bytes/modes/collisions and browses a restored private package with
the production worker. Fixtures use isolated state and no real account.

Native multi-monitor scaling/hotplug, actual ebook reader handoff and live torrent
completion still require interactive validation. Test fixtures do not prove those
paths.
