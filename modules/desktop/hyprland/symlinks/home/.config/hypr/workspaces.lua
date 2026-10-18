-- Shared by bindings, gestures and the bar's Lua IPC callback. Keep policy here
-- so navigation also works without Quickshell. Native positive IDs are the order:
-- slidevert compares those IDs, so names cannot supply animation direction.
DesktopWorkspaces = {}

local maxID = 2147483646

function DesktopWorkspaces.seed(monitor)
    -- Leave room above a fresh desktop. Create its empty starting workspace
    -- normally: changing IDs later leaves Quickshell's native model stale.
    local current = monitor.active_workspace
    if not current or current.id < 1 or current.id >= 10000 or current.windows > 0
        or current.is_persistent or monitor.active_special_workspace then return end
    local used = {}
    for _, workspace in ipairs(hl.get_workspaces()) do
        if workspace.monitor == monitor and workspace ~= current and not workspace.special then return end
        used[workspace.id] = true
    end
    local first = (monitor.id + 1) * 10000
    while used[first - 1] or used[first] or used[first + 1] do first = first + 10000 end
    if first >= maxID then return end

    local previousMonitor, previousWindow = hl.get_active_monitor(), hl.get_active_window()
    hl.dispatch(hl.dsp.focus({ monitor = monitor.id }))
    hl.dispatch(hl.dsp.focus({ workspace = first }))
    if previousMonitor and previousMonitor ~= monitor then
        hl.dispatch(hl.dsp.focus({ monitor = previousMonitor.id }))
        if previousWindow then
            hl.dispatch(hl.dsp.focus({ window = "address:" .. previousWindow.address }))
        end
    end
end

function DesktopWorkspaces.step(direction, monitorID, moveWindow)
    if direction ~= -1 and direction ~= 1 then return end
    local monitor
    if monitorID == nil then
        monitor = hl.get_active_monitor()
    else
        -- Match the bar's numeric ID directly, without monitor selector parsing.
        for _, candidate in ipairs(hl.get_monitors()) do
            if candidate.id == monitorID then monitor = candidate; break end
        end
    end
    if not monitor then return end
    local current = monitor.active_workspace
    if not current or current.id < 1 or monitor.active_special_workspace then return end
    local window = moveWindow and hl.get_active_window() or nil
    if moveWindow and (not window or window.pinned or window.workspace ~= current) then return end

    local workspaces, used = {}, {}
    for _, workspace in ipairs(hl.get_workspaces()) do
        if workspace.id > 0 then
            used[workspace.id] = true
            if workspace.monitor == monitor then table.insert(workspaces, workspace) end
        end
    end
    table.sort(workspaces, function(a, b) return a.id < b.id end)

    local index
    for i, workspace in ipairs(workspaces) do
        if workspace == current then index = i; break end
    end
    if not index then return end
    local target = workspaces[index + direction]
    local selector
    if target then
        selector = target.id
    else
        -- Empty workspaces allow returning to a neighbor, never further growth.
        if current.windows == 0 then return end
        selector = current.id + direction
        while used[selector] do selector = selector + direction end
        if selector < 1 or selector > maxID then return end
    end

    hl.dispatch(hl.dsp.focus({ monitor = monitor.id }))
    if moveWindow then
        hl.dispatch(hl.dsp.window.move({ workspace = selector, follow = true }))
    else
        hl.dispatch(hl.dsp.focus({ workspace = selector }))
    end
    -- Hyprland owns removal of nonpersistent, empty workspaces after departure.
end

-- Native callbacks are cleared on config reload; an already initialized stack
-- is left alone. Startup and newly attached displays receive room in both directions.
hl.on("monitor.added", DesktopWorkspaces.seed)
for _, monitor in ipairs(hl.get_monitors()) do DesktopWorkspaces.seed(monitor) end

-- Let native output migration finish before repairing anything left behind.
-- This also covers disabling an output and changing its position/mode/scale.
function DesktopWorkspaces.recover()
    local monitors, byName = {}, {}
    for _, monitor in ipairs(hl.get_monitors()) do
        if monitor.enabled and not monitor.is_mirror and monitor.name ~= "FALLBACK" then
            table.insert(monitors, monitor)
            byName[monitor.name] = monitor
        end
    end
    local focused = hl.get_active_monitor()
    local target = focused and byName[focused.name] or monitors[1]
    if not target then return end

    -- Move whole workspaces so tiled windows reflow and stacks stay separate.
    local rescued = {}
    for _, workspace in ipairs(hl.get_workspaces()) do
        local monitor = workspace.monitor
        if not monitor or not byName[monitor.name] then
            local selector = workspace.special and ("special:" .. workspace.name:gsub("^special:", ""))
                or workspace.id or workspace.name
            hl.dispatch(hl.dsp.workspace.move({ workspace = selector, monitor = target.name }))
            rescued[workspace.id or workspace.name] = target
        end
    end

    local function bounds(monitor)
        local width, height = monitor.width, monitor.height
        if monitor.transform % 2 == 1 then width, height = height, width end
        local reserved = monitor.reserved
        local left, top = monitor.x + reserved.left, monitor.y + reserved.top
        return left, top, monitor.x + width / monitor.scale - reserved.right,
            monitor.y + height / monitor.scale - reserved.bottom
    end
    for _, window in ipairs(hl.get_windows({ mapped = true, floating = true })) do
        if not window.hidden and window.fullscreen == 0 then
            local at, size = window.at, window.size
            local reachable = false
            for _, monitor in ipairs(monitors) do
                local left, top, right, bottom = bounds(monitor)
                if at.x < right and at.x + size.x > left and at.y < bottom and at.y + size.y > top then
                    reachable = true
                    break
                end
            end
            if not reachable then
                local workspace = window.workspace
                local monitor = workspace and (rescued[workspace.id or workspace.name] or workspace.monitor)
                monitor = monitor and byName[monitor.name] or target
                local left, top, right, bottom = bounds(monitor)
                local width, height = math.min(size.x, right - left), math.min(size.y, bottom - top)
                local selector = "address:" .. window.address
                if width ~= size.x or height ~= size.y then
                    hl.dispatch(hl.dsp.window.resize({ window = selector, x = width, y = height, relative = false }))
                end
                hl.dispatch(hl.dsp.window.move({ window = selector,
                    x = math.max(left, math.min(at.x, right - width)),
                    y = math.max(top, math.min(at.y, bottom - height)), relative = false }))
            end
        end
    end
end

local recovery = hl.timer(DesktopWorkspaces.recover, { timeout = 150, type = "oneshot" })
hl.on("monitor.layout_changed", function() recovery:set_timeout(150) end)
