# Desktop session implementation

Desktop portals use GTK for file dialogs and Hyprland for screenshots and screen
sharing. User-facing troubleshooting commands and session shortcuts are in
[README.md](README.md).

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
The Ksnip preferences disable tray behavior because the shell has no tray host.
User geometry and annotator preferences stay outside the managed defaults.

The recording shortcut launches Kooha until the planned wf-recorder controls are
implemented in the recording drawer. Satty remains an optional screenshot editor.

Night light uses the packaged `hyprsunset.service`, with a Hyprland environment
condition matching the other session services. Its enablement belongs to the
Display drawer toggle, so provisioning does not enable it globally. The native
`hyprsunset.conf` asset defines the filter and optional profiles.

Hypridle calls `desktop-idle blank` to turn off only unprotected monitors. Lock
and suspend listeners use `desktop-idle allow-session-idle` as their condition,
retrying every ten seconds. The wrapper invokes the Quickshell display helper,
which owns the session-local Keep awake leases. See
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
