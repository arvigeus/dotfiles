"""Display safety and production QML, with no host monitor mutations."""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import DESKTOP, QS, backend, described, display, state
import support


class DisplayBackendTests(unittest.TestCase):
    def setUp(self):
        self.rows = [display(), display('DP-1', x=1920)]
        self.state = state(self.rows)

    def request(self, rows=None):
        return dict(op='apply', token=self.state['token'], displays=copy.deepcopy(rows or self.rows))

    def test_snapshot_keeps_disabled_outputs_and_modes(self):
        raw = [dict(name='DP-1', width=1920, height=1080, refreshRate=59.999, scale=1.25, transform=1,
                    description='Monitor <&>', availableModes=['1920x1080@60.00Hz', 'bad', '1920x1080@60.00Hz']),
               dict(name='eDP-1', disabled=True, width=0, height=0, availableModes=['2560x1440@60.00Hz'])]
        with patch.object(backend, 'command', return_value=json.dumps(raw)):
            result = backend.snapshot()
        self.assertEqual(result['displays'][0]['mode'], '1920x1080@60.00Hz')
        self.assertEqual(result['displays'][0]['label'], 'Monitor <&>')
        self.assertEqual(result['displays'][1]['mode'], '2560x1440@60.00Hz')
        self.assertFalse(result['displays'][1]['enabled'])

    def test_invisible_fallback_is_excluded_from_inventory_and_safety(self):
        raw = [dict(id=-1, name='FALLBACK', width=1920, height=1080, refreshRate=60),
               dict(id=0, name='eDP-1', disabled=True, width=0, height=0,
                    availableModes=['2560x1600@120.00Hz'])]
        with patch.object(backend, 'command', return_value=json.dumps(raw)):
            result = backend.snapshot()
        self.assertEqual([row['name'] for row in result['displays']], ['eDP-1'])
        self.assertFalse(result['displays'][0]['enabled'])
        with self.assertRaisesRegex(ValueError, 'at least one display'):
            backend.validate(dict(token=result['token'], displays=result['displays']), result)

    def test_rejects_stale_and_invalid_actions_before_mutation(self):
        cases = []
        request = self.request(); request['token'] = 'stale'; cases.append(request)
        request = self.request(); request['displays'].pop(); cases.append(request)
        request = self.request(); request['displays'][1] = request['displays'][0]; cases.append(request)
        for values in ({'mode': '1920x1080@999Hz'}, {'scale': True}, {'scale': float('nan')}, {'scale': 0},
                       {'scale': 1.3}, {'transform': 8}, {'x': 1.5}, {'y': 99999}, {'enabled': 'false'}):
            request = self.request(); request['displays'][0].update(values); cases.append(request)
        request = self.request(); [row.update(enabled=False) for row in request['displays']]; cases.append(request)
        request = self.request(); request['displays'][1]['x'] = 100; cases.append(request)
        with patch.object(backend, 'snapshot', return_value=self.state), patch.object(backend, 'apply_rows') as apply:
            for request in cases:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    backend.validate(request, self.state)
            apply.assert_not_called()

    def test_modes_scale_rotation_and_negative_placement(self):
        request = self.request()
        request['displays'][0].update(scale=1.25, transform=1, x=-864, y=0)
        request['displays'][1].update(x=0, mode='1920x1080@120.00Hz')
        checked = backend.validate(request, self.state)
        self.assertEqual(backend.dimensions(checked[0]), (864, 1536))
        self.assertEqual(checked[1]['mode'], '1920x1080@120.00Hz')

    def test_mutations_enable_before_disabling_and_quote_names(self):
        rows = [display('old', enabled=False), display('new";os.execute("bad")')]
        with patch.object(backend, 'command', return_value='ok') as command, patch.object(backend, 'snapshot', return_value=state([rows[1]])):
            backend.apply_rows(rows, backend.selectors(rows))
        self.assertEqual(command.call_count, 2)
        self.assertIn('disabled = false', command.call_args_list[0].args[1])
        self.assertIn('disabled = true', command.call_args_list[1].args[1])
        self.assertIn('output = "new\\034;os.execute(\\034bad\\034)"', command.call_args_list[0].args[1])
        self.assertNotIn('"bad"', command.call_args_list[0].args[1])

    def test_failed_replacement_never_disables_existing_screen(self):
        rows = [display('old', enabled=False), display('new')]
        actual = state([display('old'), display('new', enabled=False)])
        with patch.object(backend, 'command', return_value='ok') as command, \
                patch.object(backend, 'snapshot', return_value=actual), \
                patch.object(backend.time, 'monotonic', side_effect=[0, 4]):
            with self.assertRaisesRegex(ValueError, 'replacement'):
                backend.apply_rows(rows, backend.selectors(rows))
        self.assertEqual(command.call_count, 1)
        self.assertNotIn('disabled = true', command.call_args.args[1])

    def test_successful_change_is_immediate_and_leaves_settings_applied(self):
        expected = copy.deepcopy(self.rows)
        expected[0]['mode'] = '1920x1080@120.00Hz'
        request = dict(name='eDP-1', identity=self.rows[0]['identity'], values=dict(mode=expected[0]['mode']))
        with patch.object(backend, 'snapshot', side_effect=[self.state, state(expected)]), patch.object(backend, 'apply_rows') as apply:
            result = backend.control(request)
        self.assertEqual(result['displays'], expected)
        apply.assert_called_once_with([expected[0]], backend.selectors(self.rows))

    def test_four_hundred_percent_scale_uses_quarter_sized_logical_desktop(self):
        before = state([display(mode='2560x1600@60.00Hz', modes=['2560x1600@60.00Hz'])])
        rows = backend.prepare_change(dict(name='eDP-1', identity=before['displays'][0]['identity'], values=dict(scale=4)), before)
        self.assertEqual(backend.dimensions(rows[0]), (640, 400))

    def test_recommended_mode_uses_native_preference_and_preserves_geometry_gaps(self):
        modes = ['3840x2160@60.00Hz', '2560x1440@74.98Hz', '2560x1440@59.95Hz', '800x600@60.32Hz']
        before = state([display('DP-1', mode=modes[-1], modes=modes, scale=1.25, transform=1),
                        display('eDP-1', x=500)])
        request = dict(name='DP-1', identity=before['displays'][0]['identity'], values=dict(mode='preferred'))
        with patch.object(backend, 'command', return_value='2560x1440@59.95100') as command:
            rows = backend.prepare_change(request, before)
        self.assertEqual(command.call_args.args[0], 'repl')
        self.assertIn('mode.preferred', command.call_args.args[1])
        self.assertEqual(rows[0]['mode'], modes[2])
        self.assertEqual((rows[0]['scale'], rows[0]['transform'], rows[0]['mirror']), (1.25, 1, 'none'))
        self.assertEqual(rows[1]['x'], 1172)
        self.assertEqual(request['values']['mode'], 'preferred')

    def test_unavailable_recommendation_never_mutates(self):
        request = dict(name='eDP-1', identity=self.rows[0]['identity'], values=dict(mode='preferred'))
        with patch.object(backend, 'snapshot', return_value=self.state), patch.object(backend, 'apply_rows') as apply:
            for reply in ('', 'ok', '3840x2160@60.00000', '1920x1080@75.00000'):
                with self.subTest(reply=reply), patch.object(backend, 'command', return_value=reply):
                    with self.assertRaisesRegex(ValueError, 'recommended mode'):
                        backend.control(request)
            apply.assert_not_called()

    def test_failed_modeset_restores_previous_settings(self):
        request = dict(name='eDP-1', identity=self.rows[0]['identity'], values=dict(mode='1920x1080@120.00Hz'))
        with patch.object(backend, 'snapshot', return_value=self.state), \
                patch.object(backend, 'apply_rows', side_effect=[RuntimeError('rejected'), None]) as apply:
            with self.assertRaisesRegex(RuntimeError, 'rejected'):
                backend.control(request)
            self.assertEqual(apply.call_count, 2)
            self.assertEqual(apply.call_args.args[0], self.rows)

    def test_resize_preserves_gaps_to_neighboring_displays(self):
        rows = backend.prepare_change(dict(name='eDP-1', identity=self.rows[0]['identity'], values=dict(scale=0.5)), self.state)
        self.assertEqual(rows[1]['x'], 3840)
        self.assertEqual(rows[1]['y'], 0)
        self.assertEqual(rows[1]['mode'], self.rows[1]['mode'])

    def test_enable_places_only_that_output_beside_existing_displays(self):
        before = state([display(), display('DP-1', enabled=False, x=0)])
        rows = backend.prepare_change(dict(name='DP-1', identity=before['displays'][1]['identity'], values=dict(enabled=True)), before)
        self.assertEqual(rows[0], before['displays'][0])
        self.assertEqual(rows[1]['x'], 1920)
        self.assertTrue(rows[1]['enabled'])

    def test_stale_identity_and_unsupported_changes_never_mutate(self):
        requests = [dict(name='eDP-1', identity=['changed'], values=dict(scale=1)),
                    dict(name='gone', identity=[], values=dict(enabled=True)),
                    dict(name='eDP-1', identity=self.rows[0]['identity'], values=dict(x=100)),
                    dict(name='eDP-1', identity=self.rows[0]['identity'], values=dict(scale=True))]
        with patch.object(backend, 'snapshot', return_value=self.state), patch.object(backend, 'apply_rows') as apply:
            for request in requests:
                with self.subTest(request=request), self.assertRaises(ValueError): backend.control(request)
            apply.assert_not_called()

    def test_failed_change_restore_keeps_remaining_output_enabled_after_unplug(self):
        before = state([display(), display('DP-1', enabled=False, x=1920)])
        current = state([display('DP-1', x=1920)])
        with patch.object(backend, 'snapshot', return_value=current), patch.object(backend, 'apply_rows') as apply:
            backend.restore(before)
            self.assertEqual(apply.call_args.args[0], current['displays'])

    def test_replaced_hardware_is_not_restored_using_an_old_identity(self):
        replacement = display('DP-1', identity=['DP-1', 'new monitor', '', '', '456'], x=0)
        with patch.object(backend, 'snapshot', return_value=state([replacement])), patch.object(backend, 'apply_rows') as apply:
            backend.restore(self.state)
            self.assertEqual(apply.call_args.args[0], [replacement])

    def test_status_and_unknown_operations_do_not_mutate_hardware(self):
        with patch.object(backend, 'snapshot', return_value=self.state), patch.object(backend, 'apply_rows') as apply:
            self.assertEqual(backend.handle(dict(op='status')), dict(data=self.state))
            for op in ('begin', 'commit', 'cancel', 'unknown', 'restore', 'sync'):
                result = backend.response(dict(op=op))
                self.assertFalse(result['ok'])
                self.assertEqual(result['data'], self.state)
            apply.assert_not_called()

    def test_mirrors_validate_targets_cycles_and_last_independent_display(self):
        request = self.request()
        request['displays'][1].update(mirror='eDP-1', x=0)
        checked = backend.validate(request, self.state)
        self.assertEqual(checked[1]['mirror'], 'eDP-1')
        for target in ('missing', 'DP-1'):
            request['displays'][1]['mirror'] = target
            with self.assertRaisesRegex(ValueError, 'enabled display'):
                backend.validate(request, self.state)
        request['displays'][1]['mirror'] = 'eDP-1'
        request['displays'][0]['mirror'] = 'DP-1'
        with self.assertRaisesRegex(ValueError, 'mirror source'):
            backend.validate(request, self.state)
        request['displays'][0].update(mirror='none', enabled=False)
        with self.assertRaisesRegex(ValueError, 'enabled display'):
            backend.validate(request, self.state)

    def test_mirror_ids_become_names_and_mirror_coordinates_are_not_compared(self):
        raw = [dict(id=0, name='eDP-1', width=1920, height=1080, refreshRate=60, availableModes=['1920x1080@60.00Hz']),
               dict(id=2, name='DP-1', width=1920, height=1080, refreshRate=60, mirrorOf='0', availableModes=['1920x1080@60.00Hz'])]
        with patch.object(backend, 'command', return_value=json.dumps(raw)):
            result = backend.snapshot()
        self.assertEqual(result['displays'][1]['mirror'], 'eDP-1')
        expected = copy.deepcopy(result['displays'])
        expected[1]['x'] = 1920
        self.assertTrue(backend.matches(expected, result))

    def test_worker_exits_after_request_without_waiting_for_eof_and_keeps_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / 'worker.py'
            helper.write_text('import importlib.util\n'
                              f'spec=importlib.util.spec_from_file_location("backend", {str(DESKTOP / "drawers/displays/backend.py")!r})\n'
                              'b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)\n'
                              f'rows={self.rows!r}\n'
                              f'log={str(root / "calls.jsonl")!r}\n'
                              'def snapshot(): return dict(available=True,displays=rows,token=b.fingerprint(rows))\n'
                              'def apply(values, names):\n'
                              ' global rows\n'
                              ' rows=[next((row for row in values if row["name"]==old["name"]),old) for old in rows]\n'
                              ' with open(log,"a") as f: f.write(b.json.dumps(rows)+"\\n")\n'
                              'b.snapshot=snapshot; b.apply_rows=apply; b.main()\n')
            request = dict(op='change', name='eDP-1', identity=self.rows[0]['identity'], values=dict(mode='1920x1080@120.00Hz'))
            with subprocess.Popen([sys.executable, '-u', str(helper)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env={**os.environ, 'XDG_RUNTIME_DIR': str(root), 'XDG_CONFIG_HOME': str(root / 'config')}) as process:
                process.stdin.write(json.dumps(request) + '\n'); process.stdin.flush()
                # Keep stdin open: a resident worker would time out here.
                self.assertEqual(process.wait(timeout=8), 0, process.stderr.read())
                result = json.loads(process.stdout.read())
                self.assertTrue(result['ok'], result['error'])
                self.assertEqual(result['data']['displays'][0]['mode'], '1920x1080@120.00Hz')
            calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
            self.assertEqual(calls[0][0]['mode'], '1920x1080@120.00Hz')
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[-1][0]['mode'], '1920x1080@120.00Hz')
            self.assertIn('output = "eDP-1", disabled = false, mode = "1920x1080@120.00"',
                          (root / 'config/hypr/displays.lua').read_text())


