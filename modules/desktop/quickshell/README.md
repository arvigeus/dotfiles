# Quickshell

The desktop shell starts with the UWSM-managed Hyprland session and stops on logout. A failed
process restarts automatically. The initial entry point runs without visible UI.

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
