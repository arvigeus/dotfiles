# Original Steam Controller desktop integration

`sc-controller` supplies the maintained userspace driver and uinput mapper;
`steam-devices` supplies Steam's device permissions. SC Controller's package also
ships its USB/uinput rules. No additional input group membership, root daemon,
kernel driver blacklist or global lizard-mode setting is needed.

The user service belongs to `graphical-session.target` and requires the Hyprland
Wayland environment. It stops when UWSM tears down the desktop, so the separate
Gamescope session always gets native Steam Input. USB/Bluetooth discovery,
reconnection, firmware mode and virtual input devices belong to upstream SCC.

The supervisor checks same-user `/proc/*/comm` for the real `steam` client every
0.5 s, ignoring zombies. It does not invoke Steam to query its state. This also
covers a Flatpak client and launches outside a wrapper. On Steam startup it
terminates and waits for its own SCC process: SCC restores fallback mode,
releases its USB claims and reattaches kernel interfaces. Steam discovers the
returned device. SCC starts again after the last client exits. An unexpected SCC
exit fails the supervisor so systemd can retry; stop has a bounded process-group
kill fallback. Only the daemon receives the initial SIGTERM, allowing SCC to
notify its OSD children while releasing devices before it closes them.

The internal `mapper` entry point wraps SCC's event loop to clean up and exit on
an exception. SCC's ordinary launcher retries `run()` in the same process, which
can register duplicate device callbacks after an input failure. Exiting lets
systemd recreate the complete driver state and reload the managed profile. Normal
SIGTERM keeps its successful status for Steam handoff and session shutdown.

SCC's generated config, socket and PID file live in the service runtime directory,
passed as `XDG_CONFIG_HOME` only to SCC and its OSD children. The ordinary SCC GUI
configuration is independent. Only the three first-generation drivers are enabled;
other controllers are not claimed. Defaults come from the installed SCC version,
with X11 input repair, automatic profile switching and news fetching disabled.
The fixed profile is a managed system asset. Change it in this module and apply.

The profile emits the desktop's existing keyboard shortcuts through SCC's virtual
keyboard. Launcher is Super+R, Spaces is Shift+Tab and Performance is
Ctrl+Shift+Tab. Hyprland's global bindings consume these combinations before an
application receives them. There are no shell-command actions or Hyprland command
strings in the profile.

Bumpers emit Super+F11/F12, which Hyprland binds to the shell's
`desktop:controller-previous/next` global shortcuts. `SpaceHost.handleBumper()`
cycles primary tabs in the active Space, traverses focus in another shell
surface, or dispatches focus-left/right, center and the layout-change event when
the desktop is active. Ordinary Super+Left/Right keyboard bindings remain native.
Grips emit Super+LeftBrace/RightBrace for the configured width
steps. Holding physical Y selects SCC modes without emitting a modifier key of
its own: bumpers use Super+Ctrl+Up/Down for workspaces, grips add Shift to move a
window and follow, and stick-click emits Super+M to toggle maximize. Normal
stick-click opens SCC's keyboard. A/B/X emit Enter/Escape/Space. Mode actions
release their selected keys even when Y is released before the action button.

The stick uses a radial ROUND deadzone: values below 6000 are neutral, while
over-range full deflection is clamped instead of converted to neutral. This
preserves a held arrow at the negative axis endpoint and with transverse jitter.
Holding Y changes horizontal stick motion to Super+F9/F10. Quickshell's active
`InteractionWindow` consumes these as previous/next focus; elsewhere they have no
desktop binding. Shell input navigation is described in the
[shared UI architecture](../../../desktop/quickshell/ARCHITECTURE.md#shared-ui).

Trackpads retain SCC's smoothing and haptics. Both left-pad scroll axes have
negative sensitivity, reversing the normal SCC directions. Right-pad click and
right trigger both emit left click; left trigger emits right click and left-pad
click emits middle click. Gyro is intentionally unbound. The Steam button's long
hold switches off wireless controllers; upstream ignores that operation for a
wired controller, and the long hold does not emit the launch shortcut.

Steam owns its native desktop, chord and game profiles while running. There is
no automatic VDF conversion or modification of Steam account/cloud files. This
keeps guide-button and per-game behavior native, as selected by the user.

## Validation

`tests/test_steam_controller.py` checks Steam ownership transitions, shutdown and
crash handling with fake processes. Native SCC checks exercise the profile's
button events, keyboard chord order, Y-mode selection/release, long holds, mouse
outputs and scroll direction using recording devices without host input access.
The recording keyboard uses SCC's real `Keyboard.pressEvent/releaseEvent` scan
translation, with only low-level output stubbed. This catches unsupported keys
as well as logical chord/release mistakes. Chords must use keys present in SCC's
`uinput.Scans` capability map; extended function keys are not assumed available.
Generation tests cover asset/service discovery. After installation, inspect
`systemctl --user status steam-controller-desktop`, its journal and the SCC socket
greeting for a connected controller and the selected profile. Start and exit the
real Steam client to check USB release/reclaim. Physical feel, haptic strength,
wireless reconnect and the on-screen keyboard need controller testing.

Upstream: [SC Controller](https://github.com/C0rn3j/sc-controller), including its
[`sc_by_cable` driver](https://github.com/C0rn3j/sc-controller/blob/main/scc/drivers/linux/sc_by_cable.py)
and [USB release lifecycle](https://github.com/C0rn3j/sc-controller/blob/main/scc/drivers/usb.py).
