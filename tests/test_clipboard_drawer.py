"""Clipboard backend: cliphist commands, watcher units and wl-copy, without real clipboard access."""

import importlib.util
import json
import os
import shlex
import struct
import subprocess
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import support

SPEC = importlib.util.spec_from_file_location(
    'desktop_clipboard', support.DESKTOP / 'drawers/clipboard/backend.py'
)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
UNIT = (
    support.REPO / 'modules/desktop/quickshell/files/etc/systemd/user/cliphist@.service'
)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 8
# Like wl-copy: read the data, then fork a server that keeps the selection and
# stderr while the foreground process exits.
WL_COPY = """#!/usr/bin/env python3
import os, sys, time
data = sys.stdin.buffer.read()
with open(os.environ['WL_COPY_LOG'], 'ab') as log:
    log.write(sys.argv[2].encode() + b' ' + data.hex().encode() + b'\\n')
if os.fork():
    os._exit(0)
os.chdir('/')
null = os.open(os.devnull, os.O_RDWR)
os.dup2(null, 0)
os.dup2(null, 1)
time.sleep(4)
"""
CLIPHIST = """#!/usr/bin/env python3
import json, os, pathlib, sys, time
state = pathlib.Path(os.environ['CLIP_STATE'])
items = json.loads(state.read_text())
command = sys.argv[1]
if command == 'list':
    for item in items:
        print(f"{item['id']}\\t{item['preview']}")
elif command == 'decode':
    item = next(item for item in items if item['id'] == int(sys.argv[2]))
    time.sleep(item.get('delay', 0))
    sys.stdout.buffer.write(bytes.fromhex(item['data']))
elif command == 'delete':
    gone = {int(line.split('\\t')[0]) for line in sys.stdin.read().splitlines()}
    state.write_text(json.dumps([item for item in items if item['id'] not in gone]))
elif command == 'wipe':
    state.write_text('[]')
"""


def completed(args, code=0, stdout=b''):
    return subprocess.CompletedProcess(args, code, stdout, b'')


def png(width, height):
    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    rows = b''.join(b'\0' + b'\x80\x40\x20' * width for _ in range(height))
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(rows))
        + chunk(b'IEND', b'')
    )


def fake_tools(root, items):
    """Install cliphist, systemctl and wl-clipboard stand-ins; return their env."""
    tools = root / 'bin'
    tools.mkdir()
    scripts = {
        'cliphist': CLIPHIST,
        'wl-copy': WL_COPY,
        'wl-paste': '#!/bin/sh\nexit 1\n',
        'systemctl': '#!/bin/sh\nexit 0\n',
    }
    for name, script in scripts.items():
        (tools / name).write_text(script)
        (tools / name).chmod(0o755)
    state = root / 'history.json'
    state.write_text(json.dumps(items))
    return dict(
        PATH=f'{tools}{os.pathsep}{os.environ["PATH"]}',
        CLIP_STATE=str(state),
        WL_COPY_LOG=str(root / 'wl-copy.log'),
    )


class ClipboardBackendTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, XDG_CACHE_HOME=self.tmp.name)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(backend.cached_images.clear)

    def run_fake(self, outputs):
        def fake(args, **kwargs):
            self.calls.append((args, kwargs.get('input')))
            for prefix, result in outputs:
                if args[: len(prefix)] == prefix:
                    return completed(args, *result)
            return completed(args)

        return patch.object(backend.subprocess, 'run', side_effect=fake)

    def test_list_and_pause_use_cliphist_and_watcher_units(self):
        listing = b'7\t[[ binary data 2 KiB png 4x4 ]]\n6\thello\n'
        with self.run_fake(
            [
                (['cliphist', 'list'], (0, listing)),
                (['systemctl', '--user', 'is-active'], (3,)),
            ]
        ):
            result = backend.handle(dict(op='list'))
            backend.handle(dict(op='pause', value=False))
        self.assertTrue(result['paused'])
        self.assertEqual(
            [(row['image'], row['preview']) for row in result['entries']],
            [(True, 'PNG · 4 × 4 · 2 KiB'), (False, 'hello')],
        )
        self.assertIn(
            (['systemctl', '--user', 'start', *backend.WATCHERS], None), self.calls
        )
        self.assertFalse(any('-max-items' in args for args, _ in self.calls))

    def test_copy_decodes_by_id_and_pipes_to_wl_copy(self):
        with self.run_fake([(['cliphist', 'decode', '7'], (0, PNG))]):
            backend.handle(dict(op='copy', id=7))
            backend.handle(dict(op='delete', id=6))
        self.assertIn((['wl-copy', '--type', 'image/png'], PNG), self.calls)
        self.assertIn((['cliphist', 'delete'], b'6\t\n'), self.calls)

    def test_copy_returns_while_wl_copy_server_keeps_the_selection(self):
        root = Path(self.tmp.name)
        items = [dict(id=3, preview='secret', data=b'line\n\0tail'.hex())]
        with patch.dict(os.environ, fake_tools(root, items)):
            started = time.monotonic()
            self.assertEqual(backend.handle(dict(op='copy', id=3)), {'op': 'copy'})
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2)
        self.assertEqual(
            (root / 'wl-copy.log').read_bytes(),
            b'text/plain;charset=utf-8 ' + b'line\n\0tail'.hex().encode() + b'\n',
        )

    def test_thumbnail_is_private_and_rejects_text(self):
        with self.run_fake(
            [
                (['cliphist', 'decode', '7'], (0, PNG)),
                (['cliphist', 'decode', '6'], (0, b'text')),
            ]
        ):
            result = backend.handle(dict(op='thumbnail', id=7))
            with self.assertRaises(ValueError):
                backend.handle(dict(op='thumbnail', id=6))
        self.assertTrue(result['url'].startswith('file://' + self.tmp.name))

    def test_previews_never_outlive_their_history_entries(self):
        folder = backend.cache_root()
        listing = b''.join(
            b'%d\t[[ binary data 2 KiB png 4x4 ]]\n' % item_id for item_id in (10, 9, 8)
        )
        with self.run_fake(
            [(['cliphist', 'decode'], (0, PNG)), (['cliphist', 'list'], (0, listing))]
        ):
            for item_id in (7, 8, 9, 10):
                backend.handle(dict(op='thumbnail', id=item_id))
            # 7 was trimmed or deleted elsewhere. The others match no search
            # but still exist, so only the missing entry loses its preview.
            listed = backend.handle(dict(op='list', query='no match'))
            deleted = backend.handle(dict(op='delete', id=8))
            self.assertEqual(sorted(p.stem for p in folder.iterdir()), ['10', '9'])
            cleared = backend.handle(dict(op='clear'))
        self.assertEqual(
            (listed['entries'], listed['expired'], deleted['expired']), ([], [7], [8])
        )
        self.assertEqual(sorted(cleared['expired']), [9, 10])
        self.assertEqual(list(folder.iterdir()), [])

    def test_preview_cache_drops_least_recent_images(self):
        with (
            patch.object(backend, 'MAX_CACHED_IMAGES', 2),
            self.run_fake([(['cliphist', 'decode'], (0, PNG))]),
        ):
            backend.handle(dict(op='thumbnail', id=1))
            backend.handle(dict(op='thumbnail', id=2))
            backend.handle(dict(op='thumbnail', id=1))
            result = backend.handle(dict(op='thumbnail', id=3))
        self.assertEqual(result['expired'], [2])
        self.assertEqual(
            sorted(p.stem for p in backend.cache_root().iterdir()), ['1', '3']
        )

    def test_command_failures_surface_as_errors(self):
        with patch.object(
            backend.subprocess,
            'run',
            side_effect=subprocess.CalledProcessError(1, ['cliphist']),
        ):
            with self.assertRaises(subprocess.SubprocessError):
                backend.handle(dict(op='copy', id=99))


