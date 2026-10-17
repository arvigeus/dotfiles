"""Timezone clocks, private weather caches and the production drawer."""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import test_display_drawer as fixtures

SOURCE = fixtures.DESKTOP / 'drawers/weather/backend.py'
SPEC = importlib.util.spec_from_file_location('desktop_weather', SOURCE)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def place(id='east', timezone='Asia/Tokyo', latitude=35, longitude=139):
    return dict(id=id, name=id.title(), detail='Test location', timezone=timezone, latitude=latitude, longitude=longitude)


def payload(now):
    hour = int(now // 3600 * 3600)
    midnight = int(now // 86400 * 86400)
    return dict(utc_offset_seconds=0,
                current=dict(time=now, temperature_2m=18.4, apparent_temperature=17, relative_humidity_2m=65,
                             wind_speed_10m=12, weather_code=61, is_day=1),
                hourly=dict(time=[hour + i * 3600 for i in range(14)], temperature_2m=[18] * 14,
                            precipitation_probability=[40] * 14, weather_code=[61] * 14, is_day=[1] * 14),
                daily=dict(time=[midnight + i * 86400 for i in range(5)], temperature_2m_max=[22] * 5,
                           temperature_2m_min=[13] * 5, precipitation_probability_max=[70] * 5, weather_code=[61] * 5))


class WeatherBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, XDG_CONFIG_HOME=self.tmp.name + '/config', XDG_CACHE_HOME=self.tmp.name + '/cache')
        self.env.start(); self.addCleanup(self.env.stop)
        # Current-location tests must never change the host timezone.
        self.zone = 'UTC'
        read_zone = patch.object(backend, 'system_timezone', side_effect=lambda: self.zone)
        set_zone = patch.object(backend, 'change_timezone', side_effect=lambda zone: setattr(self, 'zone', zone))
        read_zone.start(); set_zone.start()
        self.addCleanup(read_zone.stop); self.addCleanup(set_zone.stop)
        self.rows = [place(), place('west', 'America/New_York', 40, -74)]
        self.config(self.rows)
        self.now = datetime(2026, 10, 17, 18, 30, tzinfo=timezone.utc).timestamp()

    def config(self, rows):
        backend.atomic_json(backend.config_dir() / 'weather.json', dict(locations=rows))

    def cache(self, row, age=0, data=None):
        backend.atomic_json(backend.cache_path(row), dict(fetchedAt=self.now - age, data=data or payload(self.now)))

    def test_clock_date_and_dst_are_independent_of_network_and_system_timezone(self):
        with patch.object(backend, 'urlopen') as network:
            east = backend.status('east', self.now)
            west = backend.status('west', self.now)
        self.assertEqual((east['clock'], east['date']), ('03:30', '2026-10-18'))
        self.assertEqual([row['clock'] for row in east['locations']], ['03:30', '14:30'])
        self.assertEqual((west['clock'], west['date'], west['zone']), ('14:30', '2026-10-17', 'EDT'))
        before = datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc).timestamp()
        after = before + 3600
        self.assertEqual(backend.status('west', before)['zone'], 'EDT')
        self.assertEqual(backend.status('west', after)['zone'], 'EST')
        network.assert_not_called()

    def test_selection_persists_without_rewriting_inventory_and_removed_place_falls_back(self):
        path = backend.config_dir() / 'weather.json'; original = path.read_bytes()
        backend.status('west', self.now)
        self.assertEqual(backend.status(now=self.now)['location']['id'], 'west')
        self.assertEqual(path.read_bytes(), original)
        self.config([self.rows[0]])
        self.assertEqual(backend.status(now=self.now)['location']['id'], 'east')
        self.assertEqual((backend.config_dir() / 'weather-selection.json').stat().st_mode & 0o777, 0o600)

    def test_cache_is_per_coordinates_and_timezone_and_stale_is_explicit(self):
        self.cache(self.rows[0])
        with patch.object(backend.time, 'time', return_value=self.now):
            east = backend.status('east', self.now)
            west = backend.status('west', self.now)
            self.assertFalse(east['due']); self.assertIsNotNone(east['weather'])
            self.assertIsNone(west['weather']); self.assertTrue(west['due'])
            self.cache(self.rows[0], age=4000)
            self.assertTrue(backend.status('east', self.now)['stale'])
            self.rows[0]['latitude'] += 1; self.config(self.rows)
            self.assertIsNone(backend.status('east', self.now)['weather'])

    def test_island_reads_fixed_location_without_network_or_changing_drawer_selection(self):
        backend.status('west', self.now)
        path = backend.config_dir() / 'weather-selection.json'; original = path.read_bytes()
        self.cache(self.rows[0])
        with patch.object(backend, 'urlopen') as network:
            island = backend.island_status(self.now)
            self.assertEqual(island['location']['id'], 'east')
            self.assertIsNotNone(island['weather'])
            self.assertEqual(path.read_bytes(), original)
            backend.atomic_json(backend.config_dir() / 'weather.json', dict(locations=self.rows, islandLocation='west'))
            self.assertEqual(backend.island_status(self.now)['location']['id'], 'west')
            network.assert_not_called()

    def test_setting_current_location_preserves_private_config_and_controls_default(self):
        path = backend.config_dir() / 'weather.json'
        config = dict(locations=self.rows, custom={'keep': True})
        backend.atomic_json(path, config)
        backend.set_current('west')
        self.assertEqual(self.zone, 'America/New_York')
        self.assertEqual(backend.read_json(path), dict(config, islandLocation='west'))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(backend.island_status(self.now)['location']['id'], 'west')
        self.assertEqual(backend.status(now=self.now)['location']['id'], 'west')
        # Browsing elsewhere leaves the current location alone.
        backend.status('east', self.now)
        self.assertEqual(backend.island_status(self.now)['location']['id'], 'west')
        original = path.read_bytes()
        with self.assertRaises(ValueError): backend.set_current('unknown')
        self.assertEqual(path.read_bytes(), original)
        path.write_text('{broken')
        with self.assertRaises(ValueError): backend.set_current('west')
        self.assertEqual(path.read_text(), '{broken')

    def test_pin_authorization_failure_preserves_config_and_timezone(self):
        path = backend.config_dir() / 'weather.json'; original = path.read_bytes()
        with patch.object(backend, 'change_timezone', side_effect=backend.LocationError('Permission denied')):
            with self.assertRaisesRegex(backend.LocationError, 'Permission denied'):
                backend.set_current('west')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.zone, 'UTC')

    def test_pin_write_failure_restores_previous_timezone(self):
        path = backend.config_dir() / 'weather.json'; original = path.read_bytes()
        with patch.object(backend, 'atomic_json', side_effect=OSError('read-only')):
            with self.assertRaisesRegex(backend.LocationError, 'Could not save'):
                backend.set_current('west')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.zone, 'UTC')

    def test_pin_same_timezone_saves_location_without_mutation(self):
        self.zone = self.rows[0]['timezone']
        with patch.object(backend, 'change_timezone') as change:
            backend.set_current('east')
            change.assert_not_called()
        self.assertEqual(backend.read_json(backend.config_dir() / 'weather.json')['islandLocation'], 'east')

    def test_pin_unconfirmed_timezone_change_rolls_back_before_saving(self):
        path = backend.config_dir() / 'weather.json'; original = path.read_bytes()
        def change(zone):
            self.zone = zone
            if zone == 'America/New_York':
                raise backend.LocationError('Readback failed')
        with patch.object(backend, 'change_timezone', side_effect=change):
            with self.assertRaisesRegex(backend.LocationError, 'Readback failed'):
                backend.set_current('west')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.zone, 'UTC')

    def test_pin_reports_partial_failure_if_timezone_cannot_be_restored(self):
        path = backend.config_dir() / 'weather.json'; original = path.read_bytes()
        def change(zone):
            if zone == 'UTC': raise backend.LocationError('Restore denied')
            self.zone = zone
        with patch.object(backend, 'atomic_json', side_effect=OSError('read-only')), patch.object(backend, 'change_timezone', side_effect=change):
            with self.assertRaisesRegex(backend.LocationError, 'restoring the previous timezone failed'):
                backend.set_current('west')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.zone, 'America/New_York')

    def test_daily_outlook_uses_daylight_for_sky_and_keeps_brief_rain_separate(self):
        def rows(code=0):
            return [dict(code=code if 6 <= hour < 18 else 3, day=6 <= hour < 18, hour=hour) for hour in range(24)]
        sunny = rows()
        self.assertEqual(backend.daily_outlook(sunny), 'Mostly sunny.')
        sunny[15]['code'] = 51
        self.assertEqual(backend.daily_outlook(sunny), 'Mostly sunny, with drizzle in the afternoon.')
        self.assertEqual(backend.daily_outlook(sunny[:6]), '')
        self.assertIn('Rain for much of the day', backend.daily_outlook(rows(61)))
        self.assertEqual(backend.daily_outlook([dict(row, day=False) for row in sunny]), '')

    def test_daily_outlook_groups_hours_in_selected_timezone_without_relabeling_current_weather(self):
        zone = backend.ZoneInfo(self.rows[0]['timezone'])
        local = datetime.fromtimestamp(self.now, zone)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        data = payload(self.now)
        data['hourly'] = dict(time=[start + hour * 3600 for hour in range(48)], temperature_2m=[22]*48,
                              precipitation_probability=[0]*24 + [100]*24, weather_code=[0]*24 + [61]*24,
                              is_day=[int(6 <= hour % 24 < 18) for hour in range(48)])
        data['utc_offset_seconds'] = int(local.utcoffset().total_seconds())
        data['daily']['time'] = [start + day * 86400 for day in range(5)]
        result = backend.forecast(data, self.rows[0], self.now)
        self.assertEqual(result['outlook'], 'Mostly sunny.')
        self.assertEqual(result['daily'][0]['outlook'], result['outlook'])
        self.assertEqual(result['daily'][1]['outlook'], 'Rain for much of the day.')
        self.assertEqual(result['daily'][2]['outlook'], '')
        self.assertEqual(result['current']['code'], 61)

    def test_background_refresh_and_drawer_share_thirty_minute_cache_without_saving_selection(self):
        backend.status('west', self.now)
        selection = backend.config_dir() / 'weather-selection.json'
        original = selection.read_bytes()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload(self.now)).encode()
        with patch.object(backend.time, 'time', return_value=self.now), patch.object(backend, 'urlopen', return_value=response) as network:
            self.cache(self.rows[0], age=1799)
            self.assertFalse(backend.island_status(self.now, refresh=True)['due'])
            backend.fetch('east', force=False)
            network.assert_not_called()
            self.cache(self.rows[0], age=1800)
            self.assertFalse(backend.island_status(self.now, refresh=True)['due'])
            self.assertEqual(network.call_count, 1)
            backend.fetch('east', force=False)
            self.assertEqual(network.call_count, 1)
            backend.fetch('east', force=True)
            self.assertEqual(network.call_count, 2)
        self.assertEqual(selection.read_bytes(), original)

    def test_failed_background_refresh_preserves_weather_and_update_time(self):
        self.cache(self.rows[0], age=4000)
        original = backend.island_status(self.now)
        with patch.object(backend.time, 'time', return_value=self.now), patch.object(backend, 'urlopen', side_effect=OSError('offline')):
            result = backend.island_status(self.now, refresh=True)
        self.assertEqual(result['weather'], original['weather'])
        self.assertEqual(result['updated'], original['updated'])
        self.assertTrue(result['stale'])
        self.assertTrue(result['error'])

    def test_invalid_inventory_and_broken_cache_do_not_trigger_network(self):
        for field, value in [('latitude', float('nan')), ('longitude', 181), ('id', ''), ('timezone', '../bad')]:
            rows = copy.deepcopy(self.rows); rows[0][field] = value
            # JSON NaN is deliberately supplied as malformed user input.
            path = backend.config_dir() / 'weather.json'; path.write_text(json.dumps(dict(locations=rows)))
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                backend.status(now=self.now)
        self.config(self.rows)
        backend.cache_path(self.rows[0]).parent.mkdir(parents=True, exist_ok=True)
        backend.cache_path(self.rows[0]).write_text('{bad')
        self.assertTrue(backend.status('east', self.now)['due'])
        (backend.config_dir() / 'weather.json').unlink()
        self.assertEqual(backend.status(now=self.now)['locations'], [])

    def test_hourly_filtering_and_nullable_metrics_do_not_invent_zero(self):
        data = payload(self.now)
        data['current']['relative_humidity_2m'] = None
        data['hourly']['precipitation_probability'][1] = None
        result = backend.forecast(data, self.rows[0], self.now)
        self.assertIsNone(result['current']['humidity'])
        self.assertEqual(len(result['hourly']), 6)
        self.assertTrue(all(hour['time'] >= self.now for hour in result['hourly']))
        self.assertIsNone(result['hourly'][0]['rain'])
        data['daily']['weather_code'] = []
        with self.assertRaises(ValueError): backend.forecast(data, self.rows[0], self.now)

    def test_failed_or_partial_refresh_keeps_good_cache(self):
        row = self.rows[0]; self.cache(row)
        path = backend.cache_path(row); original = path.read_bytes()
        with patch.object(backend, 'urlopen', side_effect=OSError('offline')):
            with self.assertRaises(OSError): backend.fetch('east')
        self.assertEqual(path.read_bytes(), original)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'current': {}}).encode()
        with patch.object(backend, 'urlopen', return_value=response):
            with self.assertRaises(ValueError): backend.fetch('east')
        self.assertEqual(path.read_bytes(), original)

    def test_fetch_uses_explicit_coordinates_and_validates_before_private_atomic_write(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload(self.now)).encode()
        with patch.object(backend, 'urlopen', return_value=response) as network, patch.object(backend.time, 'time', return_value=self.now):
            backend.fetch('east')
            self.assertFalse(backend.status('east', self.now)['due'])
        request = network.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://api.open-meteo.com/v1/forecast?'))
        self.assertIn('timezone=Asia%2FTokyo', request.full_url)
        self.assertIn('latitude=35', request.full_url)
        self.assertEqual(backend.cache_path(self.rows[0]).stat().st_mode & 0o777, 0o600)


