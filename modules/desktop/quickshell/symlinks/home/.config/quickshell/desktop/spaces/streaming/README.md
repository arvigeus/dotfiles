# Streaming

YouTube search, followed channels, creator posts and offline downloads in
the Spaces drawer. Videos open in your native mpv player, with its usual captions,
speed, quality controls and playback resume. Follow a channel URL or `@handle`
to build your feed; search also accepts video URLs.

Members-only uploads are hidden. **Posts** combines your followed creators' public
updates, images, polls and shared videos. Voting and comments open on YouTube.
**Open on YouTube** uses your browser when a video requires sign-in.

**Summarize video** and **Ask Gemini** analyze the actual public video on request.
Answers are cached. These actions send the video URL and your question to Gemini;
API quotas apply. The key lives in
`~/.config/quickshell/desktop/integrations/gemini-api-key`.

**Download video** saves to `~/Videos/Streaming`. **Download audio** keeps the best
available Opus or AAC audio without re-encoding, with tags and cover art in
`~/Music`. Files use `.opus` or `.m4a` for Nextcloud Music compatibility and appear
in Music’s My Library for metadata review and explicit upload.

Playback, downloads and analysis continue while hidden. The bell shows progress
and cancellation; closing Streaming stops its owned work. Completed files stay.
Downloaded media needs a separate media backup. Keep yt-dlp current if YouTube stops
working. See [ARCHITECTURE.md](ARCHITECTURE.md) for configuration and internals.
