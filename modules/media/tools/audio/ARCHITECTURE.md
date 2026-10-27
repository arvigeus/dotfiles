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
FFmpeg/ffprobe stay owned by `media/tools/ffmpeg`; PySide6 and Mutagen are declared here.
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
Tag edits preserve encoded audio, streams and chapters. Most containers use an
FFmpeg remux. Ogg Opus uses Mutagen on a private copy: its cover is a Vorbis
picture comment, even though FFprobe exposes it as an attached video stream.
Mapping that apparent stream into FFmpeg's Opus muxer is unsupported. Native
edits preserve picture comments, unrelated tags and the original Opus packets.
Album artist, track/disc number and year aliases are normalized for the form;
editing or clearing a field removes its old aliases before saving the canonical
Vorbis name.
The tag form keeps fixed row spacing inside its scroll area. Conversion progress
and cancellation live in Convert; tag saves expose a Cancel action beside Save
tags. The shared footer starts blank and carries operation/error messages.

File jobs write a private temporary file in the destination filesystem. Successful
tag jobs are probed to verify edited fields and cover state before replacement.
The source inode/size/mtime must still match. Hard-linked sources are rejected.
Backups are opt-in in the dialog and use a unique adjacent `.tags-backup[-N]`
hard link to the original inode; then atomic replace publishes the new file.
Conversion uses an atomic hard link
to publish without overwriting even a concurrently created destination. Errors
and cancellations remove temporary files.

QProcess runs probes and the current file job asynchronously. Opus edits invoke
`core.py --write-opus-tags` in an owned Python process. Its changes are stored in
a mode-0600 adjacent JSON payload, avoiding command-line limits for long lyrics;
both payload and output are removed on abort or completion. The same verification,
source-conflict and optional-backup boundary applies to both tag writers.
Conversion progress follows
FFmpeg's progress stream (elapsed time, and percentage where duration is
known). Cancel terminates the owned process, escalating to kill after two seconds.
The window stays open until cancellation finishes. Probes/cover reads stop
before a job or on close. Diagnostics stay in the dialog; there is no background
service. Tag round-trip verification has a bounded synchronous probe after each
completed edit; it never performs file copying or conversion on the UI thread.

## Lyrics

`audio_lyrics.py` is shared with the Music space, which imports it from
`/usr/local/lib/audio-tools`. Both read
`$XDG_CONFIG_HOME/audio-tools/lyrics.json` on each provider lookup. The file is
private and declared in this module's `extra.private.files`; it is preserved by
the standalone backup/restore workflow. A missing file uses LRCLIB, and invalid
settings are reported without replacing them.

The schema is `{"version":1,"providers":[...]}` with up to eight providers.
An empty list disables online lookup. Each provider supports `name`, `base_url`
(LRCLIB-compatible `/get` endpoint), optional `headers`, `api_key`,
`api_key_header` (default `Authorization`), and `api_key_prefix` (default
`Bearer `). The built-in base URL is `https://lrclib.net/api`. Lookups send title,
artist, optional album and duration in seconds. Plain lyrics take precedence;
synced lyrics have timestamps removed. Requests have a 16-second timeout, a
1 MiB response limit and a 200,000-character lyrics limit. Provider failures
permit trying the next provider. HTTP 429 applies a per-process host cooldown;
redirects across origins are rejected so credentials stay with their provider.

Audio tools runs the helper in an owned QProcess. JSON input carries song
metadata; credentials are read in the helper, never placed in process arguments.
Fetch and Cancel fetch share a button beside the Lyrics heading. Success updates
only the draft; Save tags uses the existing atomic remux. Replacing nonempty
lyrics requires the dialog's confirmation. Editing song identity or lyrics,
discarding drafts, starting a file job, or closing cancels the lookup. Completion
also checks the original song details and lyrics before applying a response.
MP3's language-qualified ID3 lyrics are normalized for display and verification.

## Validation

`python3 -m unittest tests.test_audio_tools tests.test_audio_tools_gui tests.test_audio_lyrics` uses
throwaway fixtures: all seven presets, Unicode and cleared tags, covers,
unchanged audio, backups, source changes, output races, job errors/cancellation
and the real offscreen dialog. Native application queries verify audio MIME registration.
Lyrics fixtures check shared settings, authenticated requests, cancellation,
stale drafts, MP3/FLAC saving, provider failures and private backup/restore.
`python3 -m unittest tests.test_media_tools_gui` verifies single-file registration,
picker cancellation and native dark/light palette changes in both dialogs. The
live theme test uses an isolated D-Bus session and temporary XDG directories.
