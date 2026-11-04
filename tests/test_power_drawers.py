"""Power actions and drawer lifecycle without changing the host's hardware."""

import importlib.util
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import support


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = load('desktop_power', support.DESKTOP / 'drawers/power/backend.py')
asus = load(
    'asus_power',
    Path(__file__).resolve().parents[1]
    / 'modules/hardware/devices/zephyrus/symlinks/home/.config/devices/power/backends/asus.py',
)


def snapshot():
    return dict(
        hardware=[
            dict(
                key='asus',
                label='ASUS battery care',
                identity=':1.3',
                limit=80,
                minimum=20,
                maximum=100,
                step=1,
            )
        ],
        hardwareErrors=[],
        policy='',
        metrics=dict(
            cpu=dict(
                label='Test CPU',
                usage=23,
                frequency=2.4,
                temperature=53,
                load=['0.5', '0.4', '0.3'],
            ),
            memory=dict(
                total=16 * 1024**3,
                used=6 * 1024**3,
                swapTotal=0,
                swapUsed=0,
                pressure=0,
            ),
            gpus=[
                dict(
                    key='gpu',
                    label='Test GPU',
                    driver='amdgpu',
                    sleeping=True,
                    usage=None,
                    used=None,
                    total=None,
                    temperature=None,
                )
            ],
            fans=[dict(key='cpu', label='CPU fan', rpm=0)],
        ),
    )


