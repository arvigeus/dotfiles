# Gaming session launcher

`gaming-session` launches Gamescope's DRM backend with Steam integration, two
Xwayland servers, adaptive sync and Mangoapp. GPU, HDR and output selection comes
from `/etc/gaming-session.conf`, then the user-owned
`$XDG_CONFIG_HOME/gaming-session.conf`, with environment overrides taking
precedence. Configuration is parsed as data, never sourced as shell code.

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

When the supervisor provides `SESSION_MODE_READY_FD`, the launcher forwards it
to Gamescope's `--ready-fd` option. The supervisor owns the startup timeout and
the inherited descriptor. Without the supervisor the launcher remains usable for
diagnostics, but supplies no automatic desktop return.
`SYSTEM_GAMING_DRY_RUN=1 gaming-session` prints the effective command and
environment without starting graphics or Steam.

Reference implementations: [ChimeraOS's Steam session](https://github.com/ChimeraOS/gamescope-session-steam/blob/main/usr/share/gamescope-session-plus/sessions.d/steam)
and [desktop-return hook](https://github.com/ChimeraOS/gamescope-session-steam/blob/main/usr/bin/steamos-session-select).
The [Gamescope option definitions](https://github.com/ValveSoftware/gamescope/blob/3.16.31/src/main.cpp)
document the DRM and readiness arguments used by the installed version.

See [session ownership](../../desktop/hyprland/ARCHITECTURE.md#session-ownership)
for the console supervisor and one-shot transitions.
