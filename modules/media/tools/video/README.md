# Video tools

Use **Open with → Video tools**, the application launcher, or `video-tools FILE…`.

The information view shows container details, resolution, frame rate, codecs,
color information, audio layouts, subtitles, chapters and tags. Information can
be copied.

Seven presets provide H.264 MP4, smaller MP4 up to 1080p, VP9 WebM up to 1080p,
two AV1/MKV options, MKV remuxing with all tracks, and AAC/M4A audio extraction.
Presets live in `~/.config/video-tools/presets.json`; persistent changes belong in the managed
[presets.json](files/home/.config/video-tools/presets.json).

For smaller files, try **MKV · AV1 · balanced** first. **AV1 · compact · up to
1080p** uses more aggressive compression and caps the resolution. AV1 uses slower
software encoding; output size depends on the source and quality settings. Both
presets use 10-bit video and Opus audio. Keep H.264 for older-device compatibility.

Conversions keep the source and never overwrite existing outputs. Encoding
presets use the first video and all audio tracks, omitting subtitles; MKV remuxing
copies all supported tracks. HDR tone mapping is not provided. Progress and
cancellation work across selected files.

See [ARCHITECTURE.md](ARCHITECTURE.md) for format handling and the preset schema.
