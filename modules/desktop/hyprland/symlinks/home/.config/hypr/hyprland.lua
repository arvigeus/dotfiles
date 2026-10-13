-- Static configuration is owned by desktop/hyprland; input-method.lua belongs
-- to hardware/keyboard/input-method and loads last to preserve language policy.
-- dofile reloads each component instead of using require's cached modules.
local config = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
local directory = config .. "/hypr/"
for _, component in ipairs({
    "monitors", "session", "appearance", "animations",
    "layout", "workspaces", "input", "bindings", "windows",
}) do
    dofile(directory .. component .. ".lua")
end

-- Module-owned input defaults override the generic keyboard settings above.
local input_policy = config .. "/hypr/input-method.lua"
local input_file = io.open(input_policy, "r")
if input_file then
    input_file:close()
    dofile(input_policy)
end
