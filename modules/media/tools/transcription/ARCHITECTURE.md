# Media transcription client

`/usr/local/lib/desktop-speech/speech_gui.py` supplies `TranscriptionPanel` to the
Audio/Video tools. It uses `QLocalSocket` against the socket-activated
`desktop-capture/control.sock`, connecting when the tab is first shown. The module
owns PySide6; the Quickshell module owns the speech service and inference tools.
A missing service produces an inline connection error and retries on tab reopen.
The advertised `fileOutputs` capability gates starts so an older still-running
owner cannot silently interpret SRT requests as clipboard imports.

The panel has model and spoken-language choices plus a video-only output choice
(Plain text, copied to the clipboard, or Subtitles, saved as SRT). Audio always
uses plain text copied to the clipboard. It starts from Capture preferences,
filters the engine's complete language catalogue to the selected model, and
passes per-job overrides without changing microphone preferences. Missing
checkpoints download as part of the file job. Controls inherit the application's
native Qt palette and style.
Progress is indeterminate for decoding/inference and uses actual download progress
when available. Status is local to the tab; no transcript content crosses the
control socket.

Each start has a fresh identifier. Ordered command replies distinguish refusal
from accepted work, and cancellation includes the current identifier. Reopening
an active file reattaches by canonical source path. Closing or losing the socket
does not cancel service-owned work; the parent dialog disables its tab bar while
this panel is busy to prevent a simultaneous file edit/conversion.

The [speech owner architecture](../../../desktop/quickshell/ARCHITECTURE.md)
describes duration limits, model downloads, privacy and atomic SRT publication.
`tests/test_media_transcription.py` uses fake owners with private sockets and real
offscreen Qt/QML clients to check output choices, frozen options, cancellation,
reattachment and library navigation. `tests/test_dictation.py` covers the worker
with fake FFmpeg/Whisper executables, including long files, missing models,
empty speech, source changes, collisions and stale cancellation.
