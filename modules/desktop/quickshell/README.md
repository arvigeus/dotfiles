# Desktop shell

A Quickshell bar and drawers for apps, workspaces, devices, capture, calendar,
notifications and system maintenance. **Win+R** opens application search;
**Win+1 / Shift+Tab** opens Spaces; **Ctrl+Shift+Tab** opens Performance.
In application search, **Ctrl+D** favorites the selected app.
The [Steam Controller](../../hardware/peripherals/steam-controller/README.md)
can browse Spaces and their controls without a mouse; hold **Y + stick left/right**
to move between catalogues, toolbars and detail actions.
Bumpers switch a Space's primary tabs; **Ctrl+PageUp / Ctrl+PageDown** does the
same from the keyboard. Changing tabs focuses the catalogue for arrow navigation.

Web links, including **Watch Online**, open in a separate fullscreen Chromium
window without tabs or an address bar. Its dedicated profile retains logins and
extension settings; Chromium's managed extensions include uBlock Origin Lite.
On first use, allow the extensions to install. Close its windows and run
`desktop-browser-kiosk --setup` to check or configure them.

Choose another browser in `~/.config/quickshell/desktop/browser.json`; for example,
`{"command": ["xdg-open"]}` uses the system browser. Individual features can
override it with `"modules": {"games": ["xdg-open"]}`. Changes apply to the next
link. See [browser configuration](ARCHITECTURE.md#browser-links) for details.

Use `/movie home`, `/series severance`, `/episode severance S01E02`,
`/music`, `/song`, `/album`, `/artist`, `/radio`, `/tv`, `/game` or `/youtube`
followed by search text to search Spaces. Type `/` to discover categories and
**Tab** to complete one. Local results appear first; cards open the matching Space,
and the play button or **Ctrl+Enter** starts playback where available.
Search uses each Space's providers and saved library; open Music or Television
first to build or refresh their library/directory snapshots.
Filters can replace title text, for example:

```text
/movie genre:sci-fi year:2000..2025 rating:7 sort:rating
/game genre:rpg platform:pc installed:true
/radio genre:jazz country:Vietnam bitrate:128
/tv category:news language:English
/song artist:"Daft Punk" duration:..5m
```

`local:true` restricts results to local files/installed games; `library:true`
includes owned games, saved music and favorites. `online:false` searches saved
metadata without contacting providers. Quotes group multiword filter values;
year/duration ranges can be open-ended, and durations accept `s`, `m` or `h`.
Movie/series genre discovery online requires a TMDB key.
See [Hyprland](../hyprland/README.md) for window, session and capture shortcuts.

## Spaces

Fullscreen destinations retain their state while hidden; close a running entry
from Spaces to release it.

- [Movies](symlinks/home/.config/quickshell/desktop/spaces/movies/README.md)
  and [TV Series](symlinks/home/.config/quickshell/desktop/spaces/series/README.md):
  discovery, local libraries, subtitles and downloads.
- [Games](symlinks/home/.config/quickshell/desktop/spaces/games/README.md):
  Steam/Epic/GOG/itch.io libraries, discovery, compatibility information and launch settings.
- [Books](symlinks/home/.config/quickshell/desktop/spaces/books/README.md)
  and [Pictures](symlinks/home/.config/quickshell/desktop/spaces/pictures/README.md):
  ebook libraries and desktop wallpapers.
- [Music](symlinks/home/.config/quickshell/desktop/spaces/music/README.md),
  [Radio](symlinks/home/.config/quickshell/desktop/spaces/radio/README.md),
  [Television](symlinks/home/.config/quickshell/desktop/spaces/television/README.md)
  and [Streaming](symlinks/home/.config/quickshell/desktop/spaces/streaming/README.md):
  local/cloud music, stations, IPTV and YouTube.

**Restart → Reload desktop** reloads Hyprland and Quickshell while keeping
applications open. Quickshell drawers and Spaces can reset. **Reload session**
closes applications and starts a fresh desktop session.
Shutdown timers continue with the drawer closed. Temporary sleep/locking pauses
end on shell reload; manual lock and suspend remain available. Closing the lid can
still suspend the computer, and the session locks before sleep.

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
The assistant options can select an installed llama.cpp inference backend; a new
choice takes effect on the next message and may reload the model.
Tool-capable models can inspect local files and system state, search Spaces, and
recommend items using genre, years, ratings and other filters. They can present
a chosen shortlist as cards with reasons, including in follow-up replies.
The Assistant and Pip can identify a song from a remembered line, find songs
about a topic, and read lyrics for a named song. They check indexed embedded and
saved Nextcloud lyrics first. Open Music to refresh its index. They can also
identify movies from plot descriptions and resolve research matches to Space results.
Ask which microphone is the default, whether it is muted, or to switch to a
named input. Microphone results can open the Microphone drawer for testing.
Assistant and Pip can start or stop the same countdowns and focus sessions,
find open windows, move a window to another monitor, and read today's agenda
or the laptop lid policy. “This window” means the window active when you
opened the assistant.
Web search uses DuckDuckGo; an optional SearXNG endpoint is described in
[research configuration](ARCHITECTURE.md#web-and-lyrics-research).
Ask for “my library only” to use your collection or “offline” to search saved
metadata. Playback starts when you choose a card's play action. Shell commands and
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

## Companion

**Pip** is an animated desktop companion that talks, helps and plays. Start it
from application search or with `desktop-companion`; starting it again says
goodbye. It never starts with the session.

Click to play (where you poke matters), drag to move, double-click to type and
press and hold to talk. **Win+Space**: tap to talk hands-free, or hold until
you finish speaking. Hands-free mode offers one brief follow-up and shows
when the microphone is open. **Send now** submits what it heard and **Stop**
discards the recording.
**Win+Shift+Space** opens the message box. Right-click for listening, reading
highlighted text aloud, looking at the screen, repeating the last message,
behaviours, timers, the last answer, memory and goodbye. Choose **Chat model**
to switch between your downloaded Lemonade models. Drop files on Pip to ask
about them. Clicking while it talks interrupts.

Right-click for **Microphone settings** if Pip can't hear you, or type
“Which microphone is active?” **Continue in Assistant** brings over the last
question, answer, and available desktop and search results.

**Playful** is the default. **Friend** is geared toward children, **Assistant**
keeps reactions minimal, and **Quiet** answers in text. Switch from the menu,
by asking, or with `desktop-companion assistant`.

Pip can open apps, play songs, radio, TV, YouTube, movies and episodes from your
Spaces (or open albums, series and games there), control music, change the
volume, switch windows, set timers, check the weather, read notifications or look
at the screen when asked, search the web, and remember things in
`~/.local/share/companion/memory.md`.
Assistant and Quiet can also inspect the system and read files; commands and file
writes run only after you click **Run it** or **Write it** on the exact
preview. Speech never approves anything.

Pip folds its leaves during a focus session and stretches at the break. Its
playful reactions pause during Do Not Disturb, microphone use by other apps, or
screen sharing. The **Timers** menu can start a 25-minute focus session, stop
running timers, or open the clock and timer controls.

Pip starts Lemonade when it opens and uses the Assistant's downloaded chat model
by default. Choose a model with tool calling for desktop actions and a vision
model for screen questions. `lemonade pull kokoro-v1` adds its voice and
`lemonade pull Whisper-Small` adds faster transcription. It can also transcribe
with the local dictation model. Kokoro does not speak Bulgarian.

`~/.config/quickshell/desktop/companion.json` also accepts `name`, `voice` (a
Kokoro voice such as `af_heart` or `af_sky`), `speed`, `model`, `transcriber`,
`language`, `speechModel`, `output` (pins a monitor), `follow: false` (stays on
one monitor) and `birthdays` (`["MM-DD"]`, for party hats). See
[companion details](ARCHITECTURE.md#companion).

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
./apply.sh --restart-shell
journalctl --user -b -u desktop-shell.service -n 50
```

Launched applications survive shell restart. Steam/Wine desktop IDs containing
spaces, `+` or non-ASCII characters launch with a UWSM warning. See
[ARCHITECTURE.md](ARCHITECTURE.md) for implementation details.
