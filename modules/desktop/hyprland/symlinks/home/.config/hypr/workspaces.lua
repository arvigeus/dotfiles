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
    if monitorID == nil then monitor = hl.get_active_monitor()
    else monitor = hl.get_monitor(monitorID) end
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
