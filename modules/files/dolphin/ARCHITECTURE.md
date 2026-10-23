# Dolphin

## Preferences

`scripts/50_dolphin-preferences.sh` writes into the executor's staging home using
`kwriteconfig6`. `dolphinrc` enables `BrowseThroughArchives` and `GlobalViewProps`;
`kdeglobals` sets `[KDE] SingleClick=true` for KDE file views. Archive KIO workers
are an explicit dependency through `kio-extras`.

The shared view defaults live in
`$XDG_DATA_HOME/dolphin/view_properties/global/.directory`, using view-properties
version 4 and `VisibleRoles=Icons_size,Compact_size`. Details view retains its
default size and modification-time columns. When view settings change, Dolphin can
store them in the containing directory's `user.kde.fm.viewproperties#1` extended
attribute.

The embedded terminal uses Konsole's KPart and cannot embed Kitty. Dolphin hides
this panel on first run; do not copy a live `dolphinstaterc` into the repository,
since its serialized Qt layout also contains window geometry and other panels.
Hide an already enabled panel with F4 and let Dolphin save its own state.
The standalone terminal preference remains owned by `base/terminal`.

## File tools integration

PDF tools, File tools and Encryption tools register desktop application entries
with `%F`, file MIME types and `inode/directory`. Open with can launch them for
selected files or folders; MIME defaults are not changed. Audio/Video tools and
Project tools register their own applications. Native editors, Ark, Fooyin,
MKVToolNix, LibreOffice, Okular, Meld and Filelight own their existing workflows.
gImageReader uses its packaged desktop entry for image/PDF recognition.

The database hook refreshes the shared MIME and desktop application databases so
the checksum MIME types and installed application entries are available to KDE.
Checksum MIME definitions belong to File tools.

The three custom apps share the PySide6 shell and worker protocol described in
[desktop file tools architecture](../tools/common/ARCHITECTURE.md). Their functional
modules own the actual operations and dependencies. Regenerate
`user-configuration.json` when assets or hooks change.

`tests/test_file_app_registrations.py` verifies desktop registrations, checksum
MIME ownership and OCR package ownership. Backend and real-dialog tests live in
`tests/test_file_tools.py` and `tests/test_file_tools_gui.py`. Native desktop-entry
validation covers the three custom apps without changing the real MIME defaults.
