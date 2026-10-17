# Desktop session implementation

Desktop portals use GTK for file dialogs and Hyprland for screenshots and screen
sharing. User-facing troubleshooting commands and session shortcuts are in
[README.md](README.md).

`desktop-screenshot` keeps Hyprshot's native Hyprland capture modes, output path
and clipboard behavior. Region selection uses slurp. It waits for Hyprshot's
child capture process and skips the editor when selection produces no image.
The saved nonempty image determines success: Hyprshot's parent monitor may exit
nonzero while trying to stop an absent hyprpicker even when capture succeeds.
The current editor trial launches `ksnip --edit` with the literal image path;
Ksnip never needs to capture through its generic Wayland/portal fallback.
`DESKTOP_SCREENSHOT_EDITOR=satty` selects the previous editor for comparison.
The Ksnip preferences disable tray behavior because the shell has no tray host.
User geometry and annotator preferences stay outside the managed defaults.

The recording shortcut launches `vokoscreenNG` for the current trial; the package
is named `vokoscreen`. Satty and Kooha remain declared during evaluation.

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

`monitors.lua` registers the native `monitor.layout_changed` Lua callback and
forwards it with `hl.dsp.event("desktop-displays-changed")`. Quickshell consumes
that notification through its existing Hyprland IPC subscription to save display
preferences without polling. This callback launches no process. Lua subscriptions
are rebuilt by Hyprland on config reload. Persistence and restoration belong to
[the display service](../quickshell/ARCHITECTURE.md#displays).
