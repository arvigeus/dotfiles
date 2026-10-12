-- Owned by hardware/keyboard/input-method. No daemon is started here.
hl.config({ input = { kb_layout = "us,bg", kb_variant = ",phonetic",
    kb_options = "terminate:ctrl_alt_bksp,grp:alt_shift_toggle" } })

-- Retain the selected EN/BG or EN/VI pair across compositor config reloads.
-- Each new Hyprland instance starts from the defaults above.
local runtime = os.getenv("XDG_RUNTIME_DIR")
local instance = os.getenv("HYPRLAND_INSTANCE_SIGNATURE")
if runtime and instance then
    instance = instance:gsub("[^a-zA-Z0-9_.-]", "_")
    local path = runtime .. "/hypr/input-language-" .. instance .. ".lua"
    local file = io.open(path, "r")
    if file then
        file:close()
        dofile(path)
    end
end
