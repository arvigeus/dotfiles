# Hyprland

This module configures the desktop and its session. Edit the Lua files under
`symlinks/home/.config/hypr/`, then reload:

```sh
hyprctl reload config-only
```

Run `hyprctl configerrors` if a change does not work as expected.

## File dialogs and screen sharing

Desktop portals let applications open file dialogs and request screen sharing.
This setup uses GTK for file dialogs and Hyprland for screenshots and sharing.

If a file dialog hangs or screen sharing fails, check the portal logs:

```sh
journalctl --user -b -u xdg-desktop-portal.service -u xdg-desktop-portal-hyprland.service -u xdg-desktop-portal-gtk.service
```
