import support
import sys

sys.path.insert(0, str(support.DESKTOP))
import io
import json
import os
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from spaces.pictures import backend, providers, video_wallpaper
from spaces.pictures import wallpaper_engine as engine
from spaces.pictures.command_provider import CommandRunner

ROOT = Path(__file__).resolve().parents[1]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(
            os.environ,
            {
                'XDG_CONFIG_HOME': str(self.root / 'config'),
                'XDG_CACHE_HOME': str(self.root / 'cache'),
                'XDG_DATA_HOME': str(self.root / 'data'),
                'XDG_RUNTIME_DIR': str(self.root / 'runtime'),
                'PICTURE_FIXTURE_ROOT': str(self.root),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.config = providers.configuration_file()
        self.config.parent.mkdir(parents=True)
        self.package = self.config.parent / 'plugin with spaces'
        self.package.mkdir()
        (self.package / 'provider.py').write_text(
            (ROOT / 'tests/fixtures/picture-provider.py').read_text()
        )
        (self.package / 'manifest.json').write_text(
            json.dumps(
                {
                    'api_version': 1,
                    'command': [sys.executable, '{plugin_dir}/provider.py'],
                }
            )
        )
        (self.root / 'server.port').write_text('12345')
        self.row = {
            'id': 'personal',
            'name': 'Personal provider',
            'plugin': 'plugin with spaces',
        }
        self.configure([self.row])
        self.runner = CommandRunner(timeout=0.3)
        self.addCleanup(self.runner.close)
        runner_patch = patch.object(providers, 'runner', self.runner)
        runner_patch.start()
        self.addCleanup(runner_patch.stop)
        self.raw = {
            'provider': 'personal',
            'id': '../unsafe/id',
            'title': 'Video',
            'kind': 'video',
            'preview': 'https://example.org/poster.jpg',
            'ref': {'file': [1, 'opaque']},
        }

    def configure(self, rows):
        self.config.write_text(json.dumps({'providers': rows}))

    def requests(self):
        return [
            json.loads(line)
            for line in (self.root / 'provider-requests.jsonl').read_text().splitlines()
        ]

    def test_manifest_is_lazy_and_substitution_handles_spaces(self):
        catalog = backend.provider_catalog()
        self.assertEqual(catalog['providers'][-1]['id'], 'personal')
        self.assertFalse((self.root / 'provider-requests.jsonl').exists())
        self.assertEqual(
            providers.configured()['personal']['command'][1],
            str(self.package / 'provider.py'),
        )

    def test_browse_preserves_opaque_pagination_and_only_resolves_on_apply(self):
        first = backend.browse({'provider': 'personal', 'page': 1, 'query': 'clouds'})
        self.assertEqual(first['next'], 'opaque-next-page')
        second = backend.browse(
            {'provider': 'personal', 'page': first['next'], 'query': 'clouds'}
        )
        self.assertEqual(second['next'], 0)
        self.assertEqual(second['items'][0]['id'], 'second')
        self.assertEqual(first['items'][0]['kind'], 'video')
        self.assertEqual([r['op'] for r in self.requests()], ['browse', 'browse'])
        providers.resolve(first['items'][0])
        self.assertEqual(self.requests()[-1], {'op': 'resolve', 'ref': {'id': 'first'}})

    def test_rejects_reserved_duplicate_or_unsafe_provider_ids(self):
        for rows in (
            [dict(self.row, id='wallhaven')],
            [dict(self.row, id='../provider')],
            [self.row, dict(self.row, name='Another')],
        ):
            with self.subTest(rows=rows):
                self.configure(rows)
                with self.assertRaisesRegex(ValueError, 'unique IDs'):
                    providers.configured()

    def test_item_rejects_invalid_urls_dimensions_and_kind(self):
        for row in (
            dict(self.raw, kind='web'),
            dict(self.raw, width='invalid'),
            dict(self.raw, ref=float('nan')),
        ):
            self.assertIsNone(providers.clean_item(row))
        item = providers.clean_item(
            dict(self.raw, preview='https://user:password@example.org/poster.jpg')
        )
        self.assertEqual(item['preview'], '')
        self.assertEqual(item['ref'], self.raw['ref'])

    def test_favorite_round_trip_and_restore_provider(self):
        backend.save_favorites({'wallpaper': self.raw, 'favorite': True})
        saved = backend.load_favorites()
        self.assertEqual(saved[0]['ref'], self.raw['ref'])
        self.assertEqual(
            backend.browse_favorites({'provider': 'personal'})['items'], saved
        )
        (self.config.parent / 'wallpaper.json').write_text(
            json.dumps({'mode': 'video', 'provider': 'personal'})
        )
        self.assertEqual(backend.current_wallpaper_provider(), 'personal')
        self.configure([])
        self.assertEqual(backend.current_wallpaper_provider(), 'wallhaven')
        self.assertEqual(backend.load_favorites(), [])
        backend.save_favorites(
            {
                'wallpaper': {
                    'provider': 'wallhaven',
                    'id': 'abc123',
                    'path': 'https://w.wallhaven.cc/full/ab/wallhaven-abc123.png',
                },
                'favorite': True,
            }
        )
        self.configure([self.row])
        self.assertEqual(backend.load_favorites()[1]['ref'], self.raw['ref'])

    def response(self, content, content_type='video/mp4'):
        response = io.BytesIO(content)
        response.headers = Message()
        response.headers['Content-Type'] = content_type
        return response

    def test_download_uses_fresh_resolution_headers_and_collision_safe_cache(self):
        item = providers.clean_item(self.raw)
        content = b'\x00\x00\x00\x18ftypisom' + b'video bytes'
        with (
            patch.object(
                providers,
                'resolve',
                return_value=(
                    'https://example.org/fresh.mp4',
                    {'Referer': 'https://example.org/detail'},
                ),
            ) as resolve,
            patch.object(
                backend, 'urlopen', return_value=self.response(content)
            ) as network,
        ):
            path = backend.download_wallpaper(item)
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(
                path.parent,
                self.root / 'cache/quickshell/desktop/spaces/pictures/wallpapers',
            )
            self.assertEqual(
                network.call_args.args[0].get_header('Referer'),
                'https://example.org/detail',
            )
            self.assertEqual(backend.download_wallpaper(item), path)
            resolve.assert_called_once_with(item)
        other = providers.clean_item(dict(self.raw, id='__unsafe_id'))
        self.assertNotEqual(backend.wallpaper_file(item), backend.wallpaper_file(other))

    def test_invalid_video_and_html_leave_no_cache_or_partial_file(self):
        item = providers.clean_item(self.raw)
        for content, kind in (
            (b'<html>login</html>', 'text/html'),
            (b'PK not a video file', 'video/mp4'),
        ):
            with (
                self.subTest(kind=kind),
                patch.object(
                    providers, 'resolve', return_value=('https://example.org/file', {})
                ),
                patch.object(
                    backend, 'urlopen', return_value=self.response(content, kind)
                ),
            ):
                with self.assertRaises(ValueError):
                    backend.download_wallpaper(item)
            self.assertFalse(backend.wallpaper_file(item).exists())
            self.assertEqual(
                list(backend.wallpaper_file(item).parent.glob('*.download')), []
            )

    def test_missing_dependency_does_not_resolve_download_or_change_wallpaper(self):
        setting = self.config.parent / 'wallpaper.json'
        setting.write_text('{"image":"file:///previous.jpg"}')
        before = setting.read_bytes()
        with (
            patch.object(video_wallpaper.shutil, 'which', return_value=None),
            patch.object(providers, 'resolve') as resolve,
        ):
            with self.assertRaisesRegex(ValueError, 'Install mpvpaper'):
                backend.set_wallpaper({'wallpaper': self.raw})
        self.assertEqual(setting.read_bytes(), before)
        resolve.assert_not_called()

    def test_timeout_terminates_command(self):
        with self.assertRaisesRegex(ValueError, 'timed out'):
            backend.browse({'provider': 'personal', 'query': 'slow'})
        self.assertEqual(self.runner._processes, set())

    def test_video_failure_restores_previous_choice(self):
        setting = self.config.parent / 'wallpaper.json'
        previous = {'image': 'file:///previous.jpg', 'provider': 'bing'}
        setting.write_text(json.dumps(previous))
        video = self.root / 'video.mp4'
        video.write_bytes(b'video')
        poster = self.root / 'poster.jpg'
        poster.write_bytes(b'image')
        with (
            patch.object(video_wallpaper, 'requirements'),
            patch.object(video_wallpaper, 'still_frame', return_value=poster),
            patch.object(
                engine,
                'read_state',
                side_effect=lambda: {
                    'selection': engine.read_setting()['selection'],
                    'status': 'error',
                    'error': 'Fixture failed',
                },
            ),
            patch.object(engine, 'wait_idle') as idle,
        ):
            with self.assertRaisesRegex(ValueError, 'Fixture failed'):
                video_wallpaper.apply(video, 'personal')
        self.assertEqual(engine.read_setting(), previous)
        idle.assert_called_once()

    def test_runtime_routes_video_and_preserves_failure_latch(self):
        (self.config.parent / 'wallpaper.json').write_text(
            json.dumps(
                {'mode': 'video', 'selection': 'video-choice', 'video': '/missing.mp4'}
            )
        )
        runtime = engine.Runtime()
        self.addCleanup(runtime.close)
        with patch.object(
            runtime.video, 'sync', return_value={'screens': ['TEST']}
        ) as sync:
            self.assertEqual(runtime.sync({}), {'screens': ['TEST']})
        sync.assert_called_once()
        runtime.fail(ValueError('Fixture failed'))
        with patch.object(runtime.video, 'sync') as sync:
            self.assertIn('error', runtime.sync({}))
        sync.assert_not_called()
