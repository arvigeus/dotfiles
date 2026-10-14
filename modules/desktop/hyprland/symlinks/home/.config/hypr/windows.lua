-- Center native floating windows; leave XWayland popup positions to their apps.
hl.window_rule({
    name = "center-floating-windows",
    match = { float = true, xwayland = false },
    center = true,
})

-- PiP placement overrides centering. Use the target size in move expressions,
-- since window_w/window_h still describe the original client size at this point.
hl.window_rule({
    name = "firefox-picture-in-picture",
    match = {
        class = "^(firefox|org.mozilla.firefox)$",
        title = "^Picture-in-Picture$",
    },
    float = true,
    pin = true,
    size = { 480, 270 },
    move = { "monitor_w-480-20", "monitor_h-270-20" },
})

-- Drawers slide in QML; a compositor layer fade would animate them a second time.
-- Keep this scoped to category drawers so launcher/bar/tooltip motion is unchanged.
hl.layer_rule({
    name = "desktop-drawer-motion",
    match = { namespace = "^desktop-drawer$" },
    no_anim = true,
})
