-- Components load in order, so later files override earlier settings. Hyprland's
-- require() reports errors per file, watches each file and re-runs it on reload.
for _, component in ipairs({
    "monitors", "appearance", "animations", "layout",
    "workspaces", "input", "bindings", "windows",
}) do
    require(component)
end

-- Owned by hardware/keyboard/input-method; its layouts override input.lua.
pcall(require, "input-method")
