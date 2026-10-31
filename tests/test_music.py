import json
import os
import shutil
import tempfile
import unittest
import wave
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import sys
import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.music import backend as music
from spaces.music.records import clean_duration


class MusicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'config'
        self.data = Path(self.tmp.name) / 'data'
        for key, value in (
            ('CONFIG', self.config),
            ('DATA', self.data),
            ('_music_config', None),
        ):
            context = patch.object(music, key, value)
            context.start()
            self.addCleanup(context.stop)

    def test_discovery_playlist_continues_past_500_and_genre_filter_preserves_cursor(
        self,
    ):
        with (
            patch.object(
                music, 'music_config', return_value={'default_playlist': 'pl.fixture'}
            ),
            patch.object(
                music,
                'playlist_page',
                return_value=(
                    [{'id': '1', 'kind': 'song', 'genreNames': ['Rock']}],
                    25,
                    '/next',
                ),
            ) as page,
        ):
            result = music.search_page(
                {
                    'offset': 500,
                    'category': 'songs',
                    'genreId': '21',
                    'genreName': 'Rock',
                }
            )
            self.assertTrue(result['hasMore'])
            self.assertEqual(result['limit'], 525)
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(page.call_args.args[1], 500)

    def test_matching_preserves_non_latin_titles_and_artists(self):
        wanted = {'title': '千本桜', 'artist': '初音ミク'}
        self.assertEqual(music.score_candidate(wanted, dict(wanted)), 180)
        self.assertEqual(
            music.score_candidate(
                wanted, {'title': '別の曲', 'artist': wanted['artist']}
            ),
            0,
        )

    def test_duration_units_preserve_long_song_lyrics_and_short_catalogue_tracks(self):
        from urllib.parse import parse_qs, urlsplit

        url = music.audio_lyrics.provider_url(
            {}, dict(title='Long track', artist='Artist', duration=1800)
        )
        self.assertEqual(parse_qs(urlsplit(url).query)['duration'], ['1800'])
        song = music.normalize_apple(
            dict(id='1', attributes={'durationInMillis': 1000}), 'songs'
        )
        self.assertEqual(song['duration'], 1)
        self.assertEqual(clean_duration(float('nan')), 0)

    def test_title_only_provider_search_still_requires_confident_artist_match(self):
        wanted = {
            'kind': 'song',
            'id': '1',
            'artist': 'Radiohead',
            'title': 'Everything in Its Right Place',
        }
        provider = {
            'search_url': 'https://fixture.invalid/search',
            'stream_url': 'https://fixture.invalid/{id}',
        }
        wrong = {'id': '2', 'artist': 'Other artist', 'title': wanted['title']}
        right = {'id': '3', 'artist': 'Radiohead', 'title': wanted['title']}
        with patch.object(
            music, 'provider_results', side_effect=[[], [wrong, right]]
        ) as search:
            resolved = music.resolve_track(
                wanted, providers=[provider], local_first=False
            )
            self.assertEqual(resolved['url'], 'https://fixture.invalid/3')
            self.assertEqual(search.call_args.args[2], wanted['title'])
        with patch.object(music, 'provider_results', side_effect=[[], [wrong]]):
            with self.assertRaisesRegex(music.MusicError, 'confident match'):
                music.resolve_track(wanted, providers=[provider], local_first=False)

    def test_download_capabilities_are_independent(self):
        cases = (
            ({}, {'track': False, 'album': False}),
            (
                {'track': 'https://example.test/tracks/{id}'},
                {'track': True, 'album': False},
            ),
            (
                {'album': 'https://example.test/albums/{id}'},
                {'track': False, 'album': True},
            ),
            (
                {
                    'track': 'https://example.test/tracks/{id}',
                    'album': 'https://example.test/albums/{id}',
                },
                {'track': True, 'album': True},
            ),
        )
        for download, expected in cases:
            with (
                self.subTest(download=download),
                patch.object(
                    music,
                    'music_config',
                    return_value={'providers': [{'download': download}]},
                ),
            ):
                self.assertEqual(music.download_capabilities(), expected)

        with patch.object(
            music,
            'music_config',
            return_value={
                'providers': [
                    {
                        'search_url': 'https://example.test/search',
                        'stream_url': 'https://example.test/{id}',
                        'download': {'track': 'stream'},
                    },
                    {
                        'search_url': 'https://example.test/search',
                        'stream_url': 'https://example.test/{id}',
                        'download': {'album': 'stream'},
                    },
                ]
            },
        ):
            self.assertEqual(
                music.download_capabilities(), {'track': True, 'album': True}
            )
            self.assertEqual(
                music.download_provider('album')['download'], {'album': 'stream'}
            )

    def test_download_templates_expand_catalog_metadata(self):
        provider = {
            'base_url': 'https://example.test',
            'download': {
                'track': '{base_url}/tracks/{id}?artist={artist}&title={title}&isrc={isrc}',
                'album': '{base_url}/albums/{album_id}?name={title}',
            },
        }
        with patch.object(
            music, 'music_config', return_value={'providers': [provider]}
        ):
            self.assertEqual(
                music.download_url(
                    'track',
                    {
                        'id': 'song/42',
                        'title': 'Blue & Gold',
                        'artist': 'A/B',
                        'isrc': 'US123',
                    },
                ),
                'https://example.test/tracks/song%2F42?artist=A%2FB&title=Blue%20%26%20Gold&isrc=US123',
            )
            self.assertEqual(
                music.download_url('album', {'id': 'album 7', 'title': 'Blue & Gold'}),
                'https://example.test/albums/album%207?name=Blue%20%26%20Gold',
            )

    def test_download_template_errors_do_not_expose_url(self):
        for template, item in (
            ('https://example.test/{isrc}', {'id': '1', 'title': 'Song'}),
            ('https://example.test/{unexpected}', {'id': '1'}),
            ('file:///tmp/{id}', {'id': '1'}),
            ('https://example.test:bad/{id}', {'id': '1'}),
        ):
            with (
                self.subTest(template=template),
                patch.object(
                    music,
                    'music_config',
                    return_value={'providers': [{'download': {'track': template}}]},
                ),
            ):
                with self.assertRaises(music.MusicError) as error:
                    music.download_url('track', item)
                self.assertNotIn('example.test', str(error.exception))

        with patch.object(
            music,
            'music_config',
            return_value={
                'providers': [{'download': {'album': 'https://example.test/{id}'}}]
            },
        ):
            with self.assertRaisesRegex(music.MusicError, 'missing'):
                music.download_url(
                    'album', {'id': 'name:unknown album', 'title': 'Unknown Album'}
                )

    def test_existing_provider_config_remains_valid(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'music' / 'music.json'
            path.parent.mkdir()
            path.write_text(
                json.dumps(
                    {
                        'providers': [
                            {
                                'search_url': 'https://example.test/search',
                                'stream_url': 'https://example.test/{id}',
                            }
                        ]
                    }
                )
            )
            with (
                patch.object(music, 'CONFIG', path.parent),
                patch.object(music, '_music_config', None),
            ):
                self.assertEqual(
                    music.download_capabilities(), {'track': False, 'album': False}
                )

    def test_stream_download_requires_search_and_stream_templates(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'music' / 'music.json'
            path.parent.mkdir()
            path.write_text(
                json.dumps({'providers': [{'download': {'track': 'stream'}}]})
            )
            with (
                patch.object(music, 'CONFIG', path.parent),
                patch.object(music, '_music_config', None),
            ):
                with self.assertRaisesRegex(
                    music.MusicError, 'search_url and stream_url'
                ):
                    music.music_config()

    @unittest.skipUnless(
        shutil.which('ffmpeg'), 'ffmpeg is needed for the stream save test'
    )
    def test_stream_download_copies_audio_to_music(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'source.wav'
            with wave.open(str(source), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b'\0\0' * 800)
            destination = Path(root) / 'Music'

            class QuietHandler(SimpleHTTPRequestHandler):
                def do_GET(self):
                    if self.headers.get('X-Music-Test') != 'ok':
                        self.send_error(403)
                        return
                    super().do_GET()

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(
                ('127.0.0.1', 0), partial(QuietHandler, directory=root)
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            provider = {
                'download': {'track': 'stream'},
                'headers': {'X-Music-Test': 'ok'},
            }
            song = {
                'kind': 'song',
                'id': '42',
                'artist': 'A/B',
                'title': 'Blue & Gold',
                'album': 'Test Album',
                'releaseDate': '2020-07-03',
            }
            with (
                patch.object(
                    music, 'music_config', return_value={'providers': [provider]}
                ),
                patch.object(
                    music,
                    'resolve_track',
                    return_value={
                        'url': f'http://127.0.0.1:{server.server_port}/source.wav',
                        'headers': {},
                    },
                ) as resolve,
                patch.dict(os.environ, {'XDG_MUSIC_DIR': str(destination)}),
            ):
                result = music.open_download({'kind': 'track', 'item': song})
                second = music.open_download({'kind': 'track', 'item': song})
            self.assertEqual(result['saved'], 1)
            self.assertEqual(second['saved'], 1)
            self.assertEqual(
                Path(result['path']).name,
                'Blue & Gold - A B - Test Album (2020-07-03).flac',
            )
            self.assertEqual(
                Path(second['path']).name,
                'Blue & Gold - A B - Test Album (2020-07-03) (2).flac',
            )
            self.assertEqual(Path(result['path']).parent, destination)
            self.assertGreater(Path(result['path']).stat().st_size, 0)
            self.assertEqual(list(destination.glob('.music-*')), [])
            self.assertEqual(
                resolve.call_args.kwargs,
                {'providers': [provider], 'local_first': False},
            )

    def test_stream_download_needs_full_release_date(self):
        provider = {'download': {'track': 'stream'}}
        song = {
            'kind': 'song',
            'id': '42',
            'title': 'Blue & Gold',
            'artist': 'A/B',
            'album': 'Test Album',
            'releaseDate': '2020',
        }
        with patch.object(music, 'resolve_track') as resolve:
            with self.assertRaisesRegex(music.MusicError, 'full release date'):
                music.save_stream_track(song, provider, Path('/unused'))
        resolve.assert_not_called()

    def test_album_stream_download_reports_partial_results(self):
        provider = {'download': {'album': 'stream'}}
        tracks = [{'id': '1', 'title': 'First'}, {'id': '2', 'title': 'Second'}]
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(
                music,
                'album_details',
                return_value={
                    'album': {'id': '7', 'artist': 'Artist', 'title': 'Album'},
                    'songs': tracks,
                },
            ),
            patch.object(music, 'tracks_for_album', return_value=tracks) as pages,
            patch.object(
                music,
                'save_stream_track',
                side_effect=['/tmp/first.mka', music.MusicError('Failed')],
            ) as save,
            patch.dict(os.environ, {'XDG_MUSIC_DIR': str(Path(root) / 'Music')}),
        ):
            result = music.save_stream_download('album', {'id': '7'}, provider)
        self.assertEqual((result['saved'], result['failed']), (1, 1))
        self.assertEqual(result['path'], str(Path(root) / 'Music'))
        self.assertEqual(
            [call.args[2] for call in save.call_args_list], [Path(root) / 'Music'] * 2
        )
        pages.assert_called_once_with(
            {'id': '7', 'artist': 'Artist', 'title': 'Album'}, all_pages=True
        )

    def test_album_download_reads_later_track_pages(self):
        def page(path, params):
            self.assertEqual(path, '/albums/7/tracks')
            if params['offset'] == 0:
                return {
                    'data': [
                        {
                            'id': '1',
                            'attributes': {'name': 'First', 'artistName': 'Artist'},
                        }
                    ],
                    'next': '/more',
                }
            return {
                'data': [
                    {
                        'id': '2',
                        'attributes': {'name': 'Second', 'artistName': 'Artist'},
                    }
                ]
            }

        with patch.object(music, 'apple_url', side_effect=page) as request:
            self.assertEqual(
                len(music.tracks_for_album({'id': '7'}, all_pages=True)), 2
            )
        self.assertEqual(request.call_count, 2)

    def test_download_open_failure_uses_music_error(self):
        with (
            patch.object(
                music,
                'music_config',
                return_value={
                    'providers': [{'download': {'album': 'https://example.test/{id}'}}]
                },
            ),
            patch.object(music.subprocess, 'Popen', side_effect=OSError('missing')),
        ):
            with self.assertRaisesRegex(music.MusicError, 'Could not open'):
                music.open_download({'kind': 'album', 'item': {'id': '7'}})

    def test_artist_selection_does_not_fetch_every_album_tracklist(self):
        calls = []

        def apple(path, params=None):
            calls.append(path)
            if path.endswith('/albums'):
                return {
                    'data': [
                        {
                            'id': str(n),
                            'type': 'albums',
                            'attributes': {'name': 'Album ' + str(n)},
                        }
                        for n in range(25)
                    ],
                    'next': '/next',
                }
            if path.endswith('/view/top-songs'):
                return {'data': []}
            return {
                'data': [
                    {'id': '123', 'type': 'artists', 'attributes': {'name': 'Artist'}}
                ]
            }

        with patch.object(music, 'apple_url', side_effect=apple):
            result = music.artist_details({'id': '123', 'source': 'apple'})
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(result['albums']), 25)
        self.assertTrue(result['albumPaging']['hasMore'])
        self.assertFalse(any('/tracks' in path for path in calls))

    def test_more_artist_albums_does_not_load_tracks(self):
        with (
            patch.object(
                music,
                'apple_artist_albums',
                return_value={'items': [], 'offset': 50, 'hasMore': True},
            ),
            patch.object(
                music,
                'tracks_for_album',
                side_effect=AssertionError('Unnecessary track request'),
            ),
        ):
            self.assertEqual(
                music.artist_albums_page({'artistId': '123', 'offset': 25})['offset'],
                50,
            )

    def test_artist_songs_continue_through_album_tracks_after_top_songs(self):
        album = {'id': '456', 'title': 'Album', 'cover': ''}
        song = {'kind': 'song', 'id': '789', 'title': 'Another song'}
        with (
            patch.object(
                music, 'apple_artist_song_cursor', return_value={'data': [], 'next': ''}
            ),
            patch.object(
                music,
                'apple_artist_albums',
                return_value={'items': [album], 'offset': 1, 'hasMore': False},
            ) as albums,
            patch.object(music, 'tracks_for_album', return_value=[song]),
        ):
            top = music.artist_songs_page(
                {
                    'artistId': '123',
                    'cursor': '/v1/catalog/us/artists/123/view/top-songs?offset=25',
                }
            )
            self.assertTrue(top['hasMore'])
            page = music.artist_songs_page({'artistId': '123', 'albumOffset': 0})
        self.assertEqual(page['items'], [song])
        self.assertFalse(page['hasMore'])
        albums.assert_called_once_with('123', offset=0, limit=2)

    def test_artist_song_cursor_rejects_other_hosts_and_artists(self):
        with patch.object(music, 'music_config', return_value={'storefront': 'us'}):
            for cursor in (
                'https://other.example/v1/catalog/us/artists/123/view/top-songs',
                '/v1/catalog/us/artists/999/view/top-songs',
            ):
                with self.assertRaises(music.MusicError):
                    music.apple_artist_song_cursor('123', cursor)


class MusicWorkerCloseTests(unittest.TestCase):
    def test_close_cancels_running_transfer_removes_partials_and_reaps_converter(self):
        import signal
        import subprocess
        import time

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / 'config/quickshell/desktop/spaces/music'
            config.mkdir(parents=True)
            (config / 'music.json').write_text(
                json.dumps(
                    {
                        'providers': [
                            {
                                'search_url': 'https://fixture.invalid/search',
                                'stream_url': 'https://fixture.invalid/{id}',
                                'download': {'track': 'stream'},
                            }
                        ]
                    }
                )
            )
            executable = root / 'ffmpeg'
            executable.write_text(
                '#!/usr/bin/env python3\nimport os,sys,time\nfrom pathlib import Path\nPath(sys.argv[-1]).write_bytes(b"partial")\nPath(os.environ["MUSIC_CONVERTER_PID"]).write_text(str(os.getpid()))\ntime.sleep(60)\n'
            )
            executable.chmod(0o700)
            worker = root / 'backend.py'
            source = (support.DESKTOP / 'spaces/music/backend.py').read_text()
            source = source.replace(
                '\ndef main():',
                '\ndef resolve_track(*args, **kwargs):\n    return {"url":"https://fixture.invalid/audio", "headers":{}}\n\ndef main():',
            )
            worker.write_text(source)
            env = {
                **os.environ,
                'PYTHONPATH': os.pathsep.join(
                    (str(support.DESKTOP), str(support.AUDIO_LIB))
                ),
                'PATH': str(root) + os.pathsep + os.environ['PATH'],
                'QUICKSHELL_MEDIA_SPACE': 'music',
                'XDG_CONFIG_HOME': str(root / 'config'),
                'XDG_DATA_HOME': str(root / 'data'),
                'XDG_CACHE_HOME': str(root / 'cache'),
                'XDG_RUNTIME_DIR': str(root / 'runtime'),
                'XDG_MUSIC_DIR': str(root / 'Music'),
                'MUSIC_CONVERTER_PID': str(root / 'converter.pid'),
            }
            process = subprocess.Popen(
                [sys.executable, '-u', str(worker)],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            try:
                process.stdin.write(
                    json.dumps(
                        {
                            'id': 1,
                            'op': 'download_start',
                            'kind': 'track',
                            'item': {
                                'id': '1',
                                'kind': 'song',
                                'title': 'Track',
                                'artist': 'Artist',
                                'album': 'Album',
                                'releaseDate': '2020-01-01',
                            },
                        }
                    )
                    + '\n'
                )
                process.stdin.flush()
                reply = json.loads(process.stdout.readline())
                self.assertIn('job_id', reply['result'])
                deadline = time.monotonic() + 5
                while (
                    not (root / 'converter.pid').exists()
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                self.assertTrue(
                    (root / 'converter.pid').exists(), 'converter did not start'
                )
                converter = int((root / 'converter.pid').read_text())
                self.assertTrue(list((root / 'Music').glob('.music-*')))
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=5)
                self.assertEqual(list((root / 'Music').glob('.music-*')), [])
                stat = Path(f'/proc/{converter}/stat')
                self.assertTrue(
                    not stat.exists() or stat.read_text().split()[2] == 'Z',
                    'converter survived worker close',
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdin.close()
                process.stdout.close()
