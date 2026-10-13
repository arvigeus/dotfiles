"""Exercise workspace navigation policy without moving real desktop windows."""
from pathlib import Path
import shutil
import subprocess
import unittest


POLICY = (Path(__file__).resolve().parents[1] / 'modules/desktop/hyprland'
          / 'symlinks/home/.config/hypr/workspaces.lua')

SETUP = r'''
local monitors = { { id = 0 }, { id = 1 } }
local workspaces, actions = {}, {}
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
    get_monitor = function(id) return monitors[id + 1] end,
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
        window = { move = function(args) return { "move", args } end },
    },
}
dofile(arg[1])
'''


@unittest.skipUnless(shutil.which('lua'), 'Lua is required for workspace policy tests')
class DesktopWorkspaceTests(unittest.TestCase):
    def run_policy(self, scenario):
        result = subprocess.run(['lua', '-', str(POLICY)], input=SETUP + scenario,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_single_empty_workspace_cannot_extend_in_either_direction(self):
        self.run_policy('''
focused.active_workspace = add(1, nil, 1)
DesktopWorkspaces.step(-1)
DesktopWorkspaces.step(1)
assert(#actions == 0)
''')

    def test_occupied_workspace_extends_with_lower_and_higher_ids(self):
        self.run_policy('''
focused.active_workspace = add(10000, nil, 1, 2)
DesktopWorkspaces.step(-1)
assert(selected() == 9999)
actions = {}
DesktopWorkspaces.step(1)
assert(selected() == 10001)
''')

    def test_empty_edge_allows_return_but_cannot_extend(self):
        self.run_policy('''
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
''')

    def test_adjacent_order_survives_gaps_and_policy_reload(self):
        self.run_policy('''
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
''')

    def test_empty_middle_allows_both_existing_neighbors(self):
        self.run_policy('''
local top = add(1, nil, 1, 1)
focused.active_workspace = add(2, nil, 1)
local bottom = add(3, nil, 1, 1)
DesktopWorkspaces.step(-1)
assert(selected() == top.id)
DesktopWorkspaces.step(1)
assert(selected() == bottom.id)
''')

    def test_monitor_scope_reserved_ids_and_global_collisions(self):
        self.run_policy('''
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
''')

    def test_move_requires_a_local_unpinned_window_and_follows(self):
        self.run_policy('''
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
''')

    def test_fresh_output_seeds_a_free_middle_id_and_restores_focus(self):
        self.run_policy('''
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
''')

    def test_numeric_boundaries_do_not_wrap_or_renumber(self):
        self.run_policy('''
focused.active_workspace = add(1, nil, 1, 1)
DesktopWorkspaces.step(-1)
assert(#actions == 0 and focused.active_workspace.id == 1)
focused.active_workspace = add(2147483646, nil, 1, 1)
DesktopWorkspaces.step(1)
assert(#actions == 0 and focused.active_workspace.id == 2147483646)
''')

    def test_empty_boundary_and_named_workspace_do_not_trigger_creation(self):
        self.run_policy('''
focused.active_workspace = add(1, nil, 1)
DesktopWorkspaces.step(-1)
assert(focused.active_workspace.id == 1 and #actions == 0)
focused.active_workspace = add(-1337, "desktop:0:0", 1, 1)
DesktopWorkspaces.step(1)
assert(#actions == 0)
''')

    def test_seeding_preserves_occupied_persistent_and_existing_stacks(self):
        self.run_policy('''
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
''')


if __name__ == '__main__':
    unittest.main()
