"""Clipboard backend: cliphist commands, watcher units and wl-copy, without real clipboard access."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import support

SPEC = importlib.util.spec_from_file_location(
    'desktop_clipboard', support.DESKTOP / 'drawers/clipboard/backend.py'
)
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 8


def completed(args, code=0, stdout=b''):
    return subprocess.CompletedProcess(args, code, stdout, b'')


class ClipboardBackendTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, XDG_CACHE_HOME=self.tmp.name)
        env.start()
        self.addCleanup(env.stop)

    def run_fake(self, outputs):
        def fake(args, **kwargs):
            self.calls.append((args, kwargs.get('input')))
            for prefix, result in outputs:
                if args[: len(prefix)] == prefix:
                    return completed(args, *result)
            return completed(args)

        return patch.object(backend.subprocess, 'run', side_effect=fake)

    def test_list_and_pause_use_cliphist_and_watcher_units(self):
        listing = b'7\t[[ binary data 2 KiB png 4x4 ]]\n6\thello\n'
        with self.run_fake(
            [
                (['cliphist', 'list'], (0, listing)),
                (['systemctl', '--user', 'is-active'], (3,)),
            ]
        ):
            result = backend.handle(dict(op='list'))
            backend.handle(dict(op='pause', value=False))
        self.assertTrue(result['paused'])
        self.assertEqual(
            [row['mime'] for row in result['entries']],
            ['image/png', 'text/plain;charset=utf-8'],
        )
        self.assertIn(
            (['systemctl', '--user', 'start', *backend.WATCHERS], None), self.calls
        )
        self.assertFalse(any('-max-items' in args for args, _ in self.calls))

    def test_copy_decodes_by_id_and_pipes_to_wl_copy(self):
        with self.run_fake([(['cliphist', 'decode', '7'], (0, PNG))]):
            backend.handle(dict(op='copy', id=7, mime='text/plain'))
            backend.handle(dict(op='delete', id=6))
        self.assertIn((['wl-copy', '--type', 'image/png'], PNG), self.calls)
        self.assertIn((['cliphist', 'delete'], b'6\t\n'), self.calls)

    def test_thumbnail_is_private_and_rejects_text(self):
        with self.run_fake(
            [
                (['cliphist', 'decode', '7'], (0, PNG)),
                (['cliphist', 'decode', '6'], (0, b'text')),
            ]
        ):
            result = backend.handle(dict(op='thumbnail', id=7, mime='image/png'))
            with self.assertRaises(ValueError):
                backend.handle(dict(op='thumbnail', id=6, mime=''))
        self.assertTrue(result['url'].startswith('file://' + self.tmp.name))

    def test_command_failures_surface_as_errors(self):
        with patch.object(
            backend.subprocess,
            'run',
            side_effect=subprocess.CalledProcessError(1, ['cliphist']),
        ):
            with self.assertRaises(subprocess.SubprocessError):
                backend.handle(dict(op='copy', id=99))


if __name__ == '__main__':
    unittest.main()
