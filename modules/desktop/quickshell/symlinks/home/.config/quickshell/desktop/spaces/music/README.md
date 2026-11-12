# Music

**My Library** opens all your Nextcloud songs alongside audio found in `~/Music`.
Search filters songs; the filter button reveals Genres, Artists, Albums and
Playlists with searchable lists. Artist
pages include a picture, biography, albums and a playable song collection.

Playback prefers cached files. New local songs appear automatically with an upload
indicator; **Not uploaded** shows just those songs. **Info** reuses available metadata
and reads missing tags, embedded lyrics and format details in the background through
WebDAV, without caching the song. **Edit metadata** enables editing immediately;
background values never replace your edits. **Fetch lyrics** explicitly looks for
lyrics and opens an editable draft, ready to save. Lyrics providers share
`~/.config/audio-tools/lyrics.json` with Audio tools.
**Save** downloads the song into `~/Music` if needed, applies your changes and uploads it; cover
editing supports MP3, FLAC and M4A and keeps the song's other tags. Failed uploads keep local edits for an explicit
retry. An unavailable field stays marked as not loaded; typing replaces its value,
and its clear button explicitly removes it.

The path and **Move** action at the bottom are separate from metadata editing.
Moves preserve the audio extension and do not download uncached songs.
The notifications bell holds transfer progress and controls.

**Browse** opens your configured Apple Music playlist and searches its
catalogue. Artist and album pickers search online as you type. Downloads save
tagged FLAC files named `Title - Artist - Album (YYYY-MM-DD).flac` in `~/Music`,
ready to review and upload. FLAC preserves the source's decoded audio; it does not
improve a lossy source. Downloads try configured sources in order when a source
cannot match or save a song; songs already saved are reused.

My Library uses the shared Nextcloud account, Music API key and rclone remote.
Browse needs `music.json` with a catalogue token; full-track playback and downloads
also require a configured provider. An Apple Music subscription alone does not
configure that provider.

Music never evicts cached songs or propagates filesystem deletions. Server errors
keep local edits; overwritten server versions are retained in `Music-history`.
Playback and transfers continue while hidden; closing the Space stops owned work.
See [ARCHITECTURE.md](ARCHITECTURE.md) for configuration and implementation details.
