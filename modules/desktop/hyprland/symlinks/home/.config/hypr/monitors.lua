-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
hl.monitor({
    output   = "",
    mode     = "preferred",
    position = "auto",
    scale    = "auto",
})

-- Selected host assets supply only the outputs that need a fixed preference.
local config = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
local path = config .. "/hypr/host-monitors.lua"
local file = io.open(path, "r")
if file then
    file:close()
    dofile(path)
end
