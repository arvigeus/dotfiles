"""Local-first favorite sync, remote membership, uncertain writes and shared secrets."""

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import support

sys.path.insert(0, str(support.DESKTOP))
from integrations import nextcloud
from spaces.radio import api
from spaces.radio.backend import RadioBackend
from spaces.radio.favorites import FavoritesStore
from spaces.radio.music import MusicClient, MusicError, NoRedirect
from spaces.radio.storage import read_json
from test_radio import STATION


class Cloud:
    account_id = 'fixture-account'

    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))
        self.calls = []
        self.offline = False
        self.lose = ''

    def stations(self):
        if self.offline:
            raise MusicError('Offline')
        return copy.deepcopy(self.rows)

    def request(self, method, **args):
        self.calls.append((method, args))
        if self.offline:
            raise MusicError('Offline')
        if method == 'createInternetRadioStation':
            identity = str(max([int(row['id']) for row in self.rows] + [0]) + 1)
            self.rows.append(
                dict(
                    id=identity,
                    name=args['name'],
                    streamUrl=args['streamUrl'],
                    homePageUrl=args['homepageUrl'],
                )
            )
        elif method == 'deleteInternetRadioStation':
            self.rows = [row for row in self.rows if str(row['id']) != str(args['id'])]
        elif method == 'updateInternetRadioStation':
            row = next(row for row in self.rows if str(row['id']) == str(args['id']))
            row.update(
                name=args['name'],
                streamUrl=args['streamUrl'],
                homePageUrl=args['homepageUrl'],
            )
        else:
            raise AssertionError(method)
        if self.lose == method:
            self.lose = ''
            raise MusicError('Response lost')
        return {}


def remote(identity='1', **values):
    return dict(
        dict(
            id=identity,
            name='Saved station',
            streamUrl='https://stream.example.invalid/live',
            homePageUrl='https://example.invalid',
        ),
        **values,
    )


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cloud = Cloud()
        self.store = FavoritesStore(
            self.root / 'data', client_factory=lambda: self.cloud
        )

    def test_first_sync_empty_local_imports_all_without_writes_and_can_play_directly(
        self,
    ):
        self.cloud.rows = [
            remote(),
            remote('2', name='Other station', streamUrl='https://other.example/live'),
        ]
        result = self.store.sync()
        self.assertEqual(len(result['favorites']), 2)
        self.assertEqual(self.cloud.calls, [])
        self.assertEqual(self.store.sync()['favorites'], result['favorites'])
        station = result['favorites'][0]
        self.assertEqual(station['source'], 'nextcloud')
        backend = RadioBackend(
            self.root / 'config', self.root / 'data', self.root / 'cache'
        )
        with patch.object(api, 'api_get') as network:
            self.assertEqual(
                backend.resolve(dict(station=station))['url'],
                self.cloud.rows[0]['streamUrl'],
            )
        network.assert_not_called()

    def test_local_add_remove_roundtrip_and_no_duplicate_creates(self):
        self.store.sync()
        self.store.save([STATION])
        self.store.sync()
        self.store.sync()
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertEqual(
            [call[0] for call in self.cloud.calls], ['createInternetRadioStation']
        )
        self.store.save([])
        self.store.sync()
        self.assertEqual(self.cloud.rows, [])
        self.assertEqual(self.store.read(), [])

    def test_initial_union_matches_urls_without_erasing_local_metadata_or_cloud_stations(
        self,
    ):
        self.cloud.rows = [remote()]
        variant = dict(
            STATION,
            stationuuid='22222222-2222-2222-2222-222222222222',
            bitrate=64,
            url='https://stream.example.invalid/low',
            url_resolved='https://stream.example.invalid/low',
        )
        self.store.save([dict(STATION, variants=[STATION, variant])])
        result = self.store.sync()['favorites']
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['variants']), 2)
        self.assertEqual(result[0]['country'], 'Vietnam')
        self.assertEqual(result[0]['name'], 'Saved station')
        self.assertEqual(self.cloud.calls, [])

    def test_remote_add_rename_url_change_and_removal_propagate(self):
        self.cloud.rows = [remote()]
        station = self.store.sync()['favorites'][0]
        identity = station['stationuuid']
        self.cloud.rows[0].update(name='Renamed', streamUrl='https://new.example/live')
        changed = self.store.sync()['favorites'][0]
        self.assertEqual(changed['name'], 'Renamed')
        self.assertEqual(changed['url'], 'https://new.example/live')
        self.assertEqual(changed['stationuuid'], identity)
        self.cloud.rows.append(
            remote('2', name='Second station', streamUrl='https://second.example/live')
        )
        self.assertEqual(len(self.store.sync()['favorites']), 2)
        self.cloud.rows = []
        self.assertEqual(self.store.sync()['favorites'], [])
        self.assertEqual(self.cloud.calls, [])

    def test_offline_local_save_and_removal_survive_a_new_worker_and_retry(self):
        self.store.sync()
        self.cloud.offline = True
        self.store.save([STATION])
        with self.assertRaises(MusicError):
            self.store.sync()
        self.assertEqual(len(self.store.read()), 1)
        self.cloud.offline = False
        restarted = FavoritesStore(self.store.data, client_factory=lambda: self.cloud)
        restarted.sync()
        self.cloud.offline = True
        restarted.save([])
        with self.assertRaises(MusicError):
            restarted.sync()
        self.cloud.offline = False
        restarted.sync()
        self.assertEqual(self.cloud.rows, [])

    def test_lost_create_response_reconciles_without_duplicate_and_honors_later_unstar(
        self,
    ):
        self.store.sync()
        self.store.save([STATION])
        self.cloud.lose = 'createInternetRadioStation'
        with self.assertRaisesRegex(MusicError, 'lost'):
            self.store.sync()
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertTrue(read_json(self.store.state_path, {})['pending'])
        self.store.sync()
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertEqual(len(self.cloud.calls), 1)
        self.store.save([])
        self.store.sync()
        self.store.save([STATION])
        self.cloud.lose = 'createInternetRadioStation'
        with self.assertRaises(MusicError):
            self.store.sync()
        self.store.save([])
        self.store.sync()
        self.assertEqual(self.cloud.rows, [])
        self.assertEqual(self.store.read(), [])

    def test_lost_delete_response_does_not_repeat_delete_or_resurrect_station(self):
        self.cloud.rows = [remote()]
        self.store.sync()
        self.store.save([])
        self.cloud.lose = 'deleteInternetRadioStation'
        with self.assertRaises(MusicError):
            self.store.sync()
        self.store.sync()
        self.assertEqual(self.store.read(), [])
        self.assertEqual(len(self.cloud.calls), 1)

    def test_concurrent_syncs_serialize_and_account_change_cannot_touch_other_server(
        self,
    ):
        self.store.save([STATION])
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _: self.store.sync(), range(2)))
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertEqual(len(self.cloud.calls), 1)
        self.cloud.account_id = 'other-account'
        with self.assertRaisesRegex(MusicError, 'account changed'):
            self.store.sync()
        self.assertEqual(len(self.cloud.calls), 1)

    def test_bad_state_or_remote_scheme_preserves_both_sides(self):
        self.store.save([STATION])
        self.cloud.rows = [remote(streamUrl='file:///etc/passwd')]
        with self.assertRaisesRegex(MusicError, 'non-HTTP'):
            self.store.sync()
        self.assertEqual(self.store.read()[0]['name'], STATION['name'])
        self.assertEqual(self.cloud.calls, [])
        self.store.state_path.write_text('{bad')
        with self.assertRaisesRegex(api.RadioError, 'preserved'):
            self.store.sync()
        self.assertEqual(self.cloud.calls, [])

    def test_missing_favorites_or_invalid_links_never_delete_remote_stations(self):
        self.cloud.rows = [remote()]
        self.store.sync()
        self.store.path.unlink()
        with self.assertRaisesRegex(MusicError, 'missing'):
            self.store.sync()
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertEqual(self.cloud.calls, [])
        self.store.save([])
        self.store.state_path.write_text(
            json.dumps(
                dict(account=self.cloud.account_id, links={'1': None}, pending={})
            )
        )
        with self.assertRaisesRegex(MusicError, 'invalid'):
            self.store.sync()
        self.assertEqual(len(self.cloud.rows), 1)
        self.assertEqual(self.cloud.calls, [])


