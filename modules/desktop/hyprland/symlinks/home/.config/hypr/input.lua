hl.config({
    cursor = { no_warps = true },
    input = {
        kb_layout  = "us",
        kb_variant = "",
        kb_model   = "",
        kb_options = "",
        kb_rules   = "",

        -- Hover routes pointer input; clicking changes keyboard focus.
        follow_mouse = 2,
        float_switch_override_focus = 0,

        sensitivity = 0, -- -1.0 - 1.0, 0 means no modification.

        touchpad = {
            natural_scroll = false,
            tap_to_click = true,
        },
    },
})

hl.gesture({
    fingers = 3,
    direction = "horizontal",
    action = "scroll_move"
})

hl.gesture({
    fingers = 3,
    direction = "vertical",
    action = "workspace"
})
