-- Owned by hardware/keyboard/input-method. No daemon is started here.
-- EN/BG phonetic with Alt+Shift; Vietnamese uses US keys under Fcitx.
InputMethod = {}

function InputMethod.apply(language)
    if language == "vi" then
        hl.config({ input = { kb_layout = "us", kb_variant = "", kb_options = "" } })
    else
        hl.config({ input = { kb_layout = "us,bg", kb_variant = ",phonetic",
            kb_options = "grp:alt_shift_toggle" } })
    end
end

-- The input-method controller records this compositor instance's selection.
-- Config reloads keep it; a new instance starts from EN/BG.
local function selected()
    local runtime = os.getenv("XDG_RUNTIME_DIR")
    local instance = os.getenv("HYPRLAND_INSTANCE_SIGNATURE")
    if not runtime or not instance then return nil end
    local identity = instance:gsub("[^%w_.-]", "_")
    local file = io.open(runtime .. "/input-method/hyprland-" .. identity .. "/secondary", "r")
    if not file then return nil end
    local language = file:read("l")
    file:close()
    return language
end

InputMethod.apply(selected())
