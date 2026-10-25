"""Portable Television favorites/stream choices restore without provider accounts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import support
from test_television import datasets
from spaces.television.backend import TelevisionBackend


class TelevisionPrivateTests(unittest.TestCase):
    def test_backup_clone_restore_favorites_stream_preferences_modes_and_collisions(self):
        module=json.loads((support.REPO/'modules/desktop/quickshell/config.json').read_text())
        paths=[path for path in module['extra']['private']['files'] if '/spaces/television/' in path]
        self.assertEqual(len(paths),2)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);live=root/'live';live.mkdir(mode=0o700)
            backend=TelevisionBackend(live/'.config/quickshell/desktop/spaces/television',live/'.local/share/quickshell/desktop/spaces/television',root/'cache',fetch=lambda key:datasets(2)[key])
            backend.init();backend.handle(dict(op='refresh'))
            channel=backend.catalogue.snapshot['channels'][0]
            backend.handle(dict(op='favorite',channel=channel,value=True))
            selected=channel['streams'][1]['id']
            backend.handle(dict(op='settings-save',settings=dict(country='US',language='eng',category='news',streams={channel['id']:selected})))
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
            collision=restored/'.config/quickshell/desktop/spaces/television/television-ui.json'
            collision.parent.mkdir(parents=True,mode=0o700);collision.write_text('existing preferences')
            run(['bash',str(clone/'apply.sh')],restored)
            self.assertEqual(next(collision.parent.glob('television-ui.json.before-private-*')).read_text(),'existing preferences')
            for path in paths:
                source=live/path.removeprefix('home/');target=restored/path.removeprefix('home/')
                self.assertEqual(source.read_bytes(),target.read_bytes())
                self.assertEqual(target.stat().st_mode&0o777,0o600)
                self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            fresh=TelevisionBackend(collision.parent,restored/'.local/share/quickshell/desktop/spaces/television',root/'restored-cache')
            result=fresh.init()
            self.assertEqual(result['settings']['streams'][channel['id']],selected)
            self.assertEqual(result['favorites'][0]['streams'][1]['user_agent'],'Fixture player')
            self.assertEqual(len(fresh.handle(dict(op='browse'))['items']),1)
