# Steam Controller

Desktop controls for the original Steam Controller without running Steam.
USB, Valve's wireless receiver and Bluetooth use SC Controller. The mapping
starts with the Hyprland session and reconnects automatically.

| Control | Action |
| --- | --- |
| Steam button | Application Launcher; hold 1.5 s to power off wirelessly |
| Back / Start (left / right of Steam) | Spaces / Performance drawer |
| Left / right bumper (upper shoulder buttons) | Previous / next Space tab; on the desktop, previous / next window, centered |
| Left / right rear grip | Narrow / widen the current window |
| Right pad / left pad | Pointer / inverted scrolling, with haptics |
| Right trigger / left trigger (lower shoulder controls) | Left click / right click |
| Right / left pad click | Left click / middle click |
| Stick / stick click | Arrow keys / on-screen keyboard |
| A / B / X | Enter / Escape / Space |
| Hold Y + left / right bumper | Previous / next workspace |
| Hold Y + left / right rear grip | Move the window to the previous / next workspace and follow |
| Hold Y + stick click | Toggle maximize |
| Hold Y + stick left / right | Previous / next control within the desktop shell |

Y is a modifier; pressing it alone does nothing. Window sizing follows the same
width steps as Win+\[ and Win+\]. A confirms, B dismisses, and X toggles playback in
apps that use Space.

Spaces opens with its first entry selected. Use the stick to select, A to open,
and B to go back. Inside a Space, the stick navigates its catalogue; hold Y and
move the stick left/right to reach toolbars, filters and detail actions.
Changing a primary tab by bumper or pointer focuses its catalogue immediately.
Bumpers move between controls in drawers. Keyboard users can change Space tabs
with Ctrl+PageUp / Ctrl+PageDown.

Steam automatically takes full control while its client is running, including
its desktop layout, Steam button and per-game profiles. These desktop mappings
return after Steam exits. Layout edits in Steam and SC Controller are separate.

Check status with `systemctl --user status steam-controller-desktop` and logs
with `journalctl --user -u steam-controller-desktop -b`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for ownership and validation details.
