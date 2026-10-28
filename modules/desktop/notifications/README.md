# Notifications

The desktop shell supplies themed notification popups and history. `libnotify`
provides `notify-send` for applications and scripts. D-Bus activation of
`org.freedesktop.Notifications` starts `desktop-shell.service`.

History, including message text, persists across restarts in the private file
`~/.local/state/quickshell/desktop/notifications.json` (up to 100 items).
Clearing the drawer empties it; transient notifications are never saved.

See the [notification architecture](../quickshell/symlinks/home/.config/quickshell/desktop/drawers/notifications/ARCHITECTURE.md)
for lifecycle and storage details.
