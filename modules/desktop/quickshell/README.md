# Desktop shell

## Shortcuts

| Shortcut                   | Action                                              |
| -------------------------- | --------------------------------------------------- |
| Win+R                      | Open / close application search.                    |
| Ctrl+1                     | Open / close Spaces.                                |
| Ctrl+Shift+P               | Open / close Performance, including over fullscreen apps. |
| Ctrl+D (in search)         | Toggle the selected app's favorite.                 |
| Ctrl+Win+Up / Down         | Go to the workspace above / below.                  |
| Ctrl+Win+Shift+Up / Down   | Move the active window above / below and follow it. |
| Win+Arrow                  | Focus the window in that direction.                 |
| Win+Shift+Left / Right     | Move the active column left / right.                |
| Win+J                      | Give a stacked window its own column.               |
| Win+[ / Win+]              | Make the active column narrower / wider.            |
| Win+.                      | Center the active column.                           |
| Win+mouse wheel            | Scroll through columns.                             |
| Win+M                      | Toggle maximization.                                |
| Win+V                      | Toggle floating.                                    |
| Win+left-drag / right-drag | Move / resize a window.                             |
| Win+Q / Alt+F4             | Close the active window.                            |

Escape or clicking outside closes search/drawers. Opening another replaces the
current one. Scroll over the bar islands to reach buttons on narrow displays.

Workspace navigation stays on the current display without wrapping. A populated
workspace can create a new neighbor; empty workspaces disappear when left.
Three-finger vertical swipes switch workspaces; horizontal swipes scroll columns.
Notification indicators are currently samples.

## Battery and performance

Battery shows system and device batteries, with charge-limit control on supported
hardware. **Charge to 100% once** restores the previous limit after unplugging;
**Restore charge limit** ends it early. Changing the limit manually cancels it.
One-time charging needs the shell running; pending restorations recover at startup.
An unplug/replug cycle while the shell is stopped cannot be detected.

Performance offers power modes, resource readings, btop access and workload
recording. On Zephyrus, plugging in selects Balanced and unplugging selects
Powersave; Performance stays selected. See the
[mode comparison](../../hardware/power/README.md) for CPU, cooling and playback behavior.
Detailed readings refresh while the drawers are open; sleeping GPUs stay asleep.

