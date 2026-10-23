# Audio tools

The launcher imports `core.py` and `gui.py` from `/usr/local/lib/audio-tools`.
The PySide6 dialog uses the system Qt style, with a multi-selection file list,
Tags/artwork, Convert and File information tabs. The directory Project tools
module remains independent. A normal desktop application entry registers audio
MIME types and accepts file arguments. It appears in Open with and the launcher.
The deployment hook refreshes the desktop application database.
FFmpeg/ffprobe stay owned by `media/tools/ffmpeg`; PySide6 is declared here.
No dedicated converter package or codec-library additions are needed.

## Presets

`$XDG_CONFIG_HOME/audio-tools/presets.json` (default `~/.config`) contains
`{"version": 1, "presets": [...]}`. Each preset requires a unique lowercase/hyphen
`id`, display `name`, `extension` without a dot, and FFmpeg `codec`. Optional
fields are `description`, `bitrate` (e.g. `320k`), integer `quality` (-1–10),
`compression` (0–12), `sample_rate` (8000–384000 Hz), and `channels` (1–8).
Unknown fields and malformed IDs/extensions/options are rejected. Values become
individual subprocess arguments; no shell or command template is evaluated.
`bitrate` means total bitrate, including the AAC 320 kbps preset.
Presets are read and validated at startup. Applying dotfiles
replaces the managed config, so persistent preset edits belong in the module.

Conversions write `stem [id].extension`, beside each source or in the chosen
existing output directory. Only the first audio track is encoded; metadata and
chapters are mapped from the input. Attached pictures are copied as JPEG into
MP3/FLAC/M4A-compatible outputs, and omitted from other containers. Normalization
is optional one-pass `loudnorm=I=-16:TP=-1.5:LRA=11`, with 48 kHz output unless the
preset specifies another rate. Otherwise sample rate and channel count
follow FFmpeg defaults unless specified in the preset. Lossless encoding cannot
restore quality already lost in the source.

## Tag editing and jobs

The inspector combines first-audio-stream tags with format tags, with the format
value taking precedence. Album artist/year aliases are normalized for the form.
Drafts are stored per file; changing the current file does not discard them.
Only edited keys are written, including explicit blank values for deletion.
Batch save takes the current file's edited keys and cover change, confirms the
selection, and applies those edits to each target. Existing tags and streams use
FFmpeg's metadata/stream mapping; support for nonstandard tags follows the
container and FFmpeg muxer. All tags are visible in File information. The cover preview and adjacent remove icon sit beside the file heading; clicking
the preview opens the image picker. Covers can be added/removed in MP3, FLAC and M4A; other formats still support compatible tags.
Tag edits remux without audio re-encoding, preserving streams and chapters.

FFmpeg writes a private temporary file in the destination filesystem. Successful
tag jobs are probed to verify edited fields and cover state before replacement.
The source inode/size/mtime must still match. Hard-linked sources are rejected.
Backups use a unique adjacent `.tags-backup[-N]` hard link to the original inode;
then atomic replace publishes the new file. Conversion uses an atomic hard link
to publish without overwriting even a concurrently created destination. Errors
and cancellations remove temporary files. A completed earlier file in a batch
stays completed if a later file fails or the user cancels.

QProcess runs probes and serial FFmpeg jobs asynchronously. Progress follows
FFmpeg's progress stream (per-file elapsed time, and percentage where duration is
known). Cancel terminates the owned process, escalating to kill after two seconds.
The window stays open until cancellation finishes. Probes/cover reads stop on
selection change or close. Diagnostics stay in the dialog; there is no background
service. Tag round-trip verification has a bounded synchronous probe after each
completed remux; it never performs conversion on the UI thread.

## Validation

`python3 -m unittest tests.test_audio_tools tests.test_audio_tools_gui` uses
throwaway fixtures: all seven presets, Unicode and cleared tags, covers,
unchanged audio, backups, source changes, output races, job errors/cancellation
and the real offscreen dialog. Native application queries verify audio MIME registration.
