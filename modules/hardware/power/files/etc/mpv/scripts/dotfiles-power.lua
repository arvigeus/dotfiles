-- New players read policy immediately; a systemd path unit notifies live players.
local mp = require('mp')
local utils = require('mp.utils')
local options = {enabled = true}
require('mp.options').read_options(options, 'dotfiles-power')
if not options.enabled then return end

local profiles = {
    ['zephyrus-powersave'] = 'dotfiles-powersave',
    ['zephyrus-powersave-battery'] = 'dotfiles-powersave',
    ['zephyrus-battery'] = 'balanced',
    ['zephyrus-balanced'] = 'balanced',
    ['zephyrus-performance'] = 'performance',
    ['zephyrus-performance-battery'] = 'performance',
}
local applied = nil
local function update()
    -- Messages are notifications, never a second source of mode state.
    local file = io.open('/etc/tuned/active_profile', 'r')
    if not file then return end
    local profile = profiles[file:read('*l')]
    file:close()
    if profile == applied then return end
    if applied == 'dotfiles-powersave' then
        mp.commandv('apply-profile', applied, 'restore')
    end
    applied = profile
    if profile == 'dotfiles-powersave' then
        mp.commandv('apply-profile', profile)
    end
    mp.set_property_native('user-data/dotfiles-power/profile', profile or 'unmanaged')
end

mp.register_script_message('dotfiles-power', update)
-- Do not replace an IPC endpoint supplied by the user or another application.
local socket
local runtime = os.getenv('XDG_RUNTIME_DIR')
if runtime and mp.get_property('input-ipc-server', '') == '' then
    local directory = runtime .. '/mpv-power'
    local result = utils.subprocess({args = {'mkdir', '-p', '-m', '700', directory}, cancellable = false})
    if result.status == 0 then
        socket = directory .. '/' .. tostring(utils.getpid()) .. '.sock'
        mp.set_property('input-ipc-server', socket)
    end
end
mp.register_event('shutdown', function() if socket then os.remove(socket) end end)
update()
