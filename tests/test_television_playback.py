"""Real HLS decode/IPC with inherited mpv configuration and null audio/video outputs."""

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.television.catalogue import stream_record
from spaces.television.player import Player


@unittest.skipUnless(
    shutil.which('mpv') and shutil.which('ffmpeg'), 'mpv and ffmpeg are required'
)
class TelevisionPlaybackTests(unittest.TestCase):
    def test_real_hls_respects_mpv_configuration_and_supports_pause_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'runtime'
            runtime.mkdir(mode=0o700)
            config = root / 'config/mpv'
            config.mkdir(parents=True)
            (config / 'mpv.conf').write_text(
                'vo=null\nao=null\nvolume=37\nload-scripts=no\nosc=no\n'
            )
            created = subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'testsrc2=size=320x180:rate=15',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=r=44100:cl=mono',
                    '-t',
                    '10',
                    '-c:v',
                    'libx264',
                    '-preset',
                    'ultrafast',
                    '-g',
                    '30',
                    '-c:a',
                    'aac',
                    '-f',
                    'hls',
                    '-hls_time',
                    '2',
                    '-hls_list_size',
                    '0',
                    str(root / 'fixture.m3u8'),
                ],
                capture_output=True,
                timeout=15,
            )
            self.assertEqual(created.returncode, 0, created.stderr.decode())

            class Handler(SimpleHTTPRequestHandler):
                def log_message(self, *_):
                    pass

            server = ThreadingHTTPServer(
                ('127.0.0.1', 0), functools.partial(Handler, directory=str(root))
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            player = Player()
            try:
                with patch.dict(
                    os.environ,
                    XDG_CONFIG_HOME=str(root / 'config'),
                    XDG_RUNTIME_DIR=str(runtime),
                ):
                    stream = stream_record(
                        dict(
                            url=f'http://127.0.0.1:{server.server_port}/fixture.m3u8',
                            quality='180p',
                        )
                    )
                    player.start(
                        dict(id='Fixture.us', name='Fixture television'), stream
                    )
                    params = None
                    for _ in range(120):
                        params = player.ipc.property(player.path, 'video-params')
                        if isinstance(params, dict) and params.get('w') == 320:
                            break
                        if player.process.poll() is not None:
                            break
                        time.sleep(0.04)
                    self.assertIsInstance(
                        params, dict, 'Real mpv did not decode the HLS fixture'
                    )
                    self.assertEqual(params['w'], 320)
                    self.assertEqual(
                        player.ipc.property(player.path, 'volume'),
                        37,
                        'Television bypassed the normal mpv config',
                    )
                    self.assertTrue(player.pause()['paused'])
                    self.assertFalse(player.pause()['paused'])
                    process = player.process
                    socket = Path(player.path)
                    player.stop()
                    self.assertIsNotNone(process.poll())
                    self.assertFalse(socket.exists())
            finally:
                player.stop()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
