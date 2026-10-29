"""Keyboard LED targeting, native levels, and serialized production QML."""

import sys
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import support
import test_keyboard_drawer as fixtures

SOURCE = support.DESKTOP / 'drawers/keyboard/backlight.py'
REPO = Path(__file__).resolve().parents[1]
ADAPTERS = {
    'asus': REPO
    / 'modules/hardware/devices/zephyrus/symlinks/home/.config/devices/keyboard/backends/asus.py',
    'logitech': REPO
    / 'modules/hardware/peripherals/logitech/symlinks/home/.config/devices/keyboard/backends/logitech.py',
}
backlight = support.load('keyboard_backlight', SOURCE)
lighting = support.load('asus', ADAPTERS['asus'])
logitech = support.load('logitech', ADAPTERS['logitech'])


class AuraTests(unittest.TestCase):
    def setUp(self):
        self.aura = lighting.Provider()
        self.props = dict(
            SupportedBasicModes=[0, 2, 10],
            LedMode=0,
            LedModeData=(0, 0, (166, 0, 0), (0, 0, 0), 'Med', 'Right'),
            Brightness=0,
        )
        self.properties = patch.object(
            self.aura, 'properties', side_effect=lambda path: self.props
        )
        self.properties.start()
        self.addCleanup(self.properties.stop)

    def test_only_supported_effects_and_real_rgb_capability_are_described(self):
        row = self.aura.describe('/keyboard', self.props)
        self.assertEqual([effect['id'] for effect in row['effects']], [0, 2, 10])
        self.assertTrue(row['rgb'])
        self.props['LedMode'] = 2
        self.assertFalse(self.aura.describe('/keyboard', self.props)['rgb'])

    def test_unsupported_effect_and_color_changes_never_write(self):
        requests = [
            dict(effect=1),
            dict(effect=True),
            dict(effect=0, color='#123456'),
            dict(effect=2, color='#ff0000'),
        ]
        with patch.object(self.aura, 'call') as call:
            for request in requests:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    self.aura.change_lighting('/keyboard', request)
            self.props['LedMode'] = 2
            with self.assertRaisesRegex(ValueError, 'does not support'):
                self.aura.change_lighting('/keyboard', dict(effect=2, color='#ff0000'))
            call.assert_not_called()

    def test_effect_uses_public_mode_number_and_color_preserves_other_fields(self):
        def write(path, interface, method, signature, args):
            name, value = args[1:]
            self.props[name] = value.unpack()

        with patch.object(self.aura, 'call', side_effect=write) as call:
            self.aura.change_lighting('/keyboard', dict(effect=10))
            self.assertEqual(call.call_args.args[-1][2].get_type_string(), 'u')
            self.assertEqual(self.props['LedMode'], 10)
            # Aura's nested enum wire value is opaque; retain it when coloring.
            self.props['LedModeData'] = (9, 0, (166, 0, 0), (0, 0, 0), 'Med', 'Right')
            self.aura.change_lighting('/keyboard', dict(effect=10, color='#0080ff'))
            data = self.props['LedModeData']
            self.assertEqual(data[:2], (9, 0))
            self.assertEqual(data[2:4], ((0, 128, 255), (0, 128, 255)))
            self.assertEqual(data[4:], ('Med', 'Right'))
            self.assertEqual(self.props['Brightness'], 0)


