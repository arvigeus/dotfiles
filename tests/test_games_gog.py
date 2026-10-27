"""Heroic GOG caches, safe store identities and launcher handoffs with no accounts."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.games import backend, gog, igdb


class GogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.native = self.home / 'config/heroic'
        self.flatpak = self.home / '.var/app' / gog.APP_ID / 'config/heroic'
        self.install = self.home / 'Games/A game with spaces'
        self.install.mkdir(parents=True)
        self.env = dict(
            HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / 'config'), PATH=''
        )
        self.which = lambda name: '/bin/heroic' if name == 'heroic' else None
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
        self.record = dict(
            app_name='1234567890',
            title='Shared Game',
            art_square='https://images.gog.com/cover.jpg',
            art_background='https://images.gog.com/background.jpg',
            store_url='https://www.gog.com/en/game/shared_game',
            developer='Developer',
            extra=dict(
                about=dict(description='<p>GOG description</p>'), genres=['Adventure']
            ),
            install=dict(is_dlc=False),
            is_linux_native=True,
        )
        self.write_profile(self.native, [self.record], installed=True)

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def write_profile(self, root, games, installed=False, legacy=False):
        self.write_json(root / gog.LIBRARY_PATHS[int(legacy)], dict(games=games))
        self.write_json(
            root / 'gog_store/installed.json',
            dict(
                installed=[
                    dict(
                        appName='1234567890',
                        install_path=str(self.install),
                        platform='windows',
                    )
                ]
                if installed
                else []
            ),
        )

    def read(self):
        return gog.read(self.env, self.which, self.runner)

    def make_backend(self):
        config = self.home / 'games.json'
        config.write_text('{}')
        result = backend.GamesBackend(
            config,
            self.home / 'data',
            env=self.env,
            request=Mock(side_effect=AssertionError('Unexpected network request')),
        )
        result._which = self.which
        result._spawn_detached = Mock()
        self.state = self.read()
        result._library_snapshot = {'gog': self.state}
        result._library_updated = result._clock()
        self.game = result._save_game(
            'gog-fixture',
            dict(
                catalogProvider='fixture',
                catalogProviderId='gog-fixture',
                title='Shared Game',
                storeReferences=[dict(store='gog', externalId='1234567890')],
            ),
        )
        return result

    def test_current_native_cache_keeps_metadata_and_real_install_without_reading_auth(
        self,
    ):
        auth = self.native / 'gog_store/auth.json'
        auth.write_text('DO NOT READ')
        with patch.object(gog, '_read', wraps=gog._read) as reader:
            state = self.read()
        self.assertTrue(
            state['ownershipKnown']
            and state['installationKnown']
            and state['available']
        )
        self.assertEqual(state['command'], ['/bin/heroic'])
        self.assertEqual(state['ownedIds'], ['1234567890'])
        item = state['items'][0]
        self.assertTrue(item['installed'] and item['launchable'])
        self.assertEqual(item['metadata']['summary'], 'GOG description')
        self.assertEqual(item['metadata']['cover']['url'], self.record['art_square'])
        self.assertEqual(item['metadata']['platforms'], ['Linux'])
        self.assertNotIn(auth, [call.args[0] for call in reader.call_args_list])

    def test_flatpak_cache_uses_flatpak_launcher_and_does_not_merge_accounts(self):
        self.write_profile(
            self.flatpak,
            [dict(self.record, app_name='9876543210', title='Other account')],
        )
        self.which = lambda name: (
            '/bin/' + name if name in {'heroic', 'flatpak'} else None
        )
        self.assertEqual(self.read()['ownedIds'], ['1234567890'])
        (self.native / gog.LIBRARY_PATHS[0]).unlink()
        (self.native / 'gog_store/installed.json').unlink()
        state = self.read()
        self.assertEqual(state['ownedIds'], ['9876543210'])
        self.assertEqual(state['command'], ['/bin/flatpak', 'run', gog.APP_ID])
        self.runner.return_value = subprocess.CompletedProcess([], 1, '', '')
        state = self.read()
        self.assertFalse(state['available'])
        self.assertEqual(state['ownedIds'], ['9876543210'])
        self.assertEqual(state['command'], [])

    def test_missing_launcher_preserves_cached_games_without_claiming_launchability(
        self,
    ):
        self.which = lambda name: None
        state = self.read()
        self.assertTrue(state['ownershipKnown'] and state['items'][0]['installed'])
        self.assertFalse(state['available'] or state['items'][0]['launchable'])
        row = backend.derive_store_state(dict(title='Shared Game'), {'gog': state})[2]
        self.assertEqual(row['primaryAction']['type'], 'disabled')
        self.assertEqual(row['actions'], [])

    def test_legacy_cache_is_supported_and_corrupt_current_cache_is_not_silently_replaced(
        self,
    ):
        (self.native / gog.LIBRARY_PATHS[0]).unlink()
        self.write_profile(self.native, [self.record], legacy=True)
        self.assertEqual(self.read()['ownedIds'], ['1234567890'])
        (self.native / gog.LIBRARY_PATHS[0]).write_text('{broken')
        state = self.read()
        self.assertFalse(state['ownershipKnown'])
        self.assertIn('could not be read', state['message'])

    def test_unknown_or_malformed_caches_do_not_claim_nonownership_or_offer_install(
        self,
    ):
        (self.native / gog.LIBRARY_PATHS[0]).unlink()
        state = self.read()
        row = backend.derive_store_state(dict(title='Shared Game'), {'gog': state})[2]
        self.assertEqual(row['ownership'], 'unknown')
        self.assertIn('Sign into GOG', row['ownershipLabel'])
        self.write_profile(self.native, [self.record])
        self.write_json(
            self.native / 'gog_store/installed.json', dict(installed='broken')
        )
        state = self.read()
        row = backend.derive_store_state(dict(title='Shared Game'), {'gog': state})[2]
        self.assertTrue(state['ownershipKnown'])
        self.assertFalse(state['installationKnown'])
        self.assertEqual(row['primaryAction']['type'], 'disabled')
        self.write_json(self.native / gog.LIBRARY_PATHS[0], dict(games='broken'))
        self.assertFalse(self.read()['ownershipKnown'])

    def test_missing_install_registry_allows_install_but_missing_directory_does_not_offer_play(
        self,
    ):
        self.install.rmdir()
        state = self.read()
        self.assertFalse(state['items'][0]['installed'])
        self.assertEqual(
            backend.derive_store_state(dict(title='Shared Game'), {'gog': state})[2][
                'primaryAction'
            ]['type'],
            'install',
        )
        (self.native / 'gog_store/installed.json').unlink()
        self.assertTrue(self.read()['installationKnown'])

    def test_filters_dlc_invalid_product_ids_and_nonabsolute_install_paths(self):
        self.write_profile(
            self.native,
            [
                self.record,
                dict(self.record, app_name='gog-redist'),
                dict(self.record, app_name='--help'),
                dict(self.record, app_name='234', install=dict(is_dlc=True)),
            ],
        )
        self.write_json(
            self.native / 'gog_store/installed.json',
            dict(
                installed=[
                    dict(appName='1234567890', install_path='.', platform='windows'),
                    dict(
                        appName='--help',
                        install_path=str(self.install),
                        platform='windows',
                    ),
                ]
            ),
        )
        state = self.read()
        self.assertEqual(state['ownedIds'], ['1234567890'])
        self.assertFalse(state['items'][0]['installed'])
        with patch.object(gog, 'MAX_CACHE_BYTES', 8):
            self.assertFalse(self.read()['ownershipKnown'])

    def test_gog_websites_normalize_and_resist_foreign_hosts_options_and_credentials(
        self,
    ):
        urls = [
            'https://gog.com/game/shared_game',
            'https://www.gog.com/en/game/shared_game',
        ]
        for url in urls:
            game = igdb.normalize(
                dict(id=1, name='Shared Game', websites=[dict(url=url)])
            )
            self.assertEqual(
                game['storeReferences'],
                [
                    dict(
                        store='gog',
                        externalId='shared_game',
                        url='https://www.gog.com/en/game/shared_game',
                    )
                ],
            )
        for url in [
            'http://gog.com/game/shared_game',
            'https://gog.com.evil/game/shared_game',
            'https://user@gog.com/game/shared_game',
            'https://gog.com:8443/game/shared_game',
            'https://gog.com/game/shared_game?command=x',
            'https://gog.com/account',
        ]:
            self.assertEqual(gog.store_url(url), '')
        for identifier in ['0', '-1', '--help', '1;rm', 'abc', '1/2']:
            self.assertEqual(gog.product_id(identifier), '')

    def test_matching_uses_product_id_or_unique_slug_and_keeps_explicit_numeric_identity(
        self,
    ):
        items = self.read()['items']
        for identifier in ['1234567890', 'shared_game']:
            game = dict(
                title='Unrelated',
                storeReferences=[dict(store='gog', externalId=identifier)],
            )
            match, source = backend.match_library_item(game, 'gog', items)
            self.assertEqual((match['externalId'], source), ('1234567890', 'store-id'))
        game = dict(
            title='Shared Game', storeReferences=[dict(store='gog', externalId='111')]
        )
        self.assertIsNone(backend.match_library_item(game, 'gog', items)[0])
        self.assertIsNone(
            backend.match_library_item(dict(title='Shared Game Deluxe'), 'gog', items)[
                0
            ]
        )
        self.assertIsNone(
            backend.match_library_item(dict(title='Shared Game'), 'gog', items * 2)[0]
        )

    def test_store_actions_use_owned_install_play_buy_and_heroic_management(self):
        game = dict(title='Shared Game')
        state = self.read()
        row = backend.derive_store_state(game, {'gog': state})[2]
        self.assertEqual(row['primaryAction']['type'], 'play')
        self.assertEqual(
            [action['type'] for action in row['actions']], ['play', 'manage']
        )
        self.write_profile(self.native, [self.record])
        state = self.read()
        row = backend.derive_store_state(game, {'gog': state})[2]
        self.assertEqual(row['primaryAction']['type'], 'install')
        self.assertIn('installation prompt', row['primaryAction']['tooltip'])
        game['storeReferences'] = [
            dict(
                store='gog',
                externalId='another_game',
                url='https://gog.com/game/another_game',
            )
        ]
        game['title'] = 'Another Game'
        row = backend.derive_store_state(game, {'gog': state})[2]
        self.assertEqual(row['primaryAction']['type'], 'buy')
        self.assertEqual(row['storeUrl'], 'https://www.gog.com/en/game/another_game')

    def test_library_merges_three_stores_keeps_unique_gog_games_and_favorites(self):
        worker = self.make_backend()
        self.write_profile(
            self.native,
            [self.record, dict(self.record, app_name='222', title='Only on GOG')],
            installed=True,
        )
        worker._library_snapshot = {
            'gog': self.read(),
            **{
                store: dict(
                    available=True,
                    ownershipKnown=True,
                    installationKnown=True,
                    ownedIds=[identifier],
                    items=[
                        dict(
                            store=store,
                            externalId=identifier,
                            title='Shared Game',
                            installed=False,
                        )
                    ],
                )
                for store, identifier in [('steam', '620'), ('epic', 'EpicShared')]
            },
        }
        games = worker.library_games({})['items']
        self.assertEqual(len(games), 2)
        shared = next(game for game in games if game['title'] == 'Shared Game')
        self.assertEqual(shared['libraryStores'], ['steam', 'epic', 'gog'])
        self.assertEqual(shared['ownedBy'], ['steam', 'epic', 'gog'])
        self.assertEqual(shared['installedBy'], ['gog'])
        self.assertEqual(shared['cover']['url'], self.record['art_square'])
        self.assertEqual(len(worker.library_games(dict(mode='owned'))['items']), 2)
        self.assertEqual(len(worker.library_games(dict(mode='installed'))['items']), 1)
        worker.set_favorite(dict(gameId=shared['id'], favorite=True))
        worker.handle(
            dict(
                op='set_match',
                gameId=shared['id'],
                store='gog',
                externalId='1234567890',
            )
        )
        self.assertTrue(
            next(
                game
                for game in worker.library_games({})['items']
                if game['id'] == shared['id']
            )['favorite']
        )
        self.assertEqual(worker._store_overrides(shared['id'])['gog'], '1234567890')
        with self.assertRaises(backend.GamesError):
            worker.handle(
                dict(
                    op='set_match',
                    gameId=shared['id'],
                    store='gog',
                    externalId='--help',
                )
            )

    def test_heroic_launch_install_manage_handoffs_use_verified_arguments(self):
        worker = self.make_backend()
        request = dict(gameId=self.game['id'], actionId='gog:play:1234567890')
        self.assertTrue(worker.action(request)['handoff'])
        self.assertEqual(
            worker._spawn_detached.call_args.args[0],
            ['/bin/heroic', 'heroic://launch/gog/1234567890'],
        )
        self.write_profile(self.native, [self.record])
        worker._library_snapshot['gog'] = self.read()
        self.assertTrue(
            worker.action(dict(request, actionId='gog:install:1234567890'))['handoff']
        )
        self.assertEqual(
            worker._spawn_detached.call_args.args[0],
            ['/bin/heroic', 'heroic://launch/gog/1234567890'],
        )
        self.assertTrue(worker.action(dict(request, actionId='gog:manage'))['handoff'])
        self.assertEqual(worker._spawn_detached.call_args.args[0], ['/bin/heroic'])
        with self.assertRaises(backend.GamesError):
            worker.action(dict(request, actionId='gog:uninstall:1234567890'))

    def test_action_rechecks_installations_ownership_and_launcher_before_handoff(self):
        worker = self.make_backend()
        request = dict(gameId=self.game['id'], actionId='gog:play:1234567890')
        self.install.rmdir()
        with self.assertRaisesRegex(backend.GamesError, 'installed and launchable'):
            worker.action(request)
        self.assertFalse(worker._spawn_detached.called)
        worker._library_snapshot['gog'] = self.read()
        (self.native / gog.LIBRARY_PATHS[0]).unlink()
        with self.assertRaises(backend.GamesError):
            worker.action(dict(request, actionId='gog:install:1234567890'))
        self.which = lambda name: None
        worker._which = self.which
        with self.assertRaisesRegex(backend.GamesError, 'not available'):
            worker.action(dict(request, actionId='gog:manage'))
        self.assertFalse(worker._spawn_detached.called)


if __name__ == '__main__':
    unittest.main()
