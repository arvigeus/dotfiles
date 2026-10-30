"""Streaming identity boundaries, analysis, owned jobs and media."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.streaming.backend import StreamingBackend
from spaces.streaming.downloads import AUDIO_FORMAT
from spaces.streaming import insights
from spaces.streaming.storage import StreamingError
from spaces.streaming.youtube import (
    Commands,
    channel_url,
    command_error,
    record,
    video_id,
    watch_url,
)
from test_radio import fake_mpv

RAW = dict(
    id='aqz-KE-bpKQ',
    title='A / useful video',
    channel='Fixture creator',
    uploader='Fixture artist',
    channel_url='https://www.youtube.com/@fixture',
    duration=125,
    upload_date='20261027',
    description='Fixture description',
    chapters=[
        dict(title='Beginning', start_time=0),
        dict(title='Topic', start_time=60),
    ],
)
VIDEO = record(RAW)


def wait_job(backend, job_id, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = backend.jobs.snapshots()['jobs']
        job = next(j for j in jobs if j['job_id'] == job_id)
        if job['state'] not in ('queued', 'running'):
            return job
        time.sleep(0.03)
    raise AssertionError('Job did not settle')


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backend = StreamingBackend(
            self.root / 'config/spaces/streaming',
            self.root / 'data',
            self.root / 'cache',
            self.root / 'Music',
            self.root / 'Videos',
        )
        self.addCleanup(self.backend.close)
        self.backend.commands.details = Mock(return_value=copy.deepcopy(VIDEO))

    def test_youtube_url_boundaries_and_record_normalization(self):
        for url in [
            watch_url(VIDEO['id']) + '&list=ignored',
            'https://youtu.be/aqz-KE-bpKQ?t=60',
            'https://m.youtube.com/shorts/aqz-KE-bpKQ',
            'https://www.youtube.com/live/aqz-KE-bpKQ',
        ]:
            self.assertEqual(video_id(url), VIDEO['id'])
        for url in [
            'https://youtube.com.evil/watch?v=aqz-KE-bpKQ',
            'file:///etc/passwd',
            'https://evil@youtube.com/watch?v=aqz-KE-bpKQ',
            'https://www.youtube.com:444/watch?v=aqz-KE-bpKQ',
            'https://www.youtube.com/playlist?list=x',
            '--exec=evil',
            None,
        ]:
            with self.subTest(url=url), self.assertRaises(StreamingError):
                video_id(url)
        self.assertEqual(channel_url('@fixture'), VIDEO['channel'])
        self.assertEqual(channel_url(VIDEO['channel'] + '/videos'), VIDEO['channel'])
        self.assertEqual(VIDEO['chapters'][1]['start'], 60)
        self.assertIsNone(record(dict(id='invalid')))
        self.assertEqual(
            record(dict(RAW, thumbnail='file:///etc/passwd'))['thumbnail'], ''
        )

    def test_search_channel_feed_pagination_partial_failure_and_known_details(self):
        self.backend.handle(dict(op='subscribe', url='@fixture'))
        self.backend.handle(dict(op='subscribe', url='@fixture'))
        self.assertEqual(len(self.backend.settings()['channels']), 1)
        self.backend.commands.extract = Mock(return_value=dict(entries=[RAW]))
        rows = self.backend.handle(
            dict(op='browse', tab='search', query='fixture', page=1)
        )
        self.assertEqual(rows['items'][0]['id'], VIDEO['id'])
        self.backend.commands.extract.assert_called_with(
            'ytsearch48:fixture', flat=True, start=25, count=24
        )
        direct = self.backend.handle(
            dict(op='browse', tab='search', query=watch_url(VIDEO['id']))
        )
        self.assertEqual(direct['items'], [VIDEO])
        self.backend.handle(dict(op='subscribe', url='@other'))

        def extract(target, **kwargs):
            if '@other' in target:
                raise StreamingError('Offline')
            return dict(entries=[RAW])

        self.backend.commands.extract.side_effect = extract
        feed = self.backend.handle(dict(op='browse', tab='feed'))
        self.assertEqual([v['id'] for v in feed['items']], [VIDEO['id']])
        self.assertIn('1 channel', feed['warning'])
        with patch.object(
            self.backend, '_browse', side_effect=StreamingError('offline')
        ):
            snapshot = self.backend.handle(dict(op='browse', tab='feed', refresh=True))
        self.assertEqual([v['id'] for v in snapshot['items']], [VIDEO['id']])
        self.assertFalse(snapshot['more'])
        self.assertIn('Offline', snapshot['warning'])
        self.assertEqual(
            self.backend.handle(dict(op='browse', tab='feed', query='missing'))[
                'items'
            ],
            [],
        )
        self.backend.commands.details.side_effect = StreamingError('Offline')
        self.assertEqual(
            self.backend.handle(dict(op='details', videoId=VIDEO['id'], offline=True)),
            VIDEO,
        )
        for tab in ('saved', 'history'):
            with (
                self.subTest(tab=tab),
                self.assertRaisesRegex(StreamingError, 'Unknown Streaming view'),
            ):
                self.backend.handle(dict(op='browse', tab=tab))
        with self.assertRaisesRegex(StreamingError, 'Unknown Streaming request'):
            self.backend.handle(dict(op='save', videoId=VIDEO['id'], value=True))
        self.assertNotIn('saved', self.backend.init())
        for value in (True, -1, 1.5, 2**31):
            with self.subTest(value=value), self.assertRaises(StreamingError):
                self.backend.handle(dict(op='browse', page=value))

    def test_analysis_is_explicit_cached_per_question_and_model_and_errors_redact_key(
        self,
    ):
        self.assertFalse(self.backend.init()['gemini'])
        self.backend.key_path.parent.mkdir(parents=True)
        self.backend.key_path.write_text('fixture-secret')
        self.assertTrue(self.backend.init()['gemini'])
        response = Mock(status_code=200)
        response.json.return_value = dict(
            candidates=[dict(content=dict(parts=[dict(text='Main point at 01:00.')]))]
        )
        with patch.object(insights.requests, 'post', return_value=response) as post:
            self.backend.init()
            post.assert_not_called()
            request = dict(op='analyze', videoId=VIDEO['id'])
            result = wait_job(self.backend, self.backend.handle(request)['job_id'])
            self.assertEqual(result['state'], 'finished')
            self.assertEqual(post.call_count, 1)
            payload = post.call_args.kwargs
            self.assertEqual(payload['headers'], {'x-goog-api-key': 'fixture-secret'})
            self.assertFalse(payload['allow_redirects'])
            self.assertEqual(
                payload['json']['contents'][0]['parts'][1]['fileData']['fileUri'],
                VIDEO['url'],
            )
            wait_job(self.backend, self.backend.handle(request)['job_id'])
            self.assertEqual(post.call_count, 1)
            wait_job(
                self.backend,
                self.backend.handle(dict(request, question='Which topic?'))['job_id'],
            )
            self.assertEqual(post.call_count, 2)
            response.status_code = 429
            failed = wait_job(
                self.backend,
                self.backend.handle(dict(request, question='Other topic?'))['job_id'],
            )
            self.assertEqual(failed['state'], 'failed')
            self.assertIn('quota', failed['error'])
            self.assertNotIn('fixture-secret', json.dumps(failed))
        with self.assertRaises(StreamingError):
            insights.generate(VIDEO['id'], self.backend.key_path, 'gemini-foo/evil')

    def test_watch_uses_catalogue_metadata_and_survives_detail_failure(self):
        self.backend.commands.extract = Mock(return_value=dict(entries=[RAW]))
        self.backend.handle(dict(op='browse', tab='search', query='fixture'))
        self.backend.commands.details.side_effect = StreamingError(
            'Metadata lookup failed'
        )
        self.backend.player.start = Mock(
            return_value=dict(playing=True, connecting=True, id=VIDEO['id'])
        )
        state = self.backend.handle(dict(op='play', videoId=VIDEO['id']))
        self.assertTrue(state['playing'])
        self.backend.commands.details.assert_not_called()
        self.backend.player.start.assert_called_once_with(VIDEO, '', False, None)

    def test_direct_video_link_remains_watchable_when_metadata_fails(self):
        self.backend.commands.details.side_effect = StreamingError(
            'Metadata lookup failed'
        )
        result = self.backend.handle(
            dict(op='browse', tab='search', query=VIDEO['url'])
        )
        self.assertEqual(result['items'][0]['id'], VIDEO['id'])
        self.assertIn('details are unavailable', result['warning'])
        self.backend.player.start = Mock(return_value=dict(playing=True))
        self.backend.commands.details.reset_mock()
        self.backend.handle(dict(op='play', videoId=VIDEO['id']))
        self.backend.commands.details.assert_not_called()

    def test_restrictions_are_actionable_and_private_provider_data_never_reaches_errors(
        self,
    ):
        error = command_error(
            'ERROR: Join this channel to get access to members-only content https://media.example/?token=private'
        )
        self.assertEqual(error.code, 'members-only')
        self.assertIn('membership', str(error))
        self.assertNotIn('private', str(error))
        self.assertNotIn('https://', str(error))
        self.backend.details_cache[VIDEO['id']] = dict(
            VIDEO, availability='subscriber_only'
        )
        with patch.object(self.backend.player, 'start') as start:
            with self.assertRaisesRegex(StreamingError, 'members-only'):
                self.backend.handle(dict(op='play', videoId=VIDEO['id']))
            start.assert_not_called()
        self.assertEqual(
            VIDEO['backdrop'], 'https://i.ytimg.com/vi/aqz-KE-bpKQ/sd2.jpg'
        )

    def test_layout_preferences_preserve_followed_channels_without_quality_setting(
        self,
    ):
        self.backend.handle(dict(op='subscribe', url='@fixture'))
        settings = self.backend.handle(dict(op='layout', grid_mode=True))
        self.assertTrue(settings['grid_mode'])
        self.assertNotIn('quality', settings)
        self.assertEqual(len(settings['channels']), 1)
        fresh = StreamingBackend(
            self.backend.config, self.backend.data, self.backend.cache
        )
        self.addCleanup(fresh.close)
        self.assertTrue(fresh.init()['settings']['grid_mode'])

    def test_private_state_serializes_concurrent_mutations_and_preserves_corrupt_file(
        self,
    ):
        library = self.backend.library
        threads = [
            threading.Thread(
                target=library.put,
                args=('summaries', str(i), dict(text=str(i), videoId=VIDEO['id'])),
            )
            for i in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(library.read()['summaries']), 20)
        self.assertEqual(library.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(library.path.parent.stat().st_mode & 0o777, 0o700)
        library.path.write_text('broken')
        with self.assertRaises(StreamingError):
            library.put('summaries', VIDEO['id'], dict(text='Summary'))
        self.assertEqual(library.path.read_text(), 'broken')

    def test_owned_player_prefers_downloads_and_offline_missing_never_streams(self):
        binary = fake_mpv(self.root)
        media = self.root / 'Videos/offline.mkv'
        media.parent.mkdir()
        media.write_bytes(b'fixture')
        self.backend.library.put(
            'downloads',
            VIDEO['id'] + ':video',
            dict(path=str(media), audio=False, video=VIDEO),
        )
        from spaces.streaming import player

        original = shutil.which
        with (
            patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root)),
            patch.object(
                player.shutil,
                'which',
                side_effect=lambda name: (
                    str(binary) if name == 'mpv' else original(name)
                ),
            ),
        ):
            state = self.backend.handle(
                dict(op='play', videoId=VIDEO['id'], offline=True)
            )
            self.assertTrue(state['playing'])
            deadline = time.monotonic() + 3
            while (
                not self.backend.player.ipc.property(
                    self.backend.player.path, 'metadata'
                )
                and time.monotonic() < deadline
            ):
                time.sleep(0.03)
            self.assertTrue(self.backend.handle(dict(op='pause'))['paused'])
            process = self.backend.player.process
            self.backend.handle(dict(op='stop'))
            self.assertIsNotNone(process.poll())
            self.assertEqual(
                set(self.backend.library.read()), {'downloads', 'summaries'}
            )
            media.unlink()
            with self.assertRaisesRegex(StreamingError, 'missing'):
                self.backend.handle(dict(op='play', videoId=VIDEO['id'], offline=True))

    def test_cancellation_terminates_owned_child_and_cleans_partials(self):
        class SlowCommands(Commands):
            def ytdlp(inner, args, **kwargs):
                output = args[args.index('-o') + 1].replace('%(ext)s', 'part')
                return inner.run(
                    [
                        sys.executable,
                        '-c',
                        "import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('partial'); time.sleep(30)",
                        output,
                    ]
                )

        self.backend.commands.close()
        self.backend.commands = SlowCommands()
        self.backend.commands.details = Mock(return_value=VIDEO)
        job_id = self.backend.handle(
            dict(op='download', videoId=VIDEO['id'], audio=True)
        )['job_id']
        deadline = time.monotonic() + 3
        while (
            not list(self.backend.music.glob('.streaming-*/*.part'))
            and time.monotonic() < deadline
        ):
            time.sleep(0.03)
        self.assertTrue(list(self.backend.music.glob('.streaming-*/*.part')))
        self.backend.handle(dict(op='cancel', job_id=job_id))
        self.assertEqual(wait_job(self.backend, job_id)['state'], 'cancelled')
        self.assertEqual(list(self.backend.music.iterdir()), [])
        self.assertEqual(self.backend.commands.processes, set())

    @unittest.skipUnless(
        shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required'
    )
    def test_native_audio_import_preserves_packets_tags_cover_and_collisions(self):
        image = self.root / 'cover.ppm'
        image.write_bytes(b'P6\n16 16\n255\n' + bytes((220, 40, 50)) * 256)
        cover = self.root / 'cover.jpg'
        subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(image), str(cover)],
            check=True,
        )

        def packets(path):
            probe = json.loads(
                subprocess.check_output(
                    [
                        'ffprobe',
                        '-v',
                        'error',
                        '-select_streams',
                        'a:0',
                        '-show_packets',
                        '-show_entries',
                        'packet=data_hash',
                        '-show_data_hash',
                        'sha256',
                        '-of',
                        'json',
                        str(path),
                    ]
                )
            )
            return [p['data_hash'] for p in probe['packets']]

        from spaces.music import tags, local_files

        for codec, encoder, container, extension in (
            ('opus', 'libopus', 'webm', 'opus'),
            ('aac', 'aac', 'm4a', 'm4a'),
        ):
            with self.subTest(codec=codec):
                source = self.root / ('fixture.' + container)
                subprocess.run(
                    [
                        'ffmpeg',
                        '-nostdin',
                        '-v',
                        'error',
                        '-f',
                        'lavfi',
                        '-i',
                        'sine=frequency=440:duration=0.15',
                        '-c:a',
                        encoder,
                        str(source),
                    ],
                    check=True,
                )

                class FixtureCommands(Commands):
                    def ytdlp(inner, args, **kwargs):
                        self.assertIn('--write-thumbnail', args)
                        self.assertIn('--embed-metadata', args)
                        self.assertNotIn('--extract-audio', args)
                        self.assertNotIn('--audio-format', args)
                        destination = Path(
                            args[args.index('-o') + 1].replace('%(ext)s', container)
                        )
                        shutil.copy(source, destination)
                        shutil.copy(cover, destination.parent / 'media.jpg')
                        kwargs['on_line']('__file__' + json.dumps(str(destination)))

                self.backend.commands.close()
                self.backend.commands = FixtureCommands()
                self.backend.commands.details = Mock(return_value=VIDEO)
                for _ in range(2):
                    job = wait_job(
                        self.backend,
                        self.backend.handle(
                            dict(op='download', videoId=VIDEO['id'], audio=True)
                        )['job_id'],
                    )
                    self.assertEqual(job['state'], 'finished', job)
                files = sorted(self.backend.music.glob('*.' + extension))
                self.assertEqual(len(files), 2)
                self.assertTrue(any(f' (2).{extension}' in p.name for p in files))
                self.assertTrue(packets(source))
                self.assertEqual(
                    packets(source), packets(files[0]), 'Encoded audio packets changed'
                )
                details = tags.read(files[0], local_files.run)
                self.assertEqual(details['codec'], codec)
                for field in ('title', 'artist', 'album'):
                    self.assertEqual(details['tags'][field], VIDEO[field])
                self.assertTrue(details['coverIndexes'])
                self.assertIn(files[0].suffix, local_files.EXTENSIONS)
                # Music's metadata editor must preserve the downloaded audio and cover.
                tags.write(
                    files[0],
                    {'title': 'Edited performance', 'lyrics': 'Fixture lyrics'},
                    local_files.run,
                    local_files.signature,
                    lambda _: None,
                    lambda _: None,
                )
                edited = tags.read(files[0], local_files.run)
                self.assertEqual(edited['tags']['title'], 'Edited performance')
                self.assertEqual(edited['tags']['lyrics'], 'Fixture lyrics')
                self.assertTrue(edited['coverIndexes'])
                self.assertEqual(packets(source), packets(files[0]))
        self.assertFalse(list(self.backend.music.glob('.streaming-*')))
        self.assertEqual(len(self.backend.library.items('downloads')), 1)

    @unittest.skipUnless(shutil.which('yt-dlp'), 'yt-dlp is required')
    def test_audio_selection_ranks_supported_sources_without_forcing_a_codec(self):
        info = dict(
            id=VIDEO['id'],
            title='Fixture',
            extractor='youtube',
            webpage_url=VIDEO['url'],
            formats=[
                dict(
                    format_id=identity,
                    ext=ext,
                    acodec=codec,
                    vcodec='none',
                    quality=quality,
                    abr=bitrate,
                    url='https://media.example/' + identity,
                )
                for identity, ext, codec, quality, bitrate in (
                    ('aac128', 'm4a', 'mp4a.40.2', 2, 128),
                    ('opus128', 'webm', 'opus', 2, 128),
                    ('aac256', 'm4a', 'mp4a.40.2', 3, 256),
                    ('vorbis512', 'webm', 'vorbis', 4, 512),
                )
            ],
        )
        fixture = self.root / 'formats.json'
        for expected in ('aac256', 'opus128', None):
            fixture.write_text(json.dumps(info))
            result = subprocess.run(
                [
                    'yt-dlp',
                    '--ignore-config',
                    '--no-plugin-dirs',
                    '--no-remote-components',
                    '--skip-download',
                    '--load-info-json',
                    str(fixture),
                    '-f',
                    AUDIO_FORMAT,
                    '--print',
                    'format_id',
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if expected:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Requested format is not available', result.stderr)
            if expected == 'aac256':
                info['formats'] = [
                    f for f in info['formats'] if f['format_id'] != 'aac256'
                ]
            else:
                info['formats'] = [
                    f for f in info['formats'] if f['format_id'] == 'vorbis512'
                ]


if __name__ == '__main__':
    unittest.main()
