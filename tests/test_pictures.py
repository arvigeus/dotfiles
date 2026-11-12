import support
import sys

sys.path.insert(0, str(support.DESKTOP))
import io
import json
import os
import tempfile
import time
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from spaces.pictures import backend as pictures

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8


class WallpaperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(
            os.environ,
            {
                'XDG_CONFIG_HOME': str(self.root / 'config'),
                'XDG_CACHE_HOME': str(self.root / 'cache'),
                'XDG_DATA_HOME': str(self.root / 'data'),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        # Tests that download patch urlopen themselves; nothing reaches a real host.
        network = patch.object(
            pictures, 'urlopen', side_effect=AssertionError('network access')
        )
        network.start()
        self.addCleanup(network.stop)
        self.item = {
            'provider': 'wallhaven',
            'id': 'abc123',
            'path': 'https://w.wallhaven.cc/full/ab/wallhaven-abc123.png',
        }

    def cached_wallpaper(self):
        path = pictures.wallpaper_file(pictures.clean_item(self.item))
        path.write_bytes(PNG + b'cached image')
        return path

    def response(self, content=PNG + b'image'):
        response = io.BytesIO(content)
        response.headers = Message()
        response.headers['Content-Type'] = 'image/png'
        return response

    def test_set_updates_shell_setting_without_external_services(self):
        self.cached_wallpaper()
        with (
            patch.object(pictures, 'urlopen') as network,
        ):
            result = pictures.run({'op': 'set', 'wallpaper': self.item})
        network.assert_not_called()
        self.assertEqual(result['service'], 'desktop shell')
        setting = self.root / 'config/quickshell/desktop/spaces/pictures/wallpaper.json'
        self.assertEqual(
            json.loads(setting.read_text()),
            {
                'image': (
                    self.root
                    / 'data/quickshell/desktop/spaces/pictures/current-wallpaper'
                ).as_uri(),
                'provider': 'wallhaven',
            },
        )
        self.assertEqual(list(setting.parent.glob('.wallpaper-*')), [])

    def test_failed_setting_write_preserves_previous_wallpaper(self):
        path = self.cached_wallpaper()
        pictures.apply_shell_wallpaper(path)
        setting = self.root / 'config/quickshell/desktop/spaces/pictures/wallpaper.json'
        before = setting.read_bytes()
        other = self.root / 'other image.png'
        other.write_bytes(b'new wallpaper')
        with patch.object(pictures.os, 'replace', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                pictures.apply_shell_wallpaper(self.root / 'other image.png')
        self.assertEqual(setting.read_bytes(), before)
        self.assertEqual(list(setting.parent.glob('.wallpaper-*')), [])

    def test_current_provider_uses_saved_identity(self):
        setting = self.root / 'config/quickshell/desktop/spaces/pictures/wallpaper.json'
        setting.parent.mkdir(parents=True)
        cases = [
            ({}, 'wallhaven'),
            ({'image': 'file:///wallpapers/wallhaven-abc123.png'}, 'wallhaven'),
            ({'image': 'file:///wallpapers/bing-daily%20image.jpg'}, 'wallhaven'),
            ({'provider': 'bing', 'image': 'file:///custom.jpg'}, 'bing'),
            (
                {'mode': 'wallpaper_engine', 'image': 'file:///wallhaven-old.png'},
                'wallpaper_engine',
            ),
            ({'provider': 'unknown'}, 'wallhaven'),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                setting.write_text(json.dumps(value))
                self.assertEqual(
                    pictures.run({'op': 'providers'})['currentProvider'], expected
                )
        setting.write_text('invalid json')
        self.assertEqual(pictures.current_wallpaper_provider(), 'wallhaven')

    def test_download_saves_original_and_cleans_temporary_file(self):
        item = pictures.clean_item(self.item)
        with patch.object(pictures, 'urlopen', return_value=self.response()) as request:
            path = pictures.download_wallpaper(item)
        self.assertEqual(path.read_bytes(), PNG + b'image')
        self.assertEqual(request.call_args.kwargs['timeout'], 10)
        self.assertEqual(list(path.parent.glob('*.download')), [])

    def test_slow_download_expires_even_while_receiving_data(self):
        item = pictures.clean_item(self.item)
        path = pictures.wallpaper_file(item)
        with (
            patch.object(pictures, 'urlopen', return_value=self.response()),
            patch.object(pictures.time, 'monotonic', side_effect=[0, 1, 61]),
        ):
            with self.assertRaisesRegex(ValueError, 'download timed out'):
                pictures.download_wallpaper(item)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.glob('*.download')), [])

    def test_invalid_target_does_not_download(self):
        with patch.object(pictures, 'download_wallpaper') as download:
            with self.assertRaisesRegex(ValueError, 'Unknown wallpaper target'):
                pictures.set_wallpaper({'wallpaper': self.item, 'target': 'invalid'})
        download.assert_not_called()

    def test_random_command_defaults_to_shell(self):
        item = pictures.clean_item(self.item)
        for target in ('shell',):
            argv = ['backend.py', '--random'] + (
                ['--target=desktop'] if target == 'desktop' else []
            )
            with (
                self.subTest(target=target),
                patch.object(pictures.sys, 'argv', argv),
                patch.object(pictures, 'random_wallpaper', return_value=item),
                patch.object(
                    pictures,
                    'set_wallpaper',
                    return_value={'service': 'test', 'path': '/image'},
                ) as apply,
                patch('builtins.print'),
            ):
                self.assertEqual(pictures.command_line(), 0)
            apply.assert_called_once_with({'wallpaper': item, 'target': target})

    def test_repeated_wallpapers_update_shared_still(self):
        first = self.cached_wallpaper()
        pictures.set_wallpaper({'wallpaper': self.item})
        link = self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper'
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_bytes(), first.read_bytes())
        item = dict(self.item, id='def456')
        second = pictures.wallpaper_file(pictures.clean_item(item))
        second.write_bytes(PNG + b'new wallpaper')
        pictures.set_wallpaper({'wallpaper': item})
        self.assertEqual(link.read_bytes(), second.read_bytes())
        self.assertEqual(list(link.parent.glob('.lock-wallpaper-*')), [])

    def test_random_action_pins_wallhaven_and_updates_both_surfaces(self):
        image = self.cached_wallpaper()
        item = pictures.clean_item(self.item)
        with patch.object(pictures, 'random_wallpaper', return_value=item) as random:
            result = pictures.run({'op': 'randomSet', 'provider': 'bing'})
        random.assert_called_once_with(
            {'provider': 'wallhaven', 'filters': {'purity': '100'}}
        )
        self.assertIn('Lock screen updated', result['message'])
        self.assertEqual(
            (
                self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper'
            ).read_bytes(),
            image.read_bytes(),
        )

    def test_preferences_are_private_and_reject_oversized_data(self):
        values = dict(grid=True, provider='bing', filters={'bing': {'country': 'VN'}})
        pictures.run({'op': 'savePreferences', 'values': values})
        self.assertEqual(pictures.run({'op': 'preferences'}), values)
        target = (
            self.root / 'config/quickshell/desktop/spaces/pictures/pictures-ui.json'
        )
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        for bad in ({'grid': 'yes'}, dict(values, filters={'query': 'x' * 65000})):
            with self.assertRaises(ValueError):
                pictures.run({'op': 'savePreferences', 'values': bad})

    def test_wallhaven_filters_pagination_and_sfw_random(self):
        params = pictures.search_parameters(
            {
                'filters': {
                    'categories': '010',
                    'sorting': 'toplist',
                    'ratio': '16x9',
                    'resolution': '2560x1440',
                    'tagQuery': 'id:37',
                },
                'query': 'forest',
            }
        )
        self.assertEqual(params['purity'], '100')
        self.assertEqual(params['categories'], '010')
        self.assertIn('id:37', params['q'])
        with patch.object(
            pictures,
            'api_request',
            return_value={
                'data': [self.item],
                'meta': {'current_page': 1, 'last_page': 2, 'total': 24},
            },
        ):
            result = pictures.browse({'provider': 'wallhaven'})
        self.assertEqual(result['next'], 2)
        self.assertEqual(result['items'][0]['id'], 'abc123')

    def test_failed_json_commit_restores_previous_shared_still(self):
        first = self.cached_wallpaper()
        pictures.set_wallpaper({'wallpaper': self.item})
        other = self.root / 'other.png'
        other.write_bytes(b'new wallpaper')
        original = pictures.atomic_write

        def write(path, content, *args, **kwargs):
            if path.name == 'wallpaper.json':
                raise OSError('cannot commit')
            original(path, content, *args, **kwargs)

        with (
            patch.object(pictures, 'atomic_write', side_effect=write),
            self.assertRaises(OSError),
        ):
            pictures.apply_shell_wallpaper(other)
        self.assertEqual(
            (
                self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper'
            ).read_bytes(),
            first.read_bytes(),
        )

    def test_mislabelled_error_page_neither_applies_nor_poisons_the_cache(self):
        self.cached_wallpaper()
        pictures.set_wallpaper({'wallpaper': self.item})
        still = self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper'
        setting = self.root / 'config/quickshell/desktop/spaces/pictures/wallpaper.json'
        before = still.read_bytes(), setting.read_bytes()
        item = dict(self.item, id='def456')
        target = pictures.wallpaper_file(pictures.clean_item(item))
        page = self.response(b'<html>Too many requests</html>')
        with patch.object(pictures, 'urlopen', return_value=page):
            with self.assertRaisesRegex(ValueError, 'supported image'):
                pictures.set_wallpaper({'wallpaper': item})
        self.assertEqual((still.read_bytes(), setting.read_bytes()), before)
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.glob('.*')), [])
        # A bad file cached by an older version is fetched again, not reused.
        target.write_bytes(b'<html>cached error page</html>')
        with patch.object(pictures, 'urlopen', return_value=self.response()):
            pictures.set_wallpaper({'wallpaper': item})
        self.assertEqual(still.read_bytes(), PNG + b'image')

    def test_lock_screen_still_converts_formats_hyprlock_cannot_read(self):
        from spaces.pictures.wallpaper import update_lock_background

        binary = self.root / 'bin'
        binary.mkdir()
        ffmpeg = binary / 'ffmpeg'
        ffmpeg.write_text(
            '#!/bin/sh\nfor last; do :; done\n'
            'printf "\\211PNG\\r\\n\\032\\nframe" > "$last"\n'
        )
        ffmpeg.chmod(0o755)
        preview = self.root / 'preview.gif'
        preview.write_bytes(b'GIF89a animated Wallpaper Engine preview')
        jpeg = self.root / 'still.jpg'
        jpeg.write_bytes(b'\xff\xd8\xff jpeg')
        still = self.root / 'data/quickshell/desktop/spaces/pictures/current-wallpaper'
        with patch.dict(os.environ, {'PATH': f'{binary}:{os.environ["PATH"]}'}):
            update_lock_background(preview)
            self.assertEqual(still.read_bytes(), PNG[:8] + b'frame')
            self.assertEqual(still.stat().st_mode & 0o777, 0o600)
            update_lock_background(jpeg)
            self.assertEqual(still.read_bytes(), jpeg.read_bytes())
        # Without FFmpeg the desktop still gets the original; Qt decodes GIF.
        with patch.dict(os.environ, {'PATH': str(self.root / 'empty')}):
            update_lock_background(preview)
        self.assertEqual(still.read_bytes(), preview.read_bytes())
        self.assertEqual(list(still.parent.glob('.*')), [])

    def test_download_cache_is_bounded_and_keeps_active_and_recent_files(self):
        folder = pictures.wallpaper_cache()
        folder.mkdir(parents=True)
        old = time.time() - 3 * 86400

        def entry(name, age=old, size=10):
            path = folder / name
            path.write_bytes(b'x' * size)
            os.utime(path, (age, age))
            return path

        video = entry('personal-clip.mp4')
        poster = entry('personal-clip.poster.jpg')
        setting = self.root / 'config/quickshell/desktop/spaces/pictures/wallpaper.json'
        setting.parent.mkdir(parents=True)
        setting.write_text(
            json.dumps({'mode': 'video', 'video': str(video), 'selection': 'x'})
        )
        fresh = entry('wallhaven-fresh.png', age=time.time())
        abandoned = entry('.pictures-1-abandoned.download')
        partial = entry('.pictures-2-active.download', age=time.time())
        history = [entry(f'wallhaven-{n:02}.png', age=old + n) for n in range(40)]
        with patch.object(pictures, 'WALLPAPER_CACHE_FILES', 10):
            pictures.prune_wallpaper_cache()
        remaining = {path.name for path in folder.iterdir()}
        # Active video, its poster and a fresh download count toward the bound.
        self.assertEqual(
            remaining,
            {video.name, poster.name, fresh.name, partial.name}
            | {path.name for path in history[-7:]},
        )
        self.assertNotIn(abandoned.name, remaining)
        with patch.object(pictures, 'WALLPAPER_CACHE_BYTES', 35):
            pictures.prune_wallpaper_cache()
        self.assertEqual(
            {path.name for path in folder.iterdir()},
            {video.name, poster.name, fresh.name, partial.name},
        )
        # Pruning follows a committed Apply; a malformed choice must not fail it.
        setting.write_text(json.dumps({'mode': 'video', 'video': 'bad\u0000path'}))
        pictures.prune_wallpaper_cache()

    def test_reapplied_download_is_recent_and_apply_prunes_history(self):
        cached = self.cached_wallpaper()
        stale = time.time() - 3 * 86400
        os.utime(cached, (stale, stale))
        older = pictures.wallpaper_cache() / 'wallhaven-older.png'
        older.write_bytes(PNG)
        os.utime(older, (stale - 60, stale - 60))
        with patch.object(pictures, 'WALLPAPER_CACHE_FILES', 1):
            pictures.set_wallpaper({'wallpaper': self.item})
        self.assertTrue(cached.exists())
        self.assertGreater(cached.stat().st_mtime, stale)
        self.assertFalse(older.exists())


