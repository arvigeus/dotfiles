"""Radio's portable settings and favorites survive standalone private restore."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import support
from test_radio import STATION
from spaces.radio.backend import RadioBackend
from spaces.radio.storage import atomic_json
from integrations import nextcloud


class RadioPrivateTests(unittest.TestCase):
    def test_backup_clone_restore_modes_and_collision_preservation(self):
        config=json.loads((support.REPO/'modules/desktop/quickshell/config.json').read_text())
        paths=[p for p in config['extra']['private']['files'] if '/spaces/radio/' in p]
        self.assertEqual(len(paths),3)
        shared=['home/.config/quickshell/desktop/integrations/'+name for name in ('nextcloud.json','nextcloud-app-password','nextcloud-music-api-key')]
        for path in shared:self.assertEqual(config['extra']['private']['files'].count(path),1)
        paths+=shared
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);live=root/'live';live.mkdir(mode=0o700)
            backend=RadioBackend(live/'.config/quickshell/desktop/spaces/radio',live/'.local/share/quickshell/desktop/spaces/radio',root/'cache')
            backend.init()
            backend.save_settings(dict(settings=dict(country='Vietnam',genres=['jazz'],qualities={'fixture':'stream-id'})))
            backend.save_favorites(dict(favorites=[dict(STATION,variants=[STATION])]))
            atomic_json(backend.data/'sync.json',dict(account='fixture-account',links={'1':STATION['stationuuid']},pending={},matches={'1':dict(uuid=STATION['stationuuid'],stream=STATION['url'])}))
            integrations=live/'.config/quickshell/desktop/integrations'
            atomic_json(integrations/'nextcloud.json',dict(url='https://cloud.example/',username='fixture'))
            for name in ('nextcloud-app-password','nextcloud-music-api-key'):
                path=integrations/name;path.write_text('synthetic-fixture-secret\n');path.chmod(0o600)
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
            collision=restored/'.config/quickshell/desktop/spaces/radio/radio-ui.json'
            collision.parent.mkdir(parents=True,mode=0o700);collision.write_text('existing preferences')
            run(['bash',str(clone/'apply.sh')],restored)
            self.assertEqual(next(collision.parent.glob('radio-ui.json.before-private-*')).read_text(),'existing preferences')
            for path in paths:
                source=live/path.removeprefix('home/');target=restored/path.removeprefix('home/')
                self.assertEqual(target.read_bytes(),source.read_bytes())
                self.assertEqual(target.stat().st_mode&0o777,0o600)
                self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            result=RadioBackend(collision.parent,restored/'.local/share/quickshell/desktop/spaces/radio',root/'new-cache').init()
            self.assertEqual(result['settings']['genres'],['jazz'])
            self.assertEqual(result['settings']['qualities']['fixture'],'stream-id')
            self.assertEqual(result['favorites'][0]['variants'][0]['stationuuid'],STATION['stationuuid'])
            self.assertEqual(nextcloud.music_api_key(restored/'.config/quickshell/desktop/integrations'),'synthetic-fixture-secret')
            self.assertEqual(json.loads((restored/'.local/share/quickshell/desktop/spaces/radio/sync.json').read_text())['links']['1'],STATION['stationuuid'])
            self.assertEqual(json.loads((restored/'.local/share/quickshell/desktop/spaces/radio/sync.json').read_text())['matches']['1']['uuid'],STATION['stationuuid'])
