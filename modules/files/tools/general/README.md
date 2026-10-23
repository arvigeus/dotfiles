# File tools

Open selected files/folders with **File tools**, or run `file-tools PATH…`.

- Preview filename cleanup, then apply the reviewed renames.
- Generate/verify MD5, SHA-1, SHA-256 and SHA-512 manifests.
- Find duplicate/empty files, empty folders, symbolic/broken links and hard links.
- Create hard links in another folder, or copy image/UTF-8 text contents.

Discovery never deletes files. Rename targets and existing outputs are never
overwritten. Hard links require the same filesystem. Checksum verification only
reads paths inside the manifest's folder; move related files together. Clipboard
text is limited to 8 MiB; images to 40 megapixels.

See [ARCHITECTURE.md](ARCHITECTURE.md) for rename and checksum behavior.
