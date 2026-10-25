"""Portable Books preferences, records and private command packages restore alone."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import support
sys.path.insert(0, str(support.DESKTOP))
from spaces.books.backend import BooksBackend


class BooksPrivateTests(unittest.TestCase):
    def test_backup_clone_restore_provider_database_modes_and_collisions(self):
        module = json.loads((support.REPO / 'modules/desktop/quickshell/config.json').read_text())
        paths = [p for p in module['extra']['private']['files'] if '/spaces/books/' in p]
        self.assertEqual(len(paths), 4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); live = root / 'live'; live.mkdir(mode=0o700)
            config_dir = live / '.config/quickshell/desktop/spaces/books'
            config_dir.mkdir(parents=True, mode=0o700)
            package = config_dir / 'providers/personal'; package.mkdir(parents=True, mode=0o700)
            (config_dir / 'books.json').write_text(json.dumps({'providers':[{'name':'Personal','plugin':'providers/personal','env_file':'token.env'}]}))
            (config_dir / 'books-ui.ini').write_text('[catalogue]\ngrid=true\n')
            (package / 'manifest.json').write_text(json.dumps({'api_version':1,'command':[sys.executable,'{plugin_dir}/provider.py']}))
            (package / 'token.env').write_text('TOKEN=synthetic-fixture\n')
            (package / 'provider.py').write_text('import json,sys\njson.load(sys.stdin)\nprint(json.dumps({"success":True,"results":[{"id":"fixture","title":"Restored book","ref":{"id":"fixture"}}]}))\n')
            backend = BooksBackend(config_dir / 'books.json', live / '.local/share/quickshell/desktop/spaces/books', root / 'cache')
            backend._save_favorite(dict(id='OL100W',title='Saved book'), True)
            backend.close()
            for path in live.rglob('*'): path.chmod(0o700 if path.is_dir() else 0o600)
            config = root / 'config.json'; config.write_text(json.dumps({'extra':{'private':{'files':paths}}}))
            private = root / 'private'
            def run(argv, home):
                result = subprocess.run(argv, env={**os.environ,'HOME':str(home),'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1'},capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run(['bash',str(support.REPO / 'backup.sh'),'--config',str(config),'--destination',str(private)],live)
            run(['git','-C',str(private),'add','.'],live)
            run(['git','-C',str(private),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Fixture'],live)
            clone = root / 'clone'
            run(['git','clone','--quiet','--no-hardlinks',str(private),str(clone)],live)
            restored = root / 'restored'; restored.mkdir(mode=0o700)
            collision = restored / '.config/quickshell/desktop/spaces/books/books.json'
            collision.parent.mkdir(parents=True,mode=0o700);collision.write_text('existing configuration')
            run(['bash',str(clone/'apply.sh')],restored)
            self.assertEqual(next(collision.parent.glob('books.json.before-private-*')).read_text(),'existing configuration')
            for path in paths:
                source = live / path.removeprefix('home/')
                for source_file in list(source.rglob('*')) if source.is_dir() else [source]:
                    if source_file.is_file():
                        target = restored / source_file.relative_to(live)
                        self.assertEqual(target.read_bytes(),source_file.read_bytes())
                        self.assertEqual(target.stat().st_mode&0o777,0o600)
                        self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            result = subprocess.run([sys.executable,str(support.DESKTOP/'spaces/books/backend.py')],
                input='{"id":1,"op":"init"}\n{"id":2,"op":"providerSearch","query":"fixture"}\n{"id":3,"op":"browse","favorites":true}\n',
                env={**os.environ,'HOME':str(restored),'XDG_CONFIG_HOME':str(restored/'.config'),
                     'XDG_DATA_HOME':str(restored/'.local/share'),'XDG_CACHE_HOME':str(root/'restored-cache'),
                     'QUICKSHELL_MEDIA_SPACE':'books','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            responses = {row['id']:row for row in map(json.loads,result.stdout.splitlines())}
            self.assertEqual(responses[1]['result']['providers'],['Personal'])
            self.assertEqual(responses[2]['result']['items'][0]['title'],'Restored book')
            self.assertEqual(responses[3]['result']['items'][0]['id'],'OL100W')
