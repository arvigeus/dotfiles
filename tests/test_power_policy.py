"""Policy ownership, thermal guards and valid whole-battery accounting."""
import configparser
import copy
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
import os
import select
import signal
import subprocess
import time
import sys
from unittest.mock import patch

import test_display_drawer as displays

REPO = Path(__file__).resolve().parents[1]
POWER = REPO / 'modules/hardware/power'
loader = importlib.machinery.SourceFileLoader('power_study', str(POWER / 'files/usr/local/bin/power-study'))
spec = importlib.util.spec_from_loader(loader.name, loader)
study = importlib.util.module_from_spec(spec)
thermal_path = POWER / 'files/etc/tuned/profiles/zephyrus-common/asus-thermal.py'
thermal_spec = importlib.util.spec_from_file_location('asus_thermal', thermal_path)
thermal = importlib.util.module_from_spec(thermal_spec)
source_loader = importlib.machinery.SourceFileLoader('power_source', str(POWER / 'files/usr/local/libexec/power-source'))
source_spec = importlib.util.spec_from_loader(source_loader.name, source_loader)
source = importlib.util.module_from_spec(source_spec)
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    loader.exec_module(study)
    thermal_spec.loader.exec_module(thermal)
    source_loader.exec_module(source)
finally:
    sys.dont_write_bytecode = _bytecode_disabled


