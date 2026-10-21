# Desktop session implementation

Desktop portals use GTK for file dialogs and Hyprland for screenshots and screen
sharing. User-facing troubleshooting commands and session shortcuts are in
[README.md](README.md).

## Session ownership

The TTY1 autologin profile replaces Bash with `session-mode run`; it has no
interactive terminal fallback. The supervisor stays outside the graphical user
services and owns exactly one foreground compositor process group in the same
PAM/controlling-terminal session. Hyprland runs through `uwsm start -e -D
Hyprland hyprland.desktop`. A desktop exit restarts Hyprland; an explicit
`session-mode gaming` request instead starts the existing DRM `gaming-session`
launcher. `session-mode desktop` closes the current session and starts a fresh
Hyprland session, including when already on desktop (the Reload action).

Provisioning creates a private, user-owned `/run/desktop-session-<username>`
through `/etc/tmpfiles.d/desktop-session.conf`. An advisory owner lock proves
supervisor liveness. Atomic `next.json` requests are consumed once; expired or
malformed requests are discarded. Requests and the directory never survive a
reboot, and the ordinary initial mode is always desktop. No home preference,
display-manager default or permanent gaming selection is modified.

For an already running legacy Bash/UWSM session, the first request validates its
logind UID, TTY1 and local status, then writes a one-shot `handoff.json` and
terminates that login. Getty immediately autologins into the new profile. The
supervisor consumes the request and drains the previous UWSM envelope before
starting its replacement. The dedicated `/run` directory survives this PAM
handoff even if logind recreates the user's runtime directory. Installation
does not terminate the active desktop. `desktop-session` is removed by cleanup;
the manual launcher is no longer part of the startup path.

The supervisor stops desktop through UWSM and gaming through `steam -shutdown`.
An owned child process group is terminated after a bounded graceful-stop wait.
Gaming uses Gamescope's inherited `--ready-fd`; failure to become ready within
45 seconds returns to desktop. Any gaming child exit, including Steam Exit or a
startup failure, returns to desktop. Repeated short desktop failures retry with
a capped backoff rather than revealing a prompt. SIGTERM/SIGHUP end supervision
without restarting a compositor during system shutdown; Ctrl+C is ignored.

Steam's `-steamos3` exposes the `steamos-session-select` hook, installed in
`/usr/bin` and routed to `session-mode desktop`. See the
[gaming launcher architecture](../../gaming/gamescope-session/ARCHITECTURE.md).

`tests/test_session_modes.py` runs the production supervisor and Steam hook with
isolated compositor, Steam and logind executables. It covers both transitions,
Reload, Steam exit, gaming failure/timeout, first live handoff, rejected/stale
requests and the next-login desktop default. `test_boot_and_session.py` checks
autologin provisioning and that the profile uses exec only on a local TTY1 login.
These tests do not replace a real DRM/Steam round trip on the installed hardware.

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

`desktop-screenshot` keeps Hyprshot's native Hyprland capture modes, output path
and clipboard behavior. Region selection uses slurp. It waits for Hyprshot's
child capture process and skips the editor when selection produces no image.
The saved nonempty image determines success: Hyprshot's parent monitor may exit
nonzero while trying to stop an absent hyprpicker even when capture succeeds.
The default editor launches as `ksnip --edit` with the literal image path;
Ksnip never needs to capture through its generic Wayland/portal fallback.
`DESKTOP_SCREENSHOT_EDITOR=satty` selects the alternative editor.
The Ksnip preferences disable its tray icon and minimize/close-to-tray behavior.
User geometry and annotator preferences stay outside the managed defaults.

The helper reads `$XDG_CONFIG_HOME/quickshell/desktop/screenshot-editor` (`on` or
`off`, default `on`) for ordinary capture modes. `edit`/`--edit` force editing;
`--no-edit` forces raw capture. Print and Win+Shift+S use `region` so the shared
preference applies; Win+Shift+Print explicitly passes `--no-edit`.
The shared `screenshot-save` preference also defaults to `on`; explicit
`--save`/`--no-save` override it. Clipboard-only mode overrides editing and uses
Hyprshot's raw PNG stdout, buffered in Python memory before calling wl-copy.
No screenshot directory or temporary image is created. Empty selection leaves
the clipboard unchanged, and this path sends no notification, including on
failure. The raw consumer's exit status controls success so a Hyprshot monitor
failure cannot discard a valid capture.

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

Night light uses the packaged `hyprsunset.service`, with a Hyprland environment
condition matching the other session services. Its enablement belongs to the
Display drawer toggle, so provisioning does not enable it globally. The native
`hyprsunset.conf` asset defines the filter and optional profiles.

Hypridle calls `desktop-idle blank` to turn off only unprotected monitors. Lock
and suspend listeners use `desktop-idle allow-lock` and `allow-sleep` as their conditions,
retrying every ten seconds. The wrapper invokes the Quickshell display helper,
which owns the session-local Keep awake leases and independent temporary sleep/
locking pauses. Pauses end when the shell exits or reloads; dead lease locks are
ignored. See
[the display architecture](../quickshell/ARCHITECTURE.md#night-light-and-keep-awake)
for liveness and hardware matching. Existing application inhibitors are respected.
Manual lock and before-sleep commands remain unconditional.
`desktop-idle wake` retains the normal DPMS wake action and then notifies the
display service. Both idle resume and system resume use it, so deferred power-mode
refresh adjustments apply after wake without waking dark panels during a switch.

`monitors.lua` registers the native `monitor.layout_changed` Lua callback and
forwards it with `hl.dsp.event("desktop-displays-changed")`. Quickshell consumes
that notification through its existing Hyprland IPC subscription to save display
preferences without polling. This callback launches no process. Lua subscriptions
are rebuilt by Hyprland on config reload. Persistence and restoration belong to
[the display service](../quickshell/ARCHITECTURE.md#displays).
