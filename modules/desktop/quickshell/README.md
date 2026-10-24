# Desktop shell

A Quickshell bar and drawers for applications, workspaces, audio, networking,
displays, capture, clipboard history, calendar, notifications and system controls.

## Shortcuts

| Shortcut                 | Action                                       |
| ------------------------ | -------------------------------------------- |
| Win+R                    | Application search                           |
| Win+1 or Ctrl+Alt+Delete | Spaces and session actions                   |
| Win+Shift+P              | Performance, including over fullscreen apps  |
| Ctrl+D in search         | Favorite the selected app                    |
| Ctrl+Win+Up / Down       | Previous / next workspace on this display    |
| Ctrl+Win+Shift+Up / Down | Move the window to that workspace and follow |
| Win+Arrow                | Focus a window                               |
| Win+Shift+Left / Right   | Move a column                                |
| Win+J                    | Give a stacked window its own column         |
| Win+[ / Win+]            | Resize the current column                    |
| Win+.                    | Center the column                            |
| Win+mouse wheel          | Scroll columns                               |
| Win+M / Win+V            | Maximize / toggle floating                   |
| Win+Q or Alt+F4          | Close a window                               |

Workspace navigation stays on the current display without wrapping. Empty
workspaces disappear when left. Three-finger vertical swipes follow their natural
direction; horizontal swipes scroll columns. Amber tabs/arrows indicate windows
requesting attention. Apps must report urgency; unread browser tabs alone may not.

## Spaces and session controls

[Movies](symlinks/home/.config/quickshell/desktop/spaces/movies/README.md) offers fullscreen
discovery, favorites, playback links and a local library with subtitles and downloads.
[TV Series](symlinks/home/.config/quickshell/desktop/spaces/series/README.md) adds
season and episode browsing in the same cinematic style.

Hold session actions for two seconds. Shutdown timers continue with the drawer
closed. **Restart → Reload** closes applications and starts a fresh desktop.
Sleep/locking pauses clear on shell reload/exit; screen blanking and manual
lock/suspend remain available. See [desktop sessions](../hyprland/README.md).

## Capture and clipboard

Screenshots save under Pictures/Screenshots and copy to the clipboard. Capture's
editor/save preferences also apply to [screenshot shortcuts](../hyprland/README.md#screenshots-and-recording).
Clipboard-only capture creates no image file and skips the editor/notification.
Reopening Capture cancels its countdown.

Recording uses GPU Screen Recorder and saves H.264/AAC MP4 in Videos/Recordings.
It continues through shell reloads and saves when the graphical session ends.
Win+Shift+R selects an area when idle and stops an active recording. Webcam tests
stop on drawer dismissal; privacy controls depend on camera support.

Clipboard history is local and limited to 50 items. Pause collection before
copying sensitive data. Pausing survives shell reloads and resets at the next
login. It does not remove existing history.

## Audio, Bluetooth and power

Sound/Microphone include per-app controls and tests. Boost is remembered per
device. For names and ceilings, see [audio configuration](ARCHITECTURE.md#audio-configuration).
Bluetooth pairing and Connect authorize future reconnections. Closing the drawer
cancels unfinished pairing; searching ends after 30 seconds.

**Charge to 100% once** restores the previous limit after unplugging. It needs the
shell running; pending restoration recovers at startup, but an unplug/replug while
the shell is stopped cannot be detected. Manual limit changes cancel it.

On Zephyrus, plugging in selects Balanced and unplugging selects Powersave;
Performance stays selected. See the [mode comparison](../../hardware/power/README.md).
Performance recording observes your workload until stopped and ends on shell
exit/reload. Detailed readings do not wake sleeping GPUs.

## Networking

Wi-Fi, Ethernet, VPN and Cloudflare WARP controls share connection information and
an internet speed test following the current route. The public IPv4 lookup runs
only on opening information and caches for ten minutes. Enterprise/WEP networks
use the connection editor.

**Devices on this network** discovers reachable IPv4 devices on the connected
private network (up to 256 addresses). Hover for gateway/local-device labels and
response times when available. Sleeping or firewalled devices may not respond.

Ports opens TCP/IPv4 access from the current local subnet. Openings disappear on
firewalld reload/reboot. A changed address/subnet makes them inactive; they can
apply again if that network returns. Closing a rule may leave established
connections active. See [firewall access](../../system/security/firewall/README.md).

## Displays and keyboard

Display changes apply immediately and persist in `~/.config/hypr/displays.lua`.
Use **Save current layout** after arranging displays in wdisplays. Dock-only panel choices
return on redocking; undocking temporarily re-enables the panel when necessary.
Brightness is not restored from the layout. Powersave normally caps the internal
panel to 60 Hz; choosing another refresh overrides that until the next mode change.

Dark mode applies the [shared desktop appearance](../../look-and-feel/README.md).
Night light remembers its enabled state; edit
`~/.config/hypr/hyprsunset.conf` for warmth/times and restart `hyprsunset.service`.
Keep awake is temporary, per display, and pauses automatic locking/suspend too.

The keyboard offers English, Bulgarian phonetic and Vietnamese Telex. Alt+Shift
switches English and the selected secondary language. Lighting controls depend
on hardware; the lowest brightness is off. See [Logitech backlighting](../../hardware/peripherals/logitech/README.md).

## Time, calendar and notifications

Weather places live in `~/.config/quickshell/desktop/weather.json`; see the
[format](ARCHITECTURE.md#time-and-weather). Pinning changes the system timezone;
browsing another place leaves it unchanged. Forecasts refresh every 30 minutes
and remain visible offline. Alarms/reminders continue with the drawer closed,
clear on shell exit/reload and cannot wake a sleeping computer.

Events/tasks use Nextcloud and keep cached data available offline. Writes need a
connection; recurring event edits and individual task exceptions are read-only.
Configure `~/.config/quickshell/desktop/integrations/nextcloud.json` with the
[account example](symlinks/home/.config/quickshell/desktop/integrations/nextcloud.example.json).
Save a Nextcloud DAV app password in `integrations/nextcloud-app-password`, owned
by you with mode `0600`; keep the integrations directory private (`0700`).
Optional `calendar.json` [selections](symlinks/home/.config/quickshell/desktop/drawers/events/calendar.example.json)
choose collection names/slugs. Omitted arrays include all; empty arrays include none.

Notifications provide popups, history and Do Not Disturb. The tray highlights
reported attention or unseen desktop notifications; apps must expose one of these
signals for unread messages to be detectable. Legacy XEmbed tray icons are unsupported.

## System and storage

System combines updates, boot times, failed services/logs and timers. Package
health checks report missing files/dependency problems and can reinstall affected
repository packages with a full update. Signing repair reloads installed keyrings;
Update system obtains newer keyring packages.

Disks provides mount/unmount/unlock, on-demand drive health, Filelight and the
partition editor. System mounts stay mounted and sleeping ATA drives stay asleep.
Clean system offers selected caches, unused container/runtime resources and mise
tools. Package cleanup may request administrator authentication.

## Service

```sh
systemctl --user restart desktop-shell.service
journalctl --user -b -u desktop-shell.service -n 50
```

Applications launched from the shell run independently and survive its restart.
Temporary pauses, tests and reminders end on restart. See
[implementation and validation notes](ARCHITECTURE.md).
