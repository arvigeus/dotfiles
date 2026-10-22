# Zephyrus hardware integration

`config.json` owns the asusctl dependency. The module's
host check installs its assets only for the Zephyrus host.

## Keyboard lighting

`symlinks/home/.config/devices/keyboard/backends/asus.py` supplies the ASUS provider
for the shell's [keyboard lighting interface](../../../desktop/quickshell/ARCHITECTURE.md#keyboard).
It augments native `asus:*kbd_backlight` records with the built-in keyboard label
and capabilities from the installed daemon's `xyz.ljones.Aura` D-Bus interface.
Reads never activate the daemon. Only one unambiguous laptop Aura object may
attach to the platform LED; generic Linux brightness remains usable without it.

Effects intersect `SupportedBasicModes` with the adapter's supported handlers.
The RGB preset palette exists only for an active color-capable effect; rainbow
modes hide it. ASUS accepts continuous RGB values, so the swatches are convenience
presets rather than a discrete hardware palette. Effect changes set `LedMode`
using its public numeric ID. Color changes preserve opaque nested enum wire
values and the current speed/direction, and set both breathing colors to the
chosen swatch. Never construct the nested mode value from the public mode number:
Aura's derived enum encoding differs for Pulse. The daemon owns preference
persistence; the shell adds none.

`tests/test_keyboard_backlight.py` covers supported effects, RGB capability,
wire values, stale-controller rejection and provider routing without hardware
changes. `tests/test_generation.py` checks that other hosts omit the adapter.

## Battery care and performance

`symlinks/home/.config/devices/power/backends/asus.py` extends the desktop's
[power drawers](../../../desktop/quickshell/ARCHITECTURE.md#battery-and-performance).
It discovers `ChargeControlEndThreshold` through `SupportedProperties` on
`xyz.ljones.Platform` at `/xyz/ljones`. Reads never activate asusd. Charge limits
use the byte-valued property setter and remain persisted by asusd. The adapter
rechecks the unique daemon owner and observed limit before writing, and confirms
both after writing. The supported range is 20–100%, in integer steps, matching
asusd's setter. The shared gauge renders the actual applied value.
Unsupported or unavailable controllers expose no charge-limit controls.

Standard hwmon fan RPM and DRM metrics remain in the shared read-only backend.
The Performance drawer exposes the three coordinated modes; CPU boost and ASUS
profile selection have no independent shell controls. Hardware control ownership
and application integration are defined in the
[power architecture](../../power/ARCHITECTURE.md).

`tests/test_power_drawers.py` checks capability discovery, stale requests, preset
range validation and applied-value readback with a mock bus. Generation tests verify
that only Zephyrus installs this provider.