class ClipboardWatcherUnitTests(unittest.TestCase):
    def test_watcher_stores_nothing_while_paused(self):
        line = next(
            line
            for line in UNIT.read_text().splitlines()
            if line.startswith('ExecStart=')
        )
        argv = shlex.split(line.removeprefix('ExecStart='))
        # wl-paste stops parsing options at --watch and runs the rest as given.
        self.assertEqual(
            argv[:6],
            ['/usr/bin/wl-paste', '--type', '%i', '--watch', '/usr/bin/sh', '-c'],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / 'cliphist'
            store.write_text('#!/bin/sh\n[ "$1" = store ] && cat >> "$0.log"\n')
            store.chmod(0o755)
            script = (
                argv[6]
                .replace('%t', directory)
                .replace('/usr/bin/cliphist', str(store))
            )
            self.assertNotEqual(script, argv[6])

            def watch(data):
                subprocess.run(['sh', '-c', script], input=data, check=True, timeout=5)

            watch(b'kept\n')
            (root / 'cliphist-paused').touch()
            watch(b'private\n')
            (root / 'cliphist-paused').unlink()
            watch(b'\0binary')
            self.assertEqual((root / 'cliphist.log').read_bytes(), b'kept\n\0binary')


@unittest.skipUnless(support.QS, 'Quickshell is required')
class ClipboardDrawerQmlTests(unittest.TestCase):
    def test_drawer_refreshes_once_keeps_rows_and_search_and_copies_promptly(self):
        image = png(400, 300).hex()
        preview = '[[ binary data 1 KiB png 400x300 ]]'
        items = [
            dict(id=9, preview='hello world', data=b'hello world'.hex()),
            *(
                dict(id=item_id, preview=preview, data=image, delay=0.8)
                for item_id in (8, 7, 6)
            ),
            dict(id=5, preview='hello again', data=b'hello again'.hex()),
            dict(id=4, preview='other', data=b'other'.hex()),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, fake_tools(root, items)):
                support.run_qml(self, DRAWER_DRIVER)
            copied = (root / 'wl-copy.log').read_bytes()
        self.assertEqual(
            copied, b'text/plain;charset=utf-8 ' + b'hello world'.hex().encode() + b'\n'
        )


DRAWER_DRIVER = """import QtQuick
import Quickshell
import "drawers"
import "drawers/clipboard"
import "ui"
ShellRoot {
 FloatingWindow {
  implicitWidth:480; implicitHeight:900; visible:true; color:Theme.background
  // Like DrawerHost: the page completes, then becomes active.
  Loader {
   id:page; anchors.fill:parent; active:false
   sourceComponent:ClipboardDrawer {}
   onLoaded:item.active=true
  }
 }
 readonly property var drawer: page.item
 property int lists:0
 property int stage:0
 property int wait:0
 property var row:null
 property real copyStarted:0
 property real closedAfter:-1
 Connections {target:ClipboardService; function onEntriesChanged(){lists++;}}
 Connections {target:page.item; function onCloseRequested(){closedAfter=Date.now()-copyStarted;drawer.active=false;}}
 Component.onCompleted:ClipboardService.start()
 function check(value,message){if(!value)throw new Error(message);}
 function find(item,name){
  if(item.objectName===name)return item;
  for(let child of item.children??[]){let result=find(child,name);if(result)return result;}
  return null;
 }
 function settled(){return !ClipboardService.loading&&!ClipboardService.requestQueue.length;}
 function pending(){return Object.keys(ClipboardService.thumbnailPending).length;}
 function next(){stage++;wait=0;}
 Timer {interval:100;repeat:true;running:true;onTriggered:{try{
  check(++wait<60,"stage "+stage+" timed out: "+ClipboardService.error);
  if(stage===0){
   if(!ClipboardService.started||!settled())return;
   lists=0;page.active=true;next();
  }else if(stage===1){
   // The first preview is still decoding; closing drops the queued ones.
   if(pending()<3||ClipboardService.loading)return;
   check(lists===1,"opening listed "+lists+" times");
   drawer.active=false;
   check(!ClipboardService.requestQueue.some(item=>item.op==="thumbnail"),"queued previews survived closing");
   check(pending()===1,"cancelled previews still pending");
   next();
  }else if(stage===2){
   if(pending()||!settled())return;
   check(Object.keys(ClipboardService.thumbnails).length===1,"cancelled previews were decoded");
   // Reopen during the exit animation: the rows still exist.
   row=find(drawer,"clipboardEntry:9");lists=0;drawer.active=true;next();
  }else if(stage===3){
   const images=[8,7,6].map(id=>find(drawer,"clipboardThumbnail:"+id));
   if(pending()||!settled()||images.some(image=>!image||image.status!==Image.Ready))return;
   check(lists===1,"reopening listed "+lists+" times");
   check(find(drawer,"clipboardEntry:9")===row,"refresh recreated rows");
   for(const image of images)
    check(image.implicitWidth*image.implicitHeight<=2*88*64,"preview decoded at "+image.implicitWidth+"x"+image.implicitHeight);
   const search=find(drawer,"clipboardSearch");
   search.text="hello";search.submit();next();
  }else if(stage===4){
   if(!settled()||ClipboardService.entries.length!==2)return;
   check(find(drawer,"clipboardEntry:9")===row,"search recreated a kept row");
   find(drawer,"clipboardDelete:5").clicked();next();
  }else if(stage===5){
   if(!settled()||find(drawer,"clipboardEntry:5"))return;
   check(ClipboardService.entries.map(entry=>entry.id).join()==="9","refresh after delete lost the search: "+JSON.stringify(ClipboardService.entries));
   check(find(drawer,"clipboardEntry:9")===row,"delete recreated the remaining row");
   copyStarted=Date.now();find(drawer,"clipboardSelect:9").clicked();next();
  }else if(stage===6){
   if(closedAfter<0){check(!ClipboardService.error,ClipboardService.error);return;}
   check(closedAfter<2500,"copy took "+closedAfter+" ms");
   ClipboardService.clear();next();
  }else if(stage===7){
   if(!settled()||ClipboardService.entries.length)return;
   check(!Object.keys(ClipboardService.thumbnails).length,"cleared history kept previews");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e.message);Qt.quit();}}}
}
"""


if __name__ == '__main__':
    unittest.main()
