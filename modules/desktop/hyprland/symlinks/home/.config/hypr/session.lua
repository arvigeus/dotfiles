hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")

-- UWSM imports compositor variables and starts graphical-session.target.
-- Its Hyprland plugin includes the instance signature and cursor variables.
hl.on("hyprland.start", function ()
    hl.exec_cmd("uwsm finalize")
end)
