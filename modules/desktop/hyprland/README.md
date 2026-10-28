# Hyprland

This module configures the desktop and its session. Edit the Lua files under
`symlinks/home/.config/hypr/`; Hyprland reloads them automatically. After
something rewrites several of them at once, such as a Git checkout, pull or
rebase, run `hyprctl reload config-only`: the automatic reload can pick up a mix
of old and new files. Run `hyprctl configerrors` if a change does not work as
expected.

Alt+Tab focuses and centers the next column to the right, wrapping from the last
column to the first. Win+Left/Right also wrap between columns.

## Desktop and gaming mode

The desktop starts automatically on TTY1. Win+1 or Ctrl+Alt+Delete opens Spaces;
hold its **Switch to gaming mode** button for two seconds to enter Steam's dedicated
gaming session. Steam's **Go to Desktop** or **Exit Steam** returns to the
desktop. Rebooting always starts Hyprland.

**Restart → Reload** starts a fresh desktop session, closing running applications.
Gaming exits, startup failures and a compositor startup timeout return to Hyprland.
Returning from gaming can take about 30 seconds while Steam and Gamescope shut down.
If gaming mode stops responding, press Ctrl+Alt+F2, log in, run
`session-mode desktop`, then return with Ctrl+Alt+F1.

Per-machine Gamescope settings (`SYSTEM_GAMING_GPU`, `SYSTEM_GAMING_HDR`,
`SYSTEM_GAMING_OUTPUT`) go in `/etc/gaming-session.conf` or
`~/.config/gaming-session.conf`.
GPU `auto` selects the GPU wired to the preferred display; Steam and games
use the discrete GPU when available. Run `gaming-session --check` to validate
settings without leaving the desktop. Startup logs are available with
`journalctl -t gaming-session -b`.

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
| Print or Win+Shift+S | Select an area to capture           |
| Win+Shift+Print      | Select an area without editing      |
| Win+Print            | Capture the focused window          |
| Win+Ctrl+Print       | Select a window to capture          |
| Shift+Print          | Capture the current display         |
| Win+Shift+R          | Record an area / stop recording      |

Screenshots are saved under your Pictures directory in `Screenshots` and copied
to the clipboard before the editor opens. While selecting an area, hold Space
to move the rectangle; release Space to resize it before releasing the mouse.

The Capture drawer's **Open in editor** setting applies to these screenshot
shortcuts; Win+Shift+Print always skips editing. Ksnip is the default editor.
Satty remains available with
`DESKTOP_SCREENSHOT_EDITOR=satty desktop-screenshot edit`. Without the editor, a
notification confirms the saved file.
The shell's [Capture drawer](../quickshell/README.md#capture) adds display capture
with a delay, GPU Screen Recorder controls and a webcam test. Win+Shift+R selects
an area when idle and stops the active recording.

## File dialogs and screen sharing

If a file dialog hangs or screen sharing fails, check the portal logs:

```sh
journalctl --user -b -u xdg-desktop-portal.service -u xdg-desktop-portal-hyprland.service -u xdg-desktop-portal-gtk.service
```

See [implementation notes](ARCHITECTURE.md) for portal configuration.
