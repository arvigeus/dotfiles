# Streaming

YouTube search, followed channels, creator posts and offline downloads in
the Spaces drawer. Videos open in your native mpv player, with its usual captions,
speed, quality controls and playback resume. Switch between Movies-style rail and grid
views. Overview, Summary, Chapters and
Downloads have separate detail tabs. Follow a channel URL or `@handle` to build
your Discover feed; use the toolbar search to find YouTube videos or open a video URL.

Members-only uploads are hidden. **Posts** combines your followed creators' public
updates, images, polls and shared videos. Videos and Posts load continuously as
you scroll. Voting and comments open on YouTube.
The subscription action switches to **Unsubscribe** for followed creators.
**Open on YouTube** uses your browser when a video requires sign-in.

**Summarize video** and **Ask Gemini** analyze the actual public video on request.
Answers are cached. These actions send the video URL and your question to Gemini;
API quotas apply. The key lives in
`~/.config/quickshell/desktop/integrations/gemini-api-key` and is included in
`backup.sh`.

**Download video** saves to `~/Videos/Streaming`. **Download audio** keeps the best
available Opus or AAC audio without re-encoding, with tags and cover art in
`~/Music`. Files use `.opus` or `.m4a` for Nextcloud Music compatibility and appear
in Music’s My Library for metadata review and explicit upload.

Playback, downloads and analysis continue while hidden. The bell shows progress
and cancellation; closing Streaming stops its owned work. Completed files stay.
Settings, download associations, answers and resume positions are backed up; downloaded
media needs your separate media backup. Keep yt-dlp current if YouTube stops
working. See [ARCHITECTURE.md](ARCHITECTURE.md) for configuration and internals.