class DisplayRulesTests(unittest.TestCase):
    """Confirmed layouts become Hyprland rules in the user-owned displays.lua."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        environment = patch.dict(os.environ, XDG_CONFIG_HOME=str(self.root))
        environment.start(); self.addCleanup(environment.stop)
        self.path = self.root / 'hypr/displays.lua'
        self.panel = described('eDP-1', 'Panel Co P1', mode='1920x1080@120.00Hz', scale=1.25)
        self.external = described('DP-1', 'Dell Inc. DELL U1 X1', x=1536)
        self.current = state([self.panel, self.external])

    def lines(self):
        return self.path.read_text().splitlines()

    def test_selectors_use_unique_descriptions_and_fall_back_to_connectors(self):
        rows = [described('eDP-1', 'Panel'), described('DP-1', 'Dell U1'), described('DP-2', 'Dell U1 X2'),
                described('DP-3', ''), described('HDMI-A-1', 'Twin'), described('HDMI-A-2', 'Twin')]
        self.assertEqual(backend.selectors(rows), {
            'eDP-1': 'desc:Panel', 'DP-1': 'DP-1', 'DP-2': 'desc:Dell U1 X2', 'DP-3': 'DP-3',
            'HDMI-A-1': 'HDMI-A-1', 'HDMI-A-2': 'HDMI-A-2'})

    def test_xdg_path_is_user_owned_and_empty_or_relative_values_use_home(self):
        self.assertEqual(backend.config_path(), self.path)
        for value in ('', 'relative'):
            with self.subTest(value=value), patch.dict(os.environ, XDG_CONFIG_HOME=value), \
                    patch.object(backend.Path, 'home', return_value=self.root / 'home'):
                self.assertEqual(backend.config_path(), self.root / 'home/.config/hypr/displays.lua')

    def test_confirmed_change_saves_every_connected_output_as_a_desc_rule(self):
        request = dict(op='change', name='DP-1', identity=self.external['identity'], values=dict(scale=1))
        with patch.object(backend, 'control', return_value=self.current):
            result = backend.response(request)
        self.assertTrue(result['ok'], result['error'])
        self.assertEqual(self.lines(), backend.HEADER + [
            'hl.monitor({ output = "desc:Panel Co P1", disabled = false, mode = "1920x1080@120.00", position = "0x0", scale = 1.25, transform = 0, mirror = "" })',
            'hl.monitor({ output = "desc:Dell Inc. DELL U1 X1", disabled = false, mode = "1920x1080@60.00", position = "1536x0", scale = 1, transform = 0, mirror = "" })'])
        self.assertEqual([path.name for path in self.path.parent.iterdir()], ['displays.lua'])

    def test_unrelated_lines_survive_and_known_rules_are_replaced_in_place(self):
        self.path.parent.mkdir()
        self.path.write_text('-- mine\nhl.monitor({ output = "desc:Dell Inc. DELL U1 X1", mode = "preferred" })\n'
                             'hl.monitor({ output = "desc:Office", mode = "preferred" })\nlocal x = 1\n')
        backend.persist(self.current, False)
        lines = self.lines()
        self.assertEqual(lines[0], '-- mine')
        self.assertIn('position = "1536x0"', lines[1])
        self.assertEqual(lines[2:4], ['hl.monitor({ output = "desc:Office", mode = "preferred" })', 'local x = 1'])
        self.assertIn('output = "desc:Panel Co P1"', lines[4])
        self.assertEqual(len(lines), 5)

    def test_builtin_panel_is_never_saved_disabled(self):
        self.path.parent.mkdir()
        saved = 'hl.monitor({ output = "desc:Panel Co P1", disabled = false, mode = "1920x1080@120.00" })'
        self.path.write_text(saved + '\n')
        backend.persist(state([dict(self.panel, enabled=False), self.external]), False)
        self.assertEqual(self.lines()[0], saved)
        self.assertEqual(sum('Panel Co P1' in line for line in self.lines()), 1)
        backend.persist(state([self.panel, dict(self.external, enabled=False)]), False)
        self.assertIn('hl.monitor({ output = "desc:Dell Inc. DELL U1 X1", disabled = true })', self.lines())

    def test_mirror_rules_target_the_source_selector(self):
        mirrored = state([self.panel, dict(self.external, mirror='eDP-1', x=0)])
        backend.persist(mirrored, False)
        self.assertIn('mirror = "desc:Panel Co P1"', self.lines()[-1])

    @unittest.skipUnless(shutil.which('lua'), 'Lua is required')
    def test_saved_file_is_valid_lua_with_exact_selectors(self):
        odd = described('DP-2', 'Odd "quoted" \\ Café', x=3456)
        backend.persist(state([self.panel, self.external, odd]), False)
        script = 'local outputs = {}\nhl = {monitor = function(rule) outputs[#outputs + 1] = rule.output end}\n' \
                 'dofile(arg[1])\nprint(table.concat(outputs, "\\n"))\n'
        result = subprocess.run(['lua', '-', str(self.path)], input=script, text=True, capture_output=True, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['desc:Panel Co P1', 'desc:Dell Inc. DELL U1 X1', 'desc:Odd "quoted" \\ Café'])

    def test_failed_change_is_not_saved(self):
        with patch.object(backend, 'control', side_effect=ValueError('rejected')), \
                patch.object(backend, 'snapshot', return_value=self.current):
            result = backend.response(dict(op='change'))
        self.assertFalse(result['ok'])
        self.assertFalse(self.path.exists())

    def test_write_failure_preserves_existing_file_and_cleans_temporary(self):
        self.path.parent.mkdir()
        self.path.write_text('-- previous\n')
        with patch.object(backend.os, 'replace', side_effect=OSError('disk full')), self.assertRaises(OSError):
            backend.persist(self.current, False)
        self.assertEqual(self.path.read_text(), '-- previous\n')
        self.assertEqual([path.name for path in self.path.parent.iterdir()], ['displays.lua'])

    def test_save_validates_then_makes_live_rules_match_the_saved_layout(self):
        overlapping = state([self.panel, dict(self.external, x=0)])
        with patch.object(backend, 'snapshot', return_value=overlapping), patch.object(backend, 'apply_rows') as apply:
            self.assertFalse(backend.response(dict(op='save'))['ok'])
        apply.assert_not_called()
        self.assertFalse(self.path.exists())
        with patch.object(backend, 'snapshot', return_value=self.current), patch.object(backend, 'apply_rows') as apply:
            result = backend.response(dict(op='save'))
        self.assertTrue(result['ok'], result['error'])
        apply.assert_called_once_with(self.current['displays'], backend.selectors(self.current['displays']))
        self.assertEqual(len(self.lines()), len(backend.HEADER) + 2)

    def test_ensure_reenables_the_panel_only_when_no_display_is_usable(self):
        with patch.object(backend, 'command', return_value='ok') as command, patch.object(backend, 'snapshot') as snapshot:
            self.assertIs(backend.ensure(self.current), self.current)
            command.assert_not_called()
            dark = state([dict(self.external, enabled=False), dict(self.panel, enabled=False)])
            backend.ensure(dark)
        command.assert_called_once_with('eval', 'hl.monitor({ output = "desc:Panel Co P1", disabled = false })')
        snapshot.assert_called_once()


@unittest.skipUnless(shutil.which('lua'), 'Lua is required')
class DisplayEventBridgeTests(unittest.TestCase):
    def test_native_hook_forwards_only_when_compositor_reports_change(self):
        monitors = DESKTOP.parents[5] / 'hyprland/symlinks/home/.config/hypr/monitors.lua'
        # Read the production hook with an isolated config directory and native
        # API stand-ins. Dispatching the notification cannot launch a process.
        script = '''local callback, dispatches, rules = nil, 0, 0
hl = {
    monitor = function(rule) rules = rules + 1 end,
    on = function(name, action)
        assert(name == "monitor.layout_changed")
        assert(callback == nil)
        callback = action
    end,
    dsp = {event = function(name) return {notification = name} end},
    dispatch = function(event)
        assert(event.notification == "desktop-displays-changed")
        dispatches = dispatches + 1
    end,
}
dofile(arg[1])
assert(rules == 1 and callback ~= nil and dispatches == 0)
callback()
assert(dispatches == 1)
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['lua', '-', str(monitors)], input=script, text=True, capture_output=True,
                                    timeout=4, env={**os.environ, 'XDG_CONFIG_HOME': directory})
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(QS, 'Quickshell is required')
class DisplayQmlTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_flat_menu_closes_on_selection_and_escape_keeps_changes(self):
        rows = json.dumps([display(), display('DP-1', x=1920)])
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:displayWindow.contentItem }
 QtObject {
  id:mock
  property var state: ({available:true,displays:ROWS,token:"initial"})
  property bool loaded:true
  property bool busy:false
  property string error:""
  property var owners:[]
  readonly property int observers:owners.length
  property int calls:0
  property var lastValues: ({})
  property int brightnessCalls:0
  function brightnessFor(name) {return {available:name==="eDP-1",value:60,reason:"DDC/CI unavailable"};}
  function setBrightness(name,value) {brightnessCalls++;}
  function observe(owner,active) {owners=owners.filter(item=>item!==owner).concat(active?[owner]:[]);}
  function change(record,values) {
   calls++;
   lastValues=values;
   const applied=values.mode==="preferred"?{mode:record.modes[0]}:values;
   state={available:true,displays:state.displays.map(row=>row.name===record.name?Object.assign({},row,applied):row),token:String(calls)};
  }
  function refresh(){}
 }
 FloatingWindow {
  id:displayWindow
  implicitWidth:480;implicitHeight:900;visible:true;color:Theme.background
  DisplaysDrawer{id:drawer;x:16;y:16;width:448;height:400;active:true;service:mock}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){
  if(item.objectName===name)return item;
  for(let child of item.children??[]){const found=find(child,name);if(found)return found;}
  return null;
 }
 function choose(key){
  const entry=drawer.optionsFor(drawer.displays[1]).find(entry=>entry.key===key);
  if(!entry)throw new Error("missing option "+key);
  const button=find(drawer,"displayOptions:DP-1");
  if(!button.menu.visible)button.clicked();
  button.menu.activate(entry);
  check(!button.menu.visible,"menu stayed open on selection");
 }
 property int stage:0
 Timer{interval:180;repeat:true;running:true;onTriggered:{
  try{
   const button=find(drawer,"displayOptions:DP-1");
   if(stage===0){
    const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
    if(destination)drawer.grabToImage(result=>result.saveToFile(destination+"/displays-normal.png"));
   }else if(stage===1){
    check(drawer.displays.length===2,"inventory");
    check(!find(drawer,"displayApply")&&!find(drawer,"displayCountdown")&&!find(drawer,"displayUndoHint"),"staged controls remain");
    check(!find(drawer,"displayResolution:DP-1"),"separate controls remain");
    const brightness=find(drawer,"displayBrightness:DP-1");
    check(button.mapToItem(drawer,0,0).y===brightness.mapToItem(drawer,0,0).y,"cog not beside brightness");
    button.clicked();
   }else if(stage===2){
    check(button.menu.visible&&drawer.escapeHandler,"menu did not take Escape");
    const list=find(button.menu.contentItem,"displayOptionsList:DP-1");
    let headings=0,separators=0;
    for(let i=0;i<list.model.count;i++){
     const record=list.model.get(i).record;
     if(record.kind==="heading")headings++;
     if(record.kind==="separator")separators++;
    }
    check(headings===3&&separators===3,"flat sections incorrect");
    const card=find(drawer,"displayCard:DP-1");
    const rate=list.itemAtIndex(5);
    check(rate&&rate.record.key==="rate:1920x1080@120.00Hz","refresh rate row missing");
    input.mouseClick(rate,rate.width/2,rate.height/2);
    check(mock.calls===1&&drawer.displays[1].mode==="1920x1080@120.00Hz","refresh rate not immediate");
    check(!button.menu.visible,"menu stayed open on selection");
    choose("mirror:eDP-1");
    check(mock.calls===2&&drawer.displays[1].mirror==="eDP-1","settings not immediate");
    check(find(drawer,"displayCard:DP-1")===card,"card recreated during changes");
    check(!button.menu.visible,"menu stayed open after settings");
   }else if(stage===3){
    button.clicked();
    check(button.menu.height<=displayWindow.height-16,"menu not constrained");
    const list=find(button.menu.contentItem,"displayOptionsList:DP-1");
    check(list.contentHeight<=list.height+1,"short menu still needs scrolling: content="+list.contentHeight+" height="+list.height+" menu="+button.menu.height+" items="+button.menu.itemsHeight);
    const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
    if(destination)button.menu.contentItem.grabToImage(result=>result.saveToFile(destination+"/displays-menu.png"));
   }else if(stage===4){
    button.menu.contentItem.forceActiveFocus();
    input.keyClick(Qt.Key_Escape);
    check(!button.menu.visible,"Escape did not close menu");
    check(drawer.displays[1].mode==="1920x1080@120.00Hz"&&drawer.displays[1].scale===1&&drawer.displays[1].transform===0&&drawer.displays[1].mirror==="eDP-1","Escape changed applied settings");
    check(drawer.active&&!drawer.escapeHandler,"Escape closed drawer or retained handler");
    choose("rate:1920x1080@60.00Hz");
    button.clicked();input.mouseClick(button,button.width/2,button.height/2);
    check(!button.menu.visible&&drawer.displays[1].mode==="1920x1080@60.00Hz","second cog click changed settings");
   }else if(stage===5){
    choose("extend");button.clicked();
   }else if(stage===6){
    input.mouseClick(drawer,2,drawer.height-2);
    check(!button.menu.visible&&drawer.displays[1].mirror==="none","outside click changed settings");
    drawer.width=268;
   }else if(stage===7){
    const recommended=drawer.optionsFor(drawer.displays[1]).find(entry=>entry.key==="recommended");
    check(recommended&&recommended.text==="Use recommended resolution"&&recommended.kind==="action","recommended action missing");
    choose("recommended");
    check(mock.lastValues.mode==="preferred"&&Object.keys(mock.lastValues).length===1,"recommendation changed unrelated settings");
    check(drawer.displays[1].mode==="1920x1080@60.00Hz","recommendation not applied");
    const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
    if(destination)drawer.grabToImage(result=>result.saveToFile(destination+"/displays-narrow.png"));
    find(drawer,"displayBrightness:eDP-1:slider").moved();
    check(mock.brightnessCalls===1,"brightness missing");
    const toggle=find(drawer,"displayEnabled:DP-1");
    input.mouseClick(toggle,toggle.width/2,toggle.height/2);
    check(!drawer.displays[1].enabled,"disable was not immediate");
    input.mouseClick(toggle,toggle.width/2,toggle.height/2);
    check(drawer.displays[1].enabled,"enable was not immediate");
    check(!find(drawer,"displayBrightness:DP-1:slider").enabled,"unsupported brightness enabled");
   }else if(stage===8){
    mock.state={available:true,displays:[mock.state.displays[0]],token:"unplugged"};
    check(drawer.displays.length===1&&!find(drawer,"displayCard:DP-1"),"hotplug not reconciled");
    check(!find(drawer,"displayEnabled:eDP-1").enabled,"last display can be disabled");
    drawer.active=false;check(mock.observers===0,"observation survived dismissal");finish.start();
   }
   stage++;
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}
 }}
 Timer{id:finish;interval:100;onTriggered:{console.log("DISPLAY_PASS");Qt.quit();}}
 Timer{interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
'''.replace('ROWS',rows))

    def test_long_menu_fits_window_and_bottom_entry_is_reachable(self):
        modes = [f'2560x1600@{rate}.00Hz' for rate in range(60, 181, 10)]
        rows = json.dumps([display(), display('DP-1', x=1920, mode=modes[0], modes=modes)])
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:displayWindow.contentItem }
 QtObject {
  id:mockTests
  property string mode:""
  property string error:""
  property int calls:0
  property string output:""
  function start(kind,record){mode=kind;output=record.name;calls++;return true;}
  function identify(records){mode="identify";calls++;}
  function stop(){mode="";}
 }
 QtObject {
  id:mock
  property var state: ({available:true,displays:ROWS,token:"initial"})
  property bool loaded:true
  property bool busy:false
  property string error:""
  property int calls:0
  function brightnessFor(name) {return {available:false,value:0,reason:"Unavailable"};}
  function setBrightness(name,value) {}
  function observe(owner,active) {}
  function change(record,values) {
   calls++;
   state={available:true,displays:state.displays.map(row=>row.name===record.name?Object.assign({},row,values):row),token:String(calls)};
  }
  function refresh(){}
 }
 FloatingWindow {
  id:displayWindow
  implicitWidth:480;implicitHeight:540;visible:true;color:Theme.background
  DisplaysDrawer{id:drawer;x:16;y:displayWindow.height-height-8;width:448;height:400;active:true;service:mock;displayTests:mockTests}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){
  if(item.objectName===name)return item;
  for(let child of item.children??[]){const found=find(child,name);if(found)return found;}
  return null;
 }
 function checkBounds(menu){
  const point=menu.contentItem.mapToItem(displayWindow.contentItem,-menu.leftPadding,-menu.topPadding);
  check(point.x>=7&&point.y>=7,"popup exceeds top/left edge");
  check(point.x+menu.width<=displayWindow.width-7&&point.y+menu.height<=displayWindow.height-7,"popup exceeds bottom/right edge");
    check(menu.height<=560&&menu.height<=displayWindow.height-16,"popup too tall");
 }
 property int stage:0
 Timer{interval:180;repeat:true;running:true;onTriggered:{
  try{
   const button=find(drawer,"displayOptions:DP-1");
   if(stage===0){
    const record=drawer.displays[1];
    const entries=drawer.optionsFor(record);
    check(!entries.some(entry=>/^(resolution:|scale:|rotation:|flipped$)/.test(entry.key)),"advanced controls remain");
    const rates=entries.filter(entry=>entry.key.startsWith("rate:"));
    check(rates.length===record.modes.length&&rates.filter(entry=>entry.marked).length===1,"refresh rate choices incorrect");
    check(rates.every(entry=>Object.keys(entry.values).join() === "mode" && entry.values.mode.startsWith(record.mode.split("@")[0]+"@")),"refresh rate changes other settings");
    button.clicked();
   }else if(stage===1){
    checkBounds(button.menu);
    const list=find(button.menu.contentItem,"displayOptionsList:DP-1");
    check(list.contentHeight>list.height,"long list is not scrollable");
    const before=list.contentY;
    input.mouseWheel(list,80,80,0,-120,Qt.NoButton,Qt.NoModifier,0);
    check(list.contentY===before+120,"menu wheel not immediate");
    list.positionViewAtEnd();
   }else if(stage===2){
    checkBounds(button.menu);
    const list=find(button.menu.contentItem,"displayOptionsList:DP-1");
    const last=list.itemAtIndex(list.count-1);
    check(last&&last.record.key==="test:motion"&&list.contentY>0,"bottom option not reached");
    const point=last.mapToItem(list,0,0);
    check(point.y>=-1&&point.y+last.height<=list.height+1,"bottom option clipped: "+point.y+" + "+last.height+" > "+list.height+" content="+list.contentHeight+" scroll="+list.contentY);
    const destination=Quickshell.env("DISPLAY_PREVIEW_DIR");
    if(destination)button.menu.contentItem.grabToImage(result=>result.saveToFile(destination+"/displays-menu-bottom.png"));
    input.mouseClick(last,last.width/2,last.height/2);
    check(mock.calls===0&&mockTests.calls===1&&mockTests.mode==="motion"&&mockTests.output==="DP-1"&&!button.menu.visible,"test action was not targeted or changed settings");
    drawer.width=268;drawer.height=340;button.clicked();
   }else if(stage===3){
    checkBounds(button.menu);
    const list=find(button.menu.contentItem,"displayOptionsList:DP-1");
    list.positionViewAtEnd();
   }else if(stage===4){
    checkBounds(button.menu);
    button.menu.close();
    const patterns=drawer.optionsFor(drawer.displays[1]).find(entry=>entry.key==="test:patterns");
    button.clicked();button.menu.activate(patterns);
    check(mockTests.calls===2&&mockTests.mode==="patterns"&&mockTests.output==="DP-1"&&mock.calls===0,"patterns action incorrect");
    const identify=find(drawer,"displayIdentifyButton");
    input.mouseClick(identify,identify.width/2,identify.height/2);
    check(mockTests.mode==="identify"&&mockTests.calls===3,"identify button missing");
    input.mouseClick(identify,identify.width/2,identify.height/2);
    check(mockTests.mode==="","identify did not stop on second click");
    drawer.active=false;
    console.log("DISPLAY_PASS");Qt.quit();
   }
   stage++;
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}
 }}
 Timer{interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
'''.replace('ROWS',rows))

    def test_shared_drawer_column_uses_immediate_wheel_steps(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtTest
import Quickshell
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:displayWindow.contentItem }
 FloatingWindow {
  id:displayWindow
  implicitWidth:320;implicitHeight:400;visible:true
  TextField { id:field; x:16;y:16;width:200;height:36 }
  DrawerColumn {
   id:column;x:16;y:64;width:268;height:240
   Repeater {model:30;Button {Layout.fillWidth:true;implicitHeight:36;text:"Row"}}
  }
 }
 property int stage:0
 Timer{interval:250;repeat:true;running:true;onTriggered:{
  try{
   const view=column.contentItem;
   if(stage===0){
    field.forceActiveFocus();
    input.mouseWheel(view,80,80,0,-120,Qt.NoButton,Qt.NoModifier,0);
    if(view.contentY!==120)throw new Error("drawer column wheel not immediate: "+view.contentY+" interactive="+view.interactive+" content="+view.contentHeight);
    if(!field.activeFocus)throw new Error("scrolling stole focus");
   }else if(stage===1){
    if(view.contentY!==120)throw new Error("drawer column retained native delayed tail");
    input.mouseWheel(view,80,80,0,120,Qt.NoButton,Qt.NoModifier,0);
    if(view.contentY!==0)throw new Error("reverse wheel not immediate");
    console.log("DISPLAY_PASS");Qt.quit();
   }
   stage++;
  }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}
 }}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''')

    def test_brightness_queue_coalesces_without_blocking_layout_and_survives_dismissal(self):
        def setup(root):
            (root / 'drawers/displays/backend.py').write_text('import json,sys\nfor line in sys.stdin:\n print(json.dumps(dict(ok=True,error="",data=dict(available=True,displays=[],token="test"))),flush=True)\n')
            (root / 'drawers/displays/brightness.py').write_text('import json,sys,time\nr=json.loads(sys.stdin.readline());time.sleep(.15)\nvalues=[] if r["op"]=="status" else [dict(r,available=True)]\nprint(json.dumps(dict(ok=True,values=values)),flush=True)\n')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/displays"
ShellRoot {
 property int stage:0
 property var owner: ({})
 Timer { interval:80; repeat:true; running:true; onTriggered: {
  try {
   if(stage===0) { if(DisplayService.brightnessFor("none").available) throw new Error("invalid fallback brightness"); DisplayService.observe(owner,true);stage++; }
   else if(stage===1 && DisplayService.loaded && !DisplayService.brightnessRequest) {
    DisplayService.brightness={panel:{available:true,value:10,identity:["panel"],kind:"backlight",key:"panel"}};
    DisplayService.setBrightness("panel",30);
    DisplayService.setBrightness("panel",40);
    DisplayService.setBrightness("panel",50);
    if(DisplayService.brightnessQueue.length!==1 || DisplayService.brightnessQueue[0].value!==50) throw new Error("brightness queue not coalesced");
    if(DisplayService.busy) throw new Error("brightness blocked layout controls");
    DisplayService.run("status");
    if(DisplayService.request?.op!=="status" || !DisplayService.brightnessWorker.running) throw new Error("layout and brightness workers not independent");
    DisplayService.observe(owner,false);stage++;
   }
   else if(stage===2 && !DisplayService.brightnessWorker.running && !DisplayService.brightnessRequest && !DisplayService.brightnessQueue.length) {
    if(DisplayService.brightness.panel.value!==50) throw new Error("last brightness lost on dismissal");
    if(DisplayService.observing || DisplayService.worker.running) throw new Error("observation survived dismissal");
    console.log("DISPLAY_PASS");Qt.quit();
   }
  } catch(e) { console.error("DISPLAY_FAIL",e);Qt.quit(); }
 } }
 Timer { interval:5000; running:true; onTriggered: {console.error("DISPLAY_FAIL timeout");Qt.quit();} }
}
''', setup)

    def test_service_finishes_changes_after_dismissal_and_reopens(self):
        def setup(root):
            (root / 'drawers/displays/backend.py').write_text('import json,sys,time\nfor line in sys.stdin:\n r=json.loads(line);time.sleep(.1)\n print(json.dumps(dict(ok=True,error="",data=dict(available=True,displays=[],token="test",last=r))),flush=True)\n')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/displays"
ShellRoot {
 property int stage:0
 property var owner: ({})
 Timer { interval:120; repeat:true; running:true; onTriggered: {
  try {
   if(stage===0) { if(DisplayService.loaded) throw new Error("eager worker"); DisplayService.observe(owner,true);stage++; }
   else if(stage===1 && DisplayService.loaded && !DisplayService.worker.running) {
    DisplayService.change({name:"panel",identity:["panel"]},{scale:1.25});
    DisplayService.observe(owner,false);stage++;
   }
   else if(stage===2 && !DisplayService.worker.running) {
    if(DisplayService.state.last.op!=="change" || DisplayService.state.last.values.scale!==1.25) throw new Error("change did not finish after dismissal");
    DisplayService.observe(owner,true);stage++;
   }
   else if(stage===3 && !DisplayService.worker.running) {
    if(DisplayService.state.last.op!=="status")throw new Error("reopening did not refresh");
    DisplayService.observe(owner,false);
    if(DisplayService.observing || DisplayService.busy) throw new Error("observation survived dismissal");
    console.log("DISPLAY_PASS");Qt.quit();
   }
  } catch(e) {console.error("DISPLAY_FAIL",e);Qt.quit();}
 } }
 Timer { interval:5000; running:true; onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();} }
}
''', setup)

    def test_events_are_debounced_and_helpers_exit_between_requests(self):
        def setup(root):
            (root / 'drawers/displays/backend.py').write_text('''import json,sys,time
from pathlib import Path
counter=Path(__file__).with_suffix('.count')
count=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(count))
request=json.loads(sys.stdin.readline())
if request['op']=='crash': sys.exit(1)
time.sleep(.1)
reply=dict(ok=True,error='',data=dict(available=True,displays=[],token=str(count),last=request,count=count))
if request['op']=='power': reply['pending']=count<5
print(json.dumps(reply))
''')
        self.run_qml('''import QtQuick
import Quickshell
import Quickshell.Services.UPower
import "drawers/displays"
ShellRoot {
 property int stage:0
 property int idleTicks:0
 property int expected:0
 function settled(count){return !DisplayService.worker.running && !DisplayService.request && DisplayService.state.count===count;}
 function last(op,message){if(DisplayService.state.last.op!==op)throw new Error(message+": "+DisplayService.state.last.op);}
 Timer { interval:80; repeat:true; running:true; onTriggered: {
  try {
   if(stage===0) { DisplayService.powerProfiles=({profile:-1});DisplayService.eventDelay.interval=100;DisplayService.start();DisplayService.start();stage++; }
   else if(stage===1 && settled(1)) {
    last("ensure","startup must only check for a usable display");
    if(DisplayService.observing || DisplayService.brightnessWorker.running)throw new Error("eager brightness worker");
    DisplayService.handleEvent("activewindowv2","");
    DisplayService.handleEvent("custom","unrelated");
    if(DisplayService.eventDelay.running)throw new Error("unrelated event scheduled work");
    DisplayService.handleEvent("monitoraddedv2","");
    DisplayService.handleEvent("custom","desktop-displays-changed");
    DisplayService.handleEvent("monitorremoved","");stage++;
   }
   else if(stage===2 && settled(2) && !DisplayService.eventDelay.running) {
    last("ensure","hotplug burst must run one safety check");
    if(ComfortService.worker.running)throw new Error("hotplug started the comfort helper without Keep awake");
    // Rules re-apply themselves on reload; without Powersave nothing runs.
    DisplayService.handleEvent("configreloaded","");
    DisplayService.handleEvent("custom","desktop-displays-changed");stage++;
   }
   else if(stage===3 && !DisplayService.eventDelay.running) {
    if(!settled(2))throw new Error("reload or layout event did background work");
    DisplayService.powerProfiles=({profile:PowerProfile.PowerSaver});stage++;
   }
   else if(stage===4 && settled(3)) {
    last("power","entering Powersave did not apply the cap");
    if(!DisplayService.state.last.capped || !DisplayService.powerPending)throw new Error("cap request or pending state incorrect");
    // A blank panel retries on the next display event (the wake hook).
    DisplayService.handleEvent("custom","desktop-displays-changed");stage++;
   }
   else if(stage===5 && settled(4)) {
    last("power","pending policy was not retried");
    DisplayService.handleEvent("configreloaded","");stage++;
   }
   else if(stage===6 && settled(5)) {
    last("power","reload did not re-apply the cap");
    if(DisplayService.powerPending)throw new Error("pending state survived");
    DisplayService.change({name:"eDP-1",identity:["eDP-1"]},{mode:"1920x1080@120.00Hz"});stage++;
   }
   else if(stage===7 && settled(6)) {
    if(DisplayService.state.last.capped || DisplayService.capped)throw new Error("explicit refresh did not override the cap");
    DisplayService.handleEvent("configreloaded","");stage++;
   }
   else if(stage===8 && !DisplayService.eventDelay.running && settled(6)) {
    DisplayService.powerProfiles=({profile:-1});stage++;
   }
   else if(stage===9 && settled(7)) {
    last("power","leaving Powersave did not restore");
    if(DisplayService.state.last.capped || DisplayService.capSuppressed)throw new Error("restore request incorrect");
    DisplayService.run("crash");stage++;
   }
   else if(stage===10 && !DisplayService.worker.running && !DisplayService.request) {
    if(!DisplayService.error || DisplayService.state.available)throw new Error("failure not exposed");
    DisplayService.handleEvent("monitorremoved","");stage++;
   }
   else if(stage===11 && settled(9)) {
    expected=DisplayService.state.count;stage++;
   }
   else if(stage===12) {
    if(DisplayService.worker.running || DisplayService.state.count!==expected || DisplayService.eventDelay.running)throw new Error("idle background work");
    if(++idleTicks>=42){console.log("DISPLAY_PASS");Qt.quit();}
   }
  } catch(e) {console.error("DISPLAY_FAIL",e);Qt.quit();}
 } }
 Timer { interval:12000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout stage "+stage);Qt.quit();} }
}
''', setup)

if __name__ == '__main__':
    unittest.main()
