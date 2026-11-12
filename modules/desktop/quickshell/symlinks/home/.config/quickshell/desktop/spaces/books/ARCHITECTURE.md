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
My Library, Browse and Favorites use the shared underlined tabs. The right-hand
Refresh action forces a catalogue read in Browse. In My Library it scans
Documents/Books immediately, without a folder field, like Movies: identified
files import at once and only unidentified ones open the shared modeless
`LocalScan` review above the catalogue. A review finishing while Books is hidden
or outside My Library waits until My Library is shown again; other tabs, hide and
Escape close it. Transfer activity sits beside Refresh. See the
[shared header contract](../movies/ARCHITECTURE.md#presentation-contract).

Open restores one lazy instance. Hide retains selections, search/filter drafts,
layout and jobs. It stops search debounce, pagination, delayed detail loads and
idle torrent polling. Background transfers keep polling until settled. Hidden
provider resolution cannot launch a browser or steal focus. Restore applies any
pending search/library change and resumes appropriate focus. Close destroys both
workers and the instance-owned artwork cache; downloaded books remain on disk.
The top-left host X always hides. Escape dismisses activity, provider/sort menus,
the library review, Find interactions, filters, search text, search mode, then
the current secondary view before hiding Books.

Selection, details, author and editions requests have separate generations.
Refresh supersedes only details hydration, so favorite and local-file replies for
the same selection still apply; a stale-copy warning stays out of the book record.
A `books.json` error reported by `init` stays beside catalogue errors until Retry
rereads it. Subject chips filter Browse, switching out of My Library/Favorites.

## Providers, workers and local files

`backend.py` owns Open Library normalization, caches, favorites, optional command
provider offers and direct downloads. Work IDs and private provider names/opaque
refs retain their meanings. Requests are paced per process at 1.02 seconds
anonymously and 0.36 seconds with contact identification, which also covers the
torrent worker's short-lived backends for scan matching; identified requests
include User-Agent and email headers. Open Library's `-1` placeholder image IDs
are ignored. Searches, details, author works and editions use finite pages.
Cached pages and saved favorites remain available offline with explicit warnings;
sort order alone keeps the six-hour discovery TTL.

Favorites keep the order they were added. Detail hydration updates a saved
favorite in place and never re-creates one removed meanwhile. Every list (Browse,
snapshots, author works, My Library) takes its favorite markers from the
favorites table, never from cached pages or import records.

`BooksService` uses the current bounded JSON-lines Worker transport and its
ordered mutation lane. `jobs.py` provides two transfer slots, a bounded queue,
cancellation, progress and retries; Music and Streaming import it too, so its
`Jobs`/`progress`/`check_cancelled` contract must stay stable for them. Direct
downloads validate status, content type, file suffix and length, reject HTML and
existing destinations, and have a 30-minute transfer deadline plus per-read
socket timeouts. Temporary files are registered for close cleanup; startup
removes `downloads/tmp*` staging older than the transfer deadline plus ten
minutes, which only a killed worker leaves. `BooksBackend.close()` releases only
its own jobs, commands and staging, so other workers can build and close one;
the worker's SIGTERM path also removes the process-wide import temporaries.
SIGTERM cancels jobs, kills owned command process groups, removes partials and
imposes a two-second exit bound on blocked network threads. Completed external
reader/browser handoffs use the shell's application launcher and survive
hide/close.

The generic manifest/command transport currently lives in
`spaces/pictures/{provider_plugins,command_provider}.py`; Books reuses it
without starting Pictures. Provider commands are trusted private argv, never
shell text. A `books.json` that lists providers must be owned by the user with
mode 0600, as Movies requires for `media.json` commands; Open Library browsing
needs only its optional `contact`. Each request reads env files anew; configured
values and URLs are redacted from errors. Commands and children die on timeout
or close. Resolved URLs are neither cached nor written to the portable library.

Configured entries contain `name` and either `command: [argv...]` or
`plugin: "providers/package"`. Optional `env_file` is relative to the package (or
books.json for direct commands); optional `env` overrides it. A package manifest
has `api_version: 1` and `command`, with `{plugin_dir}` substitution. Search accepts
`{op:"search",query,page:0,limit:10}` and returns
`{success:true,results:[{title,authors:[],ref,...}]}`. Resolve accepts
`{op:"resolve",ref,purpose:"read"|"download"}` and returns `{success:true,url}`.
Failures return `{success:false,error}`. Offers can include format, identifiers
(ISBNs), size_bytes, language, publisher, pages, year, size, description,
cover_url and page_url; other fields are dropped, text fields must be strings and
counts whole numbers, while `id`, `ref` and identifiers stay opaque.

Read online and downloads share one match for the selected Work: ISBNs from its
first 72 editions decide when any are known, otherwise the exact normalized title
plus a shared author. A download matches inside its transfer job, reading
editions as Read online does, so its identity never depends on which tabs were
opened first and the ordered control lane stays fast. A matching download takes
the Work's identity and library path; anything else, including an offer that
cannot be checked offline, keeps its own `book-command:` identity. The public
module contains no private provider code.

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
existing private package). The ebook-reader module declares Okular with
ebook-tools (EPUB) and kdegraphics-mobipocket (MOBI); Okular has no AZW3 (KF8)
reader. qBittorrent remains owned by its internet module. Browser borrowing may
require an Open Library account; this shell neither stores nor backs up browser
sessions.

## Storage and fresh-install restore

User configuration and state:

- `~/.config/quickshell/desktop/spaces/books/books.json`
- `~/.config/quickshell/desktop/spaces/books/books-ui.ini`
- `~/.config/quickshell/desktop/spaces/books/providers`
- `~/.local/share/quickshell/desktop/spaces/books/library.sqlite`

The library contains favorites and cached metadata, local file associations and
Books torrent job records. Database files are mode 0600 beneath 0700
directories; a provider-bearing `books.json` must be 0600. Response/artwork
caches live under `$XDG_CACHE_HOME/quickshell/desktop/spaces/books/` and are
regenerable. Ebook payloads and browser sessions need independent storage and
account sign-in.
