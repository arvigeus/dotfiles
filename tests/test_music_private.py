"""Portable Music providers, preferences and library use standalone restore."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import support
import sys
sys.path.insert(0,str(support.DESKTOP))
from spaces.music import backend as music


class MusicPrivateTests(unittest.TestCase):
    def test_backup_clone_restore_modes_collision_and_offline_preferences(self):
        module=json.loads((support.REPO/'modules/desktop/quickshell/config.json').read_text())
        paths=[p for p in module['extra']['private']['files'] if '/spaces/music/' in p]
        self.assertEqual(len(paths),3)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);live=root/'live';live.mkdir(mode=0o700)
            config=live/'.config/quickshell/desktop/spaces/music';data=live/'.local/share/quickshell/desktop/spaces/music'
            with patch.object(music,'CONFIG',config),patch.object(music,'DATA',data):
                music.atomic_write(config/'music.json',json.dumps(dict(catalog_token='fixture-private-token',providers=[dict(search_url='https://fixture.invalid/search',stream_url='https://fixture.invalid/{id}',headers={'Authorization':'fixture-secret'})])))
                music.dispatch(dict(op='init'))
                music.settings_save(dict(section='library',views={'library':dict(category='albums',genreId='21',genreName='Rock',starred=True)}))
                # Regenerable caches and media never enter the declared snapshot.
                (live/'Music').mkdir();(live/'Music/payload.flac').write_bytes(b'media')
            declaration=root/'config.json';declaration.write_text(json.dumps(dict(extra=dict(private=dict(files=paths)))))
            private=root/'private'
            def run(argv,home):
                result=subprocess.run(argv,env={**os.environ,'HOME':str(home),'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1'},capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            run(['bash',str(support.REPO/'backup.sh'),'--config',str(declaration),'--destination',str(private)],live)
            run(['git','-C',str(private),'add','.'],live)
            run(['git','-C',str(private),'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Fixture'],live)
            clone=root/'clone';run(['git','clone','--quiet','--no-hardlinks',str(private),str(clone)],live)
            restored=root/'restored';restored.mkdir(mode=0o700)
            collision=restored/'.config/quickshell/desktop/spaces/music/music.json';collision.parent.mkdir(parents=True,mode=0o700);collision.write_text('keep me')
            run(['bash',str(clone/'apply.sh')],restored)
            self.assertEqual(next(collision.parent.glob('music.json.before-private-*')).read_text(),'keep me')
            for path in paths:
                source=live/path.removeprefix('home/');target=restored/path.removeprefix('home/')
                self.assertEqual(source.read_bytes(),target.read_bytes())
                self.assertEqual(target.stat().st_mode&0o777,0o600)
                self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            self.assertFalse((restored/'Music').exists())
            with patch.object(music,'CONFIG',collision.parent),patch.object(music,'DATA',restored/'.local/share/quickshell/desktop/spaces/music'),patch.object(music,'request_body',side_effect=AssertionError('offline init contacted provider')):
                result=music.dispatch(dict(op='init'))
                self.assertNotIn('favorites',result)
                self.assertEqual(result['settings']['section'],'library')
                with closing(sqlite3.connect(music.DATA/'library.sqlite')) as db:
                    self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_failed_init_does_not_replace_invalid_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch.object(music,'CONFIG',root/'config'),patch.object(music,'DATA',root/'data'):
                music.atomic_write(music.CONFIG/'music-ui.json','{"section":"favorites"}')
                with self.assertRaises(music.MusicError):music.dispatch(dict(op='init'))
                self.assertEqual((music.CONFIG/'music-ui.json').read_text(),'{"section":"favorites"}')
