# Audio tools

**Open with → Audio tools** opens selected audio files in a desktop dialog for:

- Tags, lyrics and cover art, including applying edited fields to several files.
- Batch conversion with progress, cancellation and optional loudness normalization.
- Audio stream details and the complete tag list.

Seven presets cover AAC/M4A 320 kbps, MP3 192/320, FLAC, Opus 192, Vorbis quality
6 and WAV PCM 16-bit. Presets live in `~/.config/audio-tools/presets.json`.
The managed copy is [presets.json](files/home/.config/audio-tools/presets.json).

Conversions keep the sources and never replace existing outputs. Unsaved tag
edits must be saved or discarded before conversion. Tags save without audio
re-encoding, keeping `filename.tags-backup` by default. Only edited fields change;
an empty edited field removes that tag. Cover editing supports MP3, FLAC and M4A.
Unsupported tag edits fail without replacing the source. Hard-linked files must
be copied before tag editing.

You can also launch **Audio tools** from the application menu or run
`audio-tools FILE…`. See [ARCHITECTURE.md](ARCHITECTURE.md) for the preset schema
and format handling.