class LogitechTests(unittest.TestCase):
    def setUp(self):
        self.adapter = logitech.Provider()
        self.state = dict(
            key='logitech:serial',
            identity='logitech:serial',
            mode=1,
            value=2,
            maximum=7,
            available=True,
            modes=[dict(id=1), dict(id=3), dict(id=255)],
        )
        self.item = SimpleNamespace(ping=lambda: True, unitId='serial', serial='serial')
        self.adapter.devices[self.state['key']] = ('receiver', self.item)
        self.read = patch.object(
            self.adapter, 'read', side_effect=lambda *args: dict(self.state)
        )
        self.read.start()
        self.addCleanup(self.read.stop)
        self.mode = SimpleNamespace(write=self.write_mode)
        self.level = SimpleNamespace(
            read=lambda **kwargs: self.state['value'], write=self.write_level
        )
        templates = SimpleNamespace(
            Backlight2=SimpleNamespace(build=lambda item: self.mode),
            Backlight2Level=SimpleNamespace(build=lambda item: self.level),
        )
        self.modules = patch.dict(
            sys.modules,
            {'logitech_receiver': SimpleNamespace(settings_templates=templates)},
        )
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.writes = []

    def write_mode(self, value, save):
        self.writes.append(('mode', value, save))
        self.state['mode'] = value
        return value

    def write_level(self, value, save):
        self.writes.append(('value', value, save))
        self.state['value'] = value
        return value

    def test_brightness_explicitly_selects_manual_then_off_without_persisting(self):
        self.adapter.change(self.state, dict(op='set', value=6, maximum=7))
        self.assertEqual(self.writes, [('value', 6, False), ('mode', 3, False)])
        self.adapter.change(self.state, dict(op='set', value=0, maximum=7))
        self.assertEqual(self.state['mode'], 255)

    def test_stale_identity_unsupported_modes_and_ranges_never_write(self):
        for request in [
            dict(op='mode', mode=2),
            dict(op='set', value=True, maximum=7),
            dict(op='set', value=8, maximum=7),
            dict(op='set', value=1, maximum=8),
        ]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.adapter.change(self.state, request)
        self.item.unitId = 'replacement'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.adapter.change(self.state, dict(op='mode', mode=1))
        self.assertEqual(self.writes, [])

    def test_failed_second_write_restores_previous_level_and_mode(self):
        original = self.mode.write

        def fail(value, save):
            if value == 3:
                raise ValueError('write failed')
            return original(value, save)

        self.mode.write = fail
        with self.assertRaisesRegex(ValueError, 'write failed'):
            self.adapter.change(self.state, dict(op='set', value=6, maximum=7))
        self.assertEqual((self.state['value'], self.state['mode']), (2, 1))


class ProviderDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.providers = Path(self.directory.name) / 'backends'
        self.native = dict(
            key='asus::kbd_backlight',
            identity='native',
            value=1,
            maximum=3,
            available=True,
            reason='',
        )
        for item in (
            patch.object(backlight, 'PROVIDERS', self.providers),
            patch.object(
                backlight, 'snapshot', side_effect=lambda: [dict(self.native)]
            ),
        ):
            item.start()
            self.addCleanup(item.stop)

    def install(self, name):
        self.providers.mkdir(exist_ok=True)
        (self.providers / (name + '.py')).symlink_to(ADAPTERS[name])

    def test_no_hardware_modules_keeps_generic_brightness_available(self):
        controller = backlight.Controller()
        self.assertEqual(controller.providers, {})
        row = controller.snapshot()[0]
        self.assertEqual((row['provider'], row['effects']), ('sysfs', []))
        with patch.object(backlight, 'handle') as handle:
            request = dict(row, op='set', value=0)
            controller.handle(request)
            handle.assert_called_once_with(request)
        with self.assertRaisesRegex(ValueError, 'does not support'):
            controller.handle(dict(row, op='lighting', effect=0))
        controller.close()

    def test_only_installed_asus_adapter_augments_native_and_routes_lighting(self):
        self.install('asus')
        controller = backlight.Controller()
        self.assertEqual(list(controller.providers), ['asus'])
        aura = controller.providers['asus']
        props = dict(
            SupportedBasicModes=[0],
            LedMode=0,
            LedModeData=(0, 0, (255, 0, 0), (0, 0, 0), 'Med', 'Right'),
        )
        with (
            patch.object(aura, 'discover', return_value=('/aura', props)),
            patch.object(aura, 'change_lighting') as change,
        ):
            rows = controller.snapshot()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(
                (row['provider'], row['connection'], row['rgb']),
                ('asus', 'Built-in keyboard', True),
            )
            with patch.object(backlight, 'handle') as handle:
                controller.handle(dict(row, op='set', value=0))
                handle.assert_called_once()
                change.assert_not_called()
            request = dict(row, op='lighting', effect=0)
            controller.handle(request)
            change.assert_called_once_with('/aura', request)
            with self.assertRaisesRegex(ValueError, 'controller changed'):
                controller.handle(dict(request, lightingPath='/replacement'))
        controller.close()

    def test_logitech_module_adds_independent_device_without_asus(self):
        self.install('logitech')
        controller = backlight.Controller()
        self.assertEqual(list(controller.providers), ['logitech'])
        adapter = controller.providers['logitech']
        remote = dict(
            key='logitech:serial',
            identity='logitech:serial',
            value=2,
            maximum=7,
            available=True,
        )
        with (
            patch.object(adapter, 'snapshot', return_value=[remote]),
            patch.object(adapter, 'change') as change,
        ):
            rows = controller.snapshot()
            self.assertEqual([row['provider'] for row in rows], ['sysfs', 'logitech'])
            request = dict(remote, op='mode', mode=1)
            controller.handle(request)
            change.assert_called_once_with(dict(remote, provider='logitech'), request)
        with self.assertRaisesRegex(ValueError, 'does not support'):
            adapter.change(remote, dict(op='lighting', effect=0))
        with patch.object(adapter, 'close') as close:
            controller.close()
            close.assert_called_once()


class BacklightTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.leds = Path(self.directory.name)
        self.light = self.leds / 'asus::kbd_backlight'
        self.light.mkdir()
        (self.light / 'brightness').write_text('1')
        (self.light / 'max_brightness').write_text('3')
        (self.leds / 'input::capslock').mkdir()
        (self.leds / 'panel_backlight').mkdir()
        for item in (
            patch.object(backlight, 'LEDS', self.leds),
            patch.object(
                backlight.shutil, 'which', return_value='/usr/bin/brightnessctl'
            ),
        ):
            item.start()
            self.addCleanup(item.stop)

    def request(self, value=0, **changes):
        row = backlight.snapshot()[0]
        return dict(
            dict(
                op='set',
                key=row['key'],
                identity=row['identity'],
                maximum=row['maximum'],
                value=value,
            ),
            **changes,
        )

    def test_snapshot_only_exposes_keyboard_lights_and_discrete_levels(self):
        rows = backlight.snapshot()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            (rows[0]['value'], rows[0]['maximum'], rows[0]['available']), (1, 3, True)
        )
        self.light.rename(self.leds / 'removed')
        self.assertEqual(backlight.snapshot(), [])

    def test_exact_native_level_and_off_are_read_back(self):
        def write(args, **kwargs):
            (self.light / 'brightness').write_text(args[-1])
            return type('Result', (), dict(returncode=0, stderr=''))()

        with patch.object(backlight.subprocess, 'run', side_effect=write) as run:
            for level in (0, 3):
                self.assertEqual(
                    backlight.handle(self.request(level))[0]['value'], level
                )
                self.assertEqual(
                    run.call_args.args[0],
                    [
                        'brightnessctl',
                        '--class=leds',
                        '--device',
                        'asus::kbd_backlight',
                        '--quiet',
                        'set',
                        str(level),
                    ],
                )

    def test_invalid_stale_and_indicator_requests_never_write(self):
        cases = [self.request(value) for value in (-1, 4, True, 1.5, '1')]
        cases += [
            self.request(identity='replaced'),
            self.request(maximum=4),
            self.request(key='../asus::kbd_backlight'),
            self.request(key='input::capslock'),
        ]
        with patch.object(backlight.subprocess, 'run') as run:
            for request in cases:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    backlight.handle(request)
            run.assert_not_called()

    def test_permission_failure_and_missing_tool_leave_hardware_unchanged(self):
        with (
            patch.object(
                backlight.subprocess,
                'run',
                return_value=type(
                    'Result', (), dict(returncode=1, stderr='Permission denied')
                )(),
            ),
            self.assertRaisesRegex(ValueError, 'Permission'),
        ):
            backlight.handle(self.request())
        self.assertEqual((self.light / 'brightness').read_text(), '1')
        with patch.object(backlight.shutil, 'which', return_value=None):
            self.assertFalse(backlight.snapshot()[0]['available'])
            with self.assertRaisesRegex(ValueError, 'brightnessctl'):
                backlight.handle(self.request())

    def test_hardware_range_change_after_write_is_reported(self):
        def write(*args, **kwargs):
            (self.light / 'max_brightness').write_text('2')
            return type('Result', (), dict(returncode=0, stderr=''))()

        with (
            patch.object(backlight.subprocess, 'run', side_effect=write),
            self.assertRaisesRegex(ValueError, 'disconnected'),
        ):
            backlight.handle(self.request())


