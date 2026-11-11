# Tests

Run from the repository root with the Python/native dependencies supplied by the
selected modules. Tests use unittest; target a feature with discovery's `-p`:

```sh
env -u DISPLAY -u WAYLAND_DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE \
    QT_QPA_PLATFORM=offscreen PIPEWIRE_REMOTE=dotfiles-tests-unavailable \
    dbus-run-session -- python3 -B -m unittest discover -s tests -v
python3 -B -m unittest discover -s tests -p 'test_generation.py' -v
```

Unset `DISPLAY_PREVIEW_PLATFORM`, `DISPLAY_PREVIEW_DIR` and `GAMESCOPE_LIVE_TEST`
for an ordinary isolated run. Unix sockets must be permitted: private D-Bus,
HTTP/player fixtures and GnuPG agents need them. Some native probes also need
Qt/KDE development headers and a C++ compiler; optional probes report skips when
those dependencies are unavailable.

## Fixture boundaries

`support.py` owns repository paths, helper loading, display snapshots, fake
Hyprland IPC and shared QML setup. `support.run_qml()` copies production components
into temporary XDG trees, substitutes only native surfaces/helpers and checks
both completion and QML diagnostics. `support.private_bus()` disables service
activation; use it for native service fixtures so they cannot activate real
portals/daemons or register with the user's tray/notification server.

Keep hardware mutations behind fake adapters. Tests must never capture host
microphone/camera audio, play sound, change radios/power/displays, touch the real
clipboard or delete real caches. Deletion/refusal checks still need temporary
HOME/XDG trees. Encryption uses disposable GnuPG homes and keys; package/session
checks use stub commands. User-launched detached fixture processes must be reaped.

Prefer observable results: published files, preserved data, protocol replies,
request ordering and real production QML state. Cover failure/cancellation and
ownership boundaries where they can lose data or leave work running. Avoid
snapshots of package lists, exact widget structure, source substrings and absence
of retired implementations. Native configuration invariants remain useful when
they guard a concrete interaction, such as plugin merge order or firewall scope.

## Native checks

Offscreen fixtures cannot establish compositor focus/stacking, multi-output scale
or hotplug behavior, device authorization, audible playback, real capture quality
or download completion. Check the changed path with disposable data after apply;
inspect installed links, `hyprctl configerrors`, service state and journal errors.

`DISPLAY_PREVIEW_PLATFORM=wayland` opens real preview windows; use deliberately.
Native tooltip tests on offset outputs may require moving the compositor pointer,
since Qt's simulated move does not reliably reach that output. Restore it after
checking. The opt-in `GAMESCOPE_LIVE_TEST=1` probe is documented in the
[Gamescope architecture](../modules/gaming/gamescope-session/ARCHITECTURE.md).
See [mpv diagnostics](../modules/media/video/mpv/ARCHITECTURE.md#validation) for
physical render measurements and [Capture](../modules/desktop/quickshell/ARCHITECTURE.md#capture)
for the Qt camera-enumeration workaround and its removal probe.
