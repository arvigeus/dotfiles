# Notifications

The desktop shell supplies themed notification popups and history. `libnotify`
provides `notify-send` for applications and scripts. Dunst is removed during setup;
D-Bus activation of `org.freedesktop.Notifications` starts `desktop-shell.service`.

See the [notification architecture](../quickshell/symlinks/home/.config/quickshell/desktop/drawers/notifications/ARCHITECTURE.md)
for lifecycle and storage details.
