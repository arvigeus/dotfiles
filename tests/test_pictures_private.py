"""Portable Pictures settings and providers survive backup, clone and restore."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import support


class PicturesPrivateTests(unittest.TestCase):
    def test_private_clone_restore_excludes_image_payloads_and_preserves_collisions(self):
        module = json.loads((support.REPO / 'modules/desktop/quickshell/config.json').read_text())
        paths = [p for p in module['extra']['private']['files'] if '/spaces/pictures/' in p]
        self.assertEqual(len(paths), 5)
        self.assertFalse(any('wallpapers' in p or 'current-wallpaper' in p for p in paths))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); live = root / 'live'; live.mkdir(mode=0o700)
            for path in paths:
                target = live / path.removeprefix('home/')
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                if target.name == 'providers':
                    target.mkdir(mode=0o700)
                    target = target / 'provider.env'
                    target.write_text('TOKEN=synthetic-fixture\n')
                else:
                    target.write_text('[]\n' if target.name == 'favorites.json' else '{}\n')
                target.chmod(0o600)
            settings = live / '.config/quickshell/desktop/spaces/pictures/pictures.json'
            settings.write_text(json.dumps({'providers':[{'id':'personal','name':'Private collection','plugin':'providers/personal','env_file':'token.env'}]}))
            package = settings.parent / 'providers/personal'
            package.mkdir(mode=0o700)
            (package / 'manifest.json').write_text(json.dumps({'api_version':1,'command':[sys.executable,'{plugin_dir}/provider.py']}))
            (package / 'token.env').write_text('TOKEN=synthetic-fixture\n')
            (package / 'provider.py').write_text("import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'success':True,'items':[{'id':'private-video','title':'Restored private video','kind':'video','ref':{'id':'private-video'}}],'next':0}))\n")
            for file in package.iterdir():file.chmod(0o600)
            config = root / 'config.json'
            config.write_text(json.dumps({'extra': {'private': {'files': paths}}}))
            private = root / 'private'
            def run(argv, home):
                result = subprocess.run(argv, env={**os.environ, 'HOME': str(home), 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run(['bash', str(support.REPO / 'backup.sh'), '--config', str(config), '--destination', str(private)], live)
            run(['git', '-C', str(private), 'add', '.'], live)
            run(['git', '-C', str(private), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture'], live)
            clone = root / 'clone'
            run(['git', 'clone', '--quiet', '--no-hardlinks', str(private), str(clone)], live)
            restored = root / 'restored'; restored.mkdir(mode=0o700)
            collision = restored / '.config/quickshell/desktop/spaces/pictures/pictures.json'
            collision.parent.mkdir(parents=True, mode=0o700); collision.write_text('existing destination')
            run(['bash', str(clone / 'apply.sh')], restored)
            self.assertEqual(next(collision.parent.glob('pictures.json.before-private-*')).read_text(), 'existing destination')
            for path in paths:
                source = live / path.removeprefix('home/')
                targets = list(source.rglob('*')) if source.is_dir() else [source]
                for source_file in targets:
                    if not source_file.is_file(): continue
                    target = restored / source_file.relative_to(live)
                    self.assertEqual(target.read_bytes(), source_file.read_bytes())
                    self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            result = subprocess.run([sys.executable, str(support.DESKTOP / 'spaces/pictures/backend.py')],
                input=json.dumps({'id':1,'op':'providers'})+'\n'+json.dumps({'id':2,'op':'browse','provider':'personal'})+'\n',
                env={**os.environ,'HOME':str(restored),'XDG_CONFIG_HOME':str(restored/'.config'),
                     'XDG_DATA_HOME':str(restored/'.local/share'),'XDG_CACHE_HOME':str(restored/'cache'),
                     'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            responses={row['id']:row for row in map(json.loads,result.stdout.splitlines())}
            self.assertIn('personal',[p['id'] for p in responses[1]['result']['providers']])
            self.assertEqual(responses[2]['result']['items'][0]['provider'],'personal')
            self.assertEqual(responses[2]['result']['items'][0]['kind'],'video')
