"""Radio discovery, persistence, playback ownership and failure behavior."""

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
from spaces.radio import api
from spaces.radio.backend import RadioBackend, metadata_title

STATION = dict(
    stationuuid='11111111-1111-1111-1111-111111111111',
    name='Fixture radio',
    url='https://stream.example.invalid/live',
    url_resolved='https://stream.example.invalid/live',
    country='Vietnam',
    countrycode='VN',
    tags='jazz',
    codec='MP3',
    bitrate=128,
)


def fake_mpv(root):
    path = root / 'mpv'
    path.write_text("""#!/usr/bin/python3
import json,os,pathlib,socket,sys
path=next(arg.split('=',1)[1] for arg in sys.argv if arg.startswith('--input-ipc-server='))
server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(path);server.listen()
pathlib.Path(path+'.pid').write_text(str(os.getpid()))
paused=False
while True:
 connection,_=server.accept()
 with connection:
  request=json.loads(connection.makefile().readline());command=request['command']
  if command==['cycle','pause']:paused=not paused
  values={'metadata':{'icy-title':'Fixture song','artist':'Fixture artist'},'media-title':'Fixture radio','pause':paused,'core-idle':False}
  data=values.get(command[1]) if command[0]=='get_property' else None
  connection.sendall((json.dumps({'request_id':1,'error':'success','data':data})+'\\n').encode())
""")
    path.chmod(0o700)
    return path


