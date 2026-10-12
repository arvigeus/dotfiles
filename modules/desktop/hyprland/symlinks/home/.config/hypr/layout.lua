hl.config({ general = { layout = "scrolling" } })

-- See https://wiki.hypr.land/Configuring/Layouts/Scrolling-Layout/ for more
hl.config({
    scrolling = {
        column_width = 0.5,
        fullscreen_on_one_column = false,
        focus_fit_method = 1, -- Scroll only enough to bring the column into view.
        wrap_focus = false,
        wrap_swapcol = false,
    },
})
