"""Beat-time matching, stale cache preservation, local artwork and private restore."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.games import hltb, presentation
from spaces.games.backend import GamesBackend


class BeatTimeTests(unittest.TestCase):
    def test_strict_links_and_unavailable_durations(self):
        self.assertEqual(hltb.game_id('https://howlongtobeat.com/game/12'), '12')
        for value in [
            '0',
            '-1',
            'https://evil.invalid/game/12',
            'https://howlongtobeat.com.evil/game/12',
            'https://howlongtobeat.com/game/12?x=1',
        ]:
            with self.assertRaises(hltb.HltbError):
                hltb.game_id(value)
        result = hltb.normalize(
            dict(game_id=12, comp_main=36000, comp_plus=0, comp_100='bad')
        )
        self.assertEqual(result['main'], 10)
        self.assertIsNone(result['extras'])
        self.assertIsNone(result['complete'])

    def test_search_auth_headers_and_refresh(self):
        calls = []

        def transport(path, body=None, headers=None):
            calls.append((path, body, headers))
            if path.endswith('/init'):
                return json.dumps(
                    dict(token='temporary', opaqueKey='field', opaqueVal='value')
                )
            self.assertEqual(json.loads(body)['field'], 'value')
            self.assertEqual(headers['x-auth-token'], 'temporary')
            return json.dumps(
                dict(data=[dict(game_id=1, game_name='Example', comp_main=3600)])
            )

        result = hltb.Client(transport).lookup('Example')
        self.assertEqual(result['main'], 1)
        self.assertEqual(len(calls), 2)

    def test_ambiguous_titles_and_wrong_steam_identity_require_correction(self):
        client = hltb.Client()
        record = dict(game_id=1, game_name='Example', comp_main=7200)
        client.search = Mock(return_value=[record, dict(record, game_id=2)])
        self.assertIn('No unique match', client.lookup('Example')['warning'])
        client.search.return_value = [dict(record, profile_steam=124)]
        self.assertIn('different Steam', client.lookup('Example', '123')['warning'])
        client.search.return_value = [
            dict(record, profile_steam=123),
            dict(record, game_id=2),
        ]
        self.assertEqual(client.lookup('Example', '123')['main'], 2)

    def test_manual_game_link_reads_only_the_selected_page(self):
        raw = dict(game_id=5, game_name='Edition', comp_main=10800)
        payload = {'props': {'pageProps': {'game': {'data': {'game': [raw]}}}}}
        transport = Mock(
            return_value='<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + '</script>'
        )
        result = hltb.Client(transport).lookup('Example', override='5')
        transport.assert_called_once_with('/game/5')
        self.assertEqual(result['main'], 3)

    def test_nested_search_route_discovery_stays_on_provider_origin(self):
        def transport(path, *args):
            if path == '/':
                return '<script src="https://evil.invalid/a.js"></script><script src="/a.js"></script>'
            self.assertEqual(path, '/a.js')
            return 'searchTerms searchOptions "/api/search/new/init"'

        client = hltb.Client(transport)
        client.discover()
        self.assertEqual(client.endpoint, '/api/search/new')


class GamesPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.config = self.home / '.config/quickshell/desktop/spaces/games/games.json'
        self.config.parent.mkdir(parents=True, mode=0o700)
        self.config.write_text('{}')
        self.config.chmod(0o600)
        self.data = self.home / '.local/share/quickshell/desktop/spaces/games'
        self.backend = GamesBackend(
            self.config, self.data, env={'HOME': str(self.home), 'PATH': ''}
        )
        self.backend.libraries = lambda force=False: {}
        self.game = self.backend._save_game(
            'fixture',
            dict(
                catalogProvider='fixture', catalogProviderId='fixture', title='Example'
            ),
        )

    def test_stale_times_survive_restart_offline_and_match_changes_preserve_favorites(
        self,
    ):
        self.backend.beat_times.lookup = Mock(return_value=dict(main=12, id='12'))
        request = dict(gameId=self.game['id'])
        self.assertEqual(self.backend.howlongtobeat(request)['main'], 12)
        self.backend.beat_times.lookup.side_effect = hltb.HltbError('offline')
        self.backend._clock = lambda: 10**12
        result = self.backend.howlongtobeat(request)
        self.assertEqual(result['main'], 12)
        self.assertTrue(result['stale'])
        cooling = self.backend.howlongtobeat(request)
        self.assertTrue(cooling['stale'])
        self.assertIn('Showing saved times', cooling['warning'])
        self.assertEqual(self.backend.beat_times.lookup.call_count, 2)
        self.backend.set_favorite(dict(request, favorite=True))
        self.backend.set_hltb_match(
            dict(request, externalId='https://howlongtobeat.com/game/20')
        )
        reopened = GamesBackend(self.config, self.data)
        with reopened._db() as connection:
            self.assertEqual(
                connection.execute('SELECT external_id FROM hltb_matches').fetchone()[
                    0
                ],
                '20',
            )
        self.assertTrue(reopened._favorite_games('', 0)['items'][0]['favorite'])
        self.backend.set_hltb_match(dict(request, externalId=''))
        with self.backend._db() as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM hltb_matches').fetchone()[0], 0
            )

    def test_custom_art_and_playtime_use_current_account_only(self):
        steam = self.home / '.steam/steam'
        user = steam / 'userdata/123'
        grid = user / 'config/grid'
        grid.mkdir(parents=True)
        (steam / 'steamapps').mkdir()
        (steam / 'config').mkdir()
        (steam / 'config/loginusers.vdf').write_text(
            '"users" { "76561197960265851" { "MostRecent" "1" } }'
        )
        (grid / '620_logo.png').write_bytes(b'fixture')
        (user / 'config/localconfig.vdf').write_text(
            '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { "620" { "Playtime" "150" "LastPlayed" "1700000000" } } } } } }'
        )
        result = self.backend.presentation(dict(gameId=self.game['id']))
        self.assertEqual(result, {})
        result = presentation.read(self.backend, '620')
        self.assertIn('620_logo.png?v=', result['logo'])
        self.assertEqual(result['playHours'], 2.5)
        self.assertTrue(result['lastPlayed'])
        (steam / 'config/loginusers.vdf').unlink()
        (steam / 'userdata/456').mkdir()
        self.assertNotIn('playHours', presentation.read(self.backend, '620'))

    def test_local_game_import_uses_owned_database_and_preserves_personal_state(self):
        title = dict(self.game, kind='game')
        source = self.root / 'setup.zip'
        source.write_bytes(b'fixture archive')
        self.backend.set_favorite(dict(gameId=self.game['id'], favorite=True))
        with patch.dict(os.environ, XDG_DATA_HOME=str(self.home / '.local/share')):
            self.backend.local.add(title, source, preserve_name=True)
            rows = self.backend.handle(dict(op='local_list'))
            self.assertEqual(rows[0]['id'], self.game['id'])
            files = self.backend.handle(dict(op='local_files', title=title))
            self.assertTrue(Path(files[0]['path']).is_relative_to(self.data))
        self.assertTrue(self.backend._favorite_games('', 0)['items'][0]['favorite'])

    def test_backup_clone_and_restore_keep_matches_favorites_and_modes(self):
        request = dict(gameId=self.game['id'])
        self.backend.set_favorite(dict(request, favorite=True))
        self.backend.set_hltb_match(dict(request, externalId='15'))
        preferences = self.config.with_name('games-ui.ini')
        preferences.write_text('[catalogue]\ngrid=true\n')
        preferences.chmod(0o600)
        module = json.loads(
            (support.REPO / 'modules/desktop/quickshell/config.json').read_text()
        )
        paths = [
            path
            for path in module['extra']['private']['files']
            if '/spaces/games/' in path
        ]
        self.assertEqual(len(paths), 3)
        shared = 'home/.config/quickshell/desktop/integrations/torrents.json'
        self.assertEqual(module['extra']['private']['files'].count(shared), 1)
        paths.append(shared)
        torrents = self.home / shared.removeprefix('home/')
        torrents.parent.mkdir(parents=True, mode=0o700)
        torrents.write_text('{"url":"http://127.0.0.1:8080"}')
        torrents.chmod(0o600)
        declaration = self.root / 'selected.json'
        declaration.write_text(json.dumps({'extra': {'private': {'files': paths}}}))
        private = self.root / 'private'

        def run(argv, home):
            result = subprocess.run(
                argv,
                env={
                    **os.environ,
                    'HOME': str(home),
                    'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_CONFIG_NOSYSTEM': '1',
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        run(
            [
                'bash',
                str(support.REPO / 'backup.sh'),
                '--config',
                str(declaration),
                '--destination',
                str(private),
            ],
            self.home,
        )
        run(['git', '-C', str(private), 'add', '.'], self.home)
        run(
            [
                'git',
                '-C',
                str(private),
                '-c',
                'user.name=Fixture',
                '-c',
                'user.email=fixture@example.invalid',
                'commit',
                '-qm',
                'Fixture',
            ],
            self.home,
        )
        clone = self.root / 'clone'
        run(
            ['git', 'clone', '--quiet', '--no-hardlinks', str(private), str(clone)],
            self.home,
        )
        restored = self.root / 'restored'
        restored.mkdir()
        run(['bash', str(clone / 'apply.sh')], restored)
        for path in paths:
            relative = path.removeprefix('home/')
            self.assertEqual(
                (self.home / relative).read_bytes(), (restored / relative).read_bytes()
            )
            self.assertEqual((restored / relative).stat().st_mode & 0o777, 0o600)
        restored_backend = GamesBackend(
            restored / self.config.relative_to(self.home),
            restored / self.data.relative_to(self.home),
        )
        with restored_backend._db() as connection:
            self.assertEqual(
                connection.execute('SELECT external_id FROM hltb_matches').fetchone()[
                    0
                ],
                '15',
            )
        self.assertTrue(restored_backend._favorite_games('', 0)['items'][0]['favorite'])