**Record performance** observes the current workload until you stop it and saves
readings and a summary. It requires `power-study`, continues with the drawer
closed, and stops on shell exit or reload.
See [power implementation notes](ARCHITECTURE.md#battery-and-performance).

## Networking

Wi-Fi, VPN and Cloudflare WARP controls, with transfer rates and an internet
speed test that follows the current route, including VPNs.

**Ports** opens TCP/IPv4 ports to devices on the connected local network. Use
the × to close one; there is no time limit. Openings clear on disconnect,
network changes, reboot or UFW reload. Closing removes the temporary allowance; existing
connections may continue.

The header info button shows connection details with copy actions for addresses
and interface names. The public IPv4 address follows the current route, including
VPN/WARP, and is fetched only when information opens, with a ten-minute cache.

## Audio

Sound and Microphone drawers provide device and per-application audio controls,
routing, playback controls, speaker/microphone tests and optional volume boost.
Custom device names and volume limits are described under
[audio configuration](ARCHITECTURE.md#audio-configuration).

## Bluetooth

Connect paired devices or search nearby devices to pair, with passkey prompts
and reported battery levels. Pairing and Connect also authorize that device's
future reconnections. Searching stops after 30 seconds or when the drawer
closes. Closing also cancels unfinished pairing. Hold the trash icon to forget a device.
The bar shows whether Bluetooth is on and lists connected devices on hover.
The header info button shows adapter details with copy actions; the pencil opens
Blueman for advanced Bluetooth settings.

## Time and weather

Choose a saved place for its local time, current weather, hourly rain chances and
five-day forecast. Selection leaves the system island unchanged. Temperatures
are in °C. The island icon and tooltip refresh weather every 30 minutes, even
with the drawer closed. The drawer shares that cache and refreshes a selected
place when its data is older than 30 minutes. The refresh button updates it
immediately. Each place in the picker shows its local time. Cached forecasts
remain visible offline with their last update time. Short daily outlooks appear
under current conditions and in forecast-row tooltips.

The pin action sets the selected place as current and applies its system timezone
without a password once the desktop timezone permission rule is installed. Clocks
and dates then use that timezone, including daylight saving changes. Browsing
other places leaves system settings alone.
Only that place refreshes in the background; other places fetch while selected
and their cache is older than 30 minutes.

Places live in `~/.config/quickshell/desktop/weather.json`, outside the dotfiles.
See [weather configuration](ARCHITECTURE.md#clock-and-weather) for the file format.

Add a one-shot alarm with a message, or a repeating focus/break reminder (25/5
minutes by default). Alarms use system-local time. Reminders keep running with
the drawer closed and clear when the shell exits or reloads. They send desktop
notifications; they do not wake a sleeping computer.

## Keyboard

English, Български (phonetic) and Tiếng Việt (Telex), with the active language
shown in the settings island. Alt+Shift switches between English and the
checkmarked secondary language. The help button has Telex, Bulgarian phonetic
and desktop shortcut references; the typing field clears when the drawer closes.
The pencil opens Fcitx input-method settings.
Keyboard cards provide brightness and supported lighting settings in a cog menu.
RGB keyboards offer color presets and supported effects. The lowest brightness
step is off; keyboard input stays enabled.

Lighting support comes from the selected hardware modules. See the
[Logitech module](../../hardware/peripherals/logitech/README.md) for MX Keys Mini
backlighting behavior.

See [input language integration](ARCHITECTURE.md#keyboard) for technical details.

## Displays

Per-display controls for refresh rate, mirroring and hardware brightness.
Each display's cog offers **Use recommended resolution** to apply and save its
preferred resolution and refresh rate.
The header edit button opens wdisplays for arrangement, resolution, scale and rotation.
Settings apply immediately, and the cog menu closes after each selection.
Identify displays labels the connected screens. Each cog also offers test patterns
and a motion test. In fullscreen tests, Space/arrow keys cycle patterns, H hides
controls, and Escape or a click exits. Mirrored outputs share their source’s image.
External brightness needs DDC/CI support and the monitor's DDC/CI setting enabled.

Dark mode switches the shell's appearance between light and dark.
Night light starts/stops hyprsunset for all active displays. Configure warmth
and optional timing in `~/.config/hypr/hyprsunset.conf`; restart
`hyprsunset.service` after editing it while active.

Keep awake in a display's cog prevents that monitor from blanking and pauses
automatic locking/suspend while it stays connected. Its bar's monitor icon turns
red. Checkmarks reset when the shell exits or reloads.

Display settings are saved automatically in
`~/.config/quickshell/desktop/displays.json` and restored after login, reconnect
and Hyprland config reload. This user-owned file is separate from the dotfiles.
Changes made in wdisplays are saved when display-change notifications settle.
Unplugging the last external display temporarily re-enables the built-in panel;
your dock-only preference returns on reconnect. Stranded workspaces and off-screen
floating windows are recovered onto an available display.
Brightness retention depends on the hardware; the drawer does not restore it.
The Night light toggle is remembered across logins.
See [display implementation notes](ARCHITECTURE.md#displays).

## Disks

Storage capacity and free space by drive, with file-manager access to mounted
locations, encrypted-volume unlock and mount/unmount. Unmounted devices remain
available to mount again. System volumes stay mounted.

The header scan button opens Filelight; the pencil opens KDE Partition Manager
for partitioning and filesystem operations. Drive health
checks run on request where supported; sleeping ATA drives stay asleep.

**Clean system** offers recoverable package, browser and developer caches, unused
Podman images and Flatpak runtimes, and optional mise tool removal. Select categories
and hold to confirm. System package cleanup may ask for administrator authentication.
See [cleanup implementation notes](ARCHITECTURE.md#system-cleanup).

## Service

Show or hide the shell with
`systemctl --user start desktop-shell.service` or
`systemctl --user stop desktop-shell.service`.
Stopping/restarting may also close applications launched by the shell.

```sh
systemctl --user status desktop-shell.service
journalctl --user -b -u desktop-shell.service -n 50
```

See [implementation notes](ARCHITECTURE.md) for development and troubleshooting.