class TimezonePermissionTests(unittest.TestCase):
    def test_timezone_commands_never_allow_authentication_prompts(self):
        result = subprocess.CompletedProcess([], 0, stdout='Europe/London\n', stderr='')
        with patch.object(backend.subprocess, 'run', return_value=result) as command:
            backend.change_timezone('Europe/London')
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ['timedatectl', '--no-ask-password', 'set-timezone', 'Europe/London'],
            ['timedatectl', '--no-ask-password', 'show', '--property=Timezone', '--value']])
        self.assertTrue(all(call.kwargs['timeout'] == 12 for call in command.call_args_list))
        with patch.object(backend.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'timedatectl')):
            with self.assertRaisesRegex(backend.LocationError, 'without authentication'):
                backend.change_timezone('Europe/London')

    def test_timezone_readback_must_match(self):
        with patch.object(backend, 'timezone_command'), patch.object(backend, 'system_timezone', return_value='UTC'):
            with self.assertRaisesRegex(backend.LocationError, 'did not apply'):
                backend.change_timezone('Europe/London')

    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute the polkit rule')
    def test_rule_only_grants_timezone_to_active_local_administrators(self):
        # Resolve from the test root so the policy remains independent of installs.
        policy = Path(__file__).resolve().parents[1] / 'modules/desktop/quickshell/files/etc/polkit-1/rules.d/50-desktop-timezone.rules'
        script = r'''const fs=require('fs');let rule;
new Function('polkit',fs.readFileSync(process.argv[2],'utf8'))({addRule:f=>rule=f,Result:{YES:'yes'}});
for(const id of ['set-timezone','set-time','set-ntp','set-local-rtc'])
 for(const local of [true,false])for(const active of [true,false])for(const admin of [true,false]){
  const allowed=rule({id:'org.freedesktop.timedate1.'+id},{local,active,isInGroup:g=>g==='wheel'&&admin});
  if((allowed==='yes')!==(id==='set-timezone'&&local&&active&&admin))throw Error(JSON.stringify({id,local,active,admin}));
 }
'''
        result = subprocess.run(['node', '-', str(policy)], input=script, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class WeatherQmlTests(unittest.TestCase):
    def run_qml(self, body, setup=None):
        return fixtures.DisplayQmlTests.run_qml(self, body, setup)

    def test_selection_keyboard_escape_states_and_resizing(self):
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "ui"
ShellRoot {
 TestCase {id:input;when:false;parent:window.contentItem}
 QtObject {
  id:mock
  property string selectedId:"east"
  property bool loading:false
  property string error:""
  property var state:({locations:[{id:"east",name:"Eastern city",detail:"East",clock:"03:30",zone:"JST"},{id:"west",name:"Western city",detail:"West",clock:"14:30",zone:"EDT"}],location:{id:"east",name:"Eastern city"},clock:"03:30",date:"2026-10-18",zone:"JST",updated:"03:15",stale:false,weather:{outlook:"Mostly sunny, with drizzle in the afternoon.",current:{temperature:18,feelsLike:17,humidity:65,wind:12,code:61,isDay:false},hourly:Array.from({length:6},(_,i)=>({label:(4+i)+":00",temperature:18+i,rain:40,code:61,isDay:i>2})),daily:Array.from({length:5},(_,i)=>({date:"2026-10-"+(18+i),today:i===0,high:22,low:13,rain:70,code:61,outlook:i<4?(i===0?"Mostly sunny, with drizzle in the afternoon.":"Rain for much of the day."):""}))}})
  function select(id){selectedId=id;state=Object.assign({},state,{clock:"14:30",date:"2026-10-17",zone:"EDT",location:{id}});}
  function fetchWeather(force){loading=true;}
 }
 FloatingWindow {id:window;implicitWidth:480;implicitHeight:800;visible:true;color:Theme.background
  WeatherDrawer {id:drawer;x:16;y:16;width:448;height:760;active:true;service:mock}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function capture(name,done){const dir=Quickshell.env("DISPLAY_PREVIEW_DIR");const item=name==="picker"?find(drawer,"weatherLocation").popup.contentItem:drawer;if(dir)item.grabToImage(result=>{result.saveToFile(dir+"/weather-"+name+".png");if(done)done();});else if(done)done();}
 property int stage:0
 Timer{interval:220;repeat:true;running:true;onTriggered:{try{
  const picker=find(drawer,"weatherLocation");
  if(stage===0){
   check(find(drawer,"locationTime").text==="03:30","initial clock");
   check(picker.width<=32&&picker.contentItem.children.length===0,"picker should be only a chevron");
   check(Math.abs(picker.x+picker.width-picker.parent.width)<1,"picker is not at far right");
   const pin=find(drawer,"weatherSetCurrent");check(pin.x+pin.width<=picker.x,"pin should precede chevron");
   check(find(drawer,"weatherTemperature").text==="18°","temperature");
   check(find(drawer,"weatherOutlook").text==="Mostly sunny, with drizzle in the afternoon.","daily outlook has redundant prefix");
   check(find(drawer,"weatherDay:2026-10-18").text==="Mostly sunny, with drizzle in the afternoon.","today row outlook");
   check(find(drawer,"weatherDay:2026-10-19").text==="Rain for much of the day.","tomorrow row outlook");
   const fallback=find(drawer,"weatherDay:2026-10-22");
   check(fallback.text==="Rain"&&fallback.data.some(item=>item.target===fallback&&item.text==="Rain"),"incomplete day tooltip fallback");
   capture("normal");picker.forceActiveFocus();input.keyClick(Qt.Key_Space);
  }else if(stage===1){
   check(picker.popup.visible&&drawer.escapeHandler,"location popup did not open");
   check(find(picker.popup.contentItem,"weatherLocationTime:east").text==="03:30"&&find(picker.popup.contentItem,"weatherLocationTime:west").text==="14:30","picker clocks");capture("picker",()=>{input.keyClick(Qt.Key_Down);input.keyClick(Qt.Key_Return);});
  }else if(stage===2){
   check(mock.selectedId==="west"&&find(drawer,"locationTime").text==="14:30","keyboard selection");
   picker.popup.open();drawer.escapeHandler();check(!picker.popup.visible&&drawer.active,"Escape closed drawer");
   mock.state=Object.assign({},mock.state,{stale:true,updated:"Yesterday 03:15"});mock.error="Weather unavailable. Try again shortly.";capture("offline");
   check(find(drawer,"weatherUpdated").text.startsWith("Outdated"),"stale state not visible");
  }else if(stage===3){
   drawer.width=268;capture("narrow");
  }else if(stage===4){
   Theme.setMode("light");capture("light");
  }else if(stage===5){
   mock.state=Object.assign({},mock.state,{weather:null});capture("no-weather");
   check(find(drawer,"locationTime").text==="14:30","offline clock lost");
   picker.popup.open();drawer.active=false;check(!picker.popup.visible,"dismissal kept popup");
  }else if(stage===6){console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''')

    def test_service_cancels_old_place_and_hides_expired_cache_when_switching_offline(self):
        def setup(root):
            (root / 'drawers/weather/backend.py').write_text('''import json,sys,time
from pathlib import Path
r=json.loads(sys.stdin.readline());id=r.get('id') or 'east'
events=Path(__file__).with_name('events')
with events.open('a') as stream:stream.write(r['op']+':'+id+'\\n')
if r['op']=='fetch':
 if id=='east':time.sleep(2)
 else:time.sleep(.15)
 print(json.dumps({'error':'Offline test'}),flush=True)
else:
 print(json.dumps(dict(locations=[dict(id='east',name='East'),dict(id='west',name='West'),dict(id='fresh',name='Fresh')],location=dict(id=id),clock='03:30' if id=='east' else '14:30',date='2026-10-18',zone='TEST',weather=None if id=='east' else dict(current=dict(temperature=8)),due=id!='fresh',stale=id=='west',updated='01:00',error='')),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/weather"
ShellRoot {
 WeatherService {id:service;active:true}
 function check(v,m){if(!v)throw new Error(m);}
 property int stage:0
 property int oldRevision:0
 Timer{interval:70;repeat:true;running:true;onTriggered:{try{
  if(stage===0&&service.loading){
   check(service.state.clock==="03:30"&&!service.state.weather,"clock must work before weather");
   oldRevision=service.revision;service.select("west");
   check(service.state.weather===null&&service.state.clock==="","old place visible after selection");
   service.receive(JSON.stringify({locations:[],location:{id:"east"},clock:"wrong"}),oldRevision,true);
   check(service.state.clock==="","delayed old response won");stage++;
  }else if(stage===1&&service.state.location?.id==="west"&&service.error==="Offline test"){
   check(service.state.clock==="14:30"&&service.state.weather===null,"switching showed expired weather or lost clock");
   check(service.state.updated==="","hidden expired weather retained update label");
   service.select("fresh");stage++;
  }else if(stage===2&&service.state.location?.id==="fresh"){
   check(service.state.weather.current.temperature===8&&!service.loading&&service.lastAttempt===0,"recent cache did not avoid fetch");
   service.active=false;check(!service.reader.running&&!service.fetcher.running&&!service.clockTimer.running,"dismissal left worker/timer active");stage++;
  }else if(stage===3){console.log("DISPLAY_PASS");Qt.quit();}
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage,service.error);Qt.quit();}}
}''', setup)

    def test_background_requests_refresh_updates_icon_and_backs_off_after_failure(self):
        def setup(root):
            shutil.copytree(fixtures.DESKTOP / 'bar', root / 'bar')
            (root / 'drawers/weather/backend.py').write_text('''import json,sys
from pathlib import Path
r=json.loads(sys.stdin.readline());p=Path(__file__).with_name('calls')
n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n))
print(json.dumps(dict(location=dict(id='east',name='East'),weather=dict(current=dict(code=61,isDay=True,temperature=18,feelsLike=17,wind=12,humidity=60)),updated='03:00',stale=False,due=n>1,error='Offline' if n>1 else '',call=n,requestedRefresh=r.get('refresh'))),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "bar"
ShellRoot {
 WeatherStatus{id:status}
 function check(value,message){if(!value)throw new Error(message);}
 property int stage:0
 Timer{interval:70;repeat:true;running:true;onTriggered:{try{
  if(status.worker.running)return;
  if(stage===0&&status.snapshot.call===1){
   check(status.snapshot.requestedRefresh,"background did not request automatic refresh");
   check(status.iconName==="weather-rain"&&status.description.includes("Rain")&&status.description.includes("18°C"),"icon and tooltip disagree");
   status.refresh();stage++;
  }else if(stage===1&&status.snapshot.call===2){
   check(status.lastFailure>0&&status.iconName==="weather-rain","failure lost icon or retry backoff");
   status.refresh();stage++;
  }else if(stage===2&&status.snapshot.call===3){
   check(!status.snapshot.requestedRefresh,"failure retried before backoff");
   status.snapshot={location:{name:"East"},weather:{current:{code:0,isDay:false,temperature:8}},updated:"04:00"};
   check(status.iconName==="moon"&&status.description.includes("8°C"),"updated conditions did not update icon and tooltip");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:4000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}''', setup)

    def test_pin_saves_current_location_updates_island_and_survives_drawer_destruction(self):
        def setup(root):
            shutil.copytree(fixtures.DESKTOP / 'bar', root / 'bar')
            cache_dir = root / 'cache'
            with patch.dict(os.environ, XDG_CONFIG_HOME=str(root / 'config'), XDG_CACHE_HOME=str(cache_dir)):
                rows = [place(), place('west', 'America/New_York', 40, -74)]
                backend.atomic_json(backend.config_dir() / 'weather.json', dict(locations=rows, islandLocation='east'))
                now = backend.time.time()
                for row in rows:
                    backend.atomic_json(backend.cache_path(row), dict(fetchedAt=now, data=payload(now)))
            bindir = root / 'bin'; bindir.mkdir()
            fake = bindir / 'timedatectl'
            fake.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\np=Path(__file__).with_name("timezone")\na=sys.argv[1:]\nassert a[0]=="--no-ask-password"\nif a[1]=="show":print(p.read_text() if p.exists() else "UTC")\nelif a[1]=="set-timezone":p.write_text(a[2])\nelse:raise SystemExit(1)\n')
            fake.chmod(0o755)
            worker = root / 'drawers/weather/backend.py'
            worker.write_text('import os\nos.environ["XDG_CACHE_HOME"] = ' + repr(str(cache_dir))
                              + '\nos.environ["PATH"] = ' + repr(str(bindir)) + ' + os.pathsep + os.environ["PATH"]\n'
                              + worker.read_text())
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "bar"
import "drawers"
import "drawers/weather"
import "ui"
ShellRoot {
 TestCase{id:input;when:false;parent:window.contentItem}
 WeatherStatus{id:bar}
 FloatingWindow{id:window;implicitWidth:480;implicitHeight:800;visible:true;color:Theme.background
  Loader{id:page;x:16;y:60;width:448;height:720;sourceComponent:Component{WeatherDrawer{active:true}}}
  Loader{id:header;x:350;y:10;sourceComponent:page.item?.headerActions??null}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 property int stage:0
 Timer{interval:80;repeat:true;running:true;onTriggered:{try{
  const drawer=page.item;
  if(stage===0&&drawer?.snapshot.location?.id==="east"&&bar.snapshot.location?.id==="east"){
   drawer.service.select("west");stage++;
  }else if(stage===1&&drawer?.snapshot.location?.id==="west"){
   check(bar.snapshot.location.id==="east","browsing changed island");
   const pin=find(drawer,"weatherSetCurrent");
   check(pin&&!pin.isCurrent,"pin incorrectly marks browsed location");
   input.mouseClick(pin,pin.width/2,pin.height/2);page.active=false;stage++;
  }else if(stage===2&&!LocationSettings.busy&&bar.snapshot.location?.id==="west"){
   check(!LocationSettings.error,"pin mutation failed");page.active=true;stage++;
  }else if(stage===3&&drawer?.snapshot.currentLocation==="west"){
   check(drawer.snapshot.location.id==="west"&&find(drawer,"weatherSetCurrent").isCurrent,"current location did not persist");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout",stage,LocationSettings.error,bar.snapshot.location);Qt.quit();}}
}''', setup)
