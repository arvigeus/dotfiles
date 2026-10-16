# Logitech hardware integration

`config.json` owns logiops, its service, and the Solaar library dependency.

## Keyboard lighting

`symlinks/home/.config/devices/keyboard/backends/logitech.py` supplies the Logitech
provider for the shell's [keyboard lighting interface](../../../desktop/quickshell/ARCHITECTURE.md#keyboard).
It uses the optional Solaar device library without starting its GUI, applying
saved settings, changing pairing, diverting keys or persisting preferences.
Its worker-local persister is disabled.

Discovery reads receiver/device identities. Inactive duplicate pairing slots
are excluded; each card is keyed by the keyboard's unique unit ID. Only Backlight2
mode/level controls reported by the device are exposed. MX Keys Mini reports a
0–7 range and Automatic, Manual and Off modes, with no RGB or effects. Slider
changes select Manual, or Off at zero. Automatic is restored through the cog.

The provider retains HID handles for its worker lifetime, reads state at most
once per two seconds, and rediscovers devices every fifteen seconds. Reads never
change lighting. Writes validate identity, mode choices and brightness range,
check readback, and attempt restoration of the previous mode/level if a partial
write fails. Closing releases device handles.

`tests/test_keyboard_backlight.py` covers mode selection, validation, rollback
and provider discovery/routing without hardware changes.
