"""Portable media Space configuration and personal records survive private restore."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import support
sys.path.insert(0, str(support.DESKTOP))
from spaces.movies.backend import Backend


class MoviesPrivateTests(unittest.TestCase):
    def test_movies_private_restore(self):
        self.check_private_restore('movies', 'movie')

    def test_series_private_restore(self):
        self.check_private_restore('series', 'tv')

    def check_private_restore(self, space, kind):
        module = json.loads((support.REPO / 'modules/desktop/quickshell/config.json').read_text())
        paths = [path for path in module['extra']['private']['files']
                 if f'/quickshell/desktop/spaces/{space}/' in path]
        self.assertEqual(len(paths), 4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / 'live'
            config = live / f'.config/quickshell/desktop/spaces/{space}'
            config.mkdir(parents=True, mode=0o700)
            for name, contents in [('media.json', '{"tmdb_key":"fixture","providers":[]}'),
                                   ('torrents.json', '{"password":"fixture"}'),
                                   ('media-ui.ini', '[catalogue]\ngrid=true\n')]:
                path = config / name
                path.write_text(contents)
                path.chmod(0o600)
            data = live / f'.local/share/quickshell/desktop/spaces/{space}'
            backend = Backend(config / 'media.json', data)
            movie = dict(id='tt001', imdbId='tt001', tmdbId=123, kind=kind, title='Fixture')
            backend.save(dict(title=movie, values=dict(favorite=True)))
            private = root / 'private'
            declaration = root / 'selected.json'
            declaration.write_text(json.dumps({'extra': {'private': {'files': paths}}}))

            def run(argv, home):
                result = subprocess.run(argv, env={**os.environ, 'HOME': str(home),
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            run(['bash', str(support.REPO / 'backup.sh'), '--config', str(declaration),
                 '--destination', str(private)], live)
            # Only synthetic fixtures are committed and cloned by this test.
            run(['git', '-C', str(private), 'add', '.'], live)
            run(['git', '-C', str(private), '-c', 'user.name=Fixture', '-c',
                 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture'], live)
            clone = root / 'clone'
            run(['git', 'clone', '--quiet', '--no-hardlinks', str(private), str(clone)], live)
            restored = root / 'restored'
            restored.mkdir(mode=0o700)
            run(['bash', str(clone / 'apply.sh')], restored)
            for path in paths:
                relative = path.removeprefix('home/')
                self.assertEqual((live / relative).read_bytes(), (restored / relative).read_bytes())
            target = restored / f'.config/quickshell/desktop/spaces/{space}/media.json'
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            restored_backend = Backend(target, restored / f'.local/share/quickshell/desktop/spaces/{space}')
            self.assertTrue(restored_backend.personal(f'tmdb:{kind}:123')['favorite'])
