"""Power actions and drawer lifecycle without changing the host's hardware."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_display_drawer as fixtures


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backend = load('desktop_power', fixtures.DESKTOP / 'drawers/power/backend.py')
asus = load('asus_power', Path(__file__).resolve().parents[1] / 'modules/hardware/devices/zephyrus/symlinks/home/.config/devices/power/backends/asus.py')


def pack(**values):
    return dict(dict(Type=2, PowerSupply=True, IsPresent=True, Model='Laptop battery', State=2,
                     Percentage=76., Energy=38., EnergyFull=50., EnergyFullDesign=60.,
                     ChargeCycles=180, EnergyRate=8., TimeToEmpty=17100, TimeToFull=0), **values)


def snapshot():
    battery = backend.battery_record('BAT0', pack())
    return dict(battery=dict(available=True, error='', onBattery=True, summary=battery, batteries=[battery]),
                profiles=dict(available=True, service='test', identity=':1.2', active='balanced',
                              choices=['power-saver', 'balanced', 'performance'], degraded='', inhibited='', holds=[], error=''),
                hardware=[dict(key='asus', label='ASUS battery care', identity=':1.3', limit=80, minimum=20, maximum=100, step=1, editor=['rog-control-center'], editorLabel='ROG hardware controls', editorHint='Fan curves and ASUS hardware settings.')],
                hardwareErrors=[],
                metrics=dict(cpu=dict(label='Test CPU', usage=23, frequency=2.4, temperature=53, load=['0.5', '0.4', '0.3']),
                             memory=dict(total=16 * 1024**3, used=6 * 1024**3, swapTotal=0, swapUsed=0, pressure=0),
                             gpus=[dict(key='gpu', label='Test GPU', driver='amdgpu', sleeping=True, usage=None, used=None, total=None, temperature=None)],
                             fans=[dict(key='cpu', label='CPU fan', rpm=0)]))


class BatteryTests(unittest.TestCase):
    def test_missing_values_and_zero_have_distinct_meanings(self):
        row = backend.battery_record('test', pack(Percentage=0., ChargeCycles=0, EnergyRate=0., TimeToEmpty=0))
        self.assertEqual((row['percentage'], row['cycles'], row['rate']), (0., 0, 0.))
        self.assertIsNone(row['seconds'])
        row = backend.battery_record('test', pack(Percentage=float('nan'), ChargeCycles=-1, EnergyFull=0, EnergyFullDesign=0))
        self.assertIsNone(row['percentage'])
        self.assertIsNone(row['cycles'])
        self.assertIsNone(row['health'])
        self.assertIsNone(backend.battery_record('test', {})['rate'])

    def test_combined_summary_uses_upower_and_excludes_peripherals(self):
        bus = Mock()
        def properties(service, path, interface):
            if path == backend.POWER_PATH: return dict(OnBattery=True)
            if path.endswith('DisplayDevice'): return pack(Percentage=63., TimeToEmpty=7200)
            return {'one': pack(Percentage=90.), 'two': pack(Percentage=30.),
                    'mouse': pack(PowerSupply=False), 'absent': pack(IsPresent=False)}[path]
        bus.properties.side_effect = properties
        bus.call.return_value = ['one', 'two', 'mouse', 'absent']
        state = backend.battery_snapshot(bus)
        self.assertEqual(len(state['batteries']), 2)
        self.assertEqual(state['summary']['percentage'], 63.)
        self.assertEqual(state['summary']['seconds'], 7200)
        self.assertAlmostEqual(state['batteries'][0]['health'], 100 * 50 / 60)

    def test_no_battery_and_service_failure_do_not_invent_charge(self):
        bus = Mock(); bus.call.return_value = []; bus.properties.return_value = dict(OnBattery=False)
        state = backend.battery_snapshot(bus)
        self.assertTrue(state['available']); self.assertIsNone(state['summary']); self.assertFalse(state['onBattery'])
        bus.properties.side_effect = RuntimeError('offline')
        self.assertFalse(backend.battery_snapshot(bus)['available'])


class ProfileTests(unittest.TestCase):
    def setUp(self):
        with patch.object(backend, 'PROVIDERS', Path('/nonexistent')):
            self.controller = backend.Controller()
        self.controller.bus = Mock()
        self.current = dict(snapshot()['profiles'], path='/test')
        self.request = dict(op='profile', value='power-saver', service='test', identity=':1.2', active='balanced')

    def test_rejects_stale_or_unsupported_profiles_before_writing(self):
        for fields in (dict(identity='stale'), dict(active='power-saver'), dict(service='other'), dict(value='turbo')):
            with self.subTest(fields=fields), patch.object(backend, 'profile_snapshot', return_value=self.current):
                with self.assertRaises(ValueError): self.controller.handle(dict(self.request, **fields))
        with patch.object(backend, 'profile_snapshot', return_value=dict(self.current, inhibited='lap-detected')):
            with self.assertRaises(ValueError): self.controller.handle(dict(self.request, value='performance'))
        self.controller.bus.set.assert_not_called()

    def test_effective_mode_detects_a_stale_frequency_cap_with_boost_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tuned = root / 'tuned'
            source = Path(__file__).resolve().parents[1] / 'modules/hardware/power/files/etc/tuned/profiles'
            shutil.copytree(source, tuned / 'profiles')
            (tuned / 'active_profile').write_text('zephyrus-performance')
            for name, value in [('firmware/acpi/platform_profile', 'performance'),
                                ('devices/system/cpu/cpufreq/boost', '1'),
                                ('devices/system/cpu/cpufreq/policy0/energy_performance_preference', 'performance'),
                                ('devices/system/cpu/cpufreq/policy0/scaling_governor', 'powersave'),
                                ('devices/system/cpu/cpufreq/policy0/scaling_max_freq', '3301000'),
                                ('devices/system/cpu/cpufreq/policy0/cpuinfo_max_freq', '4936631')]:
                path = root / 'sys' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            with patch.object(backend, 'SYS', root / 'sys'), patch.object(backend, 'TUNED', tuned):
                self.assertIn('frequency ceiling', backend.policy_warning())
                (root / 'sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq').write_text('4000000')
                self.assertEqual(backend.policy_warning(), '')
                governor = root / 'sys/devices/system/cpu/cpufreq/policy0/scaling_governor'
                governor.write_text('performance')
                self.assertIn('CPU governor', backend.policy_warning())
                governor.write_text('powersave')
                (tuned / 'profiles/zephyrus-performance/tuned.conf').unlink()
                self.assertIn('incomplete', backend.policy_warning())

    def test_closed_drawer_avoids_thermal_hardware_probing(self):
        with patch.object(self.controller, 'hardware', return_value=([], [])), \
                patch.object(self.controller.sampler, 'snapshot', return_value={}), \
                patch.object(backend, 'battery_snapshot', return_value={}), \
                patch.object(backend, 'profile_snapshot', return_value={'degraded': ''}), \
                patch.object(backend, 'thermal_warning', return_value='fan policy is not active') as thermal:
            self.controller.snapshot(details=False)
            thermal.assert_not_called()
            result = self.controller.snapshot(details=True)
            self.assertIn('fan policy', result['profiles']['degraded'])

    def test_detailed_thermal_readback_uses_dc_limits_and_actual_fan_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tuned = root / 'tuned'
            source = Path(__file__).resolve().parents[1] / 'modules/hardware/power/files/etc/tuned/profiles'
            shutil.copytree(source, tuned / 'profiles')
            (tuned / 'active_profile').write_text('zephyrus-performance-battery')
            for attribute, low, high, current in [('ppt_apu_sppt', 15, 45, 45), ('ppt_platform_sppt', 40, 60, 60)]:
                path = root / 'sys/class/firmware-attributes/asus-armoury/attributes' / attribute
                path.mkdir(parents=True)
                for name, value in [('min_value', low), ('max_value', high), ('current_value', current)]:
                    (path / name).write_text(str(value))
            chip = root / 'sys/class/hwmon/hwmon0'
            chip.mkdir(parents=True)
            for name, value in [('name', 'asus_custom_fan_curve'), ('pwm1_enable', '1'), ('pwm2_enable', '1')]:
                (chip / name).write_text(value)
            with patch.object(backend, 'SYS', root / 'sys'), patch.object(backend, 'TUNED', tuned):
                self.assertEqual(backend.thermal_warning(), '')
                (chip / 'pwm2_enable').write_text('2')
                self.assertIn('fan policy', backend.thermal_warning())

    def test_readback_controls_success_and_mutation_uses_typed_api(self):
        with patch.object(backend, 'profile_snapshot', side_effect=[self.current, dict(self.current, active='power-saver')]), \
                patch.object(self.controller, 'snapshot', return_value={'confirmed': True}):
            self.assertEqual(self.controller.handle(self.request), {'confirmed': True})
        self.controller.bus.set.assert_called_once_with('test', '/test', 'test', 'ActiveProfile', 's', 'power-saver')
        with patch.object(backend, 'profile_snapshot', return_value=self.current):
            with self.assertRaisesRegex(ValueError, 'confirm'): self.controller.handle(self.request)

    def test_both_power_profile_interfaces_and_application_holds(self):
        bus = Mock()
        bus.properties.side_effect = [RuntimeError('absent'), dict(ActiveProfile='balanced',
            Profiles=[{'Profile': 'balanced'}, {'Profile': 'performance'}, {'Profile': 'custom'}],
            PerformanceDegraded='high-operating-temperature', ActiveProfileHolds=[dict(Profile='performance', ApplicationId='game', Reason='Playing')])]
        bus.owner.return_value = ':1.4'
        with patch.object(backend, 'policy_warning', return_value=''):
            result = backend.profile_snapshot(bus)
        self.assertEqual(result['service'], 'net.hadess.PowerProfiles')
        self.assertEqual(result['choices'], ['performance', 'balanced'])
        self.assertEqual(result['holds'][0]['reason'], 'Playing')
        self.assertEqual(result['degraded'], 'high-operating-temperature')

    def test_reads_do_not_sample_detailed_metrics_and_unknown_operations_do_not_write(self):
        self.controller.sampler = Mock()
        with patch.object(backend, 'battery_snapshot'), patch.object(backend, 'profile_snapshot'), \
                patch.object(backend, 'thermal_warning', return_value=''):
            self.controller.handle(dict(op='status'))
            self.controller.sampler.snapshot.assert_not_called()
            self.controller.handle(dict(op='status', details=True))
            self.controller.sampler.snapshot.assert_called_once()
        with self.assertRaises(ValueError): self.controller.handle(dict(op='turbo'))
        self.controller.bus.set.assert_not_called()


class AsusTests(unittest.TestCase):
    def setUp(self):
        self.bus = Mock(); self.limit = 80
        self.bus.owner.return_value = ':1.3'
        self.bus.call.side_effect = lambda service, path, interface, method, *args: ['ChargeControlEndThreshold'] if method == 'SupportedProperties' else self.limit
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
        for fields in (dict(identity='stale'), dict(previous=60), dict(value=19), dict(value=101), dict(value=True)):
            with self.subTest(fields=fields), self.assertRaises(ValueError): self.provider.change(dict(self.request, **fields))
        self.bus.set.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'confirm'): self.provider.change(self.request)
        self.bus.set.side_effect = lambda *args: setattr(self, 'limit', args[-1])
        self.provider.change(self.request)
        self.bus.set.assert_called_with(asus.SERVICE, asus.PATH, asus.INTERFACE, 'ChargeControlEndThreshold', 'y', 60)
        self.provider.change(dict(self.request, previous=60, value=75))
        self.assertEqual(self.limit, 75)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.proc = self.root / 'proc'; self.sys = self.root / 'sys'
        self.proc.mkdir(); self.sys.mkdir()
        self.patches = [patch.object(backend, 'PROC', self.proc), patch.object(backend, 'SYS', self.sys)]
        for item in self.patches: item.start(); self.addCleanup(item.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)

    def test_gpu_sampling_leaves_a_long_enough_gap_for_autosuspend(self):
        device = self.sys / 'class/drm/card1/device'
        for name, data in [('vendor', '0x1002'), ('device', '0x73ef'),
                           ('power/runtime_status', 'active'), ('power/control', 'auto'),
                           ('power/autosuspend_delay_ms', '5000'), ('gpu_busy_percent', '65'),
                           ('hwmon/hwmon0/temp1_input', '55000')]:
            self.write(device / name, data)
        sampler = backend.Sampler()
        with patch.object(backend.time, 'monotonic', return_value=100):
            self.assertEqual(sampler.gpus()[0]['temperature'], 55)
        original = backend.read
        def checked(path):
            if path.name in ('gpu_busy_percent', 'temp1_input'):
                self.fail('Sensor read reset the GPU autosuspend countdown')
            return original(path)
        with patch.object(backend.time, 'monotonic', return_value=102), patch.object(backend, 'read', side_effect=checked):
            row = sampler.gpus()[0]
            self.assertEqual(row['temperature'], 55)
            self.assertEqual(row['sampleAge'], 2)
        self.write(device / 'power/runtime_status', 'suspended')
        with patch.object(backend.time, 'monotonic', return_value=106), patch.object(backend, 'read', side_effect=checked):
            row = sampler.gpus()[0]
            self.assertTrue(row['sleeping'])
            self.assertIsNone(row['temperature'])

    def test_deltas_memory_pressure_missing_values_and_resume(self):
        self.write(self.proc / 'stat', 'cpu 100 0 50 850 0 0 0 0 99 0\n')
        self.write(self.proc / 'meminfo', 'MemTotal: 1000 kB\nMemAvailable: 600 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
        self.write(self.proc / 'pressure/memory', 'some avg10=1.25 avg60=0.0 total=123\n')
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
        for name, value in [('power/runtime_status', 'suspended'), ('vendor', '0x1002'), ('device', '0x1234'),
                            ('gpu_busy_percent', '65'), ('hwmon/hwmon0/temp1_input', '55000')]:
            self.write(device / name, value)
        hwmon = self.sys / 'class/hwmon/hwmon0'; hwmon.mkdir(parents=True)
        (hwmon / 'device').symlink_to(device)
        self.write(hwmon / 'fan1_input', '2000')
        original = backend.read
        def guarded(path):
            if path.name in ('gpu_busy_percent', 'temp1_input', 'fan1_input'):
                self.fail('Read a sleeping device sensor: ' + str(path))
            return original(path)
        with patch.object(backend, 'read', side_effect=guarded):
            state = backend.Sampler().snapshot()
        self.assertTrue(state['gpus'][0]['sleeping']); self.assertIsNone(state['gpus'][0]['usage'])
        self.assertEqual(state['fans'], [])
        self.write(device / 'power/runtime_status', 'active')
        self.assertEqual(backend.Sampler().snapshot()['gpus'][0]['usage'], 65)


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class PowerQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        def prepare(root):
            shutil.copytree(fixtures.DESKTOP / 'bar', root / 'bar')
            if setup: setup(root)
        return fixtures.DisplayQmlTests.run_qml(self, body, prepare)

    def test_drawers_actual_values_actions_missing_data_narrow_and_bar(self):
        data = json.dumps(snapshot())
        self.run_qml('''import QtQuick
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
  property bool busy:false
  property bool changing:false
  property bool closing:false
  property string actionError:""
  property string statusError:""
  property var owners:[]
  property string selected:""
  property int limit:0
  function observe(owner,active,details){owners=owners.filter(x=>x!==owner).concat(active?[owner]:[]);}
  function refresh(){}
  function changeProfile(value){selected=value;}
  function chargeLimit(row,value){limit=value;}
 }
 BatteryStatus {id:barBattery; device:({isPresent:true,type:UPowerDeviceType.Battery,percentage:.76,state:UPowerDeviceState.Discharging})}
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:1080;visible:true;color:Theme.background
  BatteryDrawer {id:battery;x:16;y:16;width:window.width-32;height:window.height-32;active:true;service:mock;onDrawerRequested:key=>route=key}
  PerformanceDrawer {id:performance;x:16;y:16;width:window.width-32;height:window.height-32;visible:false;active:false;service:mock;onDrawerRequested:key=>route=key}
 }
 property string route:""
 property var focusedControl:null
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function capture(name,item){const dir=Quickshell.env("DISPLAY_PREVIEW_DIR");if(dir)item.grabToImage(result=>result.saveToFile(dir+"/power-"+name+".png"));}
 function update(fn){const state=JSON.parse(JSON.stringify(mock.state));fn(state);mock.state=state;}
 property int stage:0
 Timer {interval:200;repeat:true;running:true;onTriggered:{try{
  if(stage===0){
   check(find(battery,"batteryPercentage").text==="76%","battery percentage");
   check(find(battery,"batteryEstimate").detail.indexOf("remaining")>=0,"estimate missing");
   check(barBattery.label==="76%"&&!barBattery.charging,"bar percentage normalization");
   const gauge=find(battery,"batteryGauge"), slider=gauge.slider;
   check(slider.from===20&&slider.to===100&&slider.stepSize===1,"charge limit range");
   slider.forceActiveFocus();focusedControl=slider;input.keyClick(Qt.Key_Left);
   check(mock.limit===79,"keyboard charge action");
   check(find(battery,"chargeLimitApplied").text.indexOf("80%")>=0,"optimistic charge limit");
   const track=find(gauge,"batteryLevelTrack"), fill=find(gauge,"batteryLevelFill"), marker=find(gauge,"chargeLimitMarker");
   check(Math.abs(fill.width/track.width-.76)<.005,"battery percentage rescaled to limit");
   check(Math.abs((marker.x+marker.width/2)/track.width-.8)<.005,"charge marker not at 80 percent");
   input.mousePress(slider,slider.width*.8,slider.height/2);
   input.mouseMove(slider,slider.width*.65,slider.height/2);
   check(gauge.draft===65,"drag preview position");
   input.mouseRelease(slider,slider.width*.65,slider.height/2);
   check(mock.limit===65,"drag release did not apply charge limit");
   check(find(battery,"chargeLimitApplied").text.indexOf("80%")>=0,"drag claimed success before readback");
   capture("battery",battery);
  }else if(stage===1){
   update(s=>{s.battery.onBattery=false;});
   check(!find(battery,"batteryEstimate").visible,"AC residual discharge displayed as battery runtime");
   update(s=>{s.hardware[0].limit=75;s.battery.summary.state=1;s.battery.summary.seconds=null;s.battery.summary.percentage=0;});
   check(find(battery,"chargeLimitApplied").text.indexOf("75%")>=0,"actual custom limit hidden");
   check(find(battery,"batteryGauge").slider===focusedControl&&focusedControl.activeFocus,"refresh replaced charge control or focus");
   const gauge=find(battery,"batteryGauge"), marker=find(gauge,"chargeLimitMarker"), track=find(gauge,"batteryLevelTrack");
   check(Math.abs((marker.x+marker.width/2)/track.width-.75)<.005,"external limit marker position");
   check(find(battery,"batteryEstimate").value==="…","zero time not estimating");
   check(find(battery,"batteryPercentage").text==="0%","empty battery unavailable");
   barBattery.device=({isPresent:true,type:UPowerDeviceType.Battery,percentage:.1,state:UPowerDeviceState.Charging});
   check(barBattery.charging&&barBattery.iconName==="battery-charging","charging indicator missing");
   check(!find(battery,"batteryPerformance"),"drawers still link each other");
   battery.active=false;battery.visible=false;performance.active=true;performance.visible=true;
  }else if(stage===2){
   check(find(performance,"cpuUsage").value==="23%","CPU missing");
   const profileButton=find(performance,"powerProfile:power-saver");
   profileButton.forceActiveFocus();input.keyClick(Qt.Key_Space);check(mock.selected==="power-saver","profile action");
   focusedControl=profileButton;
   check(!find(performance,"powerProfile:power-saver").current,"optimistic profile");
   check(find(performance,"powerProfile:balanced").current,"active checkmark missing");
   capture("performance",performance);
  }else if(stage===3){
   update(s=>{s.profiles.active="power-saver";s.profiles.inhibited="lap-detected";s.metrics.cpu.usage=null;});
   check(find(performance,"powerProfile:power-saver").current,"external profile missing");
   check(find(performance,"powerProfile:power-saver")===focusedControl&&focusedControl.activeFocus,"refresh replaced profile control or focus");
   mock.busy=true;check(focusedControl.enabled,"status read disabled profile controls");mock.busy=false;
   check(!find(performance,"powerProfile:performance").enabled,"inhibited profile enabled");
   check(!find(performance,"performanceBattery"),"performance still links battery");
   check(!find(performance,"cpuBoost"),"independent boost control remains");
   battery.width=268;performance.width=268;
  }else if(stage===4){check(performance.width===268,"narrow width");capture("performance-narrow",performance);
  }else if(stage===5){Theme.setMode("light");
  }else if(stage===6){capture("performance-light",performance);
  }else if(stage===7){performance.active=false;performance.visible=false;battery.visible=true;battery.active=true;
  }else if(stage===8){capture("battery-narrow-light",battery);
  }else if(stage===9){
   update(s=>{s.battery.summary=null;s.battery.batteries=[];s.battery.onBattery=false;s.hardware=[];});
   barBattery.device=({isPresent:false,type:UPowerDeviceType.Battery,percentage:0,state:0});
   check(barBattery.label===""&&!barBattery.available,"absent bar fabricated charge");
  }else if(stage===10){
   check(find(battery,"batteryPercentage").text==="No system battery","desktop battery handling");
   check(!find(battery,"chargeLimitMarker").visible,"unsupported charge limit exposed");
   battery.active=false;check(mock.owners.length===0,"observer survived dismissal");
   console.log("DISPLAY_PASS");Qt.quit();
  }
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
'''.replace('DATA', data))

    def test_worker_actions_survive_dismissal_and_observation_stops(self):
        data = snapshot()
        def setup(root):
            (root / 'drawers/power/backend.py').write_text('''import json,sys,time
state=DATA
for line in sys.stdin:
 request=json.loads(line)
 time.sleep(.1)
 if request['op']=='profile':state['profiles']['active']=request['value']
 print(json.dumps(dict(ok=True,data=state,error='')),flush=True)
'''.replace('DATA', repr(data)))
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/power"
ShellRoot {
 QtObject {id:batteryOwner}
 QtObject {id:performanceOwner}
 property int stage:0
 function check(value,message){if(!value)throw new Error(message);}
 Timer {interval:60;repeat:true;running:true;onTriggered:{try{
  if(stage===0){PowerService.observe(batteryOwner,true,false);stage++;}
  else if(stage===1&&PowerService.loaded&&!PowerService.busy){
   check(!PowerService.detailed&&PowerService.updates.interval===10000,"battery polling");
   PowerService.observe(performanceOwner,true,true);PowerService.observe(batteryOwner,false,false);stage++;
  }else if(stage===2&&!PowerService.busy){
   check(PowerService.detailed&&PowerService.updates.interval===2000,"performance polling");
   PowerService.changeProfile("power-saver");PowerService.observe(performanceOwner,false,true);stage++;
  }else if(stage===3&&!PowerService.busy&&!PowerService.closing&&!PowerService.worker.running){
   check(PowerService.state.profiles.active==="power-saver","dismissal killed profile action");
   check(!PowerService.updates.running&&PowerService.owners.length===0,"polling survived dismissal");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
''', setup)


if __name__ == '__main__':
    unittest.main()
