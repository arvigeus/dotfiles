# Desktop shell

## Shortcuts

| Shortcut                   | Action                                              |
| -------------------------- | --------------------------------------------------- |
| Win+R                      | Open / close application search.                    |
| Ctrl+1                     | Open / close Spaces.                                |
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
Weather, language, battery and notification indicators are currently samples.

## Networking

Wi-Fi, VPN and Cloudflare WARP controls, with transfer rates and an internet
speed test that follows the current route, including VPNs.

## Audio

Sound and Microphone drawers provide device and per-application audio controls,
routing, playback controls, speaker/microphone tests and optional volume boost.
Custom device names and volume limits are described under
[audio configuration](ARCHITECTURE.md#audio-configuration).

## Displays

Per-display controls for refresh rate, mirroring and hardware brightness.
The header edit button opens wdisplays for arrangement, resolution, scale and rotation.
Settings apply immediately, and the cog menu closes after each selection.
Identify displays labels the connected screens. Each cog also offers test patterns
and a motion test. In fullscreen tests, Space/arrow keys cycle patterns, H hides
controls, and Escape or a click exits. Mirrored outputs share their source’s image.
External brightness needs DDC/CI support and the monitor's DDC/CI setting enabled.

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
Brightness retention depends on the hardware; the drawer does not restore it.
The Night light toggle is remembered across logins.
See [display implementation notes](ARCHITECTURE.md#displays).

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