class SourceSelection(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.bus = Mock()
        self.battery = False
        self.active = 'balanced'
        self.bus.on_battery.side_effect = lambda: self.battery
        self.bus.active_profile.side_effect = lambda: self.active
        self.bus.select_profile.side_effect = lambda mode: setattr(self, 'active', mode)
        self.policy = source.SourcePolicy(self.bus)
        self.policy.observe()

    def test_unplug_selects_powersave_and_plug_selects_balanced(self):
        self.battery = True
        self.policy.observe()
        self.assertEqual(self.active, 'power-saver')
        self.battery = False
        self.policy.observe()
        self.assertEqual(self.active, 'balanced')
        self.assertEqual([call.args[0] for call in self.bus.select_profile.call_args_list],
                         ['power-saver', 'balanced'])

    def test_manual_daily_mode_lasts_until_an_actual_source_change(self):
        self.active = 'power-saver'
        self.policy.observe()
        self.bus.select_profile.assert_not_called()
        self.battery = True
        self.policy.observe()
        self.active = 'balanced'
        self.policy.observe()
        self.bus.select_profile.assert_not_called()
        self.battery = False
        self.policy.observe()
        self.battery = True
        self.policy.observe()
        self.bus.select_profile.assert_called_once_with('power-saver')

    def test_performance_survives_both_source_edges(self):
        self.active = 'performance'
        self.battery = True
        self.policy.observe()
        self.battery = False
        self.policy.observe()
        self.bus.select_profile.assert_not_called()

    def test_initial_source_never_replaces_saved_mode(self):
        for battery, mode in [(False, 'power-saver'), (True, 'balanced'), (True, 'performance')]:
            self.battery, self.active = battery, mode
            source.SourcePolicy(self.bus).observe()
            self.assertEqual(self.active, mode)
        self.bus.select_profile.assert_not_called()

    def test_unknown_profile_and_invalid_source_never_select_a_mode(self):
        self.active = 'custom'
        self.battery = True
        self.policy.observe()
        self.bus.select_profile.assert_not_called()
        self.battery = None
        with self.assertRaisesRegex(RuntimeError, 'valid power source'):
            self.policy.observe()
        self.bus.select_profile.assert_not_called()

    def test_unconfirmed_switch_does_not_commit_the_source_edge(self):
        self.battery = True
        self.bus.select_profile.side_effect = None
        with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
            self.policy.observe()
        self.assertIs(self.policy.previous, False)

    @unittest.skipUnless(importlib.util.find_spec('gi'), 'PyGObject is required for native D-Bus variants')
    def test_native_signal_subscription_filters_unrelated_properties_and_handles_invalidation(self):
        from gi.repository import GLib
        from unittest.mock import Mock
        loop = Mock()
        def run():
            callback = self.bus.connection.signal_subscribe.call_args.args[-1]
            self.battery = True
            callback(None, ':1.1', source.UPOWER_PATH, source.PROPERTIES, 'PropertiesChanged',
                     GLib.Variant('(sa{sv}as)', (source.UPOWER, {'LidIsClosed': GLib.Variant('b', True)}, [])), None)
            self.bus.select_profile.assert_not_called()
            callback(None, ':1.1', source.UPOWER_PATH, source.PROPERTIES, 'PropertiesChanged',
                     GLib.Variant('(sa{sv}as)', (source.UPOWER, {}, ['OnBattery'])), None)
            self.assertEqual(self.active, 'power-saver')
            self.battery = False
            callback(None, ':1.1', source.UPOWER_PATH, source.PROPERTIES, 'PropertiesChanged',
                     GLib.Variant('(sa{sv}as)', (source.UPOWER, {'OnBattery': GLib.Variant('b', False)}, [])), None)
            self.assertEqual(self.active, 'balanced')
        loop.run.side_effect = run
        with patch.object(source, 'Bus', return_value=self.bus), patch.object(GLib, 'MainLoop', return_value=loop):
            self.assertEqual(source.main(), 0)
        self.assertEqual(self.bus.connection.signal_subscribe.call_args.args[:5],
                         (source.UPOWER, source.PROPERTIES, 'PropertiesChanged', source.UPOWER_PATH, source.UPOWER))


class ThermalDelegation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patch = patch.object(thermal, 'SYS', self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        for name, value in [('devices/virtual/dmi/id/product_name', 'ROG GA402RK'),
                            ('devices/system/cpu/cpufreq/boost', '1'),
                            ('firmware/acpi/platform_profile', 'performance'),
                            ('class/hwmon/hwmon0/name', 'asus_custom_fan_curve')]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
        self.operations = []
        self.values = {'ppt_apu_sppt': 80, 'ppt_platform_sppt': 115}
        self.maxima = dict(self.values)
        self.enabled = False
        self.platform = 1
        self.environment = patch.dict(os.environ, {
            'TUNED_asus_platform': 'performance', 'TUNED_asus_apu_limit': '45', 'TUNED_asus_platform_limit': '60'})
        self.environment.start(); self.addCleanup(self.environment.stop)
        owner = self
        class Bus:
            def get(self, interface, name, path=thermal.PATH):
                if name == 'PlatformProfile': return owner.platform
                if name == 'EnablePptGroup': return owner.enabled
                attribute = path.rsplit('/', 1)[1]
                return {'MinValue': 15, 'MaxValue': owner.maxima[attribute], 'CurrentValue': owner.values[attribute]}[name]
            def set(self, interface, name, kind, value, path=thermal.PATH):
                owner.operations.append((name, value))
                if name == 'EnablePptGroup': owner.enabled = value
                else: owner.values[path.rsplit('/', 1)[1]] = value
            def call(self, interface, method, signature, values):
                owner.operations.append((method, values))
                chip = owner.root / 'class/hwmon/hwmon0'
                if method == 'SetFanCurve':
                    _, (name, pwms, temps, enabled) = values
                    fan = 1 if name == 'CPU' else 2
                    (chip / f'pwm{fan}_enable').write_text('1' if enabled else '2')
                    for point, (pwm, temp) in enumerate(zip(pwms, temps), 1):
                        (chip / f'pwm{fan}_auto_point{point}_pwm').write_text(str(pwm))
                        (chip / f'pwm{fan}_auto_point{point}_temp').write_text(str(temp))
        self.bus = Bus()

    def test_fans_precede_limits_and_actual_firmware_readback_is_required(self):
        thermal.apply(self.bus)
        self.assertEqual(self.values, {'ppt_apu_sppt': 45, 'ppt_platform_sppt': 60})
        names = [row[0] for row in self.operations]
        self.assertLess(names.index('SetFanCurvesEnabled'), names.index('EnablePptGroup'))
        self.values['ppt_apu_sppt'] = 80
        with self.assertRaisesRegex(RuntimeError, 'power-limit readback'):
            thermal.verify(self.bus)

    def test_dc_targets_obey_the_firmware_ranges(self):
        self.maxima = {'ppt_apu_sppt': 45, 'ppt_platform_sppt': 60}
        thermal.apply(self.bus)
        self.assertEqual(self.values, {'ppt_apu_sppt': 45, 'ppt_platform_sppt': 60})

    def test_unknown_hardware_is_rejected_before_fan_or_ppt_writes(self):
        (self.root / 'devices/virtual/dmi/id/product_name').write_text('Other laptop')
        with self.assertRaisesRegex(RuntimeError, 'only on GA402RK'):
            thermal.apply(self.bus)
        self.assertEqual(self.operations, [])

    def test_inactive_hardware_fan_curve_is_not_verified_from_saved_config(self):
        thermal.apply(self.bus)
        (self.root / 'class/hwmon/hwmon0/pwm2_enable').write_text('2')
        with self.assertRaisesRegex(RuntimeError, 'GPU fan curve is not active'):
            thermal.verify(self.bus)

    def test_failed_start_falls_back_to_quiet_without_boost(self):
        from unittest.mock import Mock
        broken = Mock(); broken.get.side_effect = RuntimeError('ASUS service unavailable')
        with patch.object(thermal, 'Bus', return_value=broken), patch.object(thermal.sys, 'argv', ['thermal', 'start']):
            with self.assertRaisesRegex(SystemExit, 'ASUS service unavailable'):
                thermal.main()
        self.assertEqual((self.root / 'devices/system/cpu/cpufreq/boost').read_text(), '0')
        self.assertEqual((self.root / 'firmware/acpi/platform_profile').read_text(), 'quiet')

    def test_stop_restores_firmware_defaults_before_disabling_manual_fans(self):
        thermal.restore(self.bus)
        self.assertEqual(self.operations, [('EnablePptGroup', False), ('SetFanCurvesEnabled', (1, False))])

    def test_daily_modes_use_their_budget_and_keep_fans_off_below_sixty(self):
        self.platform = 0
        with patch.dict(os.environ, {'TUNED_asus_platform': 'balanced',
                'TUNED_asus_apu_limit': '30', 'TUNED_asus_platform_limit': '45'}):
            thermal.apply(self.bus)
            self.assertEqual(self.values, {'ppt_apu_sppt': 30, 'ppt_platform_sppt': 45})
            self.assertEqual((self.root / 'class/hwmon/hwmon0/pwm1_auto_point3_pwm').read_text(), '0')
            self.assertEqual(self.operations[0][1][0], 0)

    def test_stop_restores_the_outgoing_platform_even_when_variables_changed(self):
        self.platform = 2
        thermal.restore(self.bus)
        self.assertEqual(self.operations[-1], ('SetFanCurvesEnabled', (2, False)))


class Measurements(unittest.TestCase):
    def test_workload_descendants_are_stopped_after_the_launcher_exits(self):
        child = subprocess.Popen([sys.executable, '-c', '''import os,signal,time
if os.fork():
    os._exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print('ready', flush=True)
time.sleep(30)
'''], stdout=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self.assertTrue(select.select([child.stdout], [], [], 3)[0], 'Descendant did not initialize')
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            child.wait(timeout=3)
            study.stop_workload(child)
            self.assertTrue(select.select([child.stdout], [], [], 3)[0], 'Descendant retained the output pipe')
            self.assertEqual(child.stdout.read(), '')
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            child.stdout.close()

    def test_guard_immediately_stops_a_workload_that_ignores_graceful_termination(self):
        child = subprocess.Popen([sys.executable, '-c',
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(30)"],
            stdout=subprocess.PIPE, text=True, start_new_session=True)
        try:
            self.assertTrue(select.select([child.stdout], [], [], 3)[0], 'Child did not initialize')
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            started = time.monotonic()
            study.stop_workload(child, abort=True)
            self.assertEqual(child.returncode, -signal.SIGKILL)
            self.assertLess(time.monotonic() - started, 2, 'Thermal abort waited through the grace period')
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            child.stdout.close()

    def row(self, seconds=0, wh=40, watts=10, status='Discharging'):
        return dict(monotonic=seconds, batteries=dict(BAT0=dict(status=status, watts=watts, wh=wh, full_wh=50)),
                    temperatures={'k10temp:Tctl': 60}, gpus={'gpu': dict(state='suspended')})

    def test_battery_discharge_and_energy_delta_are_separate_estimates(self):
        result = study.summarize([self.row(), self.row(360, wh=39)])['batteries']['BAT0']
        self.assertEqual(result['mean_w'], 10)
        self.assertEqual(result['energy_delta_mean_w'], 10)
        self.assertEqual(result['estimated_full_hours'], 5)
        self.assertEqual(result['estimated_remaining_hours'], 3.9)

    def test_recording_summary_uses_cpu_deltas_without_double_counting_guest(self):
        rows = [dict(self.row(), cpu_stat='cpu 100 0 50 850 0 0 0 0 99 0', memory_used=128),
                dict(self.row(30), memory_used=512),
                dict(self.row(60), cpu_stat='cpu 130 0 70 900 0 0 0 0 199 0', memory_used=256)]
        result = study.summarize(rows)
        self.assertEqual(result['cpu_usage'], 50)
        self.assertEqual(result['peak_memory_used'], 512)

    def test_ac_and_mixed_source_runs_never_claim_battery_runtime(self):
        for status in ('Charging', 'Not charging'):
            result = study.summarize([self.row(), self.row(120, status=status)])
            self.assertNotIn('estimated_full_hours', result['batteries']['BAT0'])
        rows = [dict(self.row(), ac={'AC0': '1'}), dict(self.row(120), ac={'AC0': '1'})]
        # A charge-capped battery can discharge slightly while AC supplies the
        # laptop. That residual flow is not whole-laptop consumption.
        result = study.summarize(rows)
        self.assertNotIn('estimated_full_hours', result['batteries']['BAT0'])

    def test_guards_use_cpu_and_each_gpu_sensor_separately(self):
        row = self.row()
        self.assertEqual(study.guard(row), '')
        row['temperatures']['k10temp:Tctl'] = 82
        self.assertIn('k10temp:Tctl', study.guard(row))
        row['temperatures']['k10temp:Tctl'] = 60
        row['gpus']['gpu'].update(state='active', edge=65, junction=90)
        self.assertIn('junction', study.guard(row))
        row['gpus']['gpu'].update(junction=80, mem=90)
        self.assertIn('mem', study.guard(row))

    def test_missing_thermal_telemetry_refuses_a_guarded_load(self):
        row = self.row()
        self.assertEqual(study.sensor_failure(row), '')
        row['temperatures'] = {}
        self.assertIn('CPU temperature', study.sensor_failure(row))
        row['temperatures'] = {'k10temp:Tctl': 60}
        row['gpus']['gpu'].update(id='0x73ef', state='active')
        self.assertIn('thermal telemetry', study.sensor_failure(row))

    def test_battery_observation_never_reads_even_an_active_gpu_sensor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / 'class/drm/card1/device'
            for name, data in [('device', '0x73ef'), ('power/runtime_status', 'active'),
                               ('power/control', 'auto'), ('gpu_busy_percent', '0'),
                               ('hwmon/hwmon1/temp1_input', '60000')]:
                path = device / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            original = study.read
            def checked(path):
                if Path(path).name in ('gpu_busy_percent', 'temp1_input', 'power1_input', 'power1_average'):
                    self.fail('Passive recording read a GPU sensor: ' + str(path))
                return original(path)
            with patch.object(study, 'SYS', root), patch.object(study, 'read', side_effect=checked):
                row = study.sample()
            self.assertEqual(row['gpus']['device']['state'], 'active')
            self.assertNotIn('edge', row['gpus']['device'])

    def test_suspend_gap_invalidates_a_recording_even_when_monotonic_pauses(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'recording'
            with patch.object(study, 'SYS', root), \
                    patch.object(study.time, 'clock_gettime', side_effect=[0, 0, 2, 120]), \
                    patch.object(study.time, 'monotonic', side_effect=[0, 0, 2, 4]), \
                    patch.object(study.time, 'sleep'), patch.object(sys, 'stdout', Mock()), \
                    patch.object(sys, 'argv', ['power-study', '--duration', '4', '--warmup', '0',
                                                   '--output', str(output), 'test']):
                before = dict(sample=study.sample(), monitors=None)
                with patch.object(study, 'metadata', return_value=before):
                    code = study.main()
            summary = json.loads((output / 'summary.json').read_text())
            self.assertEqual(code, 2)
            self.assertIn('interrupted', summary['abort_reason'])


class Ownership(unittest.TestCase):
    def config(self, name):
        config = configparser.ConfigParser(interpolation=None)
        config.read(POWER / f'files/etc/tuned/profiles/zephyrus-{name}/tuned.conf')
        return config

    def test_boost_has_exactly_one_authority_and_every_mode_sets_it(self):
        common = self.config('common')
        self.assertNotIn('boost', common['cpu'])
        for name, value in [('balanced', '0'), ('battery', '0'), ('performance', '1'), ('powersave', '0')]:
            profile = self.config(name)
            self.assertEqual(profile['main']['include'], 'zephyrus-common')
            self.assertNotIn('boost', profile['cpu'])
            self.assertEqual(profile['sysfs']['/sys/devices/system/cpu/cpufreq/boost'], value)

    def test_platform_profile_is_applied_before_cpu_and_sysfs(self):
        profile = self.config('common')
        self.assertLess(int(profile['acpi']['priority']), int(profile['cpu']['priority']))
        self.assertLess(int(profile['cpu']['priority']), int(profile['sysfs']['priority']))
        self.assertLess(int(profile['sysfs']['priority']), int(profile['sysfs_cpu_limits']['priority']))
        self.assertLess(int(profile['sysfs_cpu_limits']['priority']), int(profile['script']['priority']))
        self.assertIn('cpuinfo_max_freq', profile['sysfs_cpu_limits'][
            '/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq'])

    @unittest.skipUnless(importlib.util.find_spec('tuned'), 'Native TuneD is required')
    def test_native_profile_merge_preserves_the_custom_sysfs_plugin_type(self):
        from tuned.profiles.profile import Profile
        from tuned.profiles.merger import Merger
        def profile(name):
            config = self.config(name)
            return Profile(name, {section: dict(config[section]) for section in config.sections()})
        merged = Merger().merge([profile('common'), profile('performance')])
        limits = merged.units['sysfs_cpu_limits']
        self.assertEqual(limits.type, 'sysfs')
        self.assertEqual(limits.options['/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq'], '4000000')

    def test_each_mode_forces_a_source_transition_for_thermal_reapplication(self):
        ppd = configparser.ConfigParser()
        ppd.read(POWER / 'files/etc/tuned/ppd.conf')
        for mode, parent in [('performance', 'performance'), ('power-saver', 'powersave')]:
            self.assertNotEqual(ppd['profiles'][mode], ppd['battery'][mode])
            self.assertEqual(self.config(parent + '-battery')['main']['include'], 'zephyrus-' + parent)
        self.assertNotEqual(ppd['profiles']['balanced'], ppd['battery']['balanced'])


class PanelPolicy(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'displays.json'
        self.prefs = displays.backend.Preferences(self.path)
        self.panel = displays.display('eDP-1', mode='1920x1080@120.00Hz')
        self.external = displays.display('DP-1', mode='1920x1080@120.00Hz', x=1920)
        self.before = displays.state([self.panel, self.external])
        self.prefs.remember(self.before)
        apply = patch.object(displays.backend, 'apply_setup', side_effect=lambda rows, before: displays.state(rows))
        self.apply = apply.start()
        self.addCleanup(apply.stop)

    def test_internal_only_cap_preserves_preferences_and_restores_mode(self):
        capped = self.prefs.power_refresh(self.before, True)
        self.assertEqual(capped['displays'][0]['mode'], '1920x1080@60.00Hz')
        self.assertEqual(capped['displays'][1]['mode'], '1920x1080@120.00Hz')
        # Even a simultaneous placement edit must not save the automatic cap.
        changed = copy.deepcopy(capped)
        changed['displays'][0]['y'] = 10
        self.prefs.remember(changed, capped)
        self.assertEqual(json.loads(self.path.read_text())['outputs'][0]['mode'], self.panel['mode'])
        restored = self.prefs.power_refresh(changed, False)
        self.assertEqual(restored['displays'][0]['mode'], self.panel['mode'])
        self.assertEqual(restored['displays'][0]['y'], 10)

    def test_external_manual_refresh_override_wins_until_mode_exit(self):
        capped = self.prefs.power_refresh(self.before, True)
        changed = copy.deepcopy(capped)
        changed['displays'][0]['mode'] = self.panel['mode']
        changed['token'] = displays.backend.fingerprint(changed['displays'])
        current = self.prefs.power_refresh(changed, True)
        self.assertEqual(current['displays'][0]['mode'], self.panel['mode'])
        again = self.prefs.power_refresh(current, True)
        self.assertEqual(again['displays'][0]['mode'], self.panel['mode'])
        self.prefs.power_refresh(again, False)
        self.assertEqual(self.prefs.power_refresh(again, True)['displays'][0]['mode'], '1920x1080@60.00Hz')

    def test_disabling_a_capped_panel_preserves_its_original_mode(self):
        capped = self.prefs.power_refresh(self.before, True)
        disabled = displays.state([dict(capped['displays'][0], enabled=False), self.external])
        self.prefs.remember(disabled, capped, capped)
        saved = self.prefs.saved[self.prefs.key(self.panel)]
        self.assertFalse(saved['enabled'])
        self.assertEqual(saved['mode'], self.panel['mode'])

    def test_power_signal_saves_pending_external_edits_before_updating_baseline(self):
        changed = displays.state([dict(self.panel, y=50), self.external])
        with patch.object(displays.backend, 'snapshot', return_value=changed):
            result = displays.backend.response(dict(op='power', baseline=self.before, powerMode='power-saver'), self.prefs)
        self.assertTrue(result['ok'], result['error'])
        self.assertEqual(self.prefs.saved[self.prefs.key(self.panel)]['y'], 50)
        self.assertEqual(self.prefs.saved[self.prefs.key(self.panel)]['mode'], self.panel['mode'])

    def test_enabling_a_panel_does_not_count_as_a_manual_refresh_override(self):
        disabled = displays.state([dict(self.panel, enabled=False), self.external])
        self.prefs.power_state['active'] = True
        with patch.object(displays.backend, 'snapshot', return_value=disabled), \
                patch.object(displays.backend, 'control', return_value=self.before):
            current = displays.backend.handle(dict(op='change', name=self.panel['name'],
                identity=self.panel['identity'], values={'enabled': True}), self.prefs)
        self.assertEqual(self.prefs.power_state['suppressed'], [])
        self.assertEqual(self.prefs.power_refresh(current, True)['displays'][0]['mode'], '1920x1080@60.00Hz')

    def test_failed_modeset_never_commits_a_fictitious_override(self):
        self.apply.side_effect = RuntimeError('modeset failed')
        with self.assertRaises(RuntimeError):
            self.prefs.power_refresh(self.before, True)
        self.assertFalse(self.prefs.power_state['active'])
        self.assertEqual(self.prefs.power_state['overrides'], {})

    def test_policy_does_not_wake_a_blank_panel_or_change_resolution(self):
        before = displays.state([dict(self.panel, dpms=False), self.external])
        self.prefs.power_refresh(before, True)
        self.apply.assert_not_called()
        self.panel['modes'] = ['1920x1080@120.00Hz', '1280x720@60.00Hz']
        self.prefs.power_refresh(displays.state([self.panel]), True)
        self.apply.assert_not_called()

    def test_dark_panel_restoration_is_deferred_until_wake_without_losing_original(self):
        capped = self.prefs.power_refresh(self.before, True)
        dark = displays.state([dict(capped['displays'][0], dpms=False), self.external])
        self.apply.reset_mock()
        left = self.prefs.power_refresh(dark, False)
        self.apply.assert_not_called()
        self.assertFalse(self.prefs.power_state['active'])
        self.assertTrue(self.prefs.power_state['overrides'])
        awake = displays.state([dict(left['displays'][0], dpms=True), self.external])
        restored = self.prefs.power_refresh(awake, False)
        self.assertEqual(restored['displays'][0]['mode'], self.panel['mode'])
        self.assertEqual(self.prefs.power_state['overrides'], {})

    def test_powersave_reentry_before_wake_retains_the_original_refresh(self):
        capped = self.prefs.power_refresh(self.before, True)
        dark = displays.state([dict(capped['displays'][0], dpms=False), self.external])
        self.prefs.power_refresh(dark, False)
        self.prefs.power_refresh(dark, True)
        awake = displays.state([dict(dark['displays'][0], dpms=True), self.external])
        self.assertEqual(self.prefs.power_refresh(awake, False)['displays'][0]['mode'], self.panel['mode'])


if __name__ == '__main__':
    unittest.main()
