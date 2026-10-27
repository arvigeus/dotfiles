"""Lyrics drafts cache independently of tags; thumbnails never expose credentials or alter audio."""

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.music import backend, local_files
from spaces.music.cache import JsonCache
from spaces.music.cloud import CloudLibrary


class LyricsCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = JsonCache('lyrics', self.tmp.name)
        self.song = dict(
            id='one',
            title='Fixture title',
            artist='Fixture artist',
            album='Album',
            duration=120,
        )
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch.object(backend, 'lyrics_cache', return_value=self.cache)
        )
        self.stack.enter_context(
            patch.object(
                backend.audio_lyrics,
                'read_config',
                return_value=[
                    {
                        'name': 'Fixture',
                        'base_url': 'https://lyrics.example/api',
                        'headers': {'Authorization': 'fixture-private-token'},
                    }
                ],
            )
        )

    def test_embedded_lyrics_never_contact_provider(self):
        with patch.object(
            backend.audio_lyrics,
            'request_json',
            side_effect=AssertionError('Already saved lyrics must not be looked up'),
        ):
            self.assertEqual(
                backend.fetch_lyrics({'song': self.song | {'lyrics': 'Already saved'}})[
                    'lyrics'
                ],
                'Already saved',
            )

    def test_unsaved_lyrics_are_reused_across_ids_and_worker_restarts(self):
        with patch.object(
            backend.audio_lyrics,
            'request_json',
            return_value={'plainLyrics': 'Found lyrics'},
        ) as request:
            self.assertEqual(
                backend.fetch_lyrics({'song': self.song})['lyrics'], 'Found lyrics'
            )
            with patch.object(
                backend, 'lyrics_cache', return_value=JsonCache('lyrics', self.tmp.name)
            ):
                self.assertEqual(
                    backend.fetch_lyrics({'song': self.song | {'id': 'another'}})[
                        'lyrics'
                    ],
                    'Found lyrics',
                )
            self.assertEqual(request.call_count, 1)
        with self.cache.path.open('rb') as stream:
            self.assertNotIn(b'fixture-private-token', stream.read())

    def test_no_match_is_cached_but_explicit_retry_bypasses_it(self):
        with patch.object(
            backend.audio_lyrics,
            'request_json',
            side_effect=[{}, {'plainLyrics': 'Now available'}],
        ) as request:
            self.assertFalse(backend.fetch_lyrics({'song': self.song})['available'])
            self.assertFalse(backend.fetch_lyrics({'song': self.song})['available'])
            self.assertEqual(request.call_count, 1)
            self.assertEqual(
                backend.fetch_lyrics({'song': self.song, 'refresh': True})['lyrics'],
                'Now available',
            )

    def test_failed_provider_does_not_poison_cache(self):
        with patch.object(
            backend.audio_lyrics,
            'request_json',
            side_effect=[
                backend.audio_lyrics.LyricsError('Offline'),
                {'plainLyrics': 'Recovered'},
            ],
        ):
            with self.assertRaises(backend.MusicError):
                backend.fetch_lyrics({'song': self.song})
            self.assertEqual(
                backend.fetch_lyrics({'song': self.song})['lyrics'], 'Recovered'
            )


