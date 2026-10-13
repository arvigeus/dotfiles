# Desktop bar

## Window and workspace shortcuts

| Shortcut                    | Action                                             |
| --------------------------- | -------------------------------------------------- |
| Win+1–9 / Win+0             | Switch to workspace 1–9 / 10; create it if needed. |
| Win+Shift+1–9 / Win+Shift+0 | Move the active window to workspace 1–9 / 10.      |
| Win+Arrow                   | Focus the window in that direction.                |
| Win+Shift+Left / Right      | Move the active column left / right.               |
| Win+J                       | Give a stacked window its own column.              |
| Win+[ / Win+]               | Make the active column narrower / wider.           |
| Win+.                       | Center the active column.                          |
| Win+mouse wheel             | Scroll through columns.                            |
| Win+M                       | Toggle maximization.                               |
| Win+V                       | Toggle floating.                                   |
| Win+left-drag / right-drag  | Move / resize a window.                            |
| Win+Q / Alt+F4              | Close the active window.                           |

## Hide or show the bar

To hide it and give windows the extra space:

```sh
systemctl --user stop desktop-shell.service
```

To show it again:

```sh
systemctl --user start desktop-shell.service
```

## Troubleshooting

If the bar is missing, unresponsive, or shows windows in the wrong order, restart
it from a terminal in your desktop session:

```sh
systemctl --user restart desktop-shell.service
```

If the problem persists, check its status and recent messages:

```sh
systemctl --user status desktop-shell.service
journalctl --user -b -u desktop-shell.service -n 50
```

Include those messages and the action that caused the problem when reporting it.
