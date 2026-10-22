# Desktop session implementation

Desktop portals use GTK for file dialogs and Hyprland for screenshots and screen
sharing. User-facing troubleshooting commands and session shortcuts are in
[README.md](README.md).

## Configuration loading

`hyprland.lua` loads each component with Hyprland's `require()`, which searches
`~/.config/hypr/`, records errors per file, watches the resolved files (including
symlink targets) and re-runs them on reload. Optional files use
`pcall(require, ...)`: `input-method` from the input-method module, then in
`monitors.lua` the selected host's `host-monitors` and the user-owned `displays`
written by the Displays drawer, so confirmed layouts override host defaults.
Settings equal to Hyprland's built-in defaults are omitted. Hyprland itself imports
its environment into systemd and notifies UWSM of readiness; `XCURSOR_SIZE` is
declared in `environment.d` because X11 clients otherwise choose their own size.

## Session ownership

`/etc/profile.d/zz-session-mode.sh` runs on login shells (sorted last so the session
inherits every profile export). On TTY1, when `uwsm check may-start` passes, it
replaces the shell with `session-mode run`, so no prompt appears; other consoles,
SSH and UWSM's environment preloader fail that check. `~/.hushlogin` silences the
login banner.

The supervisor runs one session at a time as an ordinary child in the console's
foreground process group: Hyprland via `uwsm start -e -D Hyprland
hyprland.desktop`, or the DRM `gaming-session` launcher. Logind grants DRM and
input through libseat to both compositors, so no terminal process-group handoff
is needed. It holds a lock on `$XDG_RUNTIME_DIR/session-mode/current`, which
records the running mode; `session-mode status` reports availability from it.

`session-mode desktop|gaming` writes the one-shot `next` request beside it and
stops the current session itself: `uwsm stop` for desktop, `steam -shutdown` for
gaming. The request is withdrawn only when that command reports failure, since
stopping the desktop normally terminates the caller too. When the child exits,
the supervisor consumes the request; without one, it starts the desktop. Any
gaming exit, including Steam Exit, a crash or startup failure, therefore returns
to Hyprland, and gaming never survives logout or reboot. Requesting desktop from
desktop is Reload. Startup discards stale requests.

Gaming passes a pipe to Gamescope's `--ready-fd` through `SESSION_MODE_READY_FD`;
no readiness within 45 seconds terminates the launcher and returns to desktop.
Desktop exits within 5 seconds without a request retry with a capped backoff.
SIGTERM/SIGHUP forward SIGTERM to the session (UWSM then stops the compositor
cleanly) and end supervision; Ctrl+C is ignored by the supervisor only.

Steam's `-steamos3` exposes the `steamos-session-select` hook, installed in
`/usr/bin` and routed to `session-mode desktop`. See the
[gaming launcher architecture](../../gaming/gamescope-session/ARCHITECTURE.md).

`tests/test_session_modes.py` runs the production supervisor and Steam hook with
isolated compositor and Steam executables, covering transitions, Reload, Steam
exit, gaming failure/timeout, failed stops, and the desktop default of a new login.
`test_boot_and_session.py` checks autologin provisioning and the TTY1 profile
gate. Neither replaces a real DRM/Steam round trip on the installed hardware.

## Desktop integration

`workspaces.lua` owns navigation policy for shortcuts, gestures and the bar.
Shortcuts use the active monitor; bar buttons pass their output's numeric monitor
ID, resolved against `hl.get_monitors()`. `hl.get_monitor()` uses a monitor
selector rather than a bare numeric ID. Regression coverage lives in
`tests/test_desktop_workspaces.py` and mocks that native lookup contract.