class MusicCoverTests(unittest.TestCase):
    def test_server_artwork_uses_authenticated_transport_and_reuses_album_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            client = MagicMock()
            client.account_id = 'fixture-account'
            client.request.return_value = {'song': {'coverArt': 'album-12'}}
            reply = BytesIO(b'fixture-image')
            reply.headers = {'Content-Type': 'image/jpeg'}
            client.open.return_value = reply
            library = CloudLibrary(client, Path(directory) / 'cache')
            song = dict(
                id='song-1',
                kind='song',
                source='nextcloud',
                account='fixture-account',
                albumId='album-12',
            )
            first = library.cover(song)
            second = library.cover(song | {'id': 'song-2'})
            self.assertEqual(first, second)
            self.assertEqual(client.open.call_count, 1)
            client.open.assert_called_once_with(
                'getCoverArt', {'id': 'album-12', 'size': 128}
            )
            self.assertNotIn('https:', first)
            self.assertEqual(
                Path(first.removeprefix('file://')).read_bytes(), b'fixture-image'
            )
            with self.assertRaises(ValueError):
                library.cover(song | {'account': 'wrong-account'})

    def test_embedded_cover_is_cached_without_changing_the_song(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music = root / 'Music'
            music.mkdir()
            art = root / 'cover.jpg'
            song = music / 'song.mp3'
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'color=c=red:s=64x64',
                    '-frames:v',
                    '1',
                    str(art),
                ],
                check=True,
            )
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc',
                    '-i',
                    str(art),
                    '-t',
                    '0.1',
                    '-map',
                    '0:a',
                    '-map',
                    '1:v',
                    '-c:v',
                    'copy',
                    '-disposition:v',
                    'attached_pic',
                    str(song),
                ],
                check=True,
            )
            before = song.read_bytes()
            item = dict(
                id='local:song.mp3',
                source='music-local',
                account='fixture',
                serverPath='/song.mp3',
            )
            with (
                patch.object(local_files, 'ROOT', music),
                patch.object(local_files, 'account_id', return_value='fixture'),
                patch.dict('os.environ', {'XDG_CACHE_HOME': str(root / 'cache')}),
            ):
                first = local_files.cover(item)
                self.assertTrue(first.startswith('file://'))
                with patch.object(
                    local_files,
                    'run',
                    side_effect=AssertionError(
                        'Cached cover must not be extracted again'
                    ),
                ):
                    self.assertEqual(first, local_files.cover(item))
            self.assertEqual(song.read_bytes(), before)


class MetadataEditingTests(unittest.TestCase):
    def test_cover_replacement_preserves_audio_and_existing_tags_in_supported_formats(
        self,
    ):
        from spaces.music import tags

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            images = []
            for color in ('red', 'blue'):
                image = root / (color + ' cover.png')
                subprocess.run(
                    [
                        'ffmpeg',
                        '-v',
                        'error',
                        '-f',
                        'lavfi',
                        '-i',
                        'color=c=' + color + ':s=64x64',
                        '-frames:v',
                        '1',
                        str(image),
                    ],
                    check=True,
                )
                images.append(image)
            for extension in ('mp3', 'flac', 'm4a'):
                with self.subTest(extension=extension):
                    song = root / ('song.' + extension)
                    subprocess.run(
                        [
                            'ffmpeg',
                            '-v',
                            'error',
                            '-f',
                            'lavfi',
                            '-i',
                            'anullsrc',
                            '-t',
                            '0.1',
                            '-metadata',
                            'title=Original',
                            str(song),
                        ],
                        check=True,
                    )

                    def audio_hash():
                        return subprocess.check_output(
                            [
                                'ffmpeg',
                                '-v',
                                'error',
                                '-i',
                                str(song),
                                '-map',
                                '0:a:0',
                                '-f',
                                'hash',
                                '-hash',
                                'sha256',
                                '-',
                            ]
                        )

                    before = audio_hash()
                    for image in images:
                        tags.write(
                            song,
                            {},
                            local_files.run,
                            local_files.signature,
                            local_files.register,
                            local_files.unregister,
                            artwork=image.as_uri(),
                        )
                        details = tags.read(song, local_files.run)
                        self.assertEqual(len(details['coverIndexes']), 1)
                        self.assertEqual(details['tags']['title'], 'Original')
                        self.assertEqual(audio_hash(), before)

    def test_file_summary_uses_real_bit_depth_and_rate(self):
        from spaces.music import tags

        with tempfile.TemporaryDirectory() as directory:
            song = Path(directory) / 'high-res.flac'
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc=r=96000',
                    '-t',
                    '0.1',
                    '-sample_fmt',
                    's32',
                    str(song),
                ],
                check=True,
            )
            details = tags.read(song, local_files.run)
            self.assertIn('FLAC', details['fileInfo'])
            self.assertIn('24-bit', details['fileInfo'])
            self.assertIn('96 kHz', details['fileInfo'])

    def test_invalid_cover_leaves_the_original_song_untouched(self):
        from spaces.music import tags

        with tempfile.TemporaryDirectory() as directory:
            song = Path(directory) / 'song.flac'
            bad = Path(directory) / 'not-an-image.png'
            bad.write_text('Not an image')
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc',
                    '-t',
                    '0.1',
                    str(song),
                ],
                check=True,
            )
            before = song.read_bytes()
            with self.assertRaises(backend.MusicError):
                tags.write(
                    song,
                    {},
                    local_files.run,
                    local_files.signature,
                    local_files.register,
                    local_files.unregister,
                    artwork=bad.as_uri(),
                )
            self.assertEqual(song.read_bytes(), before)