class RadioTests(unittest.TestCase):
    def test_genre_normalization_union_duplicate_pagination_and_combinatorial_bound(
        self,
    ):
        api.browse_sessions.clear()
        api.genre_variants.clear()
        rows = [
            dict(name='hiphop', stationcount=100),
            dict(name='hip-hop', stationcount=80),
            dict(name='jazz', stationcount=90),
        ]
        with patch.object(api, 'api_get', return_value=rows):
            genres = api.list_genres()
        self.assertEqual(genres[0]['name'], 'Hip-Hop')
        self.assertEqual(genres[0]['variants'], ['hiphop', 'hip-hop'])
        stations = [
            dict(STATION, stationuuid=str(i), clickcount=100 - i) for i in range(4)
        ]

        def search(query, country, offset, tags):
            values = stations[:3] if tags == ['hiphop'] else stations[1:]
            return dict(
                items=values[offset : offset + 2],
                nextOffset=offset + 2 if offset + 2 < len(values) else -1,
            )

        with (
            patch.object(api, 'PAGE_SIZE', 2),
            patch.object(api, 'station_search', side_effect=search),
        ):
            first = api.browse(dict(tags=['Hip-Hop']))
            second = api.browse(dict(tags=['Hip-Hop'], offset=first['nextOffset']))
        self.assertEqual(
            [row['stationuuid'] for row in first['items'] + second['items']],
            ['0', '1', '2', '3'],
        )
        self.assertEqual(second['nextOffset'], -1)
        api.genre_variants.update(
            {str(i): list(map(str, range(100))) for i in range(12)}
        )
        with self.assertRaisesRegex(api.RadioError, 'fewer genres'):
            api.browse(dict(tags=list(map(str, range(12)))))

    def test_offline_snapshot_favorites_permissions_and_corrupt_records_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = RadioBackend(root / 'config', root / 'data', root / 'cache')
            self.assertEqual(backend.init()['favorites'], [])
            backend.save_settings(
                dict(
                    settings=dict(
                        country='Vietnam',
                        genres=['jazz'],
                        qualities={'fixture': 'uuid'},
                    )
                )
            )
            backend.save_favorites(dict(favorites=[dict(STATION, variants=[STATION])]))
            with patch.object(
                api, 'browse', return_value=dict(items=[STATION], nextOffset=100)
            ):
                backend.cached('browse', {})
            with patch.object(api, 'browse', side_effect=api.RadioError('Offline')):
                saved = backend.cached('browse', {})
                self.assertEqual(saved['nextOffset'], -1)
                self.assertIn('Offline', saved['warning'])
                self.assertEqual(saved['items'][0]['name'], STATION['name'])
            self.assertEqual(backend.init()['settings']['country'], 'Vietnam')
            self.assertEqual(
                backend.init()['favorites'][0]['variants'][0]['bitrate'], 128
            )
            for path in [root / 'config/radio-ui.json', root / 'data/favorites.json']:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            (root / 'data/favorites.json').write_text('invalid')
            with self.assertRaisesRegex(api.RadioError, 'preserved'):
                backend.init()
            self.assertEqual((root / 'data/favorites.json').read_text(), 'invalid')
            with patch.object(api, 'api_get', side_effect=api.RadioError('offline')):
                self.assertEqual(
                    backend.resolve(dict(station=STATION))['url'], STATION['url']
                )
            with patch.object(
                api, 'api_get', return_value={'url': 'file:///etc/passwd'}
            ):
                with self.assertRaisesRegex(api.RadioError, 'HTTP'):
                    backend.resolve(dict(station=STATION))

    def test_real_player_ipc_pause_switch_stop_failure_and_worker_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_mpv(root)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            env = {
                **os.environ,
                'XDG_RUNTIME_DIR': str(runtime),
                'PATH': str(root) + os.pathsep + os.environ['PATH'],
                'XDG_CONFIG_HOME': str(root / 'config'),
                'XDG_DATA_HOME': str(root / 'data'),
                'XDG_CACHE_HOME': str(root / 'cache'),
                'QUICKSHELL_MEDIA_SPACE': 'radio',
                'PYTHONDONTWRITEBYTECODE': '1',
            }
            with patch.dict(os.environ, env):
                backend = RadioBackend(root / 'config', root / 'data', root / 'cache')
                try:
                    backend.start(dict(station=STATION, url=STATION['url']))
                    first = backend.player
                    for _ in range(100):
                        if Path(backend.ipc_path).exists():
                            break
                        time.sleep(0.01)
                    self.assertEqual(
                        backend.status()['title'], 'Fixture artist - Fixture song'
                    )
                    self.assertTrue(backend.handle(dict(op='pause'))['paused'])
                    first_socket = Path(backend.ipc_path)
                    backend.start(dict(station=STATION, url=STATION['url']))
                    self.assertIsNotNone(first.poll())
                    self.assertFalse(first_socket.exists())
                    second = backend.player
                    second.kill()
                    second.wait()
                    self.assertIn('could not be played', backend.status()['error'])
                finally:
                    backend.stop()
            worker = subprocess.Popen(
                [sys.executable, str(support.DESKTOP / 'spaces/radio/backend.py')],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid = None
            child = None
            try:
                worker.stdin.write(
                    json.dumps(
                        dict(id=1, op='start', station=STATION, url=STATION['url'])
                    )
                    + '\n'
                )
                worker.stdin.flush()
                self.assertTrue(
                    json.loads(worker.stdout.readline())['result']['playing']
                )
                for _ in range(100):
                    records = list(runtime.rglob('*.pid'))
                    running = [
                        int(path.read_text())
                        for path in records
                        if Path('/proc/' + path.read_text()).exists()
                    ]
                    if running:
                        pid = running[-1]
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(pid)
                child = Path('/proc') / str(pid)
                worker.terminate()
                worker.wait(timeout=4)
                for _ in range(100):
                    if not child.exists():
                        break
                    time.sleep(0.01)
                self.assertFalse(child.exists(), 'worker close orphaned its player')
                self.assertFalse(
                    list(runtime.rglob('*.sock')), 'worker close left an IPC socket'
                )
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait()
                if child and child.exists():
                    os.kill(pid, signal.SIGKILL)
                worker.stdin.close()
                worker.stdout.close()
                worker.stderr.close()

    def test_metadata_empty_and_non_title_values(self):
        self.assertEqual(metadata_title(None), '')
        self.assertEqual(
            metadata_title({'icy-title': 'Singer - Song', 'artist': 'Singer'}),
            'Singer - Song',
        )
        self.assertEqual(metadata_title({'title': {'unexpected': 'object'}}), '')
