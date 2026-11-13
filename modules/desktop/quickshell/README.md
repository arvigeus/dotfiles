# Desktop shell

A Quickshell bar and drawers for apps, workspaces, devices, capture, calendar,
notifications and system maintenance. **Win+R** opens application search;
**Win+1 / Shift+Tab** opens Spaces; **Ctrl+Shift+Tab** opens Performance.
In application search, **Ctrl+D** favorites the selected app.
See [Hyprland](../hyprland/README.md) for window, session and capture shortcuts.

## Spaces

Fullscreen destinations retain their state while hidden; close a running entry
from Spaces to release it.

- [Movies](symlinks/home/.config/quickshell/desktop/spaces/movies/README.md)
  and [TV Series](symlinks/home/.config/quickshell/desktop/spaces/series/README.md):
  discovery, local libraries, subtitles and downloads.
- [Games](symlinks/home/.config/quickshell/desktop/spaces/games/README.md):
  Steam/Epic/GOG libraries, discovery and compatibility information.
- [Books](symlinks/home/.config/quickshell/desktop/spaces/books/README.md)
  and [Pictures](symlinks/home/.config/quickshell/desktop/spaces/pictures/README.md):
  ebook libraries and desktop wallpapers.
- [Music](symlinks/home/.config/quickshell/desktop/spaces/music/README.md),
  [Radio](symlinks/home/.config/quickshell/desktop/spaces/radio/README.md),
  [Television](symlinks/home/.config/quickshell/desktop/spaces/television/README.md)
  and [Streaming](symlinks/home/.config/quickshell/desktop/spaces/streaming/README.md):
  local/cloud music, stations, IPTV and YouTube.

**Restart → Reload** closes applications and starts a fresh desktop session.
Shutdown timers continue with the drawer closed. Temporary sleep/locking pauses
end on shell reload; manual lock and suspend remain available.

## Capture

Screenshots save to Pictures/Screenshots and copy to the clipboard. Capture's
editor/save preferences also apply to shortcuts; clipboard-only mode creates no
file or notification. Reopen Capture during a countdown to cancel it.
Screen recording saves H.264/AAC MP4 to Videos/Recordings, survives shell reloads
and finalizes at session end.

**Win+Shift+D** starts/finishes the selected speech action. Transcription runs
locally with Whisper; download a model once for offline use. Setup downloads the
model without recording. Dictation is limited to two minutes; saved WAV audio to
30 minutes, under Music/Recordings. Audio/Video tools also transcribe files or
create subtitles for media up to six hours. Results arrive as notifications.
Auto-paste skips insertion if focus changed or a shell surface is open. Temporary
microphone unmuting restores the original mute when recording stops.

Clipboard history retains 50 local items. Pause before copying sensitive data;
pause survives shell reloads until the next login and leaves existing history.

## Assistant

Assistant uses local Lemonade models and starts the server on demand for sending,
model selection or opening its app. Closing the drawer keeps replies/downloads
running; a reply that finishes meanwhile sends a notification. Chats and drafts
last until New chat or shell restart; preferences persist. Replies never load
remote content: images appear as links and HTML as text. Copy gives the original
Markdown. Native aliases can be created with `lemonade alias add NAME MODEL_ID`.
Model search includes Hugging Face and ModelScope catalogs through Lemonade;
enter at least three characters, then choose a repository and quantization to download.
Tool-capable models can inspect local files and system state. Shell commands and
file writes require approval in the conversation. Models without tool calling
continue as ordinary chat models. An API key in `~/.config/lemonade/lemond.conf`
is used automatically. Commands run noninteractively with a 30-second limit;
password prompts are unsupported. File replacement refuses symlinks.

Attach images, text/code, PDF, DOCX or ODT through the paperclip, paste or drop.
Limits are six files/message, 16 MB/file and 64,000 extracted characters/document.
Images require a vision model; scanned PDFs need OCR or page images.
Dolphin's **Share → Add to Assistant** accumulates frozen file snapshots in the
draft without opening the drawer or sending. Restart Dolphin after installation
if the Share action is missing. See [service details](ARCHITECTURE.md#assistant).

## Devices and networking

Audio boost is remembered per device; hardware names/ceilings use
[audio drop-ins](ARCHITECTURE.md#audio-configuration). Bluetooth Connect authorizes
future reconnections; dismissal cancels unfinished pairing.
**Charge to 100% once** restores the previous limit after unplugging. It requires
the shell running; an unplug/replug while stopped cannot be detected. See
[power modes](../../hardware/power/README.md).

Wi-Fi enterprise/WEP setup uses the connection editor. Devices discovery checks
up to 256 private IPv4 addresses; sleeping/firewalled devices may not answer.
Ports opens TCP/IPv4 access from the current subnet until firewalld reload/reboot;
closing a rule may leave established connections alive. See
[firewall access](../../system/security/firewall/README.md).

Each connected monitor combination remembers its own layout, including disabled
displays. Undocking keeps the panel usable. Brightness is independent; Powersave
caps the panel to 60 Hz until an explicit refresh change or another mode change.
`display-tools` edits arrangement; hold Shift while dragging to bypass snapping.
Night light uses `~/.config/hypr/hyprsunset.conf`; restart `hyprsunset.service`
after editing. Keep awake is temporary and also pauses automatic lock/suspend.

## Calendar and notifications

Weather places use `~/.config/quickshell/desktop/weather.json`; see the
[format](ARCHITECTURE.md#time-and-weather). Pinning changes the system timezone;
browsing does not. Alarms/reminders survive shell reloads until logout, keep their
local clock time across timezone changes and cannot wake a sleeping computer.
Alarms bypass Do Not Disturb; focus/break prompts follow it.

Events/tasks use Nextcloud with offline cached reads; writes require a connection.
The calendar badge counts today's events. Opening the drawer clears the unread
highlight and keeps the count. With no events today, a neutral `!` marks an event
within seven days. Hover for the next event's title and date.
Recurring-event edits and individual task exceptions are read-only.
Configure `~/.config/quickshell/desktop/integrations/nextcloud.json` from the
[account example](symlinks/home/.config/quickshell/desktop/integrations/nextcloud.example.json).
Save the DAV app password in `integrations/nextcloud-app-password` with mode 0600
and keep the directory mode 0700. Optional
[calendar selections](symlinks/home/.config/quickshell/desktop/drawers/events/calendar.example.json)
choose names/slugs: omitted arrays include all, empty arrays none.
Tray attention requires an application attention signal or unseen notification;
legacy XEmbed icons are unsupported.

## Maintenance

System offers updates, service logs and package health/repair. Disks offers
mount/unlock, on-demand health, Filelight and selected cache cleanup. Unmounting
encrypted volumes locks them unless `/etc/crypttab` owns them. Drives are never
powered off; use the file manager for safe removal. Sleeping ATA drives stay asleep.

```sh
systemctl --user restart desktop-shell.service
journalctl --user -b -u desktop-shell.service -n 50
```

Launched applications survive shell restart. Steam/Wine desktop IDs containing
spaces, `+` or non-ASCII characters launch with a UWSM warning. See
[ARCHITECTURE.md](ARCHITECTURE.md) for implementation details.
