local terminal    = "kitty"
local fileManager = "dolphin"
local browser     = "firefox"

local mainMod = "SUPER"

-- Applications run in their own systemd units rather than as compositor children.
local function app(command)
    return hl.dsp.exec_cmd("uwsm-app -- " .. command)
end

local function bind(keys, dispatcher, description, flags)
    flags = flags or {}
    flags.description = description
    hl.bind(keys, dispatcher, flags)
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

bind(mainMod .. " + T", app(terminal), "Open terminal")
bind(mainMod .. " + F", app(fileManager), "Open file manager")
bind(mainMod .. " + B", app(browser), "Open web browser")
bind(mainMod .. " + Q", hl.dsp.window.close(), "Close active window")
bind("ALT + F4", hl.dsp.window.close(), "Close active window")
bind(mainMod .. " + M", hl.dsp.window.fullscreen({ mode = "maximized", action = "toggle" }), "Toggle maximize")
-- Hypridle answers lock-session by starting hyprlock.
bind(mainMod .. " + L", hl.dsp.exec_cmd("loginctl lock-session"), "Lock screen")
bind(mainMod .. " + V", hl.dsp.window.float({ action = "toggle" }), "Toggle floating window")
bind(mainMod .. " + R", hl.dsp.global("desktop:launcher"), "Open application search")
bind(mainMod .. " + 1", hl.dsp.global("desktop:spaces"), "Open Spaces")
bind("CTRL + ALT + DELETE", hl.dsp.global("desktop:spaces"), "Open Spaces")
bind(mainMod .. " + SHIFT + P", hl.dsp.global("desktop:performance"), "Open Performance")
-- Screenshots may open an editor, so they run as applications too.
bind("PRINT", app("desktop-screenshot region"), "Select screenshot area")
bind(mainMod .. " + SHIFT + S", app("desktop-screenshot region"), "Select screenshot area")
bind(mainMod .. " + SHIFT + PRINT", app("desktop-screenshot region --no-edit"), "Capture area without editing")
bind(mainMod .. " + PRINT", app("desktop-screenshot active-window"), "Capture focused window")
bind(mainMod .. " + CTRL + PRINT", app("desktop-screenshot window"), "Select window to capture")
bind("SHIFT + PRINT", app("desktop-screenshot output"), "Capture current display")
bind(mainMod .. " + SHIFT + R", hl.dsp.global("desktop:record-region"), "Start or stop area recording")
bind(mainMod .. " + period", layoutAction(hl.dsp.layout("center")), "Center current column")
bind(mainMod .. " + J", layoutAction(hl.dsp.layout("promote")), "Promote stacked window to its own column")
bind(mainMod .. " + bracketright", layoutAction(hl.dsp.layout("colresize +conf")), "Widen current column")
bind(mainMod .. " + bracketleft", layoutAction(hl.dsp.layout("colresize -conf")), "Narrow current column")
bind(mainMod .. " + SHIFT + left", layoutAction(hl.dsp.layout("swapcol l")), "Move column left")
bind(mainMod .. " + SHIFT + right", layoutAction(hl.dsp.layout("swapcol r")), "Move column right")

-- Move focus with mainMod + arrow keys
bind("ALT + TAB", function()
    hl.dispatch(hl.dsp.layout("focus r"))
    hl.dispatch(hl.dsp.layout("center"))
    hl.dispatch(hl.dsp.event("desktop-layout-changed"))
end, "Focus and center next column")
bind(mainMod .. " + left",  hl.dsp.layout("focus l"), "Focus column to the left")
bind(mainMod .. " + right", hl.dsp.layout("focus r"), "Focus column to the right")
bind(mainMod .. " + up",    hl.dsp.focus({ direction = "up" }), "Focus window above")
bind(mainMod .. " + down",  hl.dsp.focus({ direction = "down" }), "Focus window below")

-- Vertical workspace navigation shares the bar/gesture policy in workspaces.lua.
for _, step in ipairs({ { "up", -1 }, { "down", 1 } }) do
    local direction = step[2]
    local workspace = direction < 0 and "previous" or "next"
    bind(mainMod .. " + CTRL + " .. step[1], function()
        DesktopWorkspaces.step(direction)
    end, "Switch to " .. workspace .. " workspace on this display")
    bind(mainMod .. " + CTRL + SHIFT + " .. step[1], function()
        DesktopWorkspaces.step(direction, nil, true)
    end, "Move window to " .. workspace .. " workspace and follow")
end

-- Scroll the current workspace by columns with mainMod + wheel.
bind(mainMod .. " + mouse_down", layoutAction(hl.dsp.layout("move +col")), "Scroll columns right")
bind(mainMod .. " + mouse_up",   layoutAction(hl.dsp.layout("move -col")), "Scroll columns left")

-- Move/resize windows with mainMod + LMB/RMB and dragging
bind(mainMod .. " + mouse:272", hl.dsp.window.drag(), "Move window", { mouse = true })
bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), "Resize window", { mouse = true })

-- WORKAROUND, paired with layoutAction above: border drags need no modifier;
-- SUPER can also be released before a drag ends.
-- Observe releases with any modifiers, without consuming application clicks.
for _, button in ipairs({ "mouse:272", "mouse:273" }) do
    bind(button, hl.dsp.event("desktop-layout-changed"), "Notify shell after window drag", {
        release = true, ignore_mods = true, non_consuming = true,
    })
end

-- Laptop multimedia keys for volume and LCD brightness
bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), "Increase volume", { locked = true, repeating = true })
bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), "Decrease volume", { locked = true, repeating = true })
bind("XF86AudioMute",        hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), "Mute or unmute volume", { locked = true, repeating = true })
bind("XF86AudioMicMute",     hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), "Mute or unmute microphone", { locked = true, repeating = true })
bind("XF86MonBrightnessUp",  hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), "Increase display brightness", { locked = true, repeating = true })
bind("XF86MonBrightnessDown",hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), "Decrease display brightness", { locked = true, repeating = true })

-- Requires playerctl
bind("XF86AudioNext",  hl.dsp.exec_cmd("playerctl next"), "Play next track", { locked = true })
bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), "Toggle playback", { locked = true })
bind("XF86AudioPlay",  hl.dsp.exec_cmd("playerctl play-pause"), "Toggle playback", { locked = true })
bind("XF86AudioPrev",  hl.dsp.exec_cmd("playerctl previous"), "Play previous track", { locked = true })
