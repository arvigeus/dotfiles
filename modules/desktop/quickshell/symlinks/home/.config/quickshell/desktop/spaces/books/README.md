# Books

Open Library discovery and search, favorites, author profiles and editions in a
fullscreen cover browser. Local ebooks open in the system reader; **Scan** adds
existing files after you choose their catalogue match. **Find** searches
qBittorrent and any configured private providers.

No account or API key is required. Optional settings live in
`~/.config/quickshell/desktop/spaces/books/books.json`; see
[books.example.json](books.example.json). An optional `contact` email identifies
Open Library requests. Language filters use three-letter codes such as `eng` or
`vie`. Downloaded books go beneath the XDG Documents `Books` folder.

Restore the private checkout alongside the public shell to recover favorites,
preferences and private providers. Ebook files require their own backup. Reading
opens your browser or installed reader; reading progress is not synchronized.

See [architecture](ARCHITECTURE.md) for providers, storage and validation.