class StoredLyricsTests(unittest.TestCase):
    def test_server_information_reads_metadata_only_and_preserves_missing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = MagicMock()
            client.account_id = 'fixture'
            client.request.return_value = {
                'song': {
                    'id': 'one',
                    'title': 'Server title',
                    'artist': 'Artist',
                    'album': 'Album',
                    'path': '/Artist/song.flac',
                    'composer': 'Composer',
                    'track': 3,
                }
            }
            library = CloudLibrary(client, root / 'cache')
            song = dict(
                id='one',
                source='nextcloud',
                kind='song',
                account='fixture',
                serverPath='/Artist/song.flac',
            )
            with (
                patch.object(local_files, 'DATA', root / 'data'),
                patch.object(
                    local_files,
                    'cached',
                    side_effect=backend.MusicError(
                        'rclone configuration is unavailable'
                    ),
                ),
                patch.object(
                    local_files,
                    'download',
                    side_effect=AssertionError('Preview must not download audio'),
                ),
                patch('spaces.music.cloud.CloudLibrary', return_value=library),
            ):
                result = backend.song_information({'song': song})
            self.assertEqual(result['tags']['composer'], 'Composer')
            self.assertEqual(result['tags']['comment'], '')
            self.assertEqual(result['relativePath'], 'Artist/song.flac')
            client.request.assert_called_once_with('getSong', id='one')
            client.open.assert_not_called()

    def test_server_lyrics_use_song_identity_without_downloading_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            client = MagicMock()
            client.account_id = 'fixture'
            client.request.return_value = {
                'lyricsList': {
                    'structuredLyrics': [
                        {
                            'synced': False,
                            'line': [
                                {'value': 'Saved line one'},
                                {'value': 'Saved line two'},
                            ],
                        }
                    ]
                }
            }
            library = CloudLibrary(client, Path(directory) / 'cache')
            song = dict(
                id='track-7',
                source='nextcloud',
                account='fixture',
                artist='Artist',
                title='Title',
            )
            with (
                patch('spaces.music.cloud.CloudLibrary', return_value=library),
                patch.object(
                    local_files,
                    'download',
                    side_effect=AssertionError('Lyrics must not download audio'),
                ),
                patch.object(
                    backend.audio_lyrics,
                    'request_json',
                    side_effect=AssertionError(
                        'Saved lyrics must skip internet lookup'
                    ),
                ),
            ):
                result = backend.fetch_lyrics({'song': song})
            self.assertTrue(result['saved'])
            self.assertEqual(result['lyrics'], 'Saved line one\nSaved line two')
            client.request.assert_called_once_with('getLyricsBySongId', id='track-7')

    def test_cached_file_lyrics_take_precedence_without_cloud_or_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            song = root / 'saved.flac'
            subprocess.run(
                [
                    'ffmpeg',
                    '-v',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'anullsrc',
                    '-t',
                    '0.1',
                    '-metadata',
                    'lyrics=Saved local lyrics',
                    str(song),
                ],
                check=True,
            )
            item = dict(
                id='local:saved.flac',
                source='music-local',
                account='fixture',
                serverPath='/saved.flac',
                localPath=str(song),
                title='Song',
                artist='Artist',
            )
            with (
                patch.object(local_files, 'ROOT', root),
                patch.object(local_files, 'account_id', return_value='fixture'),
                patch.object(
                    local_files,
                    'download',
                    side_effect=AssertionError('No download permitted'),
                ),
                patch(
                    'spaces.music.cloud.CloudLibrary',
                    side_effect=AssertionError('No cloud read needed'),
                ),
            ):
                result = backend.fetch_lyrics({'song': item})
            self.assertTrue(result['saved'])
            self.assertEqual(result['lyrics'], 'Saved local lyrics')
            self.assertIn('FLAC', result['fileInfo'])
