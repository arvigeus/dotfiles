# Desktop file tools runtime

PDF tools, File tools and Encryption tools install their Python task modules beside
`tools_gui.py`, `tool_worker.py`, `tool_jobs.py` and `tool_specs.py` in
`/usr/local/lib/desktop-file-tools`. Each app has an executable and desktop entry
with `%F`; files/folders are individual arguments. The shared module owns PySide6.
File/Encryption tools use the grouped tab shell. PDF tools own their document
editor (`pdf_gui.py`), draft lifecycle (`pdf_drafts.py`), SVG icons and Qt SVG
dependency. Visible action text replaces tooltips. gImageReader independently owns
image/PDF recognition.

PDF sessions expand folders to PDFs and retain original identities and logical
names separately from private paths. Combination uses every sidebar document in
order. The central preview stays visible; metadata, reports and diagnostics live
in the wider right pane. Toolbar menus/popovers hold edits and Export profiles.

PDF sessions own mode-0700 temporary directories. `_edit` and `_save` dispatch
through `pdf_edits.py`; `_pdf_export` stages a transformed copy without modifying
the draft. Per-input subdirectories avoid basename collisions. Only complete
successful edit batches enter undo history. Errors/cancellation preserve the
previous draft. Saved signatures track draft paths/names, so Undo after Export
becomes unsaved again. Batch export preflights names; atomic publication protects
against races. Successful members of partial batches become clean individually.
Closing offers Save/Discard/Cancel; active workers stop before session cleanup.
History and passwords remain in memory. Drafts are private ordinary temporary
files, not encrypted storage.

Workers scan at most 200,000 entries without following symlink directories. Native
GnuPG agent/pinentry owns passphrases; PDF passwords travel through worker stdin
and library calls.

## Workers and publication

QProcess launches a fresh Python worker for each explicit action. One JSON object
on stdin selects an allowlisted app/action and supplies paths/options. JSON-lines
stdout emits progress, rows, errors, key lists, rename previews and completion.
External commands use argv arrays, with no shell expansion. The worker owns each
subprocess group. SIGTERM terminates it, waits two seconds, then kills any
remaining group; temporary output contexts unwind before completion. The UI
prevents closing while cancellation is in progress, with a final worker-kill
fallback after ten seconds. Earlier successful explicit saves/exports remain after later errors
or cancellation; private edits are adopted as a complete batch. There is no persisted job/history database.

Outputs stage in private adjacent temporary directories. New files use mode 0600
and output directories 0700. Complete files publish
using atomic hard links; complete multi-file directories use Linux renameat2
with RENAME_NOREPLACE. Existing or concurrently created outputs are refused.
Sources remain unchanged except an explicitly applied rename. Publication and
renaming do not fall back to overwrite-capable operations. Long native tool
operations report progress per input file rather than fabricated percentages.

## Validation

`python3 -m unittest tests.test_file_tools tests.test_file_tools_gui
 tests.test_file_app_registrations tests.test_generation` uses disposable PDFs, unusual
filenames, collisions, checksum tampering, stale rename previews and real offscreen
dialogs. PDF regressions exercise cumulative edits, undo, passwords, toolbar/menu
controls, export destinations, page ranges, archival conversion without OCR and
child-process cancellation.
Encryption tests use disposable GnuPG homes/keys, never the user's keyring.
Environments that block Unix agent sockets need isolated tests outside that
restriction. Live smoke checks likewise use disposable fixtures.
