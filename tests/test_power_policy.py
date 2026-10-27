"""Policy ownership and valid whole-battery accounting."""

import configparser
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
import os
import sys
from unittest.mock import patch

import support

REPO = Path(__file__).resolve().parents[1]
POWER = REPO / 'modules/hardware/power'
loader = importlib.machinery.SourceFileLoader(
    'power_study', str(POWER / 'files/usr/local/bin/power-study')
)
spec = importlib.util.spec_from_loader(loader.name, loader)
study = importlib.util.module_from_spec(spec)
thermal_path = POWER / 'files/etc/tuned/profiles/zephyrus-common/asus-thermal.py'
thermal_spec = importlib.util.spec_from_file_location('asus_thermal', thermal_path)
thermal = importlib.util.module_from_spec(thermal_spec)
source_loader = importlib.machinery.SourceFileLoader(
    'power_source', str(POWER / 'files/usr/local/libexec/power-source')
)
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
        self.assertEqual(
            [call.args[0] for call in self.bus.select_profile.call_args_list],
            ['power-saver', 'balanced'],
        )

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

    def test_initial_source_reconciles_saved_daily_mode_without_a_signal(self):
        for battery, saved, expected in [
            (False, 'power-saver', 'balanced'),
            (True, 'balanced', 'power-saver'),
            (False, 'balanced', 'balanced'),
            (True, 'power-saver', 'power-saver'),
        ]:
            with self.subTest(battery=battery, saved=saved):
                self.battery, self.active = battery, saved
                self.bus.select_profile.reset_mock()
                policy = source.SourcePolicy(self.bus)
                policy.observe()
                self.assertEqual(self.active, expected)
                self.assertEqual(
                    self.bus.select_profile.call_count, int(saved != expected)
                )
                # A manual choice after startup survives repeated source reads.
                self.active = saved
                policy.observe()
                self.assertEqual(self.active, saved)

    def test_initial_source_preserves_performance_and_unknown_profiles(self):
        for battery in (False, True):
            for mode in ('performance', 'custom'):
                self.battery, self.active = battery, mode
                source.SourcePolicy(self.bus).observe()
                self.assertEqual(self.active, mode)
        self.bus.select_profile.assert_not_called()

    def test_initial_unconfirmed_switch_does_not_commit_source(self):
        self.battery = True
        self.bus.select_profile.side_effect = None
        policy = source.SourcePolicy(self.bus)
        with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
            policy.observe()
        self.assertIsNone(policy.previous)

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

    @unittest.skipUnless(
        importlib.util.find_spec('gi'),
        'PyGObject is required for native D-Bus variants',
    )
    def test_native_signal_subscription_filters_unrelated_properties_and_handles_invalidation(
        self,
    ):
        from gi.repository import GLib
        from unittest.mock import Mock

        loop = Mock()

        def run():
            callback = self.bus.connection.signal_subscribe.call_args.args[-1]
            self.battery = True
            callback(
                None,
                ':1.1',
                source.UPOWER_PATH,
                source.PROPERTIES,
                'PropertiesChanged',
                GLib.Variant(
                    '(sa{sv}as)',
                    (source.UPOWER, {'LidIsClosed': GLib.Variant('b', True)}, []),
                ),
                None,
            )
            self.bus.select_profile.assert_not_called()
            callback(
                None,
                ':1.1',
                source.UPOWER_PATH,
                source.PROPERTIES,
                'PropertiesChanged',
                GLib.Variant('(sa{sv}as)', (source.UPOWER, {}, ['OnBattery'])),
                None,
            )
            self.assertEqual(self.active, 'power-saver')
            self.battery = False
            callback(
                None,
                ':1.1',
                source.UPOWER_PATH,
                source.PROPERTIES,
                'PropertiesChanged',
                GLib.Variant(
                    '(sa{sv}as)',
                    (source.UPOWER, {'OnBattery': GLib.Variant('b', False)}, []),
                ),
                None,
            )
            self.assertEqual(self.active, 'balanced')

        loop.run.side_effect = run
        with (
            patch.object(source, 'Bus', return_value=self.bus),
            patch.object(GLib, 'MainLoop', return_value=loop),
        ):
            self.assertEqual(source.main(), 0)
        self.assertEqual(
            self.bus.connection.signal_subscribe.call_args.args[:5],
            (
                source.UPOWER,
                source.PROPERTIES,
                'PropertiesChanged',
                source.UPOWER_PATH,
                source.UPOWER,
            ),
        )


