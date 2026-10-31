-- Refer to https://wiki.hypr.land/Configuring/Basics/Variables/
hl.config({
    general = {
        gaps_in  = 4,
        gaps_out = 10,

        border_size = 2,

        resize_on_border = true,
        extend_border_grab_area = 8,
    },

    decoration = {
        rounding = 8,

        shadow = {
            range = 18,
            color = "rgba(00000044)",
        },

        blur = {
            size = 3,
        },

        motion_blur = {
            enabled = true,
        },
    },

    misc = {
        disable_hyprland_logo = true,
        disable_splash_rendering = true,
    },
})

-- Generated from the shared shell palette after the first shell start.
pcall(require, "theme")
