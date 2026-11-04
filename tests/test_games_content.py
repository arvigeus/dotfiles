"""Native content labels, identity isolation, caching and unsupported stores."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.games import backend, content


def steam_response(identifier='123', ids=None):
    return {
        identifier: dict(
            success=True,
            data=dict(
                steam_appid=int(identifier),
                content_descriptors=dict(ids=ids or []),
            ),
        )
    }


def gog_response(identifier='456', slugs=None):
    return dict(
        _embedded=dict(
            product=dict(id=int(identifier)),
            properties=[dict(slug=slug) for slug in (slugs or [])],
        )
    )


class ContentParsingTests(unittest.TestCase):
    def test_steam_explicit_and_frequent_sexual_content_only(self):
        for ids, expected in [
            ([], False),
            ([1, 2, 5], False),
            ([3, 5], True),
            ([1, 4, 5], True),
        ]:
            with self.subTest(ids=ids):
                self.assertIs(content.steam(steam_response(ids=ids), '123'), expected)

    def test_gog_uses_native_nsfw_property_and_does_not_guess_from_maturity(self):
        self.assertIs(content.gog(gog_response(slugs=['nsfw']), '456'), True)
        self.assertIs(
            content.gog(
                gog_response(slugs=['mature', 'nudity', 'sexual-content']), '456'
            ),
            False,
        )
        self.assertIs(content.gog(gog_response(), '456'), False)
        raw = gog_response()
        del raw['_embedded']['properties']
        raw['_embedded']['tags'] = [dict(slug='nsfw')]
        self.assertIsNone(content.gog(raw, '456'))

    def test_malformed_missing_or_other_product_data_remains_unknown(self):
        for raw in [
            None,
            {},
            {'123': None},
            {'123': dict(success=False)},
            steam_response('124'),
            {
                '123': dict(
                    success=True,
                    data=dict(steam_appid=124, content_descriptors=dict(ids=[3])),
                )
            },
            steam_response(ids=['3']),
            steam_response(ids=[True]),
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(content.steam(raw, '123'))
        for raw in [
            None,
            {},
            gog_response('457'),
            {'_embedded': {'product': {'id': 456}}},
            {'_embedded': {'product': {'id': 456}, 'properties': [None]}},
            {'_embedded': {'product': {'id': 456}, 'properties': [{'name': 'NSFW'}]}},
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(content.gog(raw, '456'))


class ContentBackendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        config = self.root / 'games.json'
        config.write_text('{}')
        self.now = 1000000
        self.request = Mock(side_effect=backend.GamesError('private provider error'))
        self.worker = backend.GamesBackend(
            config,
            self.root / 'data',
            env=dict(HOME=str(self.root), PATH=''),
            request=self.request,
            clock=lambda: self.now,
        )

    def game(self, references):
        return self.worker._save_game(
            str(len(references)) + json.dumps(references),
            dict(
                catalogProvider='fixture',
                catalogProviderId=json.dumps(references),
                title='Same title',
                storeReferences=[
                    dict(store=store, externalId=identifier)
                    for store, identifier in references
                ],
            ),
        )

    def rating(self, game, **values):
        return self.worker.handle(
            dict(op='content_rating', gameId=game['id'], **values)
        )['content']

    def test_list_is_lazy_and_labels_are_cached_per_product_across_restart(self):
        game = self.game([('gog', '456')])
        initial = self.worker._with_library_indicators([game])[0]['content']
        self.assertEqual(initial, dict(supported=True, nsfw=None, pending=True))
        self.request.assert_not_called()
        self.request.side_effect = None
        self.request.return_value = gog_response(slugs=['nsfw'])
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertIn('/v2/games/456?', self.request.call_args.args[0])
        self.assertFalse(self.rating(game)['pending'])
        self.assertEqual(self.request.call_count, 1)
        self.worker = backend.GamesBackend(
            self.root / 'games.json',
            self.root / 'data',
            env=dict(PATH=''),
            request=self.request,
            clock=lambda: self.now,
        )
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertEqual(self.request.call_count, 1)

    def test_steam_content_fetch_also_fills_description_cache(self):
        game = self.game([('steam', '123')])
        self.request.side_effect = None
        self.request.return_value = steam_response(ids=[4])
        self.request.return_value['123']['data']['short_description'] = 'Store summary'
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertEqual(
            self.worker._cache_get('steam-metadata:v1:123')[0]['summary'],
            'Store summary',
        )

    def test_listing_does_not_wait_for_an_inflight_content_request(self):
        game = self.game([('gog', '456')])
        entered, release = threading.Event(), threading.Event()

        def request(*args):
            entered.set()
            release.wait(3)
            return gog_response()

        self.request.side_effect = request
        with ThreadPoolExecutor(max_workers=2) as pool:
            fetching = pool.submit(self.rating, game)
            try:
                self.assertTrue(entered.wait(1))
                listing = pool.submit(self.worker._with_library_indicators, [game])
                self.assertIsNone(listing.result(timeout=0.3)[0]['content']['nsfw'])
            finally:
                release.set()
            self.assertIs(fetching.result(timeout=1)['nsfw'], False)

    def test_simultaneous_steam_metadata_and_labels_share_one_request(self):
        game = self.game([('steam', '123')])
        entered, release, duplicate = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def request(*args):
            if entered.is_set():
                duplicate.set()
            entered.set()
            release.wait(3)
            raw = steam_response()
            raw['123']['data']['short_description'] = 'Shared metadata'
            return raw

        self.request.side_effect = request
        with ThreadPoolExecutor(max_workers=2) as pool:
            labels = pool.submit(self.rating, game)
            try:
                self.assertTrue(entered.wait(1))
                metadata = pool.submit(
                    self.worker.library_metadata, dict(gameId=game['id'])
                )
                duplicate.wait(0.3)
            finally:
                release.set()
            self.assertIs(labels.result(timeout=1)['nsfw'], False)
            self.assertEqual(
                metadata.result(timeout=1)['game']['summary'], 'Shared metadata'
            )
        self.assertEqual(self.request.call_count, 1)

    def test_steam_outage_pauses_other_products_and_metadata_too(self):
        first = self.game([('steam', '123')])
        second = self.game([('steam', '124')])
        self.assertIsNone(self.rating(first)['nsfw'])
        self.assertIsNone(self.rating(second, refresh=True)['nsfw'])
        self.worker.library_metadata(dict(gameId=second['id']))
        self.assertEqual(self.request.call_count, 1)
        self.assertFalse(
            self.worker._with_library_indicators([second])[0]['content']['pending']
        )
        self.now += 301
        self.rating(second)
        self.assertEqual(self.request.call_count, 2)

    def test_library_refresh_allows_one_new_probe_after_steam_outage(self):
        game = self.game([('steam', '123')])
        self.rating(game)
        self.worker.libraries = Mock(return_value={})
        self.worker.handle(dict(op='refresh_libraries'))
        self.request.side_effect = None
        self.request.return_value = steam_response()
        self.assertIs(self.rating(game, refresh=True)['nsfw'], False)
        self.assertEqual(self.request.call_count, 2)

    def test_unavailable_steam_product_does_not_pause_other_games(self):
        first = self.game([('steam', '123')])
        second = self.game([('steam', '124')])
        self.request.side_effect = [dict(), steam_response('124')]
        self.assertIsNone(self.rating(first)['nsfw'])
        self.assertIs(self.rating(second)['nsfw'], False)
        self.assertEqual(self.request.call_count, 2)

    def test_any_explicit_store_label_wins_and_unknown_is_never_safe(self):
        game = self.game([('steam', '123'), ('gog', '456'), ('epic', 'EpicGame')])
        self.worker._cache_put('native-content:v1:steam:123', False)
        self.assertIsNone(
            self.worker._with_library_indicators([game])[0]['content']['nsfw']
        )
        self.worker._cache_put('native-content:v1:gog:456', True)
        self.assertIs(self.rating(game)['nsfw'], True)
        self.request.assert_not_called()

    def test_failure_keeps_stale_positive_and_cools_down_without_exposing_errors(self):
        game = self.game([('gog', '456')])
        self.worker._cache_put('native-content:v1:gog:456', True)
        self.now += 8 * 86400
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertEqual(self.request.call_count, 1)
        self.assertNotIn('private', str(self.rating(game)))
        self.now += 301
        self.rating(game)
        self.assertEqual(self.request.call_count, 2)

    def test_unknown_failure_stays_unknown_and_explicit_refresh_retries(self):
        game = self.game([('gog', '456')])
        self.assertEqual(
            self.rating(game), dict(supported=True, nsfw=None, pending=False)
        )
        self.rating(game)
        self.assertEqual(self.request.call_count, 1)
        self.request.side_effect = None
        self.request.return_value = gog_response()
        self.assertIs(self.rating(game, refresh=True)['nsfw'], False)

    def test_product_mismatch_cannot_classify_and_overrides_replace_cached_identity(
        self,
    ):
        game = self.game([('gog', '456')])
        self.request.side_effect = None
        self.request.return_value = gog_response('999', ['nsfw'])
        self.assertIsNone(self.rating(game)['nsfw'])
        self.worker._cache_put('native-content:v1:gog:456', True)
        self.worker._save_store_match(game['id'], 'gog', '789')
        self.request.return_value = gog_response('789')
        self.assertIs(self.rating(game)['nsfw'], False)
        self.assertIn('/v2/games/789?', self.request.call_args.args[0])

    def test_epic_local_and_unresolved_gog_slugs_are_unsupported(self):
        for references in [[('epic', 'EpicGame')], [], [('gog', 'a_game')]]:
            game = self.game(references)
            self.assertEqual(
                self.rating(game), dict(supported=False, nsfw=None, pending=False)
            )
        self.request.assert_not_called()

    def test_gog_slug_resolves_through_exact_heroic_product_match(self):
        game = self.game([('gog', 'same_title')])
        self.worker._library_snapshot = dict(
            gog=dict(
                items=[dict(externalId='456', title='Same title', slug='same_title')]
            )
        )
        self.request.side_effect = None
        self.request.return_value = gog_response(slugs=['nsfw'])
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertIn('/v2/games/456?', self.request.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
