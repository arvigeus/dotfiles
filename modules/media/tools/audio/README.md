# Audio tools

**Open with → Audio tools** opens an audio file in a desktop dialog for:

- Tags, lyrics and cover art.
- Conversion with progress, cancellation and optional loudness normalization.
- Audio stream details, the complete tag list and same-folder file renaming.

**Fetch lyrics** fills the lyrics draft; **Save tags** writes it to the file.
Lyrics providers share `~/.config/audio-tools/lyrics.json` with the Music space
(LRCLIB by default).

Seven presets cover AAC/M4A 320 kbps, MP3 192/320, FLAC, Opus 192, Vorbis quality
6 and WAV PCM 16-bit. Presets live in `~/.config/audio-tools/presets.json`.
The managed copy is [presets.json](files/home/.config/audio-tools/presets.json).

Conversions keep the sources and never replace existing outputs. Unsaved tag
edits must be saved or discarded before conversion. Tags save without audio
re-encoding, optionally keeping `filename.tags-backup`. Backups are off by default.
Only edited fields change; an empty edited field removes that tag. Cover editing
supports MP3, FLAC and M4A.
File renaming keeps the current extension and never replaces an existing file.
Unsupported tag edits fail without replacing the source. Hard-linked files must
be copied before tag editing.

You can also launch **Audio tools** from the application menu or run
`audio-tools FILE`. See [ARCHITECTURE.md](ARCHITECTURE.md) for the preset schema
and format handling.
