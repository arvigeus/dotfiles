# Hyprland

This module configures the desktop and its session. Edit the Lua files under
`symlinks/home/.config/hypr/`, then reload:

```sh
hyprctl reload config-only
```

Run `hyprctl configerrors` if a change does not work as expected.

## Locking

**Win+L** locks the desktop.

To change the lock screen's appearance, edit `~/.config/hypr/hyprlock.conf`.
Changes take effect the next time you lock.

If Win+L does nothing, check `systemctl --user status hypridle.service`.

## Idle and sleep

After 5 minutes without input, displays turn off.
After 6 minutes, the desktop locks. After 30 minutes, the system suspends.
It also locks before suspend and turns displays back on when waking.
Applications can keep the desktop awake through idle or sleep inhibitors.

To adjust the timeouts, edit `~/.config/hypr/hypridle.conf`, then run:

```sh
systemctl --user restart hypridle.service
```

The Display drawer offers Night light and Keep awake. If Night light is
unavailable, check `systemctl --user status hyprsunset.service`.
Edit `~/.config/hypr/hyprsunset.conf` to set its temperature or timed profiles.

## Screenshots and recording

| Shortcut             | Action                              |
| -------------------- | ----------------------------------- |
| Print or Win+Shift+S | Select an area and edit it in Ksnip |
| Win+Shift+Print      | Select an area without editing      |
| Win+Print            | Capture the focused window          |
| Win+Ctrl+Print       | Select a window to capture          |
| Shift+Print          | Capture the current display         |
| Win+Shift+R          | Open vokoscreenNG's recording controls |

Screenshots are saved under your Pictures directory in `Screenshots` and copied
to the clipboard before the editor opens. While selecting an area, hold Space
to move the rectangle; release Space to resize it before releasing the mouse.

Ksnip and vokoscreenNG are the current trial tools. To compare the previous
editor, run `DESKTOP_SCREENSHOT_EDITOR=satty desktop-screenshot edit`.
Kooha remains available from the launcher.

## File dialogs and screen sharing

If a file dialog hangs or screen sharing fails, check the portal logs:

```sh
journalctl --user -b -u xdg-desktop-portal.service -u xdg-desktop-portal-hyprland.service -u xdg-desktop-portal-gtk.service
```

See [implementation notes](ARCHITECTURE.md) for portal configuration.
