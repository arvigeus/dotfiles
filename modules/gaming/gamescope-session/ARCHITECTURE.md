# Gaming session launcher

`gaming-session` launches Gamescope's DRM backend with Steam integration, two
Xwayland servers, adaptive sync and Mangoapp. Existing GPU, HDR and output
selection comes from `/etc/system/gaming-session.conf`, then the user-owned
`$XDG_CONFIG_HOME/system/gaming-session.conf`, with environment overrides taking
precedence. Configuration is parsed as data, never sourced as shell code.

Steam runs with `-gamepadui -steamos3` so its desktop-return action calls
`/usr/bin/steamos-session-select`. This hook requests `session-mode desktop`;
it never modifies a persistent session choice. The dedicated gaming session's
desktop entry starts the supervisor with `--initial gaming`; the autologin
profile always uses its default desktop mode. Steam Exit or Gamescope failure
also returns to desktop through the supervisor.

When the supervisor provides `SESSION_MODE_READY_FD`, the launcher forwards it
to Gamescope's `--ready-fd` option. The supervisor owns startup and teardown
timeouts and the inherited descriptor. Without the supervisor the launcher
remains usable for diagnostics, but supplies no automatic desktop return.
`SYSTEM_GAMING_DRY_RUN=1 gaming-session` prints the effective argument vector
without starting graphics or Steam.

Reference implementations: [ChimeraOS's Steam launch flags](https://github.com/ChimeraOS/gamescope-session-steam/blob/main/usr/share/gamescope-session-plus/sessions.d/steam)
and [desktop-return hook](https://github.com/ChimeraOS/gamescope-session-steam/blob/main/usr/bin/steamos-session-select).
The [Gamescope option definitions](https://github.com/ValveSoftware/gamescope/blob/3.16.31/src/main.cpp)
document the DRM and readiness arguments used by the installed version.

See [session ownership](../../desktop/hyprland/ARCHITECTURE.md#session-ownership)
for the console loop, one-shot transitions and first live handoff.
