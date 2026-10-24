# Audio tools

The launcher imports `core.py` and `gui.py` from `/usr/local/lib/audio-tools`.
The PySide6 dialog edits one file, with Tags/artwork, Convert and File
information tabs. It inherits the native Qt style and palette through the KDE
platform theme; `desktop-theme` supplies colors and live change notifications.
The directory Project tools module remains independent. A normal desktop application entry registers audio
MIME types and accepts a single file argument (`%f`). Launching without a path
opens a single-file picker; cancelling exits without opening the dialog. It
appears in Open with and the launcher.
File information uses a Property/Value tree grouped into container, audio tracks
and tags, with a summary and Copy information action matching Video tools.
Durations use hours/minutes/seconds with tenths, including carry at rounding
boundaries; missing or invalid durations display Unknown.
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
Drafts remain in memory until saved or discarded.
Only edited keys are written, including explicit blank values for deletion.
Existing tags and streams use FFmpeg's metadata/stream mapping; support for nonstandard tags follows the
container and FFmpeg muxer. All tags are visible in File information. The cover
preview and adjacent remove icon sit beside the file heading; clicking the
preview opens the image picker. Covers can be added/removed in MP3, FLAC and M4A;
other formats still support compatible tags.
Tag edits remux without audio re-encoding, preserving streams and chapters.
The tag form keeps fixed row spacing inside its scroll area. Conversion progress
and cancellation live in Convert; tag saves expose a Cancel action beside Save
tags. The shared footer starts blank and carries operation/error messages.

FFmpeg writes a private temporary file in the destination filesystem. Successful
tag jobs are probed to verify edited fields and cover state before replacement.
The source inode/size/mtime must still match. Hard-linked sources are rejected.
Backups are opt-in in the dialog and use a unique adjacent `.tags-backup[-N]`
hard link to the original inode; then atomic replace publishes the new file.
Conversion uses an atomic hard link
to publish without overwriting even a concurrently created destination. Errors
and cancellations remove temporary files.

QProcess runs probes and the current FFmpeg job asynchronously. Progress follows
FFmpeg's progress stream (elapsed time, and percentage where duration is
known). Cancel terminates the owned process, escalating to kill after two seconds.
The window stays open until cancellation finishes. Probes/cover reads stop
before a job or on close. Diagnostics stay in the dialog; there is no background
service. Tag round-trip verification has a bounded synchronous probe after each
completed remux; it never performs conversion on the UI thread.

## Validation

`python3 -m unittest tests.test_audio_tools tests.test_audio_tools_gui` uses
throwaway fixtures: all seven presets, Unicode and cleared tags, covers,
unchanged audio, backups, source changes, output races, job errors/cancellation
and the real offscreen dialog. Native application queries verify audio MIME registration.
`python3 -m unittest tests.test_media_tools_gui` verifies single-file registration,
picker cancellation and native dark/light palette changes in both dialogs. The
live theme test uses an isolated D-Bus session and temporary XDG directories.
