# Quickshell

The desktop shell starts with the UWSM-managed Hyprland session and stops on logout. A failed
process restarts automatically. A passive top bar appears on each connected display.
It reserves 44 logical pixels for tiled windows and shows a small Desktop pill.
Fullscreen applications cover it; it accepts no keyboard or pointer input.

Bar geometry lives in `symlinks/home/.config/quickshell/desktop/bar/Bar.qml`, with
shared dimensions in `ui/Theme.qml`. Quickshell owns one bar per screen and removes
it when that screen disappears. Stopping the shell removes the bars and releases
their reserved space; starting it restores them.

Edit `symlinks/home/.config/quickshell/desktop/shell.qml` in this module.
The installed entry point links to the checkout, and Quickshell reloads QML
changes automatically. If a reload fails, inspect the journal for the file and
line; fix the source and save it again.

To check the process and its logs:

```sh
systemctl --user status desktop-shell.service
journalctl --user -b -u desktop-shell.service
```

To restart or temporarily stop the shell:

```sh
systemctl --user restart desktop-shell.service
systemctl --user stop desktop-shell.service
```

Start it again with `systemctl --user start desktop-shell.service` from the
running desktop session. Use the service for normal startup; running the same
configuration with `qs --no-duplicate` exits if an instance already exists.

If startup reports a dependency failure, check
`systemctl --user status graphical-session.target`. The service requires a
UWSM-managed session; a direct Hyprland login may leave this target inactive.

After editing the service asset, apply the configuration, then run
`systemctl --user daemon-reload` and restart the shell to use it immediately.

Shared colors, fonts, spacing, and geometry live in
`symlinks/home/.config/quickshell/desktop/ui/Theme.qml`. Components in `ui/` supply
plain text, bordered surfaces, Lucide interface icons, and system application
icons. Dimensions use logical pixels; Qt handles each display's scale.

The selected mode lives in the regular local file
`${XDG_CONFIG_HOME:-$HOME/.config}/quickshell/desktop/theme-mode`, containing
`dark` or `light`. The shell reads it at startup. Shell controls call
`Theme.setMode()` to save the choice and reload it after a successful write; the
preview uses Ctrl+T to switch it. Restart the shell to pick up external edits or
changes made by another instance. Palettes and components remain linked to the
checkout.
Missing or unrecognized mode content uses dark colors. Apply currently replaces
this local file with the repository default.

Open the style preview with:

```sh
qs --no-duplicate --path "${XDG_CONFIG_HOME:-$HOME/.config}/quickshell/desktop/preview.qml"
```

It runs independently of the desktop service. If Hyprland tiles it, use Super+V
to float it and Super+left-drag to move it. Interface icons are bundled under
`icons/`, with their upstream license and source reference.
