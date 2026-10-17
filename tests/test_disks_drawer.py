"""UDisks targeting and production drawer interactions; no host storage mutations."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_display_drawer as fixtures

DESKTOP = fixtures.DESKTOP
SPEC = importlib.util.spec_from_file_location('desktop_disks', DESKTOP / 'drawers/disks/backend.py')
backend = importlib.util.module_from_spec(SPEC)
_bytecode_disabled = sys.dont_write_bytecode
sys.dont_write_bytecode = True
SPEC.loader.exec_module(backend)
sys.dont_write_bytecode = _bytecode_disabled
D = backend.BASE + '/drives/test'
B = backend.BASE + '/block_devices/'


def encoded(value):
    return list(value.encode() + b'\0')


def drive(**values):
    return {backend.DRIVE: dict(dict(Model='Portable drive', Size=1000, Removable=True,
                                    CanPowerOff=True, Ejectable=True, TimeDetected=123,
                                    TimeMediaDetected=123, Serial='test', ConnectionBus='usb'), **values)}


def block(name, mounted=None, **values):
    result = {backend.BLOCK: dict(dict(Device=encoded('/dev/' + name), DeviceNumber=1,
                                       Drive=D, IdUUID=name, Size=1000, IdType='ext4',
                                       CryptoBackingDevice='/'), **values)}
    if mounted is not None:
        result[backend.FS] = dict(MountPoints=[encoded(p) for p in mounted])
    return result


def objects():
    return {D: drive(), B+'test1': block('test1', ['/media/Backup'], IdLabel='Backup'),
            B+'test2': dict(block('test2', IdType='crypto_LUKS', IdLabel='Vault'),
                           **{backend.CRYPT: dict(CleartextDevice='/')})}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.data = objects()
        self.storage = backend.Storage.__new__(backend.Storage)
        self.storage.objects = Mock(side_effect=lambda: copy.deepcopy(self.data))
        self.storage.call = Mock(side_effect=self.mutate)
        self.slaves = patch.object(backend, 'slaves', return_value=[])
        self.slaves.start(); self.addCleanup(self.slaves.stop)
        stats = SimpleNamespace(f_blocks=100, f_frsize=10, f_bfree=30, f_bavail=20)
        self.stats = patch.object(backend.os, 'statvfs', return_value=stats)
        self.stats.start(); self.addCleanup(self.stats.stop)

    def mutate(self, path, interface, method, **fields):
        if method == 'Unmount': self.data[path][backend.FS]['MountPoints'] = []
        elif method == 'Mount': self.data[path][backend.FS]['MountPoints'] = [encoded('/media/Backup')]
        elif method == 'Lock':
            clear = self.data[path][backend.CRYPT]['CleartextDevice']
            self.data.pop(clear, None)
            self.data[path][backend.CRYPT]['CleartextDevice'] = '/'

    def request(self, op, key=B+'test1'):
        identity = self.storage.drive_identity(self.data, key) if op in ('eject', 'health') else self.storage.block_identity(self.data, key)
        return dict(op=op, key=key, identity=identity)

    def volumes(self):
        return self.storage.snapshot()['drives'][0]['volumes']

    def test_inventory_uses_available_space_keeps_unknowns_and_never_checks_health(self):
        rows = self.volumes()
        self.assertEqual((rows[0]['capacity'], rows[0]['free'], rows[0]['used']), (1000, 200, 700))
        self.assertEqual(rows[0]['mounts'], ['/media/Backup'])
        self.assertTrue(rows[1]['locked'])
        self.assertIsNone(rows[1]['free'])
        self.storage.call.assert_not_called()
        with patch.object(backend.os, 'statvfs', side_effect=PermissionError()):
            row = self.volumes()[0]
        self.assertIsNone(row['free'])
        self.assertTrue(row['capacityError'])

    def test_unmount_keeps_device_available_for_remount_without_powering_off(self):
        before = self.volumes()[0]
        result = self.storage.response(self.request('unmount'))
        self.assertTrue(result['ok'])
        device = next(d for d in result['data']['drives'] if d['key'] == D)
        volume = next(v for v in device['volumes'] if v['key'] == before['key'])
        self.assertEqual(volume['identity'], before['identity'])
        self.assertEqual(volume['mounts'], [])
        self.assertTrue(volume['canMount'])
        self.storage.call.assert_called_once_with(B+'test1', backend.FS, 'Unmount')
        self.storage.handle(self.request('mount'))
        self.assertEqual(self.volumes()[0]['mounts'], ['/media/Backup'])

    def test_hidden_mounted_system_volume_is_visible_and_cannot_be_unmounted_or_ejected(self):
        self.data[B+'test1'][backend.BLOCK]['HintIgnore'] = True
        self.data[B+'test1'][backend.FS]['MountPoints'] = [encoded('/'), encoded('/home')]
        self.assertFalse(self.volumes()[0]['canUnmount'])
        self.assertFalse(self.storage.snapshot()['drives'][0]['canEject'])
        for req in (self.request('unmount'), self.request('eject', D)):
            with self.assertRaisesRegex(backend.StorageError, '[Ss]ystem'):
                self.storage.handle(req)
        self.storage.call.assert_not_called()

    def test_lvm_above_encryption_resolves_to_physical_drive_without_duplicate_container(self):
        self.data[B+'test2'][backend.CRYPT]['CleartextDevice'] = B+'mapped'
        self.data[B+'mapped'] = block('mapped', Drive='/', CryptoBackingDevice=B+'test2', IdType='LVM2_member')
        self.data[B+'logical'] = block('logical', ['/'], Drive='/', IdType='btrfs')
        with patch.object(backend, 'slaves', side_effect=lambda device: ['mapped'] if device == '/dev/logical' else []):
            rows = self.volumes()
            self.assertEqual(len(rows), 2)
            system = next(r for r in rows if '/' in r['mounts'])
            self.assertEqual(system['drive'], D)
            self.assertFalse(self.storage.snapshot()['drives'][0]['canEject'])

    def test_directly_unlocked_filesystem_keeps_parent_identity_and_mount_target(self):
        self.data[B+'test2'][backend.CRYPT]['CleartextDevice'] = B+'mapped'
        self.data[B+'mapped'] = block('mapped', [], Drive='/', CryptoBackingDevice=B+'test2')
        row = next(r for r in self.volumes() if r['key'] == B+'test2')
        self.assertFalse(row['locked']); self.assertTrue(row['canMount'])
        self.assertEqual(len(self.volumes()), 2)
        self.storage.handle(self.request('mount', B+'test2'))
        self.storage.call.assert_called_once_with(B+'mapped', backend.FS, 'Mount')

    def test_ignored_encrypted_parent_does_not_hide_mounted_filesystem(self):
        self.data[B+'test2'][backend.BLOCK]['HintIgnore'] = True
        self.data[B+'test2'][backend.CRYPT]['CleartextDevice'] = B+'mapped'
        self.data[B+'mapped'] = block('mapped', ['/media/Vault'], Drive='/', CryptoBackingDevice=B+'test2')
        self.assertTrue(any(row['mounts'] == ['/media/Vault'] for row in self.volumes()))

    def test_real_dbus_unlock_signature_and_errors_do_not_echo_secrets(self):
        self.storage.bus = Mock()
        self.storage.bus.call_sync.return_value = backend.GLib.Variant('(o)', (B+'mapped',))
        backend.Storage.call(self.storage, B+'test2', backend.CRYPT, 'Unlock', password='private')
        args = self.storage.bus.call_sync.call_args.args
        self.assertEqual(args[4].get_type_string(), '(sa{sv})')
        self.assertEqual(args[4].unpack(), ('private', {}))
        self.storage.bus.call_sync.side_effect = backend.GLib.Error('private diagnostic')
        for code, expected in [('DeviceBusy', 'busy'), ('WouldWakeup', 'asleep'), ('Failed', 'Unlock failed')]:
            with patch.object(backend.Gio.DBusError, 'get_remote_error', return_value=backend.BUS+'.Error.'+code):
                with self.assertRaisesRegex(backend.StorageError, expected) as error:
                    backend.Storage.call(self.storage, B+'test2', backend.CRYPT, 'Unlock', password='private')
                self.assertNotIn('private', str(error.exception))

    def test_stale_hardware_media_and_filesystem_identity_never_mutate(self):
        for field, new_value in (('Serial', 'replacement'), ('TimeDetected', 999), ('TimeMediaDetected', 999)):
            request = self.request('eject', D)
            old = self.data[D][backend.DRIVE][field]
            self.data[D][backend.DRIVE][field] = new_value
            with self.assertRaisesRegex(backend.StorageError, 'changed'): self.storage.handle(request)
            self.data[D][backend.DRIVE][field] = old
        request = self.request('unmount')
        self.data[B+'test1'][backend.BLOCK]['IdUUID'] = 'reformatted'
        with self.assertRaisesRegex(backend.StorageError, 'changed'): self.storage.handle(request)
        self.storage.call.assert_not_called()

    def test_unlock_sends_secret_only_to_dbus_and_clears_request(self):
        request = dict(self.request('unlock', B+'test2'), password='secret with spaces')
        result = self.storage.response(request)
        self.assertTrue(result['ok'], result)
        self.assertNotIn('password', request)
        self.assertNotIn('secret with spaces', json.dumps(result))
        self.storage.call.assert_called_once_with(B+'test2', backend.CRYPT, 'Unlock', password='secret with spaces')

    def test_password_is_cleared_when_unlock_validation_or_service_fails(self):
        for identity in ('stale', self.storage.block_identity(self.data, B+'test2')):
            request = dict(op='unlock', key=B+'test2', identity=identity, password='private')
            self.storage.call.side_effect = RuntimeError('private')
            result = self.storage.response(request)
            self.assertFalse(result['ok']); self.assertNotIn('password', request)
            self.assertNotIn('private', json.dumps(result))

    def test_unmount_then_eject_never_forces_and_returns_device_confirmation(self):
        result = self.storage.handle(self.request('eject', D))
        self.assertIn('Portable drive', result['message'])
        self.assertEqual([(c.args[0], c.args[2]) for c in self.storage.call.call_args_list],
                         [(B+'test1', 'Unmount'), (D, 'PowerOff')])
        self.assertTrue(all(not c.kwargs for c in self.storage.call.call_args_list))

    def test_busy_volume_stops_removal_and_keeps_refreshed_inventory(self):
        self.storage.call.side_effect = backend.StorageError('The device is busy.')
        result = self.storage.response(self.request('eject', D))
        self.assertFalse(result['ok']); self.assertIn('busy', result['error'])
        self.assertTrue(result['data']['drives'][0]['volumes'][0]['mounts'])
        self.assertEqual(self.storage.call.call_count, 1)

    def test_new_mapping_during_removal_is_not_unmounted_or_powered_off(self):
        def change(*args, **kwargs):
            self.mutate(*args, **kwargs)
            self.data[B+'new'] = block('new', ['/media/New'])
        self.storage.call.side_effect = change
        with self.assertRaisesRegex(backend.StorageError, 'contents changed'):
            self.storage.handle(self.request('eject', D))
        self.assertEqual(self.storage.call.call_count, 1)

    def test_removal_unmounts_and_locks_encrypted_filesystem_before_poweroff(self):
        self.data[B+'test2'][backend.CRYPT]['CleartextDevice'] = B+'mapped'
        self.data[B+'mapped'] = block('mapped', ['/media/Vault'], Drive='/', CryptoBackingDevice=B+'test2')
        self.storage.handle(self.request('eject', D))
        methods = [c.args[2] for c in self.storage.call.call_args_list]
        self.assertEqual(methods, ['Unmount', 'Unmount', 'Lock', 'PowerOff'])

    def test_shared_power_and_active_swap_block_removal_before_any_unmount(self):
        self.data[D][backend.DRIVE]['SiblingId'] = 'reader'
        self.data[D+'2'] = drive(SiblingId='reader')
        self.assertFalse(self.storage.snapshot()['drives'][0]['canEject'])
        with self.assertRaisesRegex(backend.StorageError, 'Shares power'):
            self.storage.handle(self.request('eject', D))
        del self.data[D+'2']
        self.data[B+'swap'] = dict(block('swap'), **{backend.SWAP: dict(Active=True)})
        with self.assertRaisesRegex(backend.StorageError, 'swap'):
            self.storage.handle(self.request('eject', D))
        self.storage.call.assert_not_called()

    def test_health_is_explicit_ata_avoids_wakeup_and_nvme_uses_controller(self):
        self.data[D][backend.ATA] = dict(SmartSupported=True, SmartEnabled=True, SmartUpdated=123,
                                        SmartTemperature=300, SmartPowerOnSeconds=7200,
                                        SmartFailing=False, SmartNumBadSectors=2)
        result = self.storage.handle(self.request('health', D))['health']
        self.assertTrue(result['warning']); self.assertEqual(result['temperature'], 27)
        self.assertEqual(result['hours'], 2)
        self.assertTrue(self.storage.call.call_args.kwargs['options']['nowakeup'].unpack())
        self.data[D][backend.NVME] = dict(SmartUpdated=123, SmartTemperature=0, SmartCriticalWarning=[], SmartPowerOnHours=12)
        result = self.storage.handle(self.request('health', D))['health']
        self.assertFalse(result['warning']); self.assertIsNone(result['temperature'])
        self.assertEqual(self.storage.call.call_args.args[1], backend.NVME)

    def test_unknown_and_status_requests_never_mutate(self):
        self.assertTrue(self.storage.response(dict(op='status'))['ok'])
        self.assertFalse(self.storage.response(dict(op='format'))['ok'])
        self.storage.call.assert_not_called()


@unittest.skipUnless(fixtures.QS, 'Quickshell is required')
class DisksQmlTests(unittest.TestCase):
    run_qml = fixtures.DisplayQmlTests.run_qml

    def test_inventory_actions_unlock_escape_keyed_refresh_and_narrow_layout(self):
        storage = backend.Storage.__new__(backend.Storage)
        data = objects()
        internal = D + '_internal'
        data[internal] = drive(Model='Internal SSD', Removable=False, CanPowerOff=False, Ejectable=False)
        data[internal][backend.NVME] = dict(SmartUpdated=123)
        data[B+'system'] = block('system', ['/'], Drive=internal, IdLabel='System')
        storage.objects = lambda: data
        with patch.object(backend, 'slaves', return_value=[]), patch.object(backend.os, 'statvfs',
                return_value=SimpleNamespace(f_blocks=100, f_frsize=10**9, f_bfree=30, f_bavail=30)):
            state = storage.snapshot()
        self.run_qml('''import QtQuick
import QtQuick.Controls
import QtTest
import Quickshell
import "drawers"
import "ui"
ShellRoot {
 TestCase { id:input; when:false; parent:window.contentItem }
 QtObject {
  id:mock
  property var state: STATE
  property bool loaded:true
  property bool busy:false
  property bool closing:false
  property string pendingKey:""
  property string pendingOp:""
  property string actionError:""
  property string statusError:""
  property string errorKey:""
  property string message:""
  property var owners:[]
  property var calls:[]
  property var health:null
  function observe(owner,active){owners=owners.filter(o=>o!==owner).concat(active?[owner]:[]);}
  function refresh(){}
  function healthFor(record){return record.key.endsWith("_internal")?health:null;}
  function dismissError(){actionError="";errorKey="";}
  function change(record,op,password=""){calls=calls.concat([{key:record.key,op,password}]);}
 }
 FloatingWindow {
  id:window; implicitWidth:480; implicitHeight:780; visible:true; color:Theme.background
  DisksDrawer {id:drawer;x:16;y:16;width:448;height:748;active:true;service:mock}
 }
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){
  if(item.objectName===name)return item;
  for(let child of item.children??[]){let result=find(child,name);if(result)return result;}
  return null;
 }
 function capture(name){let path=Quickshell.env("DISPLAY_PREVIEW_DIR");if(path)drawer.grabToImage(r=>r.saveToFile(path+"/disks-"+name+".png"));}
 property int stage:0
 property var originalCard:null
 property var originalAction:null
 Timer {interval:200;repeat:true;running:true;onTriggered:{try{
  const mount=find(drawer,"volumeAction:BLOCKtest1");
  const locked=find(drawer,"volumeAction:BLOCKtest2");
  if(stage===0){
   check(mock.calls.length===0,"opening did work");
   check(!find(drawer,"diskDetails:DRIVE").visible,"details initially expanded");
   check(find(drawer,"diskCard:DRIVE").height<150,"default card not compact");
   check(!find(drawer,"volumeAction:BLOCKsystem").visible,"system unmount exposed");
   check(!find(drawer,"diskOptions:DRIVE"),"settings cog remains");
   check(!find(drawer,"diskHealth:DRIVE").enabled,"unsupported health action enabled");
   check(mount.visible&&mount.iconName==="hard-drive-upload","mounted summary does not offer unmount");
   originalCard=find(drawer,"diskCard:DRIVE");originalAction=mount;
   capture("normal");
  }else if(stage===1){
   find(drawer,"diskExpand:DRIVE").clicked();
   check(find(drawer,"diskDetails:DRIVE").visible,"details did not expand");
  }else if(stage===2){
   capture("expanded");
   mount.clicked();check(mock.calls[0].op==="unmount"&&mock.calls[0].key==="BLOCKtest1","unmount did not target volume");
   const mountedState=mock.state;
   const unmountedState=JSON.parse(JSON.stringify(mock.state));
   const volume=unmountedState.drives.find(d=>d.key==="DRIVE").volumes.find(v=>v.key==="BLOCKtest1");
   volume.mounts=[];volume.canMount=true;volume.canUnmount=false;volume.free=null;volume.capacity=null;volume.used=null;
   mock.state=unmountedState;
   check(find(drawer,"volumeAction:BLOCKtest1")===mount&&mount.iconName==="hard-drive-download","button did not switch in place to mount");
   check(!find(drawer,"diskExpand:DRIVE").enabled&&!find(drawer,"diskDetails:DRIVE").visible,"unmounted drive still expandable");
   mount.clicked();check(mock.calls[1].op==="mount"&&mock.calls[1].key==="BLOCKtest1","mount did not target volume");
   mock.state=mountedState;check(mount.iconName==="hard-drive-upload","button did not return to unmount");
   check(find(drawer,"diskExpand:DRIVE").enabled,"remounted drive cannot expand");
   find(drawer,"diskExpand:DRIVE").clicked();
   const options=find(drawer,"diskHealth:DRIVE_internal");options.clicked();
   check(options.menu.visible&&drawer.escapeHandler,"health popover missing");
   check(mock.calls[2].op==="health","health routing");
   mock.health={summary:"No problems reported",warning:false,temperature:42,hours:120,badSectors:0,detail:"",updated:1700000000};
  }else if(stage===3){
   const options=find(drawer,"diskHealth:DRIVE_internal");
   check(find(options.menu.contentItem,"diskHealthRefresh:DRIVE_internal").text==="Refresh health","health result did not update menu");
   options.menu.contentItem.forceActiveFocus();input.keyClick(Qt.Key_Escape);
   check(!options.menu.visible&&drawer.active&&!drawer.escapeHandler,"menu did not consume Escape");
   mock.state=JSON.parse(JSON.stringify(mock.state));
   check(find(drawer,"diskCard:DRIVE")===originalCard&&find(drawer,"volumeAction:BLOCKtest1")===originalAction,"refresh recreated controls");
   check(find(drawer,"diskDetails:DRIVE").visible,"refresh collapsed details");
   mock.busy=true;check(!mount.enabled&&!locked.enabled,"actions enabled while busy");mock.busy=false;
   locked.clicked();
  }else if(stage===4){
   check(drawer.unlockPopup.visible&&drawer.escapeHandler,"unlock popup missing");
   const field=find(drawer.unlockPopup.contentItem,"diskPassphrase");
   field.forceActiveFocus();input.keyClick(Qt.Key_T);input.keyClick(Qt.Key_E);input.keyClick(Qt.Key_Escape);
   check(!drawer.unlockPopup.visible&&field.text===""&&drawer.active,"Escape retained password or dismissed drawer");
   locked.clicked();
  }else if(stage===5){
   const field=find(drawer.unlockPopup.contentItem,"diskPassphrase");
   field.forceActiveFocus();input.keyClick(Qt.Key_T);input.keyClick(Qt.Key_E);input.keyClick(Qt.Key_Return);
   check(mock.calls[3].op==="unlock"&&mock.calls[3].password==="te","unlock input routing");
   check(!drawer.unlockPopup.visible&&field.text==="","submitted password retained");
   mock.errorKey="BLOCKtest2";mock.actionError="The device is busy. Close files and try again.";
   find(drawer,"diskExpand:DRIVE").clicked();capture("error");
  }else if(stage===6){
   mock.dismissError();drawer.width=268;
  }else if(stage===7){
   check(find(drawer,"diskCard:DRIVE").width<=drawer.width,"card overflow");capture("narrow");
   find(drawer,"diskExpand:DRIVE").clicked();locked.clicked();
  }else if(stage===8){
   drawer.width=448;
   const field=find(drawer.unlockPopup.contentItem,"diskPassphrase");field.text="discard";drawer.active=false;
   check(mock.owners.length===0&&!drawer.unlockPopup.visible&&field.text==="","dismissal retained input or observer");
   drawer.active=true;Theme.setMode("light");
  }else if(stage===9){
   capture("light");
  }else if(stage===10){
   find(drawer,"diskHealth:DRIVE_internal").clicked();
  }else if(stage===11){
   const menu=find(drawer,"diskHealth:DRIVE_internal").menu;
   const path=Quickshell.env("DISPLAY_PREVIEW_DIR");if(path)menu.contentItem.parent.grabToImage(r=>r.saveToFile(path+"/disks-health.png"));
  }else if(stage===12){
   find(drawer,"diskHealth:DRIVE_internal").menu.close();
   mock.state={drives:mock.state.drives.filter(d=>d.key!=="DRIVE"),editorAvailable:false};
   check(!find(drawer,"diskCard:DRIVE"),"hot unplug retained drive");
  }else {console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
}'''.replace('STATE', json.dumps(state)).replace('BLOCK', B).replace('DRIVE', D))

    def test_analyzer_and_directory_launches_close_drawer_and_preserve_literal_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'launched'
            executable = root / 'filelight'
            executable.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\n'
                                  f'Path({str(marker)!r}).write_text(json.dumps(sys.argv[1:]))\n')
            executable.chmod(0o700)
            folder_marker = root / 'folder'
            file_manager = root / 'dolphin'
            file_manager.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\n'
                                    f'Path({str(folder_marker)!r}).write_text(json.dumps(sys.argv[1:]))\n')
            file_manager.chmod(0o700)
            editor_marker = root / 'editor'
            editor = root / 'partitionmanager'
            editor.write_text('#!' + sys.executable + '\nimport json,sys\nfrom pathlib import Path\n'
                              f'Path({str(editor_marker)!r}).write_text(json.dumps(sys.argv[1:]))\n')
            editor.chmod(0o700)
            location = '/media/Backup #1/space\tand\nnewline;$(echo ignored)'
            with patch.dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH']):
                self.run_qml('''import QtQuick
import Quickshell
import "drawers"
import "ui"
ShellRoot {
 QtObject {
  id:mock
  property var state: ({drives:[],editorAvailable:false,analyzerAvailable:false})
  property bool loaded:true
  property bool busy:false
  property bool closing:false
  property string statusError:""
  property string actionError:""
  property string errorKey:""
  property string message:""
  function observe(owner,active){}
 }
 FloatingWindow {
  implicitWidth:480;implicitHeight:780;visible:true
  DisksDrawer {id:drawer;width:448;height:700;active:true;service:mock;onCloseRequested:closes++}
  Loader {id:header;sourceComponent:drawer.headerActions}
 }
 property int closes:0
 property int stage:0
 Timer {interval:200;repeat:true;running:true;onTriggered:{try{
  const button=header.item.children.find(c=>c.objectName==="disksUsage");
  if(stage===0){
   if(button.enabled)throw new Error("missing analyzer enabled");
   mock.state={drives:[],editorAvailable:true,analyzerAvailable:true};
   if(!button.enabled)throw new Error("installed analyzer disabled");
   button.clicked();
   if(closes!==1)throw new Error("analyzer did not close drawer");
  }else if(stage===1){
   drawer.openLocation(LOCATION);
   if(closes!==2)throw new Error("directory did not close drawer");
  }else if(stage===2){
   const editor=header.item.children.find(c=>c.objectName==="disksEditor");
   if(!editor.enabled)throw new Error("partition editor disabled");
   editor.clicked();
   if(closes!==3)throw new Error("partition editor did not close drawer");
  }else {console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
}
'''.replace('LOCATION', json.dumps(location)))
            self.assertEqual(json.loads(marker.read_text()), [])
            self.assertEqual(json.loads(folder_marker.read_text()), ['--', location])
            self.assertEqual(json.loads(editor_marker.read_text()), [])

    def test_service_finishes_action_after_dismissal_and_stops_observation(self):
        def setup(root):
            (root / 'drawers/disks/backend.py').write_text('''import json,sys,time
for line in sys.stdin:
 request=json.loads(line)
 if request['op']!='status': time.sleep(.5)
 result=dict(ok=True,error='',data=dict(drives=[],editorAvailable=False))
 if request['op']=='health': result.update(ok=False,error='The drive is asleep.')
 print(json.dumps(result),flush=True)
''')
        self.run_qml('''import QtQuick
import Quickshell
import "drawers/disks"
ShellRoot {
 QtObject {id:owner}
 Component.onCompleted: DisksService.observe(owner,true)
 function check(v,m){if(!v)throw new Error(m);}
 property int stage:0
 Timer {interval:150;repeat:true;running:true;onTriggered:{try{
  if(stage===0){if(!DisksService.loaded)return;DisksService.change({key:"drive",identity:"old",label:"Drive"},"health");DisksService.observe(owner,false);check(DisksService.busy,"action cancelled by dismissal");}
  else if(stage===1){if(DisksService.busy)return;check(DisksService.actionError==="The drive is asleep.","action error missing");check(DisksService.errorKey==="drive","error identity missing");}
  else if(stage===2){check(!DisksService.worker.running&&!DisksService.updates.running,"closed drawer still observing");DisksService.observe(owner,true);}
  else if(stage===3){if(DisksService.busy)return;check(DisksService.actionError!=="","status erased action error");DisksService.observe(owner,false);}
  else if(stage===4){
   if(DisksService.worker.running)return;
   DisksService.change({key:"vault",identity:"vault",label:"Vault"},"unlock","private");
   check(DisksService.busy&&!DisksService.request.password,"secret retained in action metadata");
  }
  else if(stage===5){
   if(DisksService.busy)return;
   check(DisksService.startupInput==="","startup password retained");
  }
  else {check(!DisksService.worker.running,"cold-start worker leaked");console.log("DISPLAY_PASS");Qt.quit();}
  stage++;
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
}''', setup=setup)
