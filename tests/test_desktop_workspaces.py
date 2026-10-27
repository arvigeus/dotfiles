"""Exercise workspace navigation policy without moving real desktop windows."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


POLICY = (
    Path(__file__).resolve().parents[1]
    / 'modules/desktop/hyprland'
    / 'symlinks/home/.config/hypr/workspaces.lua'
)

SETUP = r"""
local monitors = { { id = 0, name = "DP-1" }, { id = 1, name = "DP-2" } }
local workspaces, actions, windows, timers = {}, {}, {}, {}
local focused, activeWindow = monitors[1], nil
local applyFocus, registered = false, {}
local function add(id, name, monitor, windows)
    local workspace = { id = id, name = name or tostring(id),
        monitor = monitors[monitor], windows = windows or 0 }
    table.insert(workspaces, workspace)
    return workspace
end
local function selected() return actions[#actions][2].workspace end
hl = {
    get_active_monitor = function() return focused end,
    get_monitors = function() return monitors end,
    on = function(event, callback) registered[event] = callback end,
    timer = function(callback, options)
        assert(options.type == "oneshot")
        local timer = { callback = callback, timeout = options.timeout, restarts = 0 }
        function timer:set_timeout(timeout) self.timeout = timeout; self.restarts = self.restarts + 1 end
        table.insert(timers, timer)
        return timer
    end,
    get_windows = function(filters)
        assert(filters.mapped and filters.floating)
        local result = {}
        for _, window in ipairs(windows) do
            if window.mapped and window.floating then table.insert(result, window) end
        end
        return result
    end,
    -- Bare numeric IDs from the bar do not reliably resolve as native selectors.
    get_monitor = function(name)
        for _, monitor in ipairs(monitors) do
            if name == monitor.name then return monitor end
        end
    end,
    get_active_window = function() return activeWindow end,
    get_workspaces = function() return workspaces end,
    get_workspace = function(selector)
        for _, workspace in ipairs(workspaces) do
            if selector == workspace.id then return workspace end
        end
    end,
    dispatch = function(action)
        table.insert(actions, action)
        if applyFocus and action[1] == "focus" then
            local args = action[2]
            if args.monitor then focused = monitors[args.monitor + 1] end
            if args.workspace then
                local workspace = hl.get_workspace(args.workspace)
                    or add(args.workspace, nil, focused.id + 1)
                focused.active_workspace = workspace
            end
        end
    end,
    dsp = {
        focus = function(args) return { "focus", args } end,
        window = {
            move = function(args) return { "move", args } end,
            resize = function(args) return { "resize", args } end,
        },
        workspace = { move = function(args) return { "workspace_move", args } end },
    },
}
dofile(arg[1])
local function panel(monitor, values)
    monitor.enabled, monitor.is_mirror = true, false
    monitor.x, monitor.y, monitor.width, monitor.height = 0, 0, 1920, 1080
    monitor.scale, monitor.transform = 1, 0
    monitor.reserved = { left = 0, top = 44, right = 0, bottom = 0 }
    for key, value in pairs(values or {}) do monitor[key] = value end
    return monitor
end
local function floating(workspace, x, y, width, height)
    local window = { address = tostring(#windows + 1), workspace = workspace,
        at = { x = x, y = y }, size = { x = width or 600, y = height or 400 },
        mapped = true, floating = true, hidden = false, fullscreen = 0 }
    table.insert(windows, window)
    return window
end
"""


@unittest.skipUnless(shutil.which('lua'), 'Lua is required for workspace policy tests')
class DesktopWorkspaceTests(unittest.TestCase):
    def run_policy(self, scenario):
        result = subprocess.run(
            ['lua', '-', str(POLICY)],
            input=SETUP + scenario,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recovery_moves_orphaned_workspaces_without_merging_or_changing_focus(self):
        self.run_policy("""
panel(monitors[1])
panel(monitors[2], { enabled = false })
focused.active_workspace = add(10000, nil, 1, 2)
add(20000, nil, 2, 3)
local missing = add(30000, nil, 2, 1); missing.monitor = nil
local special = add(-99, "special:scratch", 2, 1); special.special = true
DesktopWorkspaces.recover()
assert(#actions == 3)
assert(actions[1][1] == "workspace_move" and actions[1][2].workspace == 20000)
assert(actions[2][2].workspace == 30000 and actions[3][2].workspace == "special:scratch")
for _, action in ipairs(actions) do assert(action[2].monitor == "DP-1") end
assert(focused.active_workspace.id == 10000)
""")

    def test_fallback_and_mirrors_are_not_recovery_destinations(self):
        self.run_policy("""
panel(monitors[1], { name = "FALLBACK" })
panel(monitors[2], { is_mirror = true })
add(10000, nil, 1, 2)
DesktopWorkspaces.recover()
assert(#actions == 0)
panel(monitors[2])
DesktopWorkspaces.recover()
assert(#actions == 1 and actions[1][2].monitor == "DP-2")
""")

    def test_recovery_fits_stranded_floats_to_scaled_rotated_work_area(self):
        self.run_policy("""
panel(monitors[1], { x = -900, y = -100, width = 2560, height = 1600, scale = 1.25, transform = 1 })
panel(monitors[2], { enabled = false })
local workspace = add(10000, nil, 1, 2)
floating(workspace, 8000, 4000, 3000, 2500)
DesktopWorkspaces.recover()
assert(#actions == 2 and actions[1][1] == "resize" and actions[2][1] == "move")
assert(actions[1][2].x == 1280 and actions[1][2].y == 2004)
assert(actions[2][2].x == -900 and actions[2][2].y == -56)
assert(actions[1][2].relative == false and actions[2][2].relative == false)
assert(actions[2][2].window == "address:1")
""")

    def test_recovery_leaves_reachable_hidden_fullscreen_and_scrolling_windows_alone(
        self,
    ):
        self.run_policy("""
panel(monitors[1])
panel(monitors[2], { x = 1920 })
local workspace = add(10000, nil, 1, 6)
floating(workspace, 10, 60)
floating(workspace, 1800, 60) -- spans outputs
floating(workspace, 2200, 60) -- still reachable on the other output
floating(workspace, 8000, 0).hidden = true
floating(workspace, 8000, 0).fullscreen = 2
floating(workspace, 8000, 0).floating = false -- scrolling layout's intentional off-screen column
DesktopWorkspaces.recover()
assert(#actions == 0)
""")

    def test_recovery_runs_once_after_layout_events_settle(self):
        self.run_policy("""
assert(#timers == 1 and timers[1].timeout == 150)
panel(monitors[1]); panel(monitors[2], { enabled = false })
add(20000, nil, 2, 1)
registered["monitor.layout_changed"]()
registered["monitor.layout_changed"]()
assert(#actions == 0 and timers[1].restarts == 2)
timers[1].callback()
assert(#actions == 1 and actions[1][1] == "workspace_move")
""")

    def test_single_empty_workspace_cannot_extend_in_either_direction(self):
        self.run_policy("""
focused.active_workspace = add(1, nil, 1)
DesktopWorkspaces.step(-1)
DesktopWorkspaces.step(1)
assert(#actions == 0)
""")

    def test_occupied_workspace_extends_with_lower_and_higher_ids(self):
        self.run_policy("""
focused.active_workspace = add(10000, nil, 1, 2)
DesktopWorkspaces.step(-1)
assert(selected() == 9999)
actions = {}
DesktopWorkspaces.step(1)
assert(selected() == 10001)
""")

    def test_empty_edge_allows_return_but_cannot_extend(self):
        self.run_policy("""
local occupied = add(10000, nil, 1, 2)
focused.active_workspace = add(9999, nil, 1)
DesktopWorkspaces.step(-1)
assert(#actions == 0)
DesktopWorkspaces.step(1)
assert(selected() == occupied.id)
actions = {}
table.remove(workspaces, 2)
focused.active_workspace = add(10001, nil, 1)
DesktopWorkspaces.step(1)
assert(#actions == 0)
DesktopWorkspaces.step(-1)
assert(selected() == occupied.id)
""")

    def test_adjacent_order_survives_gaps_and_policy_reload(self):
        self.run_policy("""
local top = add(9990, nil, 1, 1)
local middle = add(10000, nil, 1, 1)
local bottom = add(10005, nil, 1, 1)
focused.active_workspace = top
dofile(arg[1])
DesktopWorkspaces.step(1)
assert(selected() == middle.id)
focused.active_workspace = middle
DesktopWorkspaces.step(1)
assert(selected() == bottom.id)
""")

    def test_empty_middle_allows_both_existing_neighbors(self):
        self.run_policy("""
local top = add(1, nil, 1, 1)
focused.active_workspace = add(2, nil, 1)
local bottom = add(3, nil, 1, 1)
DesktopWorkspaces.step(-1)
assert(selected() == top.id)
DesktopWorkspaces.step(1)
assert(selected() == bottom.id)
""")

    def test_monitor_scope_reserved_ids_and_global_collisions(self):
        self.run_policy("""
focused.active_workspace = add(10000, nil, 1, 1)
local special = add(-99, "special:scratch", 1, 1)
special.special = true
local other = add(20000, nil, 2, 1)
monitors[2].active_workspace = other
add(9999, nil, 2, 1)
add(9998, nil, 2, 1)
add(-1337, "desktop:0:0", 1, 1)
DesktopWorkspaces.step(-1)
assert(selected() == 9997)
DesktopWorkspaces.step(-1, 1)
assert(actions[#actions - 1][2].monitor == 1)
assert(selected() == 9999)
actions = {}
focused.active_special_workspace = special
DesktopWorkspaces.step(1)
focused.active_special_workspace = nil
DesktopWorkspaces.step(1, 999)
DesktopWorkspaces.step(0)
assert(#actions == 0)
""")

    def test_bar_targets_numeric_monitor_ids_in_both_directions(self):
        self.run_policy("""
focused.active_workspace = add(10000, nil, 1, 1)
monitors[2].id = 7
monitors[2].active_workspace = add(80000, nil, 2, 1)
DesktopWorkspaces.step(-1, 7)
assert(actions[#actions - 1][2].monitor == 7 and selected() == 79999)
DesktopWorkspaces.step(1, 7)
assert(actions[#actions - 1][2].monitor == 7 and selected() == 80001)
actions = {}
DesktopWorkspaces.step(1, 999)
assert(#actions == 0)
""")

    def test_move_requires_a_local_unpinned_window_and_follows(self):
        self.run_policy("""
focused.active_workspace = add(1, nil, 1, 1)
DesktopWorkspaces.step(1, nil, true)
assert(#actions == 0)
activeWindow = { workspace = focused.active_workspace, pinned = true }
DesktopWorkspaces.step(1, nil, true)
assert(#actions == 0)
activeWindow.pinned = false
DesktopWorkspaces.step(1, nil, true)
assert(actions[#actions][1] == "move")
assert(selected() == 2)
assert(actions[#actions][2].follow)
actions = {}
activeWindow.workspace = add(9, nil, 2, 1)
DesktopWorkspaces.step(1, nil, true)
assert(#actions == 0)
""")

    def test_fresh_output_seeds_a_free_middle_id_and_restores_focus(self):
        self.run_policy("""
focused.active_workspace = add(10000, nil, 1, 1)
monitors[2].active_workspace = add(2, nil, 2)
add(20000, nil, 1, 1)
add(29999, nil, 1, 1)
activeWindow = { address = "0x123", workspace = focused.active_workspace }
applyFocus = true
registered["monitor.added"](monitors[2])
assert(monitors[2].active_workspace.id == 40000)
assert(focused == monitors[1] and actions[#actions][2].window == "address:0x123")
actions = {}
DesktopWorkspaces.seed(monitors[2])
assert(#actions == 0)
""")

    def test_numeric_boundaries_do_not_wrap_or_renumber(self):
        self.run_policy("""
focused.active_workspace = add(1, nil, 1, 1)
DesktopWorkspaces.step(-1)
assert(#actions == 0 and focused.active_workspace.id == 1)
focused.active_workspace = add(2147483646, nil, 1, 1)
DesktopWorkspaces.step(1)
assert(#actions == 0 and focused.active_workspace.id == 2147483646)
""")

    def test_empty_boundary_and_named_workspace_do_not_trigger_creation(self):
        self.run_policy("""
focused.active_workspace = add(1, nil, 1)
DesktopWorkspaces.step(-1)
assert(focused.active_workspace.id == 1 and #actions == 0)
focused.active_workspace = add(-1337, "desktop:0:0", 1, 1)
DesktopWorkspaces.step(1)
assert(#actions == 0)
""")

    def test_seeding_preserves_occupied_persistent_and_existing_stacks(self):
        self.run_policy("""
focused.active_workspace = add(1, nil, 1, 1)
DesktopWorkspaces.seed(focused)
assert(#actions == 0)
focused.active_workspace.windows = 0
focused.active_workspace.is_persistent = true
DesktopWorkspaces.seed(focused)
assert(#actions == 0)
focused.active_workspace.is_persistent = false
add(2, nil, 1, 1)
DesktopWorkspaces.seed(focused)
assert(#actions == 0)
""")


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(shutil.which('lua'), 'Lua is required for configuration tests')
class ConfigurationLoadTests(unittest.TestCase):
    def test_components_and_input_policy_load_through_require(self):
        hypr = POLICY.parent
        method = (
            POLICY.parents[7]
            / 'modules/hardware/keyboard/input-method/symlinks/home/.config/hypr'
        )
        with tempfile.TemporaryDirectory() as runtime:
            state = Path(runtime) / 'input-method/hyprland-a_b'
            state.mkdir(parents=True)
            (state / 'secondary').write_text('vi\n')
            script = f"""
package.path = {str(hypr / '?.lua')!r} .. ";" .. {str(method / '?.lua')!r}
local layouts = {{}}
local stub
stub = setmetatable({{}}, {{ __index = function() return stub end, __call = function() return stub end }})
hl = setmetatable({{
    config = function(values)
        if values.input and values.input.kb_layout then table.insert(layouts, values.input.kb_layout) end
    end,
    get_monitors = function() return {{}} end,
    get_workspaces = function() return {{}} end,
}}, {{ __index = function() return stub end }})
dofile({str(hypr / 'hyprland.lua')!r})
for _, name in ipairs({{"monitors", "appearance", "animations", "layout", "workspaces", "input", "bindings", "windows", "input-method"}}) do
    assert(package.loaded[name], name)
end
assert(not package.loaded["host-monitors"] and not package.loaded["displays"])
assert(layouts[#layouts] == "us", "saved Vietnamese selection not reapplied")
InputMethod.apply("bg")
assert(layouts[#layouts] == "us,bg")
"""
            result = subprocess.run(
                ['lua', '-'],
                input=script,
                text=True,
                capture_output=True,
                env=dict(
                    os.environ,
                    XDG_RUNTIME_DIR=runtime,
                    HYPRLAND_INSTANCE_SIGNATURE='a/b',
                ),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
