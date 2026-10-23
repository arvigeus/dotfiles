# File tools implementation

`file_tasks.py` owns the task descriptors and operations; the shared runtime owns
the window and process lifecycle. Renames preserve file extensions and support
case, accent, parentheses and whitespace/dash cleanup. Preview records source
identity (device/inode/size/mtime/mode) and target names. Applying recomputes and
compares the complete plan before mutation. Existing targets, duplicate targets
and selecting both a parent and child are rejected. Each native rename refuses
concurrent target creation. A later failure retains earlier successful renames.
Changing selection/options invalidates the UI's apply button.

Checksum generation writes an adjacent `filename.algorithm` for each selected
file, or an `ALGORITHMSUMS` inside each selected directory. GNU text/binary
manifest markers and escaped backslashes/newlines/carriage returns are accepted.
Verification rejects absolute, escaping and symlink targets; source identity is
rechecked after hashing. MD5/SHA-1 are provided for existing manifests, not as
signatures. Custom checksum MIME definitions belong to this module.

Duplicate discovery groups by size then SHA-256. Link discovery uses native
filesystem metadata and does not follow symbolic directory links. Hard-link
creation uses os.link without overwrite. Clipboard content uses Qt's clipboard;
image reads are dimension bounded and text must be UTF-8 without NUL bytes.

See the [shared runtime](../common/ARCHITECTURE.md) for publication and validation.