class MusicClientTests(unittest.TestCase):
    def client(self, payload):
        opener = MagicMock()
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode()
        opener.open.return_value.__enter__.return_value = response
        return MusicClient(
            dict(url='https://cloud.example/nc/', username='alice'),
            key='synthetic-secret',
            opener=opener,
        )

    def test_post_credentials_share_account_and_never_enter_url_or_provider_errors(
        self,
    ):
        client = self.client(
            {
                'subsonic-response': {
                    'status': 'ok',
                    'internetRadioStations': {'internetRadioStation': [remote()]},
                }
            }
        )
        self.assertEqual(client.stations()[0]['id'], '1')
        request = client.opener.open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            'https://cloud.example/nc/index.php/apps/music/subsonic/rest/getInternetRadioStations.view',
        )
        self.assertEqual(parse_qs(request.data.decode())['p'], ['synthetic-secret'])
        self.assertNotIn('synthetic-secret', request.full_url)
        malformed = self.client({'subsonic-response': {'status': 'ok'}})
        with self.assertRaisesRegex(MusicError, 'omitted'):
            malformed.stations()
        client = self.client(
            {
                'subsonic-response': {
                    'status': 'failed',
                    'error': {'code': 40, 'message': 'echo synthetic-secret'},
                }
            }
        )
        with self.assertRaises(MusicError) as raised:
            client.stations()
        self.assertNotIn('synthetic-secret', str(raised.exception))
        with self.assertRaises(MusicError):
            NoRedirect().redirect_request(
                None, None, 302, '', {}, 'https://evil.example/'
            )

    def test_shared_music_secret_has_same_permission_and_symlink_rules_as_dav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / 'nextcloud-music-api-key'
            with self.assertRaises(nextcloud.CredentialMissing):
                nextcloud.music_api_key(root)
            key.write_text('synthetic-secret\n')
            key.chmod(0o600)
            self.assertEqual(nextcloud.music_api_key(root), 'synthetic-secret')
            key.chmod(0o644)
            with self.assertRaises(nextcloud.NextcloudError):
                nextcloud.music_api_key(root)
            key.unlink()
            target = root / 'target'
            target.write_text('secret')
            key.symlink_to(target)
            with self.assertRaises(nextcloud.NextcloudError):
                nextcloud.music_api_key(root)
