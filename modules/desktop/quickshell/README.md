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

- Click the Wireless icon to toggle Wi-Fi; click a network/VPN to connect or
  disconnect. Hover for details. Passwords submit with Enter or the arrow button.
- The pencil beside Close opens NetworkManager for all connection types.
  Cloudflare's settings menu contains modes and registration.
- The speed-test button starts/cancels a test of the current internet route,
  including VPNs. The footer shows local transfer rates and adapter link speed.

## Service

QML edits reload automatically. Show or hide the shell with
`systemctl --user start desktop-shell.service` or
`systemctl --user stop desktop-shell.service`.
Stopping/restarting may also close applications launched by the shell.

```sh
systemctl --user status desktop-shell.service
journalctl --user -b -u desktop-shell.service -n 50
```

See [implementation notes](ARCHITECTURE.md) for development and troubleshooting.
