"""IPTV metadata/stream normalization, local favorites and owned desktop playback."""

import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.television.backend import TelevisionBackend, clean_channel
from spaces.television.catalogue import normalize
from spaces.television.storage import TelevisionError, atomic_json
from test_radio import fake_mpv


def datasets(count=110):
    channels = [
        dict(
            id=f'Fixture{i}.us',
            name=f'Channel {i:03}',
            alt_names=['Alias ' + str(i)],
            country='US',
            categories=['news'],
            is_nsfw=False,
        )
        for i in range(count)
    ]
    channels[0]['website'] = 'https://station.example'
    feeds = [
        dict(channel=row['id'], id='HD', name='Main', is_main=True, languages=['eng'])
        for row in channels
    ]
    streams = [
        dict(
            channel=row['id'],
            feed='HD',
            title=row['name'],
            url=f'https://stream.example/{i}/index.m3u8',
            quality='720p',
            labels=[],
        )
        for i, row in enumerate(channels)
    ]
    streams.insert(
        1,
        dict(
            channel=channels[0]['id'],
            feed='HD',
            url='https://stream.example/high/index.m3u8',
            quality='1080p',
            labels=['Geo-blocked'],
            user_agent='Fixture player',
            referrer='https://station.example/',
        ),
    )
    return dict(
        channels=channels,
        feeds=feeds,
        streams=streams,
        countries=[dict(code='US', name='United States')],
        languages=[dict(code='eng', name='English')],
        categories=[dict(id='news', name='News')],
        blocklist=[],
    )


class TelevisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = datasets()
        self.backend = TelevisionBackend(
            self.root / 'config',
            self.root / 'data',
            self.root / 'cache',
            fetch=lambda key: copy.deepcopy(self.data[key]),
        )
        self.addCleanup(self.backend.player.stop)

    def test_catalogue_groups_feeds_headers_unknown_channels_and_provider_exclusions(
        self,
    ):
        self.data['channels'][2]['is_nsfw'] = True
        self.data['channels'][3]['closed'] = '2020-01-01'
        self.data['blocklist'] = [dict(channel='Fixture4.us')]
        self.data['streams'] += [
            dict(
                title='Unidentified',
                url='https://other.example/live.m3u8',
                quality='480p',
            ),
            dict(channel='Fixture5.us', url='file:///etc/passwd'),
        ]
        result = self.backend.handle(dict(op='refresh'))
        self.assertEqual(result['total'], 108)
        channel = self.backend.catalogue.snapshot['channels'][0]
        self.assertEqual(len(channel['streams']), 2)
        self.assertNotIn('Geo-blocked', channel['streams'][0]['labels'])
        self.assertEqual(channel['languageNames'], ['English'])
        self.assertEqual(channel['categoryNames'], ['News'])
        self.assertEqual(channel['streams'][1]['user_agent'], 'Fixture player')
        self.assertTrue(
            any(
                row['id'].startswith('stream:')
                for row in self.backend.catalogue.snapshot['channels']
            )
        )
        self.assertEqual(clean_channel(channel)['streams'], channel['streams'])

    def test_filters_search_pagination_favorites_and_offline_refresh(self):
        self.backend.init()
        self.backend.handle(dict(op='refresh'))
        first = self.backend.handle(dict(op='browse'))
        self.assertEqual(len(first['items']), 100)
        self.assertEqual(
            len(
                self.backend.handle(dict(op='browse', offset=first['nextOffset']))[
                    'items'
                ]
            ),
            10,
        )
        self.assertEqual(
            len(
                self.backend.handle(
                    dict(
                        op='browse',
                        query='alias 5',
                        country='US',
                        language='eng',
                        category='news',
                    )
                )['items']
            ),
            11,
        )
        self.assertEqual(
            self.backend.handle(dict(op='browse', language='fra'))['items'], []
        )
        channel = first['items'][10]
        self.backend.handle(dict(op='favorite', channel=channel, value=True))
        pinned = self.backend.handle(dict(op='browse'))
        self.assertEqual(pinned['items'][0]['id'], channel['id'])
        self.assertEqual(pinned['total'], 110)
        self.backend.catalogue.fetch = lambda _: (_ for _ in ()).throw(
            TelevisionError('Offline')
        )
        self.assertIn('Offline', self.backend.handle(dict(op='refresh'))['warning'])
        self.assertEqual(self.backend.catalogue.summary()['total'], 110)
        self.backend.catalogue.snapshot = {}
        self.assertEqual(len(self.backend.handle(dict(op='browse'))['items']), 1)

    def test_private_preferences_modes_and_corruption_preservation(self):
        self.backend.init()
        self.backend.handle(
            dict(
                op='settings-save',
                settings=dict(
                    country='US',
                    language='eng',
                    category='news',
                    streams={'Fixture0.us': 'choice'},
                ),
            )
        )
        self.assertEqual(
            self.backend.init()['settings']['streams'], {'Fixture0.us': 'choice'}
        )
        for path in (
            self.root / 'config/television-ui.json',
            self.root / 'data/favorites.json',
        ):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        favorite_path = self.root / 'data/favorites.json'
        favorite_path.write_text('{broken')
        with self.assertRaisesRegex(TelevisionError, 'preserved'):
            self.backend.init()
        self.assertEqual(favorite_path.read_text(), '{broken')

    def test_empty_or_failed_refresh_does_not_replace_a_working_snapshot(self):
        self.backend.handle(dict(op='refresh'))
        before = (self.root / 'cache/catalogue.json').read_bytes()
        self.backend.catalogue.fetch = lambda _: []
        self.assertTrue(self.backend.handle(dict(op='refresh'))['warning'])
        self.assertEqual((self.root / 'cache/catalogue.json').read_bytes(), before)

    def test_stream_injection_is_rejected_and_stale_selection_cannot_launch(self):
        data = datasets(2)
        data['streams'][1]['user_agent'] = 'unsafe\r\nAuthorization: secret'
        snapshot = normalize(data)
        self.assertEqual(snapshot['channels'][0]['streams'][1]['user_agent'], '')
        self.backend.handle(dict(op='refresh'))
        with patch('spaces.television.player.subprocess.Popen') as start:
            with self.assertRaisesRegex(TelevisionError, 'stream changed'):
                self.backend.handle(
                    dict(op='play', channelId='Fixture0.us', streamId='stale')
                )
        start.assert_not_called()
        with self.assertRaises(TelevisionError):
            clean_channel(
                dict(
                    id='invalid',
                    name='Invalid',
                    streams=[dict(url='https://a:password@example/live')],
                )
            )

    def test_real_player_ipc_switch_stop_headers_and_standard_mpv_configuration(self):
        self.backend.handle(dict(op='refresh'))
        player = fake_mpv(self.root)
        runtime = self.root / 'runtime'
        runtime.mkdir(mode=0o700)
        channel = self.backend.catalogue.snapshot['channels'][0]
        with (
            patch.dict(os.environ, XDG_RUNTIME_DIR=str(runtime)),
            patch('spaces.television.player.shutil.which', return_value=str(player)),
        ):
            state = self.backend.handle(
                dict(
                    op='play',
                    channelId=channel['id'],
                    streamId=channel['streams'][1]['id'],
                )
            )
            self.assertTrue(state['playing'])
            process = self.backend.player.process
            socket = Path(self.backend.player.path)
            for _ in range(100):
                if socket.exists():
                    break
                time.sleep(0.01)
            command = process.args
            self.assertNotIn('--no-config', command)
            self.assertIn('--cache-secs=20', command)
            self.assertIn('--user-agent=Fixture player', command)
            self.assertIn('--referrer=https://station.example/', command)
            self.assertTrue(self.backend.handle(dict(op='pause'))['paused'])
            self.backend.handle(
                dict(
                    op='play',
                    channelId=channel['id'],
                    streamId=channel['streams'][0]['id'],
                )
            )
            self.assertIsNotNone(process.poll())
            self.assertFalse(socket.exists())
            process = self.backend.player.process
            self.backend.handle(dict(op='stop'))
            self.assertIsNotNone(process.poll())
            self.assertFalse(self.backend.player.status()['playing'])

    def test_worker_close_releases_player_process_group_and_ipc(self):
        fake_mpv(self.root)
        runtime = self.root / 'runtime'
        runtime.mkdir(mode=0o700)
        data = self.root / 'xdg-data/quickshell/desktop/spaces/television'
        channel = normalize(datasets(2))['channels'][0]
        atomic_json(data / 'favorites.json', [channel])
        worker = subprocess.Popen(
            [sys.executable, str(support.DESKTOP / 'spaces/television/backend.py')],
            env={
                **os.environ,
                'XDG_CONFIG_HOME': str(self.root / 'xdg-config'),
                'XDG_DATA_HOME': str(self.root / 'xdg-data'),
                'XDG_CACHE_HOME': str(self.root / 'xdg-cache'),
                'XDG_RUNTIME_DIR': str(runtime),
                'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
                'QUICKSHELL_MEDIA_SPACE': 'television',
                'PYTHONDONTWRITEBYTECODE': '1',
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pid = None
        try:
            worker.stdin.write(
                json.dumps(
                    dict(
                        id=1,
                        op='play',
                        channelId=channel['id'],
                        streamId=channel['streams'][0]['id'],
                    )
                )
                + '\n'
            )
            worker.stdin.flush()
            self.assertTrue(json.loads(worker.stdout.readline())['result']['playing'])
            for _ in range(100):
                files = list(runtime.rglob('*.pid'))
                if files:
                    pid = int(files[0].read_text())
                    break
                time.sleep(0.01)
            self.assertIsNotNone(pid)
            worker.terminate()
            worker.wait(timeout=4)
            self.assertFalse(Path('/proc', str(pid)).exists())
            self.assertFalse(list(runtime.rglob('*.sock')))
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
            if pid and Path('/proc', str(pid)).exists():
                os.kill(pid, signal.SIGKILL)
            worker.stdin.close()
            worker.stdout.close()
            worker.stderr.close()

    def test_player_stop_reaps_plugin_helpers_in_its_process_group(self):
        player = fake_mpv(self.root)
        source = player.read_text().replace(
            'import json,os,pathlib,socket,sys',
            'import json,os,pathlib,socket,sys,signal,subprocess',
        )
        source = source.replace(
            'server=socket.socket',
            """child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
pathlib.Path(path+'.child.pid').write_text(str(child.pid))
def shutdown(*_):
 child.wait(timeout=2)
 sys.exit(0)
signal.signal(signal.SIGTERM,shutdown)
server=socket.socket""",
        )
        player.write_text(source)
        runtime = self.root / 'runtime'
        runtime.mkdir(mode=0o700)
        self.backend.handle(dict(op='refresh'))
        channel = self.backend.catalogue.snapshot['channels'][0]
        with (
            patch.dict(os.environ, XDG_RUNTIME_DIR=str(runtime)),
            patch('spaces.television.player.shutil.which', return_value=str(player)),
        ):
            self.backend.handle(
                dict(
                    op='play',
                    channelId=channel['id'],
                    streamId=channel['streams'][0]['id'],
                )
            )
            marker = Path(self.backend.player.path + '.child.pid')
            for _ in range(100):
                if marker.exists():
                    break
                time.sleep(0.01)
            child = int(marker.read_text())
            self.backend.player.stop()
            self.assertFalse(
                Path('/proc', str(child)).exists(),
                'mpv plugin helper survived player stop',
            )
