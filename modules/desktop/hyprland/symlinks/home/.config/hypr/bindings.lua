local terminal    = "kitty"
local fileManager = "dolphin"
local browser     = "firefox"

local mainMod = "SUPER"

-- Applications run in their own systemd units rather than as compositor children.
local function app(command)
    return hl.dsp.exec_cmd("uwsm-app -- " .. command)
end

-- WORKAROUND: missing geometry events (https://github.com/hyprwm/Hyprland/discussions/15519).
-- Stale bar order? Check this wrapper, release hooks below, and desktop/shell.qml's
-- "desktop-layout-changed" listener. New reorder paths must notify it too.
-- Remove these hooks when native geometry/order notifications cover their actions.
local function layoutAction(action)
    return function()
        hl.dispatch(action)
        hl.dispatch(hl.dsp.event("desktop-layout-changed"))
    end
end

hl.bind(mainMod .. " + T", app(terminal))
hl.bind(mainMod .. " + F", app(fileManager))
hl.bind(mainMod .. " + B", app(browser))
hl.bind(mainMod .. " + Q", hl.dsp.window.close())
hl.bind("ALT + F4", hl.dsp.window.close())
hl.bind(mainMod .. " + M", hl.dsp.window.fullscreen({ mode = "maximized", action = "toggle" }))
-- Hypridle answers lock-session by starting hyprlock.
hl.bind(mainMod .. " + L", hl.dsp.exec_cmd("loginctl lock-session"))
hl.bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mainMod .. " + R", hl.dsp.global("desktop:launcher"))
hl.bind(mainMod .. " + 1", hl.dsp.global("desktop:spaces"))
hl.bind("CTRL + ALT + DELETE", hl.dsp.global("desktop:spaces"))
hl.bind(mainMod .. " + SHIFT + P", hl.dsp.global("desktop:performance"))
-- Screenshots may open an editor, so they run as applications too.
hl.bind("PRINT", app("desktop-screenshot region"))
hl.bind(mainMod .. " + SHIFT + S", app("desktop-screenshot region"))
hl.bind(mainMod .. " + SHIFT + PRINT", app("desktop-screenshot region --no-edit"))
hl.bind(mainMod .. " + PRINT", app("desktop-screenshot active-window"))
hl.bind(mainMod .. " + CTRL + PRINT", app("desktop-screenshot window"))
hl.bind("SHIFT + PRINT", app("desktop-screenshot output"))
hl.bind(mainMod .. " + SHIFT + R", hl.dsp.global("desktop:record-region"))
hl.bind(mainMod .. " + period", layoutAction(hl.dsp.layout("center")))
hl.bind(mainMod .. " + J", layoutAction(hl.dsp.layout("promote"))) -- Give a stacked window its own column.
hl.bind(mainMod .. " + bracketright", layoutAction(hl.dsp.layout("colresize +conf")))
hl.bind(mainMod .. " + bracketleft",  layoutAction(hl.dsp.layout("colresize -conf")))
hl.bind(mainMod .. " + SHIFT + left",  layoutAction(hl.dsp.layout("swapcol l")))
hl.bind(mainMod .. " + SHIFT + right", layoutAction(hl.dsp.layout("swapcol r")))

-- Move focus with mainMod + arrow keys
hl.bind(mainMod .. " + left",  hl.dsp.layout("focus l"))
hl.bind(mainMod .. " + right", hl.dsp.layout("focus r"))
hl.bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Vertical workspace navigation shares the bar/gesture policy in workspaces.lua.
for _, step in ipairs({ { "up", -1 }, { "down", 1 } }) do
    local direction = step[2]
    hl.bind(mainMod .. " + CTRL + " .. step[1], function()
        DesktopWorkspaces.step(direction)
    end)
    hl.bind(mainMod .. " + CTRL + SHIFT + " .. step[1], function()
        DesktopWorkspaces.step(direction, nil, true)
    end)
end

-- Scroll the current workspace by columns with mainMod + wheel.
hl.bind(mainMod .. " + mouse_down", layoutAction(hl.dsp.layout("move +col")))
hl.bind(mainMod .. " + mouse_up",   layoutAction(hl.dsp.layout("move -col")))

-- Move/resize windows with mainMod + LMB/RMB and dragging
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- WORKAROUND, paired with layoutAction above: border drags need no modifier;
-- SUPER can also be released before a drag ends.
-- Observe releases with any modifiers, without consuming application clicks.
for _, button in ipairs({ "mouse:272", "mouse:273" }) do
    hl.bind(button, hl.dsp.event("desktop-layout-changed"), {
        release = true, ignore_mods = true, non_consuming = true,
    })
end

-- Laptop multimedia keys for volume and LCD brightness
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"),      { locked = true, repeating = true })
hl.bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"),     { locked = true, repeating = true })
hl.bind("XF86AudioMicMute",     hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"),   { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"),                  { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"),                  { locked = true, repeating = true })

-- Requires playerctl
hl.bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"),       { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"),   { locked = true })
