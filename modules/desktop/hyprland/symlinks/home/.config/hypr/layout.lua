-- See https://wiki.hypr.land/Configuring/Layouts/Scrolling-Layout/ for more
hl.config({
    general = { layout = "scrolling" },
    scrolling = {
        column_width = 0.75,
        -- Keep the configured width even when a workspace has one column.
        fullscreen_on_one_column = false,
        wrap_focus = true,
        wrap_swapcol = false,
    },
})
