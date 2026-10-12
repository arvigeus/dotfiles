# Hyprland

This module configures the desktop and its session. Edit the Lua files under
`symlinks/home/.config/hypr/`, then reload:

```sh
hyprctl reload config-only
```

Run `hyprctl configerrors` if a change does not work as expected.

## Locking

Press **Win+L** to lock the desktop. Enter your login password to unlock it.

To change the lock screen's appearance, edit `~/.config/hypr/hyprlock.conf`.
Changes take effect the next time you lock.

If Win+L does nothing, check `systemctl --user status hypridle.service`.

## Idle and sleep

After 5 minutes without input, displays turn off; input turns them back on.
After 6 minutes, the desktop locks. After 30 minutes, the system suspends.
It also locks before suspend and turns displays back on when waking.
Applications can keep the desktop awake through idle or sleep inhibitors.

To adjust the timeouts, edit `~/.config/hypr/hypridle.conf`, then run:

```sh
systemctl --user restart hypridle.service
```

## File dialogs and screen sharing

Desktop portals let applications open file dialogs and request screen sharing.
This setup uses GTK for file dialogs and Hyprland for screenshots and sharing.

If a file dialog hangs or screen sharing fails, check the portal logs:

```sh
journalctl --user -b -u xdg-desktop-portal.service -u xdg-desktop-portal-hyprland.service -u xdg-desktop-portal-gtk.service
```
