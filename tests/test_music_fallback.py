import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.books.jobs import Cancelled
from spaces.music import backend as music


class MusicFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.song = {
            'id': '1',
            'kind': 'song',
            'title': 'Fixture Song',
            'artist': 'Fixture Artist',
            'album': 'Fixture Album',
            'releaseDate': '2026-01-02',
            'isrc': 'FIXTURE001',
        }
        self.runner = music.CommandRunner(label='Music', timeout=0.5)
        self.addCleanup(self.runner.close)
        for key, value in [
            ('COMMANDS', self.runner),
            ('DATA', self.root / 'data'),
            ('CONFIG', self.root),
            ('_music_config', None),
        ]:
            context = patch.object(music, key, value)
            context.start()
            self.addCleanup(context.stop)
        self.script = self.root / 'provider.py'
        self.script.write_text("""import json,os,sys,time
request=json.load(sys.stdin)
if os.environ.get('WAIT'): time.sleep(5)
if request['op']=='search':
    result={'results':[{'id':'offer','title':'Fixture Song','artist':os.environ.get('ARTIST','Fixture Artist'),'ref':{'opaque':'reference'}}]}
else:
    assert request['ref']=={'opaque':'reference'}
    result={'url':os.environ.get('URL','https://example.test/audio.wav'),'headers':{'X-Source':'backup'}}
print(json.dumps({'success':True,**result}))
""")
        self.backup = {
            'name': 'Backup',
            'command': [sys.executable, str(self.script)],
            'env': {},
            'download': {'track': 'stream', 'album': 'stream'},
        }
        self.primary = {
            'search_url': 'https://example.test/search?q={query}',
            'stream_url': 'https://example.test/audio/{id}',
            'download': {'track': 'stream', 'album': 'stream'},
        }

    def test_failed_http_search_falls_back_to_real_command_and_preserves_headers(self):
        with patch.object(
            music, 'request_json', side_effect=music.MusicError('Endpoint unavailable')
        ) as request:
            result = music.resolve_track(
                self.song, [self.primary, self.backup], local_first=False
            )
        self.assertEqual(request.call_count, 1)
        self.assertEqual(
            result,
            {
                'url': 'https://example.test/audio.wav',
                'headers': {'X-Source': 'backup'},
            },
        )

    def test_command_matching_rejects_another_artist(self):
        self.backup['env']['ARTIST'] = 'Different Artist'
        with self.assertRaisesRegex(music.MusicError, 'confident match'):
            music.resolve_track(self.song, [self.backup], local_first=False)

    def test_timed_out_command_falls_back_to_http_without_exposing_details(self):
        self.backup['env']['WAIT'] = '1'
        with patch.object(
            music,
            'request_json',
            return_value={
                'tracks': [
                    {
                        'trackId': '42',
                        'title': self.song['title'],
                        'artistName': self.song['artist'],
                    },
                ]
            },
        ):
            result = music.resolve_track(
                self.song, [self.backup, self.primary], local_first=False
            )
        self.assertEqual(result['url'], 'https://example.test/audio/42')
        self.assertEqual(self.runner._processes, set())

    def test_plugin_configuration_uses_private_relative_paths_and_stream_capabilities(
        self,
    ):
        plugin = self.root / 'providers' / 'example'
        plugin.mkdir(parents=True)
        (plugin / 'manifest.json').write_text(
            json.dumps(
                {
                    'api_version': 1,
                    'command': [sys.executable, '{plugin_dir}/provider.py'],
                }
            )
        )
        (self.root / 'music.json').write_text(
            json.dumps(
                {
                    'providers': [
                        self.primary | {'timeout': 8},
                        {
                            'name': 'Backup',
                            'plugin': 'providers/example',
                            'download': {'track': 'stream'},
                        },
                    ]
                }
            )
        )
        providers = music.music_config()['providers']
        self.assertEqual(providers[1]['command'][1], str(plugin / 'provider.py'))
        self.assertEqual(music.download_providers('track'), providers)
        self.assertEqual(music.download_providers('album'), providers[:1])

    def test_file_write_errors_and_cancellation_do_not_try_another_source(self):
        for error in (OSError('Disk unavailable'), Cancelled('Cancelled')):
            with (
                self.subTest(error=type(error).__name__),
                patch.object(music, 'save_stream_track', side_effect=error) as save,
            ):
                with self.assertRaises(type(error)):
                    music.save_track_with_fallback(
                        self.song, [self.primary, self.backup], self.root
                    )
                self.assertEqual(save.call_count, 1)

    def test_album_retries_only_the_failed_song_and_preserves_provider_order(self):
        tracks = [self.song | {'id': '1'}, self.song | {'id': '2'}]
        with (
            patch.object(
                music, 'album_details', return_value={'album': {'id': 'album'}}
            ),
            patch.object(music, 'tracks_for_album', return_value=tracks),
            patch.object(
                music,
                'save_stream_track',
                side_effect=[
                    '/tmp/first.flac',
                    music.MusicError('Source failed'),
                    '/tmp/second.flac',
                ],
            ) as save,
            patch.dict(os.environ, {'XDG_MUSIC_DIR': str(self.root / 'Music')}),
        ):
            result = music.save_stream_download(
                'album', {'id': 'album'}, [self.primary, self.backup]
            )
        self.assertEqual((result['saved'], result['failed']), (2, 0))
        self.assertEqual(
            [(call.args[0]['id'], call.args[1]) for call in save.call_args_list],
            [
                ('1', self.primary),
                ('2', self.primary),
                ('2', self.backup),
            ],
        )

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_unreadable_primary_audio_falls_back_and_publishes_one_tagged_file(self):
        source = self.root / 'source.wav'
        with wave.open(str(source), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\0\0' * 800)
        (self.root / 'broken').write_bytes(b'not audio')

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith('/search?'):
                    body = json.dumps(
                        {
                            'tracks': [
                                {
                                    'trackId': 'broken',
                                    'title': 'Fixture Song',
                                    'artistName': 'Fixture Artist',
                                }
                            ]
                        }
                    ).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if (
                    self.path == '/source.wav'
                    and self.headers.get('X-Source') != 'backup'
                ):
                    self.send_error(403)
                    return
                super().do_GET()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(
            ('127.0.0.1', 0), partial(Handler, directory=str(self.root))
        )
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        self.primary.update(
            search_url=base + '/search?q={query}', stream_url=base + '/{id}'
        )
        self.backup['env']['URL'] = base + '/source.wav'
        destination = self.root / 'Music'
        with (
            patch.object(
                music,
                'music_config',
                return_value={'providers': [self.primary, self.backup]},
            ),
            patch.dict(os.environ, {'XDG_MUSIC_DIR': str(destination)}),
        ):
            result = music.open_download({'kind': 'track', 'item': self.song})
        self.assertEqual(result['saved'], 1)
        self.assertEqual(list(destination.glob('.music-*')), [])
        self.assertEqual(len(list(destination.glob('*.flac'))), 1)
        probe = music.subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format_tags=title,artist,album,date',
                '-of',
                'json',
                result['path'],
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            json.loads(probe.stdout)['format']['tags']['title'], self.song['title']
        )


if __name__ == '__main__':
    unittest.main()