@unittest.skipUnless(support.QS, 'Quickshell is required')
class WallpaperWindowTests(unittest.TestCase):
    run_qml = support.run_qml

    def test_background_tolerates_a_removed_output(self):
        def setup(root):
            support.floating_window(root / 'spaces/pictures/WallpaperBackground.qml')

        # Variants keeps a delegate briefly after its screen disappears.
        self.run_qml(
            """import QtQuick
import Quickshell
import "spaces/pictures"
ShellRoot {
 WallpaperBackground {output:null;external:true}
 Timer {interval:200;running:true;onTriggered:{console.log("DISPLAY_PASS");Qt.quit();}}
}""",
            setup,
        )


# A stand-in controller: records each sync and follows a per-sync script.
RUNTIME_FIXTURE = """import json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from spaces.movies.worker import serve
log=root/'syncs.jsonl'
setting=root/'config/quickshell/desktop/spaces/pictures/wallpaper.json'
def sync(request):
    try:
        choice=json.loads(setting.read_text())
    except (OSError,ValueError):
        choice={}
    count=len(log.read_text().splitlines()) if log.exists() else 0
    with log.open('a') as stream:
        stream.write(json.dumps({'pid':os.getpid(),'mode':choice.get('mode',''),'request':sorted(request)})+'\\n')
    script=json.loads((root/'script.json').read_text()) if (root/'script.json').exists() else {}
    if choice.get('mode') not in ('video','wallpaper_engine'):
        return {'screens':[]}
    action=script.get(str(count),'')
    if action=='error':
        raise ValueError('fixture worker failure')
    if action=='fail':
        return {'screens':[],'error':'fixture renderer failure'}
    return {'screens':['FIXTURE']}
serve(sync,controls=('sync',))
"""