class PolicyTests(unittest.TestCase):
    def setUp(self):
        with patch.object(backend, 'PROVIDERS', Path('/nonexistent')):
            self.controller = backend.Controller()
        self.controller.bus = Mock()

    def test_effective_mode_detects_a_stale_frequency_cap_with_boost_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tuned = root / 'tuned'
            source = (
                Path(__file__).resolve().parents[1]
                / 'modules/hardware/power/files/etc/tuned/profiles'
            )
            shutil.copytree(source, tuned / 'profiles')
            (tuned / 'active_profile').write_text('zephyrus-performance')
            for name, value in [
                ('firmware/acpi/platform_profile', 'performance'),
                ('devices/system/cpu/cpufreq/boost', '1'),
                (
                    'devices/system/cpu/cpufreq/policy0/energy_performance_preference',
                    'performance',
                ),
                ('devices/system/cpu/cpufreq/policy0/scaling_governor', 'powersave'),
                ('devices/system/cpu/cpufreq/policy0/scaling_max_freq', '3301000'),
                ('devices/system/cpu/cpufreq/policy0/cpuinfo_max_freq', '4936631'),
            ]:
                path = root / 'sys' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            with (
                patch.object(backend, 'SYS', root / 'sys'),
                patch.object(backend, 'TUNED', tuned),
            ):
                self.assertIn('frequency ceiling', backend.policy_warning())
                (
                    root / 'sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq'
                ).write_text('4000000')
                self.assertEqual(backend.policy_warning(), '')
                governor = (
                    root / 'sys/devices/system/cpu/cpufreq/policy0/scaling_governor'
                )
                governor.write_text('performance')
                self.assertIn('CPU governor', backend.policy_warning())
                governor.write_text('powersave')
                (tuned / 'profiles/zephyrus-performance/tuned.conf').unlink()
                self.assertIn('incomplete', backend.policy_warning())

    def test_closed_drawer_avoids_thermal_hardware_probing(self):
        with (
            patch.object(self.controller, 'hardware', return_value=([], [])),
            patch.object(
                self.controller.sampler, 'snapshot', return_value={}
            ) as sampler,
            patch.object(backend, 'policy_warning', return_value='') as policy,
            patch.object(
                backend, 'thermal_warning', return_value='fan policy is not active'
            ) as thermal,
        ):
            self.assertEqual(self.controller.handle(dict(op='status'))['policy'], '')
            thermal.assert_not_called()
            policy.assert_not_called()
            sampler.assert_not_called()
            result = self.controller.handle(dict(op='status', details=True))
            self.assertIn('fan policy', result['policy'])
            sampler.assert_called_once()
        with self.assertRaises(ValueError):
            self.controller.handle(dict(op='profile', value='performance'))
        with self.assertRaises(ValueError):
            self.controller.handle(dict(op='charge-limit', key='missing'))
        self.controller.bus.set.assert_not_called()

    def applied_policy(
        self, root, profile, platform, preference, boost, ceiling, apu, budget
    ):
        """Simulate firmware/CPU state after TuneD fully applied one shipped profile."""
        tuned = root / 'tuned'
        if not (tuned / 'profiles').exists():
            shutil.copytree(
                Path(__file__).resolve().parents[1]
                / 'modules/hardware/power/files/etc/tuned/profiles',
                tuned / 'profiles',
            )
        (tuned / 'active_profile').write_text(profile)
        sysfs = root / 'sys'
        for name, value in [
            ('firmware/acpi/platform_profile', platform),
            ('devices/system/cpu/cpufreq/boost', boost),
            (
                'devices/system/cpu/cpufreq/policy0/energy_performance_preference',
                preference,
            ),
            ('devices/system/cpu/cpufreq/policy0/scaling_governor', 'powersave'),
            ('devices/system/cpu/cpufreq/policy0/scaling_max_freq', ceiling),
            ('devices/system/cpu/cpufreq/policy0/cpuinfo_max_freq', '4936631'),
            ('class/hwmon/hwmon0/name', 'asus_custom_fan_curve'),
            ('class/hwmon/hwmon0/pwm1_enable', '1'),
            ('class/hwmon/hwmon0/pwm2_enable', '1'),
        ] + [
            (f'class/firmware-attributes/asus-armoury/attributes/{name}', value)
            for attribute, current in (
                ('ppt_apu_sppt', apu),
                ('ppt_platform_sppt', budget),
            )
            for name, value in (
                (f'{attribute}/min_value', '15'),
                (f'{attribute}/max_value', '80'),
                (f'{attribute}/current_value', current),
            )
        ]:
            path = sysfs / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        return tuned, sysfs

    def test_included_profiles_are_verified_as_tuned_merges_them(self):
        # platform, EPP, boost, CPU ceiling, APU W, platform W
        quiet = 'quiet power 0 4936631 25 40'.split()
        performance = 'performance performance 1 4000000 45 60'.split()
        expected = {
            'zephyrus-balanced': 'balanced balance_power 0 4936631 30 45'.split(),
            # Balanced on battery has no options of its own; it includes Powersave.
            'zephyrus-battery': quiet,
            'zephyrus-powersave': quiet,
            'zephyrus-powersave-battery': quiet,
            'zephyrus-performance': performance,
            'zephyrus-performance-battery': performance,
        }
        for profile, values in expected.items():
            with (
                self.subTest(profile=profile),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                tuned, sysfs = self.applied_policy(root, profile, *values)
                with (
                    patch.object(backend, 'SYS', sysfs),
                    patch.object(backend, 'TUNED', tuned),
                ):
                    self.assertEqual(backend.policy_warning(), '')
                    self.assertEqual(backend.thermal_warning(), '')
                    (sysfs / 'devices/system/cpu/cpufreq/boost').write_text(
                        '0' if values[2] == '1' else '1'
                    )
                    self.assertIn('CPU boost', backend.policy_warning())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tuned, sysfs = self.applied_policy(root, 'zephyrus-battery', *quiet)
            (tuned / 'profiles/zephyrus-battery/tuned.conf').write_text(
                '[main]\ninclude=zephyrus-missing\n'
            )
            with (
                patch.object(backend, 'SYS', sysfs),
                patch.object(backend, 'TUNED', tuned),
            ):
                self.assertIn('incomplete', backend.policy_warning())

    def test_readback_waits_while_tuned_applies_a_switched_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            tuned = Path(directory)
            active = tuned / 'active_profile'
            active.write_text('zephyrus-balanced')
            with (
                patch.object(backend, 'TUNED', tuned),
                patch.object(self.controller, 'hardware', return_value=([], [])),
                patch.object(self.controller.sampler, 'snapshot', return_value={}),
                patch.object(
                    backend,
                    'policy_warning',
                    return_value='Policy not fully applied: platform',
                ) as policy,
                patch.object(backend, 'thermal_warning', return_value='') as thermal,
            ):
                # TuneD writes active_profile, then applies in its own thread.
                self.assertEqual(self.controller.snapshot(True)['policy'], '')
                policy.assert_not_called()
                thermal.assert_not_called()
                old = time.time() - backend.SETTLE_SECONDS - 1
                os.utime(active, (old, old))
                self.assertIn('platform', self.controller.snapshot(True)['policy'])

    def test_detailed_thermal_readback_uses_dc_limits_and_actual_fan_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tuned = root / 'tuned'
            source = (
                Path(__file__).resolve().parents[1]
                / 'modules/hardware/power/files/etc/tuned/profiles'
            )
            shutil.copytree(source, tuned / 'profiles')
            (tuned / 'active_profile').write_text('zephyrus-performance-battery')
            for attribute, low, high, current in [
                ('ppt_apu_sppt', 15, 45, 45),
                ('ppt_platform_sppt', 40, 60, 60),
            ]:
                path = (
                    root
                    / 'sys/class/firmware-attributes/asus-armoury/attributes'
                    / attribute
                )
                path.mkdir(parents=True)
                for name, value in [
                    ('min_value', low),
                    ('max_value', high),
                    ('current_value', current),
                ]:
                    (path / name).write_text(str(value))
            chip = root / 'sys/class/hwmon/hwmon0'
            chip.mkdir(parents=True)
            for name, value in [
                ('name', 'asus_custom_fan_curve'),
                ('pwm1_enable', '1'),
                ('pwm2_enable', '1'),
            ]:
                (chip / name).write_text(value)
            with (
                patch.object(backend, 'SYS', root / 'sys'),
                patch.object(backend, 'TUNED', tuned),
            ):
                self.assertEqual(backend.thermal_warning(), '')
                (chip / 'pwm2_enable').write_text('2')
                self.assertIn('fan policy', backend.thermal_warning())


class AsusTests(unittest.TestCase):
    def setUp(self):
        self.bus = Mock()
        self.limit = 80
        self.bus.owner.return_value = ':1.3'
        self.bus.call.side_effect = lambda service, path, interface, method, *args: (
            ['ChargeControlEndThreshold']
            if method == 'SupportedProperties'
            else self.limit
        )
        self.provider = asus.Provider(self.bus)
        self.request = dict(identity=':1.3', previous=80, value=60)

    def test_vendor_capabilities_and_actual_limit_are_not_assumed(self):
        self.limit = 75
        self.assertEqual(self.provider.snapshot()['limit'], 75)
        self.bus.call.side_effect = RuntimeError('not running')
        self.assertIsNone(self.provider.snapshot()['limit'])
        self.assertEqual(self.provider.snapshot()['minimum'], 20)
        self.bus.set.assert_not_called()

    def test_charge_limit_revalidates_and_confirms(self):
        for fields in (
            dict(identity='stale'),
            dict(previous=60),
            dict(value=19),
            dict(value=101),
            dict(value=True),
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.provider.change(dict(self.request, **fields))
        self.bus.set.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.provider.change(self.request)
        self.bus.set.side_effect = lambda *args: setattr(self, 'limit', args[-1])
        self.provider.change(self.request)
        self.bus.set.assert_called_with(
            asus.SERVICE,
            asus.PATH,
            asus.INTERFACE,
            'ChargeControlEndThreshold',
            'y',
            60,
        )
        self.provider.change(dict(self.request, previous=60, value=75))
        self.assertEqual(self.limit, 75)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.proc = self.root / 'proc'
        self.sys = self.root / 'sys'
        self.proc.mkdir()
        self.sys.mkdir()
        self.patches = [
            patch.object(backend, 'PROC', self.proc),
            patch.object(backend, 'SYS', self.sys),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def test_gpu_sampling_leaves_a_long_enough_gap_for_autosuspend(self):
        device = self.sys / 'class/drm/card1/device'
        for name, data in [
            ('vendor', '0x1002'),
            ('device', '0x73ef'),
            ('power/runtime_status', 'active'),
            ('power/control', 'auto'),
            ('power/autosuspend_delay_ms', '5000'),
            ('gpu_busy_percent', '65'),
            ('hwmon/hwmon0/temp1_input', '55000'),
        ]:
            self.write(device / name, data)
        sampler = backend.Sampler()
        with patch.object(backend.time, 'monotonic', return_value=100):
            self.assertEqual(sampler.gpus()[0]['temperature'], 55)
        original = backend.read

        def checked(path):
            if path.name in ('gpu_busy_percent', 'temp1_input'):
                self.fail('Sensor read reset the GPU autosuspend countdown')
            return original(path)

        with (
            patch.object(backend.time, 'monotonic', return_value=102),
            patch.object(backend, 'read', side_effect=checked),
        ):
            row = sampler.gpus()[0]
            self.assertEqual(row['temperature'], 55)
            self.assertEqual(row['sampleAge'], 2)
        self.write(device / 'power/runtime_status', 'suspended')
        with (
            patch.object(backend.time, 'monotonic', return_value=106),
            patch.object(backend, 'read', side_effect=checked),
        ):
            row = sampler.gpus()[0]
            self.assertTrue(row['sleeping'])
            self.assertIsNone(row['temperature'])

    def test_deltas_memory_pressure_missing_values_and_resume(self):
        self.write(self.proc / 'stat', 'cpu 100 0 50 850 0 0 0 0 99 0\n')
        self.write(
            self.proc / 'meminfo',
            'MemTotal: 1000 kB\nMemAvailable: 600 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n',
        )
        self.write(
            self.proc / 'pressure/memory', 'some avg10=1.25 avg60=0.0 total=123\n'
        )
        sampler = backend.Sampler()
        self.assertIsNone(sampler.snapshot()['cpu']['usage'])
        self.write(self.proc / 'stat', 'cpu 130 0 70 900 0 0 0 0 99 0\n')
        state = sampler.snapshot()
        self.assertEqual(state['cpu']['usage'], 50)
        self.assertEqual(state['memory']['used'], 400 * 1024)
        self.assertEqual(state['memory']['pressure'], 1.25)
        self.assertEqual(state['memory']['swapUsed'], 0)
        sampler.sampled_at -= 20
        self.assertIsNone(sampler.snapshot()['cpu']['usage'])
        (self.proc / 'meminfo').unlink()
        self.assertIsNone(sampler.snapshot()['memory']['used'])

    def test_sleeping_gpu_and_hwmon_never_read_sensor_files(self):
        device = self.sys / 'class/drm/card0/device'
        for name, value in [
            ('power/runtime_status', 'suspended'),
            ('vendor', '0x1002'),
            ('device', '0x1234'),
            ('gpu_busy_percent', '65'),
            ('hwmon/hwmon0/temp1_input', '55000'),
        ]:
            self.write(device / name, value)
        hwmon = self.sys / 'class/hwmon/hwmon0'
        hwmon.mkdir(parents=True)
        (hwmon / 'device').symlink_to(device)
        self.write(hwmon / 'fan1_input', '2000')
        original = backend.read

        def guarded(path):
            if path.name in ('gpu_busy_percent', 'temp1_input', 'fan1_input'):
                self.fail('Read a sleeping device sensor: ' + str(path))
            return original(path)

        with patch.object(backend, 'read', side_effect=guarded):
            state = backend.Sampler().snapshot()
        self.assertTrue(state['gpus'][0]['sleeping'])
        self.assertIsNone(state['gpus'][0]['usage'])
        self.assertEqual(state['fans'], [])
        self.write(device / 'power/runtime_status', 'active')
        self.assertEqual(backend.Sampler().snapshot()['gpus'][0]['usage'], 65)

    def test_any_display_driver_hwmon_is_left_to_the_paced_gpu_sampler(self):
        # An awake discrete GPU on another driver: its sensor reads would reset
        # the autosuspend countdown every two seconds.
        device = self.sys / 'devices/pci0000:00/0000:01:00.0'
        self.write(device / 'class', '0x030000')
        self.write(device / 'power/runtime_status', 'active')
        gpu = self.sys / 'class/hwmon/hwmon0'
        self.write(gpu / 'name', 'nouveau')
        self.write(gpu / 'fan1_input', '1800')
        self.write(gpu / 'temp1_input', '60000')
        (gpu / 'device').symlink_to(device)
        cpu = self.sys / 'class/hwmon/hwmon1'
        self.write(cpu / 'name', 'k10temp')
        self.write(cpu / 'temp1_input', '48000')
        self.write(self.sys / 'class/hwmon/hwmon2/name', 'asus')
        self.write(self.sys / 'class/hwmon/hwmon2/fan1_input', '2100')
        self.write(self.sys / 'class/hwmon/hwmon2/fan1_label', 'cpu_fan')
        original = backend.read

        def guarded(path):
            if path.parent == gpu and path.name != 'name':
                self.fail('Read a display device sensor outside the GPU sampler')
            return original(path)

        with patch.object(backend, 'read', side_effect=guarded):
            state = backend.Sampler().snapshot()
        self.assertEqual(state['cpu']['temperature'], 48)
        self.assertEqual([fan['label'] for fan in state['fans']], ['CPU fan'])

    def test_constant_cpu_and_gpu_names_are_read_once_from_local_files(self):
        database = self.root / 'pci.ids'
        database.write_text(
            '# comment\n'
            '10de  NVIDIA Corporation\n'
            '\t73ef  Other vendor, same device ID\n'
            '1002  Advanced Micro Devices, Inc. [AMD/ATI]\n'
            '\t1681  Rembrandt [Radeon 680M]\n'
            '\t\t1043 1e12  Subsystem\n'
            '\t73ef  Navi 23 [Radeon RX 6650 XT / 6700S / 6800S]\n'
            '1022  Advanced Micro Devices, Inc. [AMD]\n'
            '\t1681  Not a graphics device\n'
        )
        for card, identifier in (('card0', '0x73ef'), ('card1', '0x1681')):
            device = self.sys / 'class/drm' / card / 'device'
            self.write(device / 'vendor', '0x1002')
            self.write(device / 'device', identifier)
            self.write(device / 'power/runtime_status', 'suspended')
        self.write(self.proc / 'cpuinfo', 'model name\t: Test CPU 6900HS\n')
        reads = []
        original = backend.read

        def counted(path):
            reads.append(path.name)
            return original(path)

        sampler = backend.Sampler()
        with (
            patch.object(backend, 'PCI_IDS', database),
            patch.object(backend, 'read', side_effect=counted),
        ):
            backend.pci_name.cache_clear()
            first = sampler.snapshot()
            second = sampler.snapshot()
        backend.pci_name.cache_clear()
        self.assertEqual(
            [gpu['label'] for gpu in first['gpus']],
            ['Navi 23 [Radeon RX 6650 XT / 6700S / 6800S]', 'Rembrandt [Radeon 680M]'],
        )
        self.assertEqual(second['gpus'][1]['label'], 'Rembrandt [Radeon 680M]')
        self.assertEqual(second['cpu']['label'], 'Test CPU 6900HS')
        self.assertEqual(reads.count('cpuinfo'), 1)


# Native UPower stand-ins: plain objects (UPowerDevice percentages are 0-1).
UPOWER = """
 function device(values){return Object.assign({type:UPowerDeviceType.Battery,powerSupply:true,isPresent:true,isLaptopBattery:true,ready:true,model:"Laptop battery",nativePath:"BAT0",
  state:UPowerDeviceState.Discharging,percentage:.76,energy:38,energyCapacity:50,changeRate:8,timeToEmpty:17100,timeToFull:0,healthPercentage:83.3,healthSupported:true},values);}
 property var up: ({onBattery:true,displayDevice:device({}),devices:{values:[device({})]}})
 function setPower(fn){const u=Object.assign({},up);fn(u);up=u;}
"""


@unittest.skipUnless(support.QS, 'Quickshell is required')
class PowerQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            shutil.copytree(support.DESKTOP / 'bar', root / 'bar')
            if setup:
                setup(root)

        return support.run_qml(self, body, prepare)

    def test_drawers_native_values_actions_missing_data_narrow_and_bar(self):
        self.run_qml(
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import Quickshell.Services.UPower
import "drawers"
import "bar"
import "ui"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:mock
  property var state: DATA
  property bool loaded:true
  property bool reading:false
  property bool changing:false
  property string error:""
  property var owners:[]
  property int limit:0
  function observe(owner,active,details){owners=owners.filter(x=>x!==owner).concat(active?[owner]:[]);}
  function refresh(){}
  function chargeLimit(row,value){limit=value;}
 }
 QtObject {id:utilities;property bool ready:true;property bool busy:false;property string error:"";property var state:({once:null,recording:null,recordAvailable:false,modesAvailable:true});property var sent:[];function send(request){sent=sent.concat([request]);}}
 QtObject {id:profiles;property int profile:PowerProfile.Balanced;property bool hasPerformanceProfile:true;property int degradationReason:PerformanceDegradationReason.None;property var holds:[]}
UPOWER
 BatteryStatus {id:barBattery; device:({isPresent:true,type:UPowerDeviceType.Battery,percentage:.76,state:UPowerDeviceState.Discharging})}
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:1080;visible:true;color:Theme.background
  BatteryDrawer {id:battery;x:16;y:16;width:window.width-32;height:window.height-32;active:true;service:mock;session:utilities;upower:up}
  PerformanceDrawer {id:performance;x:16;y:16;width:window.width-32;height:window.height-32;visible:false;active:false;service:mock;session:utilities;profiles:profiles}
 }
 property var focusedControl:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function capture(name,item){const dir=Quickshell.env("DISPLAY_PREVIEW_DIR");if(dir)item.grabToImage(result=>result.saveToFile(dir+"/power-"+name+".png"));}
 function update(fn){const state=JSON.parse(JSON.stringify(mock.state));fn(state);mock.state=state;}
 property int stage:0
 Timer {interval:200;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   const modes=["power-saver","balanced","performance"].map(name=>find(performance,"powerProfile:"+name));
   check(modes[0].x < modes[1].x && modes[1].x < modes[2].x,"power modes are not ordered from savings to performance");
   check(find(battery,"batteryPercentage").text==="76%","battery percentage");
   check(find(battery,"batteryEstimate").detail.indexOf("remaining")>=0,"estimate missing");
   check(find(battery,"batteryHealth").value==="83.3%","health");
   check(barBattery.label==="76%"&&!barBattery.charging,"bar percentage normalization");
   const gauge=find(battery,"batteryGauge"), slider=gauge.slider;
   check(slider.from===20&&slider.to===100&&slider.stepSize===1,"charge limit range");
   slider.forceActiveFocus();focusedControl=slider;input.keyClick(Qt.Key_Left);
   check(mock.limit===79,"keyboard charge action");
   check(find(battery,"chargeLimitApplied").text.indexOf("80%")>=0,"optimistic charge limit");
   const track=find(gauge,"batteryLevelTrack"), fill=find(gauge,"batteryLevelFill"), marker=find(gauge,"chargeLimitMarker");
   check(Math.abs(fill.width/track.width-.76)<.005,"battery percentage rescaled to limit");
   check(Math.abs((marker.x+marker.width/2)/track.width-.8)<.005,"charge marker not at 80 percent");
   capture("battery",battery);
  }else if(stage===1){
   setPower(u=>u.onBattery=false);
   check(!find(battery,"batteryEstimate").visible,"AC residual discharge displayed as battery runtime");
   update(s=>{s.hardware[0].limit=75;});
   setPower(u=>u.displayDevice=device({state:UPowerDeviceState.Charging,timeToFull:0,percentage:0}));
   check(find(battery,"chargeLimitApplied").text.indexOf("75%")>=0,"actual custom limit hidden");
   check(find(battery,"batteryGauge").slider===focusedControl&&focusedControl.activeFocus,"refresh replaced charge control or focus");
   check(find(battery,"batteryEstimate").value==="…","zero time not estimating");
   check(find(battery,"batteryPercentage").text==="0%","empty battery unavailable");
   barBattery.device=({isPresent:true,type:UPowerDeviceType.Battery,percentage:.1,state:UPowerDeviceState.Charging});
   check(barBattery.charging&&barBattery.iconName==="battery-charging","charging indicator missing");
   battery.active=false;battery.visible=false;performance.active=true;performance.visible=true;
  }else if(stage===2){
   check(find(performance,"cpuUsage").value==="23%","CPU missing");
   const profileButton=find(performance,"powerProfile:power-saver");
   profileButton.forceActiveFocus();input.keyClick(Qt.Key_Space);
   check(utilities.sent.length===1&&utilities.sent[0].op==="profile"&&utilities.sent[0].value==="power-saver","mode request");
   // PowerProfiles follows PPD's confirmed property; the drawer never pre-selects.
   check(profiles.profile===PowerProfile.Balanced&&!profileButton.current,"unconfirmed mode shown as active");
   utilities.busy=true;check(!profileButton.enabled,"mode selectable while a change is pending");utilities.busy=false;
   profiles.profile=PowerProfile.PowerSaver;check(profileButton.current,"confirmed mode not shown");
   check(!find(performance,"performanceModesUnavailable").visible,"available modes reported unavailable");
   check(!find(performance,"performanceDegraded").visible&&!find(performance,"performancePolicy").visible,"spurious warnings");
   capture("performance",performance);
  }else if(stage===3){
   profiles.hasPerformanceProfile=false;profiles.degradationReason=PerformanceDegradationReason.HighTemperature;
   profiles.holds=[{applicationId:"Game",profile:PowerProfile.Performance,reason:"Playing"}];
   update(s=>{s.policy="Policy not fully applied: CPU boost";s.metrics.cpu.usage=null;});
   check(!find(performance,"powerProfile:performance"),"unavailable performance profile offered");
   check(find(performance,"performanceHold").text==="Game requests Performance: Playing","hold profile label");
   check(find(performance,"performanceDegraded").visible&&find(performance,"performancePolicy").visible,"warnings hidden");
   utilities.state=Object.assign({},utilities.state,{modesAvailable:false});
   check(!find(performance,"powerProfile:balanced").visible&&find(performance,"performanceModesUnavailable").visible,"modes offered without a power mode service");
   utilities.state=Object.assign({},utilities.state,{modesAvailable:true});
   battery.width=268;performance.width=268;
  }else if(stage===4){capture("performance-narrow",performance);Theme.setMode("light");
  }else if(stage===5){performance.active=false;performance.visible=false;battery.visible=true;battery.active=true;
  }else if(stage===6){
   capture("battery-narrow-light",battery);
   update(s=>{s.hardware=[];});setPower(u=>{u.devices={values:[]};});
   barBattery.device=({isPresent:false,type:UPowerDeviceType.Battery,percentage:0,state:0});
   check(barBattery.label===""&&!barBattery.available,"absent bar fabricated charge");
  }else if(stage===7){
   check(find(battery,"batteryPercentage").text==="No system battery","desktop battery handling");
   check(!find(battery,"chargeLimitMarker").visible,"unsupported charge limit exposed");
   battery.active=false;check(mock.owners.length===0,"observer survived dismissal");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""".replace('UPOWER', UPOWER).replace('DATA', json.dumps(snapshot()))
        )

    def test_polling_follows_observers_and_stops_on_dismissal(self):
        def setup(root):
            (root / 'drawers/power/backend.py').write_text(
                """import json,sys
state=DATA
for line in sys.stdin:
 request=json.loads(line)
 print(json.dumps(dict(ok=True,data=dict(state,metrics=state['metrics'] if request['details'] else None),error='')),flush=True)
""".replace('DATA', repr(snapshot()))
            )
            (root / 'drawers/power/session.py').write_text(
                'import sys\nsys.stdin.read()\n'
            )

        self.run_qml(
            """import QtQuick
import Quickshell
import "drawers/power"
ShellRoot {
 QtObject {id:batteryOwner}
 QtObject {id:performanceOwner}
 property int stage:0
 function check(value,message){if(!value)throw new Error(message);}
 Timer {interval:60;repeat:true;running:true;onTriggered:{try{
  if(stage===0){PowerService.observe(batteryOwner,true,false);stage++;}
  else if(stage===1&&PowerService.loaded&&!PowerService.reading){
   check(PowerService.interval===10000&&PowerService.state.metrics===null,"battery polling sampled telemetry");
   PowerService.observe(performanceOwner,true,true);PowerService.observe(batteryOwner,false,false);stage++;
  }else if(stage===2&&!PowerService.reading){
   check(PowerService.interval===2000&&PowerService.state.metrics!==null,"performance polling");
   PowerService.observe(performanceOwner,false,true);stage++;
  }else if(stage===3&&!PowerService.running){
   PowerService.observe(batteryOwner,true,false);stage++;
  }else if(stage===4&&PowerService.loaded&&!PowerService.reading&&PowerService.running){
   PowerService.observe(batteryOwner,false,false);stage++;
  }else if(stage===5&&!PowerService.running){
   check(PowerService.error==="","restart reported an error");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
            setup,
        )


if __name__ == '__main__':
    unittest.main()