class ThermalDelegation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patch = patch.object(thermal, 'SYS', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for name, value in [
            ('devices/virtual/dmi/id/product_name', 'ROG GA402RK'),
            ('devices/system/cpu/cpufreq/boost', '1'),
            ('firmware/acpi/platform_profile', 'performance'),
            ('class/hwmon/hwmon0/name', 'asus_custom_fan_curve'),
        ]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        self.operations = []
        self.values = {'ppt_apu_sppt': 80, 'ppt_platform_sppt': 115}
        self.maxima = dict(self.values)
        self.enabled = False
        self.platform = 1
        self.environment = patch.dict(
            os.environ,
            {
                'TUNED_asus_platform': 'performance',
                'TUNED_asus_apu_limit': '45',
                'TUNED_asus_platform_limit': '60',
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        owner = self

        class Bus:
            def get(self, interface, name, path=thermal.PATH):
                if name == 'PlatformProfile':
                    return owner.platform
                if name == 'EnablePptGroup':
                    return owner.enabled
                attribute = path.rsplit('/', 1)[1]
                return {
                    'MinValue': 15,
                    'MaxValue': owner.maxima[attribute],
                    'CurrentValue': owner.values[attribute],
                }[name]

            def set(self, interface, name, kind, value, path=thermal.PATH):
                owner.operations.append((name, value))
                if name == 'EnablePptGroup':
                    owner.enabled = value
                else:
                    owner.values[path.rsplit('/', 1)[1]] = value

            def call(self, interface, method, signature, values):
                owner.operations.append((method, values))
                chip = owner.root / 'class/hwmon/hwmon0'
                if method == 'SetFanCurve':
                    _, (name, pwms, temps, enabled) = values
                    fan = 1 if name == 'CPU' else 2
                    (chip / f'pwm{fan}_enable').write_text('1' if enabled else '2')
                    for point, (pwm, temp) in enumerate(zip(pwms, temps), 1):
                        (chip / f'pwm{fan}_auto_point{point}_pwm').write_text(str(pwm))
                        (chip / f'pwm{fan}_auto_point{point}_temp').write_text(
                            str(temp)
                        )

        self.bus = Bus()

    def test_fans_precede_limits_and_actual_firmware_readback_is_required(self):
        thermal.apply(self.bus)
        self.assertEqual(self.values, {'ppt_apu_sppt': 45, 'ppt_platform_sppt': 60})
        names = [row[0] for row in self.operations]
        self.assertLess(
            names.index('SetFanCurvesEnabled'), names.index('EnablePptGroup')
        )
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

        broken = Mock()
        broken.get.side_effect = RuntimeError('ASUS service unavailable')
        with (
            patch.object(thermal, 'Bus', return_value=broken),
            patch.object(thermal.sys, 'argv', ['thermal', 'start']),
        ):
            with self.assertRaisesRegex(SystemExit, 'ASUS service unavailable'):
                thermal.main()
        self.assertEqual(
            (self.root / 'devices/system/cpu/cpufreq/boost').read_text(), '0'
        )
        self.assertEqual(
            (self.root / 'firmware/acpi/platform_profile').read_text(), 'quiet'
        )

    def test_stop_restores_firmware_defaults_before_disabling_manual_fans(self):
        thermal.restore(self.bus)
        self.assertEqual(
            self.operations,
            [('EnablePptGroup', False), ('SetFanCurvesEnabled', (1, False))],
        )

    def test_daily_modes_use_their_budget_and_keep_fans_off_below_sixty(self):
        self.platform = 0
        with patch.dict(
            os.environ,
            {
                'TUNED_asus_platform': 'balanced',
                'TUNED_asus_apu_limit': '30',
                'TUNED_asus_platform_limit': '45',
            },
        ):
            thermal.apply(self.bus)
            self.assertEqual(self.values, {'ppt_apu_sppt': 30, 'ppt_platform_sppt': 45})
            self.assertEqual(
                (self.root / 'class/hwmon/hwmon0/pwm1_auto_point3_pwm').read_text(), '0'
            )
            self.assertEqual(self.operations[0][1][0], 0)

    def test_stop_restores_the_outgoing_platform_even_when_variables_changed(self):
        self.platform = 2
        thermal.restore(self.bus)
        self.assertEqual(self.operations[-1], ('SetFanCurvesEnabled', (2, False)))


class Measurements(unittest.TestCase):
    def row(self, seconds=0, wh=40, watts=10, status='Discharging'):
        return dict(
            monotonic=seconds,
            batteries=dict(BAT0=dict(status=status, watts=watts, wh=wh, full_wh=50)),
            temperatures={'k10temp:Tctl': 60},
            gpus={'gpu': dict(state='suspended')},
        )

    def test_battery_discharge_and_energy_delta_are_separate_estimates(self):
        result = study.summarize([self.row(), self.row(360, wh=39)])['batteries'][
            'BAT0'
        ]
        self.assertEqual(result['mean_w'], 10)
        self.assertEqual(result['energy_delta_mean_w'], 10)
        self.assertEqual(result['estimated_full_hours'], 5)
        self.assertEqual(result['estimated_remaining_hours'], 3.9)

    def test_recording_summary_uses_cpu_deltas_without_double_counting_guest(self):
        rows = [
            dict(self.row(), cpu_stat='cpu 100 0 50 850 0 0 0 0 99 0', memory_used=128),
            dict(self.row(30), memory_used=512),
            dict(
                self.row(60), cpu_stat='cpu 130 0 70 900 0 0 0 0 199 0', memory_used=256
            ),
        ]
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

    def test_battery_observation_never_reads_even_an_active_gpu_sensor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / 'class/drm/card1/device'
            for name, data in [
                ('device', '0x73ef'),
                ('power/runtime_status', 'active'),
                ('power/control', 'auto'),
                ('gpu_busy_percent', '0'),
                ('hwmon/hwmon1/temp1_input', '60000'),
            ]:
                path = device / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data)
            original = study.read

            def checked(path):
                if Path(path).name in (
                    'gpu_busy_percent',
                    'temp1_input',
                    'power1_input',
                    'power1_average',
                ):
                    self.fail('Passive recording read a GPU sensor: ' + str(path))
                return original(path)

            with (
                patch.object(study, 'SYS', root),
                patch.object(study, 'read', side_effect=checked),
            ):
                row = study.sample()
            self.assertEqual(row['gpus']['device']['state'], 'active')
            self.assertNotIn('edge', row['gpus']['device'])

    def test_suspend_gap_invalidates_a_recording_even_when_monotonic_pauses(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'recording'
            with (
                patch.object(study, 'SYS', root),
                patch.object(study.time, 'clock_gettime', side_effect=[0, 0, 2, 120]),
                patch.object(study.time, 'monotonic', side_effect=[0, 0, 2, 4]),
                patch.object(study.time, 'sleep'),
                patch.object(sys, 'stdout', io.StringIO()),
                patch.object(
                    sys,
                    'argv',
                    [
                        'power-study',
                        '--duration',
                        '4',
                        '--warmup',
                        '0',
                        '--output',
                        str(output),
                        'test',
                    ],
                ),
            ):
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
        for name, value in [
            ('balanced', '0'),
            ('performance', '1'),
            ('powersave', '0'),
        ]:
            profile = self.config(name)
            self.assertEqual(profile['main']['include'], 'zephyrus-common')
            self.assertNotIn('boost', profile['cpu'])
            self.assertEqual(
                profile['sysfs']['/sys/devices/system/cpu/cpufreq/boost'], value
            )

    def test_platform_profile_is_applied_before_cpu_and_sysfs(self):
        profile = self.config('common')
        self.assertLess(
            int(profile['acpi']['priority']), int(profile['cpu']['priority'])
        )
        self.assertLess(
            int(profile['cpu']['priority']), int(profile['sysfs']['priority'])
        )
        self.assertLess(
            int(profile['sysfs']['priority']),
            int(profile['sysfs_cpu_limits']['priority']),
        )
        self.assertLess(
            int(profile['sysfs_cpu_limits']['priority']),
            int(profile['script']['priority']),
        )
        self.assertIn(
            'cpuinfo_max_freq',
            profile['sysfs_cpu_limits'][
                '/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq'
            ],
        )

    @unittest.skipUnless(importlib.util.find_spec('tuned'), 'Native TuneD is required')
    def test_native_profile_merge_preserves_the_custom_sysfs_plugin_type(self):
        from tuned.profiles.profile import Profile
        from tuned.profiles.merger import Merger

        def profile(name):
            config = self.config(name)
            return Profile(
                name, {section: dict(config[section]) for section in config.sections()}
            )

        merged = Merger().merge([profile('common'), profile('performance')])
        limits = merged.units['sysfs_cpu_limits']
        self.assertEqual(limits.type, 'sysfs')
        self.assertEqual(
            limits.options['/sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq'],
            '4000000',
        )

    def test_each_mode_forces_a_source_transition_for_thermal_reapplication(self):
        ppd = configparser.ConfigParser()
        ppd.read(POWER / 'files/etc/tuned/ppd.conf')
        for mode, parent in [
            ('performance', 'performance'),
            ('power-saver', 'powersave'),
        ]:
            self.assertNotEqual(ppd['profiles'][mode], ppd['battery'][mode])
            self.assertEqual(
                self.config(parent + '-battery')['main']['include'],
                'zephyrus-' + parent,
            )
        self.assertNotEqual(ppd['profiles']['balanced'], ppd['battery']['balanced'])


class PanelPolicy(unittest.TestCase):
    """Powersave's 60 Hz panel cap lives only in Hyprland's live rules."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, XDG_CONFIG_HOME=temporary.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.path = Path(temporary.name) / 'hypr/displays.lua'
        self.backend = support.backend
        self.panel = support.described('eDP-1', 'Panel', mode='1920x1080@120.00Hz')
        self.external = support.described(
            'DP-1', 'External', mode='1920x1080@120.00Hz', x=1920
        )
        self.before = support.state([self.panel, self.external])
        self.capped = support.state(
            [dict(self.panel, mode='1920x1080@60.00Hz'), self.external]
        )
        apply = patch.object(
            self.backend,
            'apply_setup',
            side_effect=lambda rows, before: support.state(rows),
        )
        self.apply = apply.start()
        self.addCleanup(apply.stop)
        # The native preferred-mode query; tests never reach Hyprland.
        preferred = patch.object(
            self.backend, 'command', return_value='1920x1080@120.00000'
        )
        self.command = preferred.start()
        self.addCleanup(preferred.stop)

    def save(self, mode):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(
            f'hl.monitor({{ output = "desc:Panel", disabled = false, mode = "{mode}" }})\n'
        )

    def modes(self, result):
        return [row['mode'] for row in result['displays']]

    def test_powersave_caps_only_internal_panels_without_saving(self):
        result, pending = self.backend.power(self.before, True)
        self.assertEqual(
            self.modes(result), ['1920x1080@60.00Hz', '1920x1080@120.00Hz']
        )
        self.assertFalse(pending)
        self.assertFalse(self.path.exists())
        self.apply.reset_mock()
        self.assertEqual(self.backend.power(result, True), (result, False))
        self.apply.assert_not_called()

    def test_leaving_powersave_restores_the_saved_or_default_refresh(self):
        result, _ = self.backend.power(self.capped, False)
        self.assertEqual(self.modes(result)[0], '1920x1080@120.00Hz')
        self.assertEqual(self.command.call_args.args[0], 'repl')
        self.command.reset_mock()
        self.save('1920x1080@120.00')
        result, _ = self.backend.power(self.capped, False)
        self.assertEqual(self.modes(result)[0], '1920x1080@120.00Hz')
        self.command.assert_not_called()

    def test_a_saved_60hz_choice_is_not_raised(self):
        self.save('1920x1080@60.00')
        self.apply.reset_mock()
        self.assertEqual(self.backend.power(self.capped, False), (self.capped, False))
        self.apply.assert_not_called()

    def test_saving_while_capped_keeps_the_uncapped_refresh(self):
        moved = support.state([dict(self.capped['displays'][0], y=10), self.external])
        self.backend.persist(moved, True)
        rule = next(
            line for line in self.path.read_text().splitlines() if 'desc:Panel' in line
        )
        self.assertIn('mode = "1920x1080@120.00"', rule)
        self.assertIn('position = "0x10"', rule)
        # An explicit refresh choice (not capped) is saved as chosen.
        self.backend.persist(moved, False)
        self.assertIn('mode = "1920x1080@60.00"', self.path.read_text())

    def test_powersave_change_saves_then_reapplies_the_cap(self):
        enabled = support.state([self.panel, self.external])
        request = dict(
            op='change',
            name='eDP-1',
            identity=self.panel['identity'],
            values=dict(enabled=True),
            capped=True,
        )
        with patch.object(self.backend, 'control', return_value=enabled):
            result = self.backend.response(request)
        self.assertTrue(result['ok'], result['error'])
        self.assertEqual(self.modes(result['data'])[0], '1920x1080@60.00Hz')
        self.assertIn('mode = "1920x1080@120.00"', self.path.read_text())
        self.apply.reset_mock()
        with patch.object(self.backend, 'control', return_value=enabled):
            result = self.backend.response(dict(request, capped=False))
        self.apply.assert_not_called()
        self.assertEqual(self.modes(result['data'])[0], '1920x1080@120.00Hz')

    def test_blank_panels_are_not_woken_and_report_pending(self):
        for powersave, current in ((True, self.before), (False, self.capped)):
            dark = support.state(
                [dict(current['displays'][0], dpms=False), self.external]
            )
            with self.subTest(powersave=powersave):
                self.assertEqual(self.backend.power(dark, powersave), (dark, True))
        self.apply.assert_not_called()

    def test_policy_never_changes_resolution_or_external_outputs(self):
        panel = dict(self.panel, modes=['1920x1080@120.00Hz', '1280x720@60.00Hz'])
        current = support.state([panel, self.external])
        self.assertEqual(self.backend.power(current, True), (current, False))
        self.apply.assert_not_called()

    def test_failed_modeset_is_reported(self):
        self.apply.side_effect = RuntimeError('modeset failed')
        with patch.object(self.backend, 'snapshot', return_value=self.before):
            result = self.backend.response(dict(op='power', capped=True))
        self.assertFalse(result['ok'])
        self.assertIn('modeset failed', result['error'])


if __name__ == '__main__':
    unittest.main()