@unittest.skipUnless(support.QS, 'Quickshell is required')
class WallpaperRuntimeTests(unittest.TestCase):
    """The session controller owns renderer workers only while they are needed."""

    run_qml = support.run_qml

    def runtime_setup(self, choice, script=None, journal=False):
        def setup(root):
            (root / 'spaces/pictures/wallpaper_engine.py').write_text(RUNTIME_FIXTURE)
            config = root / 'config/quickshell/desktop/spaces/pictures'
            config.mkdir(parents=True)
            (config / 'wallpaper.json').write_text(json.dumps(choice))
            if journal:
                (config / '.engine-ownership.json').write_text(
                    json.dumps({'owner': 'f' * 32})
                )
            if script:
                (root / 'script.json').write_text(json.dumps(script))

        return setup

    PRELUDE = """import QtQuick
import Quickshell
import Quickshell.Io
import "spaces/pictures"
ShellRoot {
 id:root
 property int step:0
 property double since:0
 WallpaperRuntime {id:runtime}
 FileView {id:choice;path:WallpaperService.configRoot+"/wallpaper.json";atomicWrites:true}
 function check(v,m){if(!v)throw new Error(m);}
 function workers(){let n=0;const visit=item=>{if(item.objectName==="wallpaperRuntimeWorker")n++;for(const c of item.children??[])visit(c);};visit(runtime);return n;}
 // A fresh reader per check: a reused FileView can return text from before a reply.
 function log(){const view=Qt.createQmlObject('import Quickshell.Io; FileView {blockLoading:true;printErrors:false}',root);view.path=Quickshell.shellPath("syncs.jsonl");const text=view.text()||"";view.destroy();return text.split("\\n").filter(Boolean).map(line=>JSON.parse(line));}
 function choose(value){choice.setText(JSON.stringify(value));}
 function waited(ms){if(!root.since)root.since=Date.now();if(Date.now()-root.since<ms)return false;root.since=0;return true;}
"""

    def test_animated_choice_retries_recovers_latches_failure_and_stops(self):
        self.run_qml(
            self.PRELUDE
            + """ Timer {interval:50;running:true;repeat:true;onTriggered:{try{
  const entries=root.log();
  if(root.step===0){
   // Still images never start a controller.
   if(!root.waited(700))return;
   check(!entries.length && !root.workers() && !runtime.externalScreens.length,"static choice started a controller");
   root.choose({mode:"video",selection:"first",image:"file:///still"});root.step++;return;
  }
  if(root.step===1){
   if(String(runtime.externalScreens)!=="FIXTURE")return;
   check(root.workers()===1,"animated choice has no single controller");
   check(entries[0].request.indexOf("monitors")<0,"QML must leave compositor queries to the controller");
   runtime.sync();root.step++;return;
  }
  if(root.step===2){
   // Sync 1 fails at the worker level: back off and release the worker.
   if(!runtime.retrying)return;
   check(!runtime.externalScreens.length && runtime.workerRestarts===1,"worker failure did not back off");
   root.step++;return;
  }
  if(root.step===3){
   // The restarted worker succeeds and regains the whole retry budget.
   if(runtime.retrying || String(runtime.externalScreens)!=="FIXTURE" || entries.length<3)return;
   check(entries.length===3 && entries[2].pid!==entries[0].pid,"worker failure did not restart the controller");
   check(runtime.workerRestarts===0 && !runtime.failed,"a recovered worker kept its failure count");
   runtime.sync();root.step++;return;
  }
  if(root.step===4){
   // A renderer error latches until the user applies again.
   if(!runtime.failed)return;
   check(!runtime.externalScreens.length,"failed renderer still hides the still image");
   if(!root.waited(600))return;
   check(!root.workers() && entries.length===4,"failed choice kept its controller or kept syncing");
   root.choose({mode:"video",selection:"second",image:"file:///still"});root.step++;return;
  }
  if(root.step===5){
   if(String(runtime.externalScreens)!=="FIXTURE")return;
   check(!runtime.failed,"new selection did not clear the failure latch");
   root.choose({image:"file:///still",provider:"wallhaven"});root.step++;return;
  }
  if(root.step===6){
   // The stop sync runs once in the same worker, then the worker is released.
   if(runtime.stopping || root.workers())return;
   check(!runtime.externalScreens.length && entries[entries.length-1].mode==="","static choice did not reach the controller");
   console.log("DISPLAY_PASS");Qt.quit();
  }
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:13000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout step "+root.step);Qt.quit();}}
}""",
            self.runtime_setup(
                {'image': 'file:///still', 'provider': 'wallhaven'},
                script={'1': 'error', '3': 'fail'},
            ),
        )

    def test_orphan_journal_with_still_choice_runs_one_cleanup_sync(self):
        self.run_qml(
            self.PRELUDE
            + """ Timer {interval:50;running:true;repeat:true;onTriggered:{try{
  const entries=root.log();
  if(root.step===0){
   if(!entries.length || runtime.stopping || root.workers())return;
   check(entries[0].mode==="","cleanup sync saw an animated choice");
   root.step++;return;
  }
  if(!root.waited(700))return;
  check(root.log().length===1 && !root.workers() && !runtime.externalScreens.length,"cleanup controller kept running");
  console.log("DISPLAY_PASS");Qt.quit();
 }catch(e){console.error("DISPLAY_FAIL",e);Qt.quit();}}}
 Timer {interval:8000;running:true;onTriggered:{console.error("DISPLAY_FAIL timeout step "+root.step);Qt.quit();}}
}""",
            self.runtime_setup({'image': 'file:///still'}, journal=True),
        )