`DesktopWorkspaces.recover()` runs through a 150 ms native one-shot timer after
`monitor.layout_changed`, and once after configuration load. Enabled independent
outputs are recovery destinations; disabled/mirrored outputs and Hyprland's
invisible `FALLBACK` are excluded. Workspaces whose output is unavailable move
intact to the focused usable output or first survivor, retaining their separate
stacks without switching focus. Mapped, non-hidden, non-fullscreen floating
windows wholly outside all usable output rectangles are fitted into their
workspace's surviving output (or the recovery destination), including reserved
edges, scale and rotation. Reachable floats and tiled scrolling columns keep
their placement. This policy launches no helper and has no repeating timer.
The Quickshell display service owns re-enabling a disabled panel when no real
independent output would survive; it excludes `FALLBACK` from its inventory.

`desktop-screenshot` selects with slurp (`-d` for areas, `-r` over visible window
boxes) before capturing with grim, so cancelling writes nothing and leaves the
clipboard alone. Window boxes come from `hyprctl -j` and are clipped to their
monitor's logical area, keeping scrolled-off columns out of the image. Whole
displays use `grim -o NAME`, which captures at native resolution with the
output's transform. Saved images are copied to the clipboard; without the editor,
a notification confirms the file. The default editor launches as
`ksnip --edit` with the literal image path; `DESKTOP_SCREENSHOT_EDITOR=satty`
selects the alternative. The Ksnip preferences disable its tray icon and
minimize/close-to-tray behavior. User geometry and annotator preferences stay
outside the managed defaults. Bindings start the helper through `uwsm-app`, like
other applications, so an editor runs in its own unit.

The helper reads `$XDG_CONFIG_HOME/quickshell/desktop/screenshot-editor` (`on` or
`off`, default `on`) for ordinary capture modes. `edit`/`--edit` force editing;
`--no-edit` forces raw capture. Print and Win+Shift+S use `region` so the shared
preference applies; Win+Shift+Print explicitly passes `--no-edit`.
The shared `screenshot-save` preference also defaults to `on`; explicit
`--save`/`--no-save` override it. Clipboard-only mode overrides editing; grim's PNG
stdout is buffered in Python memory and checked before calling wl-copy, so a
failed capture cannot replace the clipboard. No screenshot directory or temporary
image is created, and this path sends no notification, including on failure.

The Capture drawer uses `output --output NAME` or `region`, plus `--report` and
explicit editor/save flags, to read back a saved image path (or `clipboard`) and
optionally launch the editor
without keeping capture busy until the editor closes. Missing whole-display
images are failures rather than selection cancellation. The drawer owns delay
and dismissal timing; the helper performs the capture immediately.

The recording shortcut invokes Quickshell's `desktop:record-region` global
shortcut. It selects an area through Slurp when idle and stops an active recording.
The shell owns recording preferences and the supervised recording service; see
[Capture architecture](../quickshell/ARCHITECTURE.md#capture).

Night light uses the packaged `hyprsunset.service`. Its enablement belongs to the
Display drawer toggle, so provisioning does not enable it globally. The native
`hyprsunset.conf` asset defines the filter and optional profiles.

Hypridle calls `desktop-idle blank` to turn off only unprotected monitors. Lock
and suspend listeners use `desktop-idle allow-lock` and `allow-sleep` as their
conditions, retrying every ten seconds. The wrapper invokes the Quickshell display
helper, which owns the session-local Keep awake leases and independent temporary
sleep/locking pauses; it exits 0 to allow, 1 to defer and any other status on
failure. Helper failures allow locking but block automatic suspend. See
[the display architecture](../quickshell/ARCHITECTURE.md#night-light-and-keep-awake)
for liveness and hardware matching. Existing application inhibitors are respected.
Manual lock and before-sleep commands remain unconditional. Idle and system resume
turn every display on with the DPMS dispatcher, then emit
`desktop-displays-changed` so the display service reapplies adjustments it skipped
while panels were dark.

`monitors.lua` registers the native `monitor.layout_changed` Lua callback and
forwards it with `hl.dsp.event("desktop-displays-changed")`. Quickshell consumes
that notification through its existing Hyprland IPC subscription to save display
preferences without polling. This callback launches no process. Lua subscriptions
are rebuilt by Hyprland on config reload. Persistence and restoration belong to
[the display service](../quickshell/ARCHITECTURE.md#displays).
