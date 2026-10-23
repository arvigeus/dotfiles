# PDF tools implementation

The module owns pikepdf, Ghostscript, qpdf, Poppler and Qt WebEngine's Qt PDF
libraries, Qt SVG and OCRmyPDF. `pdf_gui.PdfEditor` inherits the draft lifecycle
from `pdf_drafts.PdfDraftDialog` and builds a dedicated document editor. Its sidebar
contains documents only. The
Rotate split button immediately edits the current page, with whole-document
angles in its menu. Page focus survives edits and Undo. Password and watermark
settings use anchored modal sheets; dialog modality permits nested file choosers
without dismissing the sheet. Empty required fields and invalid page ranges
disable confirmation. Cancelling a sheet makes no edit. Remove metadata sits in
the document properties header; Digital signatures is a button immediately below the properties. Add PDFs has a folder
option. Combining is attached to the document list and follows its visual order.

The right pane shows Qt PDF metadata without starting an inspection worker.
Signatures, exports and diagnostics appear beneath it, keeping the preview visible.
Find PDFs and OCR are absent from the task allowlist and worker implementation.
Recognition belongs to gImageReader, configured by `media/tools/ocr`.

Edits run against private drafts and enter the undo history only after complete
worker success. Export's main action copies the current PDF bytes, preserving
final encryption and linearization. Its menu offers web optimization, 150/300 dpi
reduction, archival PDF/A-2b, page selections and embedded images. `_pdf_export`
runs a single selected profile against the current draft in a private session
subdirectory, then publishes the selected destination atomically. Intermediate
Saved events are suppressed in the editor. Export never adopts the profile output
as a draft edit or adds an undo step. Complete-document exports mark that draft
revision exported; selected-page/image exports leave its export state alone.
Cancellation/failure preserves the working draft and does not mark it exported.

Qt PDF supplies fit-page/fit-width/actual-size zoom, one pair of page arrows and a
number field without stepper arrows. Each document retains its own unlock password
in memory, reused for edits and preview. Combining uses all sidebar documents in
order, opens each with its own password and creates one unencrypted draft. Undo
restores the source documents and their previous drafts. Password changes update
the draft's preview credentials. There is no second current-password control.

`pdf_tasks.py` uses pikepdf for page assembly, rotation, encryption, linearization, metadata removal and PDF
watermarks. The first watermark page is fitted onto each source page with native
overlay/underlay methods. AES-256 protection uses a user password and a generated
independent owner password. Unprotection requires the supplied current password;
other pikepdf rewrites retain existing encryption. PDF passwords are not placed
on subprocess command lines or persisted to disk.

Ghostscript's ebook/printer presets implement 150/300 dpi reduction. OCRmyPDF
converts archival exports with `--ocr-engine none --skip-text --output-type pdfa-2`;
it performs no text recognition and requires no language choice. PDF/A conversion
uses the format-conversion pipeline rather than claiming conformance from an
unchecked Ghostscript rewrite. Poppler provides image extraction and native signature diagnostics. Signature/info results are read-only.

Page export accepts one-based comma-separated page numbers and ascending inclusive
ranges (`1-5,7`). Blank means all pages; invalid syntax, reversed ranges and pages
outside the document fail before output staging. Inputs are bounded to 4,096
characters. Overlaps are deduplicated, preserving the first written occurrence.
One-PDF exports retain that order; separate PDFs use original page numbers in
filenames. Both retain at least the input PDF version and create new documents
without document-level metadata/bookmarks or source encryption.

Combined PDFs retain selected page order and the greatest input PDF version;
new split/combined documents do not merge document-level metadata or outlines.
Metadata removal deletes document info and XMP in a full rewrite. Directory
outputs publish only when all pages/images for that input are ready. Private batch
edits are adopted only when every input succeeds. Explicit exports
can retain earlier successful outputs after a later failure.

See the [shared runtime](../../../files/tools/common/ARCHITECTURE.md) for workers,
publication and validation.
