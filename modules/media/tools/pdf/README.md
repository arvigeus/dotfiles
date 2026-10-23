# PDF tools

Open PDFs or folders with **PDF tools**, or run `pdf-tools FILE…`.

Rotate the current page from the toolbar, combine documents in sidebar order,
and add watermarks or passwords. Edits accumulate in a draft,
with Undo; originals and existing output files are preserved.

**Export** saves the current PDF. Its menu offers web optimization, 150/300 dpi
size reduction, PDF/A-2b, embedded images and page ranges such as `1-5,7` as one
PDF or separate pages. Export profiles leave the working draft unchanged.

Unlock protected documents individually before combining. Combining/page exports
do not merge document-level bookmarks. Rewriting signed PDFs can invalidate
signatures; size reduction may change visual content.

See [ARCHITECTURE.md](ARCHITECTURE.md) for format handling.
