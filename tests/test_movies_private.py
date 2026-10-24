"""Portable Movies configuration and personal records survive private restore."""
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
    def test_selected_declarations_restore_credentials_preferences_and_favorites(self):
        module = json.loads((support.REPO / 'modules/desktop/quickshell/config.json').read_text())
        paths = [path for path in module['extra']['private']['files']
                 if '/quickshell/desktop/spaces/movies/' in path]
        self.assertEqual(len(paths), 4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / 'live'
            config = live / '.config/quickshell/desktop/spaces/movies'
            config.mkdir(parents=True, mode=0o700)
            for name, contents in [('media.json', '{"tmdb_key":"fixture","providers":[]}'),
                                   ('torrents.json', '{"password":"fixture"}'),
                                   ('media-ui.ini', '[catalogue]\ngrid=true\n')]:
                path = config / name
                path.write_text(contents)
                path.chmod(0o600)
            data = live / '.local/share/quickshell/desktop/spaces/movies'
            backend = Backend(config / 'media.json', data)
            movie = dict(id='tt001', imdbId='tt001', tmdbId=123, kind='movie', title='Fixture')
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
            target = restored / '.config/quickshell/desktop/spaces/movies/media.json'
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            restored_backend = Backend(target, restored / '.local/share/quickshell/desktop/spaces/movies')
            self.assertTrue(restored_backend.personal('tmdb:movie:123')['favorite'])
