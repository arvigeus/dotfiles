# Gaming session launcher

`gaming-session` launches Gamescope's DRM backend with Steam integration, two
Xwayland servers, adaptive sync and Mangoapp. GPU, HDR and output selection comes
from `/etc/gaming-session.conf`, then the user-owned
`$XDG_CONFIG_HOME/gaming-session.conf`, with environment overrides taking
precedence. Configuration is parsed as data, never sourced as shell code.

`SYSTEM_GAMING_GPU` selects the compositor/scanout GPU. In DRM mode Gamescope
opens the KMS node of its selected Vulkan GPU; it cannot scan out through a
different GPU. `auto` resolves the first connected preferred output to its
sysfs DRM card and passes that card's PCI vendor/device ID to
`--prefer-vk-device`. Automatic output order prefers external connectors, then
internal panels. Output preferences are filtered to connectors on the selected
GPU. A forced GPU without a connected preferred output fails validation rather
than starting a displayless compositor. `gaming-session --check` performs this
validation without starting graphics or writing runtime files; `session-mode
gaming` runs it before stopping the desktop, and the launcher repeats it at start.
`SYSTEM_GAMING_DRM_ROOT` supplies an isolated sysfs tree in regression tests.

Steam is launched through `switcherooctl launch`, honoring its packaged
`PrefersNonDefaultGPU` policy independently of Gamescope's scanout GPU. The
discrete GPU remains available to Steam and its games on hybrid laptops whose
screens are wired to the integrated GPU. On a single-GPU system the same native
launcher uses the default GPU. This module owns the switcheroo-control dependency
and service.

Steam only offers features the session advertises, so the launcher exports the
SteamOS flags that match the Gamescope options it passes: multiple Xwayland
servers, VRR, tearing, HDR (only with `--hdr-enabled`), Mangoapp presets, dynamic
VRS, Steam's volume handler and URL opening. Steam writes the performance overlay
level and VRS rate to fresh files under `$XDG_RUNTIME_DIR/gaming-session/`; the
overlay starts hidden.

Steam runs with `-gamepadui -steamos3` so its desktop-return action calls
`/usr/bin/steamos-session-select`, the path SteamOS and ChimeraOS use. This hook
requests `session-mode desktop`; it never saves a session choice. Gaming mode is
entered only through `session-mode gaming`; there is no display-manager entry.

When the supervisor provides `SESSION_MODE_READY_FD`, the launcher passes
`/proc/self/fd/N` to Gamescope's `--ready-fd`: despite the option name, Gamescope
opens the argument as a path. A bare number silently fails to open and never
signals readiness. The supervisor owns readiness and bounded graceful-stop waits, its child
process group and the inherited descriptor. Without the supervisor the launcher remains usable for
diagnostics, but supplies no automatic desktop return.
`SYSTEM_GAMING_DRY_RUN=1 gaming-session` prints the effective command and
environment without starting graphics or Steam.

The launcher sends Gamescope and initial Steam output to the system journal with
the `gaming-session` identifier. Use `journalctl -t gaming-session -b` for the
current boot or `-b -1` for the preceding boot. `systemd-cat` execs the command,
preserving process ownership, exit status and the readiness descriptor.

Reference implementations: [ChimeraOS's Steam session](https://github.com/ChimeraOS/gamescope-session-steam/blob/main/usr/share/gamescope-session-plus/sessions.d/steam)
and [desktop-return hook](https://github.com/ChimeraOS/gamescope-session-steam/blob/main/usr/bin/steamos-session-select).
The [Gamescope option definitions](https://github.com/ValveSoftware/gamescope/blob/3.16.31/src/main.cpp)
document the DRM arguments; the
[readiness implementation](https://github.com/ValveSoftware/gamescope/blob/3.16.31/src/steamcompmgr.cpp)
opens the readiness path and writes the X11/Wayland display names. Run
`GAMESCOPE_LIVE_TEST=1 python3 -m unittest discover -s tests -p test_session_modes.py`
to check the installed compositor's readiness contract with a headless backend
and temporary Xwayland server, without switching the desktop or starting Steam.

See [session ownership](../../desktop/hyprland/ARCHITECTURE.md#session-ownership)
for the console supervisor and one-shot transitions.
