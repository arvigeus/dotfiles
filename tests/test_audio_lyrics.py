"""Shared provider configuration and bounded HTTP lyric lookups."""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import support
import audio_lyrics
import sys

sys.path.insert(0, str(support.DESKTOP))
from spaces.music import backend as music
from spaces.music.cache import JsonCache


class SharedLyricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.song = dict(
            title='Long song / 千本桜',
            artist='Fixture artist',
            album='Album',
            duration=1800,
        )
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                owner.requests.append((self.path, self.headers.get('Authorization')))
                if self.path.startswith('/redirect/'):
                    self.send_response(302)
                    self.send_header('Location', 'http://localhost:1/private')
                    self.end_headers()
                    return
                if self.path.startswith('/limited/'):
                    self.send_response(429)
                    self.send_header('Retry-After', '60')
                    self.end_headers()
                    return
                if self.path.startswith('/missing/'):
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.path.startswith('/oversized/'):
                    body = b' ' * (audio_lyrics.MAX_RESPONSE_BYTES + 1)
                else:
                    body = json.dumps(
                        dict(syncedLyrics='[00:01.00]Line one\n[00:02.000]Line two')
                    ).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.provider = dict(
            name='Fixture',
            base_url=f'http://127.0.0.1:{self.server.server_port}/api',
            api_key='fixture-private-token',
        )
        self.env = patch.dict(os.environ, XDG_CONFIG_HOME=str(self.root / 'config'))
        self.env.start()
        self.addCleanup(self.env.stop)
        settings = audio_lyrics.config_path()
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps(dict(version=1, providers=[self.provider])))
        self.addCleanup(audio_lyrics._cooldowns.clear)

    def test_music_and_audio_helper_read_the_same_private_config(self):
        direct = audio_lyrics.lookup(self.song)
        cache = JsonCache('lyrics', self.root / 'cache')
        with (
            patch.object(music, 'lyrics_cache', return_value=cache),
            patch.object(
                music,
                'music_config',
                side_effect=AssertionError('Music-specific lyrics config is obsolete'),
            ),
        ):
            through_music = music.fetch_lyrics(dict(song=self.song, refresh=True))
        self.assertEqual(direct, through_music)
        self.assertEqual(direct['lyrics'], 'Line one\nLine two')
        self.assertEqual(len(self.requests), 2)
        for url, authorization in self.requests:
            self.assertEqual(authorization, 'Bearer fixture-private-token')
            self.assertIn('duration=1800', url)
            self.assertNotIn('fixture-private-token', url)
        self.assertNotIn(b'fixture-private-token', cache.path.read_bytes())

    def test_missing_provider_falls_back_and_rate_limits_do_not_repeat_http(self):
        missing = self.provider | {
            'base_url': self.provider['base_url'].replace('/api', '/missing')
        }
        self.assertTrue(
            audio_lyrics.lookup(self.song, [missing, self.provider])['available']
        )
        limited = self.provider | {
            'base_url': self.provider['base_url'].replace('/api', '/limited')
        }
        for _ in range(2):
            with self.assertRaisesRegex(audio_lyrics.LyricsError, 'rate-limited'):
                audio_lyrics.lookup(self.song, [limited])
        self.assertEqual(len(self.requests), 3)

    def test_oversized_responses_and_cross_origin_redirects_are_rejected(self):
        for endpoint, message in [
            ('oversized', 'oversized'),
            ('redirect', 'different origin'),
        ]:
            with (
                self.subTest(endpoint=endpoint),
                self.assertRaisesRegex(audio_lyrics.LyricsError, message),
            ):
                audio_lyrics.lookup(
                    self.song,
                    [
                        self.provider
                        | {
                            'base_url': self.provider['base_url'].replace(
                                '/api', '/' + endpoint
                            )
                        }
                    ],
                )

    def test_invalid_configuration_is_preserved_and_missing_config_uses_lrclib(self):
        path = audio_lyrics.config_path()
        path.write_text('{invalid-private-settings')
        with self.assertRaisesRegex(audio_lyrics.LyricsError, 'configuration'):
            audio_lyrics.read_config()
        self.assertEqual(path.read_text(), '{invalid-private-settings')
        path.unlink()
        self.assertEqual(
            audio_lyrics.read_config(), audio_lyrics.DEFAULT_CONFIG['providers']
        )
        self.assertFalse(path.exists())
        for provider in [
            self.provider | {'headers': {'X-Unsafe': 'secret\nInjected: value'}},
            self.provider | {'base_url': 'file:///private'},
        ]:
            with self.assertRaises(audio_lyrics.LyricsError):
                audio_lyrics.lookup(self.song, [provider])
        self.assertEqual(self.requests, [])

    def test_shared_settings_are_in_private_backup_and_restore(self):
        import subprocess

        paths = json.loads(
            (support.REPO / 'modules/media/tools/audio/config.json').read_text()
        )['extra']['private']['files']
        config = self.root / 'declaration.json'
        config.write_text(json.dumps(dict(extra=dict(private=dict(files=paths)))))
        live = self.root / 'config/audio-tools/lyrics.json'
        # The backup engine resolves home/ paths independently of XDG variables.
        home = self.root / 'home'
        target = home / '.config/audio-tools/lyrics.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(live.read_bytes())
        target.chmod(0o600)
        private = self.root / 'private'
        env = dict(os.environ, HOME=str(home))
        result = subprocess.run(
            [
                'bash',
                str(support.REPO / 'backup.sh'),
                '--config',
                str(config),
                '--destination',
                str(private),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        target.unlink()
        result = subprocess.run(
            ['bash', str(private / 'apply.sh')], env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), live.read_bytes())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