@unittest.skipUnless(support.QS, 'Quickshell is required')
class BacklightQmlTests(unittest.TestCase):
    def test_latest_slider_change_finishes_after_dismissal_and_polling_stops(self):
        def setup(root):
            (root / 'drawers/keyboard/backlight.py').write_text("""import json,sys,time
from pathlib import Path
p=Path(__file__).with_name('light-state.json')
s=json.loads(p.read_text()) if p.exists() else dict(key='keyboard::kbd_backlight',identity='test',maximum=3,value=1,available=True,reason='',history='')
for line in sys.stdin:
 r=json.loads(line);time.sleep(.1)
 if r['op']=='set':s['value']=r['value'];s['history']+=str(r['value'])+',';p.write_text(json.dumps(s))
 print(json.dumps(dict(ok=True,values=[s],error='')),flush=True)
""")

        fixtures.run_qml(
            self,
            """import QtQuick
import Quickshell
import "drawers/keyboard"
ShellRoot {
 QtObject{id:owner}
 property int stage:0
 Timer{interval:80;repeat:true;running:true;onTriggered:{try{
  if(stage===0){BacklightService.observe(owner,true);stage++;}
  else if(stage===1&&BacklightService.values.length&&!BacklightService.busy){
   const row=BacklightService.values[0];
   for(const level of [1,2,3,0])BacklightService.setBrightness(row,level);
   if(BacklightService.queue.length!==1)throw new Error("slider queue did not coalesce");
   BacklightService.observe(owner,false);stage++;
  }else if(stage===2&&!BacklightService.busy){
   const row=BacklightService.values[0];
   if(row.value!==0||row.history!=="1,0,")throw new Error("latest adjustment was lost on dismissal");
   if(BacklightService.owners.length||BacklightService.updates.running)throw new Error("observation survived dismissal");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
            setup,
        )

    def test_queued_brightness_is_never_replaced_by_an_older_snapshot(self):
        def setup(root):
            (root / 'drawers/keyboard/backlight.py').write_text("""import json,sys,time
s=dict(key='kb::kbd_backlight',identity='t',maximum=10,value=1,available=True,reason='',history='')
for line in sys.stdin:
 r=json.loads(line);time.sleep(.3)
 if r['op']=='set':s['value']=r['value'];s['history']+=str(r['value'])+','
 print(json.dumps(dict(ok=True,values=[s],error='')),flush=True)
""")

        fixtures.run_qml(
            self,
            """import QtQuick
import QtTest
import Quickshell
import "drawers"
import "drawers/keyboard"
ShellRoot {
 TestCase{id:input;when:false;parent:window.contentItem}
 QtObject{id:language;property string language:"en";property string secondary:"bg";property bool available:true;property bool loaded:true;property bool selecting:false;property string selectingLanguage:"";property string error:"";signal selectionFinished(string code,bool success);function refresh(){}}
 FloatingWindow{id:window;visible:true;implicitWidth:480;implicitHeight:900;KeyboardDrawer{id:drawer;anchors.fill:parent;active:true;service:language}}
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 property int stage:0
 property int expected:0
 property var seen:[]
 Timer{interval:40;repeat:true;running:true;onTriggered:{try{
  const slider=find(drawer,"keyboardBacklightSlider:kb::kbd_backlight");
  if(expected)seen.push(slider.value);
  if(stage===0&&slider&&BacklightService.loaded&&!BacklightService.busy){
   // Arrow keys while a read is in flight: the read predates the change.
   BacklightService.refresh();slider.forceActiveFocus();
   for(let i=0;i<3;i++)input.keyClick(Qt.Key_Right);
   expected=4;seen=[slider.value];stage++;
  }else if(stage===1&&!BacklightService.busy){
   if(seen.some(value=>value!==4)||BacklightService.values[0].history!=="4,")throw new Error("keyboard steps were undone: "+seen+" "+BacklightService.values[0].history);
   // A drag finishes before the slow device confirms its first level.
   input.mousePress(slider,slider.leftPadding+2,slider.height/2);
   input.mouseMove(slider,slider.leftPadding+slider.availableWidth*0.8,slider.height/2);
   input.mouseRelease(slider,slider.leftPadding+slider.availableWidth*0.8,slider.height/2);
   expected=8;seen=[slider.value];stage++;
  }else if(stage===2&&!BacklightService.busy){
   if(seen.some(value=>value!==8)||BacklightService.values[0].value!==8)throw new Error("released slider jumped: "+seen);
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
            setup,
        )

    def test_helper_stop_reports_status_and_lost_changes_separately(self):
        def setup(root):
            # The first status read and the first write each kill the helper.
            (root / 'drawers/keyboard/backlight.py').write_text("""import json,os,sys
from pathlib import Path
here=Path(__file__).parent
s=dict(key='kb::kbd_backlight',identity='t',maximum=3,value=1,available=True,reason='')
for line in sys.stdin:
 r=json.loads(line);marker=here/('stopped-'+r['op'])
 if not marker.exists():marker.touch();os._exit(3)
 if r['op']=='set':s['value']=r['value']
 print(json.dumps(dict(ok=True,values=[s],error='')),flush=True)
""")

        fixtures.run_qml(
            self,
            """import QtQuick
import Quickshell
import "drawers/keyboard"
ShellRoot {
 QtObject{id:owner}
 property int stage:0
 Timer{interval:80;repeat:true;running:true;onTriggered:{try{
  if(stage===0){BacklightService.observe(owner,true);stage++;}
  else if(stage===1&&!BacklightService.busy&&BacklightService.statusError){
   if(BacklightService.actionError)throw new Error("a read was reported as a lost change");
   stage++;
  }else if(stage===2&&BacklightService.loaded&&!BacklightService.busy){
   if(BacklightService.error)throw new Error("recovered read kept its error: "+BacklightService.error);
   BacklightService.setBrightness(BacklightService.values[0],3);stage++;
  }else if(stage===3&&!BacklightService.busy&&!BacklightService.refreshPending){
   if(!BacklightService.actionError.includes("stopped"))throw new Error("lost change was not reported");
   if(BacklightService.values[0].value!==1)throw new Error("unconfirmed level stayed visible after the hardware was read");
   BacklightService.observe(owner,false);console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:6000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
            setup,
        )

    def test_cards_filter_color_effect_and_logitech_mode_controls(self):
        fixtures.run_qml(
            self,
            """import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "ui"
ShellRoot {
 TestCase{id:input;when:false;parent:window.contentItem}
 QtObject {
  id:language
  property string language:"en"
  property string secondary:"bg"
  property bool available:true
  property bool loaded:true
  property bool selecting:false
  property string selectingLanguage:""
  property string error:""
  signal selectionFinished(string code,bool success)
  function refresh(){}
  function languageName(code){return code;}
 }
 QtObject {
  id:lights
  property string error:""
  property bool busy:false
  property var values:[
   {key:"asus",identity:"asus",label:"ROG Zephyrus G14",connection:"Built-in keyboard",value:2,maximum:3,available:true,reason:"",effect:0,rgb:true,color:"#ff0000",effects:[{id:0,label:"Solid",colors:true},{id:2,label:"Rainbow cycle",colors:false}],modes:[],mode:-1},
   {key:"mx",identity:"mx",label:"Logitech MX Keys Mini",connection:"Wireless keyboard",value:3,maximum:7,available:true,reason:"",effect:-1,rgb:false,color:"",effects:[],modes:[{id:1,label:"Automatic"},{id:3,label:"Manual"},{id:255,label:"Off"}],mode:3}
  ]
  function observe(owner,active){}
  function update(row,change){values=values.map(item=>item.key===row.key?Object.assign({},item,change):item);}
  function setBrightness(row,value){update(row,{value});}
  function setEffect(row,effect){update(row,{effect,rgb:effect===0});}
  function setColor(row,color){update(row,{color});}
  function setMode(row,mode){update(row,{mode});}
 }
 FloatingWindow {
  id:window;implicitWidth:480;implicitHeight:1000;visible:true;color:Theme.background
  KeyboardDrawer{id:drawer;x:16;y:16;width:448;height:920;active:true;service:language;backlightService:lights}
 }
 function find(item,name){if(item.objectName===name)return item;for(let child of item.children??[]){const found=find(child,name);if(found)return found;}return null;}
 function check(value,message){if(!value)throw new Error(message);}
 function open(key){find(drawer,"keyboardOptions:"+key).clicked();return find(drawer,"keyboardCard:"+key).menu;}
 function capture(name,item,done){const dir=Quickshell.env("DISPLAY_PREVIEW_DIR");if(dir)(item||drawer).grabToImage(result=>{result.saveToFile(dir+"/keyboard-cards-"+name+".png");if(done)done();});else if(done)done();}
 property int stage:0
 Timer{interval:200;repeat:true;running:true;onTriggered:{try{
  const asus=find(drawer,"keyboardCard:asus");const mx=find(drawer,"keyboardCard:mx");
  if(stage===0){
   check(asus&&mx,"separate keyboard cards missing");
   check(find(drawer,"keyboardBacklightSlider:mx").to===7,"MX native range");
   lights.busy=true;
   check(find(drawer,"keyboardOptions:asus").enabled&&find(drawer,"keyboardOptions:mx").enabled,"background refresh disabled lighting cogs");
   capture("normal");open("asus");
  }else if(stage===1){
   check(asus.menu.visible,"busy service prevented opening lighting settings");
   lights.busy=false;
   lights.update(lights.values[1],{available:false});
   check(!find(drawer,"keyboardOptions:mx").enabled,"unavailable keyboard retained enabled cog");
   lights.update(lights.values[1],{available:true});
   check(drawer.openLighting===asus.menu&&drawer.escapeHandler,"lighting Escape not forwarded");
   check(find(asus.menu.contentItem,"keyboardColors").visible,"RGB palette missing");
   check(!find(asus.menu.contentItem,"keyboardEffect:1"),"unsupported effect offered");
   capture("rgb",asus.menu.contentItem,()=>{find(asus.menu.contentItem,"keyboardEffect:2").clicked();
   check(!asus.menu.visible&&lights.values[0].effect===2,"effect did not apply and close");open("asus");});
  }else if(stage===2){
   check(!find(asus.menu.contentItem,"keyboardColors").visible,"rainbow offered arbitrary colors");
   find(asus.menu.contentItem,"keyboardEffect:0").clicked();open("asus");
   find(asus.menu.contentItem,"keyboardColor:#0080ff").clicked();
   check(lights.values[0].color==="#0080ff"&&lights.values[1].mode===3,"color changed another device");open("mx");
  }else if(stage===3){
   check(!find(mx.menu.contentItem,"keyboardColors").visible&&!find(mx.menu.contentItem,"keyboardEffect:0"),"MX offered RGB/effects");
   capture("mx",mx.menu.contentItem,()=>{find(mx.menu.contentItem,"keyboardMode:1").clicked();
   check(lights.values[1].mode===1&&lights.values[0].effect===0,"mode targeted wrong keyboard");open("mx");
   input.keyClick(Qt.Key_Escape);check(!mx.menu.visible&&drawer.active,"Escape dismissed drawer");
   drawer.width=268;});
  }else if(stage===4){capture("narrow");open("asus");
  }else if(stage===5){capture("rgb-narrow",asus.menu.contentItem,()=>{drawer.active=false;check(!asus.menu.visible,"dismissal retained popup");});
  }else if(stage===6){console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer{interval:5000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout");Qt.quit();}}
}
""",
        )


if __name__ == '__main__':
    unittest.main()
