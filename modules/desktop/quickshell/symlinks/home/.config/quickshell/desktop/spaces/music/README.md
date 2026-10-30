# Music

**My Library** opens all your Nextcloud songs alongside audio found in `~/Music`.
Search filters songs; the filter button reveals Genres, Artists, Albums and
Playlists with searchable lists. Artist
pages include a picture, biography, albums and a playable song collection.

Playback prefers cached files. New local songs appear automatically with an upload
indicator; **Not uploaded** shows just those songs. **Info** opens read-only metadata
without downloading the song. **Fetch lyrics** loads lyrics on request.
Lyrics providers share `~/.config/audio-tools/lyrics.json` with Audio tools.
**Edit metadata** prepares a local copy and enables tag editing and the cover's
pencil button. **Save** writes the local file and uploads it; cover editing supports
MP3, FLAC and M4A. Failed uploads keep local edits for an explicit retry.

The path and **Move** action at the bottom are separate from metadata editing.
Moves preserve the audio extension and do not download uncached songs.
The notifications bell holds transfer progress and controls.

**Discover** browses your configured Apple Music playlist and searches its
catalogue. Artist and album pickers search online as you type. Downloads save
tagged FLAC files named `Title - Artist - Album (YYYY-MM-DD).flac` in `~/Music`,
ready to review and upload. FLAC preserves the source's decoded audio; it does not
improve a lossy source.

My Library uses the shared Nextcloud account, Music API key and rclone remote.
Discover needs `music.json` with a catalogue token; full-track playback and downloads
also require a configured provider. An Apple Music subscription alone does not
configure that provider.

Music never evicts cached songs or propagates filesystem deletions. Server errors
keep local edits; overwritten server versions are retained in `Music-history`.
Playback and transfers continue while hidden; closing the Space stops owned work.
See [ARCHITECTURE.md](ARCHITECTURE.md) for configuration and implementation details.
