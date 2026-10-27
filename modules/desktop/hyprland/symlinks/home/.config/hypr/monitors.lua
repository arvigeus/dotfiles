-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = "auto",
})

-- Optional rules; later rules for an output replace earlier ones. The selected
-- host supplies fixed preferences, then the display service's active monitor set.
pcall(require, "host-monitors")
pcall(require, "displays")

-- Forward native output changes (including mode/position edits) to
-- the shell's existing IPC subscription. No command or polling process is used.
hl.on("monitor.layout_changed", function()
    hl.dispatch(hl.dsp.event("desktop-displays-changed"))
end)
