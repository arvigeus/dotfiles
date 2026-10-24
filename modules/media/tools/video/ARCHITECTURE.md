# Video tools

`video-tools` launches the PySide6 dialog in `/usr/local/lib/video-tools`.
The normal desktop entry registers video MIME types for Open with; defaults are
not changed. Each dialog handles one file, with `%f` desktop registration and an
optional single CLI path. Without a path, a single-file picker opens first;
cancelling exits. The dialog inherits the native Qt style and KDE palette,
including `desktop-theme` change notifications. FFmpeg/ffprobe stay owned by
`media/tools/ffmpeg`; PySide6 is declared here.

ffprobe supplies container, stream and chapter JSON. The dialog renders codec,
resolution, average frame rate, pixel format, color primaries/transfer/space,
bit depth when available, audio channel layout/sample rate, language, tags and
chapters. It rejects inputs without a non-cover video stream. Probes and
conversions use QProcess; no project/history/settings database is created.
Progress and cancellation live in Convert, with its options disabled during a
job. The shared footer starts blank and carries operation/error messages.

## Presets and output

`$XDG_CONFIG_HOME/video-tools/presets.json` has version 1 and a nonempty `presets`
list. Each object needs unique lowercase/hyphen `id`, `name`, `extension` and
`mode` (`encode`, `copy` or `audio`). Optional keys: `description`, `codec`
(libx264/libx265/libvpx-vp9/libsvtav1 for encoding), integer `quality`
(0–51 for H.264/HEVC, 0–63 for VP9/AV1), encoder `speed`,
`pixel_format` (yuv420p or yuv420p10le), `max_width`/`max_height` together (2–16384), `audio_codec` and `audio_bitrate`
(e.g. `192k`). Containers are MP4/MKV/WebM/M4A. Unknown/malformed keys are rejected.
Native encoder/container incompatibilities fail as FFmpeg errors. Applying
dotfiles replaces the managed preset file. Presets are read and validated at startup. No shell command strings or arbitrary FFmpeg arguments are loaded.

Encoding maps the first non-cover video and all audio, uses even dimensions,
and copies container tags/chapters. Pixel format defaults to yuv420p, or
yuv420p10le for AV1. Maximum dimensions downscale without
upscaling; VP9 uses CRF plus zero target bitrate, row threading and CPU-used 4.
SVT-AV1 uses the FFmpeg `libsvtav1` encoder already supplied by the shared FFmpeg
package, with CRF and integer speed presets 0–13 (higher is faster). Other encoder
speed settings remain strings such as `medium`. The managed AV1 presets use speed
6 and 10-bit pixels: CRF 32 at original resolution / Opus 160 kbps, or CRF 36
capped at 1080p / Opus 128 kbps. They encode on the CPU without requiring GPU
features. CRF is encoder-specific and cannot be compared numerically across
codecs; these are starting points, not fixed size/quality guarantees.
MP4/M4A use faststart. Subtitle streams are omitted from encode/audio modes.
Copy mode maps all streams with stream copy, including subtitles and attachments
supported by the destination. Audio mode transcodes only the first audio track.
HDR-to-SDR tone mapping is not implemented; use a suitable dedicated workflow
when color conversion requires it.

Outputs are `stem [id].extension`, beside the source or in an existing chosen
folder. FFmpeg writes private temporary files on that filesystem. Publication
uses an atomic hard link, refusing collisions even if a destination appears
during encoding. Sources are never modified. Errors and cancellation remove
partial files. Cancellation sends terminate and then kills the owned process
after two seconds if necessary.
Escape/close also use that path, keeping the dialog open until it finishes.

`tests/test_video_tools.py` exercises all seven presets (including actual 10-bit AV1 encoding) on generated video with
subtitles, audio, tags and chapters; no upscaling, source retention, publication
races and the actual offscreen dialog's conversion/cancellation.

`tests/test_media_tools_gui.py` also checks single-file launch behavior and native
dark/light palette changes in both media dialogs, using an isolated D-Bus session
and temporary XDG directories.
