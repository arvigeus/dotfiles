-- Refer to https://wiki.hypr.land/Configuring/Basics/Variables/
hl.config({
    general = {
        gaps_in  = 4,
        gaps_out = 10,

        border_size = 2,

        col = {
            active_border   = "rgba(ff465ccc)",
            inactive_border = "rgba(454c4eff)",
        },

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
    },

    misc = {
        disable_hyprland_logo = true,
        disable_splash_rendering = true,
    },
})
