"""Native content labels, identity isolation, caching and unsupported stores."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

import support

sys.path.insert(0, str(support.DESKTOP))
from spaces.games import backend, content


def steam_item(identifier='123', ids=None, linux=False, success=1):
    """One IStoreBrowseService/GetItems store item."""
    item = dict(
        appid=int(identifier),
        success=success,
        platforms=dict(windows=True, **({'steamos_linux': True} if linux else {})),
    )
    if ids:
        item['content_descriptorids'] = ids
    return item


def steam_items(*items):
    return dict(response=dict(store_items=list(items)))


def write_appinfo(path, apps, magic=content.APPINFO_MAGIC):
    """Write a Steam client appinfo.vdf v29 cache with string-table keys."""
    strings = []

    def key(name):
        if name not in strings:
            strings.append(name)
        return struct.pack('<I', strings.index(name))

    def values(record):
        encoded = b''
        for name, value in record.items():
            if isinstance(value, dict):
                encoded += b'\x00' + key(name) + values(value) + b'\x08'
            elif isinstance(value, int):
                encoded += b'\x02' + key(name) + struct.pack('<i', value)
            else:
                encoded += b'\x01' + key(name) + value.encode() + b'\x00'
        return encoded

    entries = b''
    for app_id, record in apps.items():
        body = (
            struct.pack('<IIQ', 2, 0, 0)
            + bytes(20)
            + struct.pack('<I', 1)
            + bytes(20)
            + values({'appinfo': record})
            + b'\x08'
        )
        entries += struct.pack('<II', app_id, len(body)) + body
    entries += struct.pack('<I', 0)
    table = b''.join(name.encode() + b'\x00' for name in strings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        struct.pack('<IIq', magic, 1, 16 + len(entries))
        + entries
        + struct.pack('<I', len(strings))
        + table
    )


def gog_page(ids, pages=1):
    """One `tags=is:nsfw` GOG catalogue page."""
    return dict(
        pages=pages,
        productCount=len(ids),
        products=[
            dict(id=str(identifier), tags=[dict(name='NSFW', slug='nsfw')])
            for identifier in ids
        ],
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
                self.assertIs(
                    content.steam_item(steam_item(ids=ids), '123')['nsfw'], expected
                )

    def test_steam_linux_comes_from_store_platforms(self):
        self.assertIs(content.steam_item(steam_item(linux=True), '123')['linux'], True)
        self.assertIs(content.steam_item(steam_item(), '123')['linux'], False)
        item = steam_item()
        del item['platforms']
        self.assertIsNone(content.steam_item(item, '123')['linux'])

    def test_gog_catalogue_page_lists_tagged_products(self):
        self.assertEqual(
            content.gog_nsfw_page(gog_page(['456', 457], pages=2)), (['456', '457'], 2)
        )
        self.assertEqual(content.gog_nsfw_page(gog_page([], pages=0)), ([], 0))
        # If GOG ignored the filter, the page must not label the whole store.
        raw = gog_page(['456'])
        raw['products'].append(dict(id='457', tags=[dict(slug='mature')]))
        self.assertIsNone(content.gog_nsfw_page(raw))

    def test_malformed_missing_or_other_product_data_remains_unknown(self):
        for item in [
            None,
            {},
            steam_item(success=15),
            steam_item('124', [3]),
        ]:
            with self.subTest(item=item):
                self.assertIsNone(content.steam_item(item, '123'))
        for ids in (['3'], [True], [3, 'x'], 'adult'):
            with self.subTest(ids=ids):
                item = dict(steam_item(), content_descriptorids=ids)
                self.assertIsNone(content.steam_item(item, '123')['nsfw'])
        for raw in [
            None,
            {},
            dict(products=[]),
            dict(products=None, pages=1),
            dict(products=[None], pages=1),
            dict(products=[dict(id='x', tags=[dict(slug='nsfw')])], pages=1),
            dict(products=[dict(id='456')], pages=1),
            dict(gog_page(['456']), pages='1'),
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(content.gog_nsfw_page(raw))


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

    def test_list_is_lazy_and_one_gog_catalogue_pass_serves_every_game(self):
        game = self.game([('gog', '456')])
        other = self.game([('gog', '457')])
        initial = self.worker._with_library_indicators([game])[0]['content']
        self.assertEqual(
            initial, dict(supported=True, nsfw=None, pending=True, awaiting=True)
        )
        self.request.assert_not_called()
        self.request.side_effect = [gog_page(['456'], 2), gog_page(['999'], 2)]
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertEqual(self.request.call_count, 2)
        urls = [call.args[0] for call in self.request.call_args_list]
        self.assertTrue(all(url.startswith(backend.GOG_CATALOGUE) for url in urls))
        self.assertTrue(all('tags=is%3Ansfw' in url for url in urls))
        self.assertIn('page=2', urls[1])
        self.assertIs(self.rating(other)['nsfw'], False)
        self.assertFalse(self.rating(game)['pending'])
        self.assertEqual(self.request.call_count, 2)
        self.worker = backend.GamesBackend(
            self.root / 'games.json',
            self.root / 'data',
            env=dict(PATH=''),
            request=self.request,
            clock=lambda: self.now,
        )
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertEqual(self.request.call_count, 2)

    def test_gog_catalogue_renews_weekly_daily_on_refresh_and_secret_products_show(
        self,
    ):
        game = self.game([('gog', '456')])
        secret = self.game([('gog', '2028023186')])
        self.request.side_effect = None
        self.request.return_value = gog_page(['456'])
        self.rating(game)
        # Secret products are absent from GOG's catalogue listing.
        self.assertIs(self.rating(secret)['nsfw'], False)
        self.now += 2 * 86400
        self.rating(game)
        self.assertEqual(self.request.call_count, 1)
        self.rating(game, refresh=True)
        self.assertEqual(self.request.call_count, 2)
        self.rating(game, refresh=True)
        self.assertEqual(self.request.call_count, 2)
        self.now += backend.GOG_NSFW_TTL + 1
        self.assertTrue(self.listing(game)['pending'])
        self.rating(game)
        self.assertEqual(self.request.call_count, 3)

    def test_unreadable_gog_catalogue_keeps_the_previous_set(self):
        game = self.game([('gog', '456')])
        self.worker._cache_put('gog-nsfw:v1', dict(ids=['456']))
        self.now += backend.GOG_NSFW_TTL + 1
        untagged = gog_page(['456'])
        untagged['products'].append(dict(id='457', tags=[dict(slug='indie')]))
        self.request.side_effect = None
        self.request.return_value = untagged
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertTrue(self.worker._cooling(backend.CONTENT_PROVIDERS['gog'])[1])
        self.assertEqual(self.worker._cache_get('gog-nsfw:v1')[0], dict(ids=['456']))

    def ratings(self, games, **values):
        result = self.worker.handle(
            dict(op='content_rating', gameIds=[game['id'] for game in games], **values)
        )
        return {item['id']: item['content'] for item in result['items']}

    def test_steam_labels_for_a_batch_share_one_store_request(self):
        games = [self.game([('steam', str(app))]) for app in (123, 124, 125)]
        self.request.side_effect = None
        self.request.return_value = steam_items(
            steam_item('123', [3]), steam_item('124', [2, 5]), steam_item('125')
        )
        labels = self.ratings([*games, dict(id='missing-game')])
        self.assertEqual(
            [labels[game['id']]['nsfw'] for game in games], [True, False, False]
        )
        self.assertEqual(self.request.call_count, 1)
        url = self.request.call_args.args[0]
        self.assertTrue(url.startswith(backend.STEAM_ITEMS))
        self.assertNotIn('store.steampowered.com', url)
        # Cached labels and platforms need no further requests.
        self.ratings(games)
        self.assertEqual(self.request.call_count, 1)
        self.assertEqual(
            self.worker._cache_get('steam-platforms:v1:125')[0], dict(linux=False)
        )

    def test_steam_labels_survive_an_unreachable_store_host(self):
        game = self.game([('steam', '123')])

        def request(url, *args):
            if 'store.steampowered.com' in url:
                raise backend.GamesError('Provider is unreachable')
            return steam_items(steam_item('123', [4]))

        self.request.side_effect = request
        self.worker.library_metadata(dict(gameId=game['id']))
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertTrue(self.worker._cooling(backend.STEAM_DETAILS)[1])
        self.assertFalse(self.worker._cooling(backend.CONTENT_PROVIDERS['steam'])[1])

    def test_listing_does_not_wait_for_an_inflight_content_request(self):
        game = self.game([('gog', '456')])
        entered, release = threading.Event(), threading.Event()

        def request(*args):
            entered.set()
            release.wait(3)
            return gog_page([])

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

    def test_steam_outage_pauses_labels_across_products_and_backs_off(self):
        first = self.game([('steam', '123')])
        second = self.game([('steam', '124')])
        self.assertIsNone(self.rating(first)['nsfw'])
        self.assertIsNone(self.rating(second, refresh=True)['nsfw'])
        self.assertEqual(self.request.call_count, 1)
        self.assertEqual(
            self.worker._with_library_indicators([second])[0]['content'],
            dict(supported=True, nsfw=None, pending=False, awaiting=False),
        )
        self.now += 301
        self.rating(second)
        self.assertEqual(self.request.call_count, 2)
        # A continuing outage doubles the pause instead of probing every 5 minutes.
        self.now += 301
        self.rating(second)
        self.assertEqual(self.request.call_count, 2)
        self.now += 300
        self.request.side_effect = None
        self.request.return_value = steam_items(steam_item('124'))
        self.assertIs(self.rating(second)['nsfw'], False)
        self.assertEqual(self.request.call_count, 3)
        self.assertFalse(self.worker._cooling(backend.CONTENT_PROVIDERS['steam'])[0])

    def test_library_refresh_allows_one_new_probe_after_steam_outage(self):
        game = self.game([('steam', '123')])
        self.rating(game)
        self.worker.libraries = Mock(return_value={})
        self.worker.handle(dict(op='refresh_libraries'))
        self.request.side_effect = None
        self.request.return_value = steam_items(steam_item())
        self.assertIs(self.rating(game, refresh=True)['nsfw'], False)
        self.assertEqual(self.request.call_count, 2)

    def test_unavailable_steam_product_does_not_pause_other_games(self):
        first = self.game([('steam', '123')])
        second = self.game([('steam', '124')])
        self.request.side_effect = None
        self.request.return_value = steam_items(
            steam_item('123', success=15), steam_item('124')
        )
        labels = self.ratings([first, second])
        self.assertIsNone(labels[first['id']]['nsfw'])
        self.assertIs(labels[second['id']]['nsfw'], False)
        self.assertFalse(self.worker._cooling(backend.CONTENT_PROVIDERS['steam'])[1])
        self.now += 3600
        self.rating(first)
        self.assertEqual(self.request.call_count, 1)

    def test_any_explicit_store_label_wins_and_unknown_is_never_safe(self):
        game = self.game([('steam', '123'), ('gog', '456'), ('epic', 'EpicGame')])
        self.worker._cache_put('native-content:v1:steam:123', False)
        self.assertIsNone(
            self.worker._with_library_indicators([game])[0]['content']['nsfw']
        )
        self.worker._cache_put('gog-nsfw:v1', dict(ids=['456']))
        self.assertIs(self.rating(game)['nsfw'], True)
        self.request.assert_not_called()

    def test_failure_keeps_stale_positive_and_cools_down_without_exposing_errors(self):
        game = self.game([('gog', '456')])
        self.worker._cache_put('gog-nsfw:v1', dict(ids=['456']))
        self.now += backend.GOG_NSFW_TTL + 1
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
            self.rating(game),
            dict(supported=True, nsfw=None, pending=False, awaiting=False),
        )
        self.rating(game)
        self.assertEqual(self.request.call_count, 1)
        # Refresh clears the provider pause before re-reading labels.
        self.worker.libraries = Mock(return_value={})
        self.worker.handle(dict(op='refresh_libraries'))
        self.request.side_effect = None
        self.request.return_value = gog_page([])
        self.assertIs(self.rating(game, refresh=True)['nsfw'], False)

    def test_overrides_replace_the_classified_gog_identity(self):
        game = self.game([('gog', '456')])
        self.worker._cache_put('gog-nsfw:v1', dict(ids=['456']))
        self.assertIs(self.rating(game)['nsfw'], True)
        self.worker._save_store_match(game['id'], 'gog', '789')
        self.assertIs(self.rating(game)['nsfw'], False)
        self.request.assert_not_called()

    def test_epic_local_and_unresolved_gog_slugs_are_unsupported(self):
        for references in [[('epic', 'EpicGame')], [], [('gog', 'a_game')]]:
            game = self.game(references)
            self.assertEqual(
                self.rating(game),
                dict(supported=False, nsfw=None, pending=False, awaiting=False),
            )
        self.request.assert_not_called()

    def listing(self, game):
        return self.worker._with_library_indicators([game])[0]['content']

    def test_failed_attempt_shows_unknown_label_and_retries_after_cooldown(self):
        game = self.game([('gog', '456')])
        self.assertTrue(self.listing(game)['awaiting'])
        self.rating(game)
        self.assertEqual(
            self.listing(game),
            dict(supported=True, nsfw=None, pending=False, awaiting=False),
        )
        self.now += 301
        self.assertEqual(
            self.listing(game),
            dict(supported=True, nsfw=None, pending=True, awaiting=False),
        )

    def test_gog_outage_pauses_other_products_until_library_refresh(self):
        first = self.game([('gog', '456')])
        second = self.game([('gog', '457')])
        self.rating(first)
        self.assertEqual(
            self.listing(second),
            dict(supported=True, nsfw=None, pending=False, awaiting=False),
        )
        self.assertIsNone(self.rating(second, refresh=True)['nsfw'])
        self.assertEqual(self.request.call_count, 1)
        self.worker.libraries = Mock(return_value={})
        self.worker.handle(dict(op='refresh_libraries'))
        self.request.side_effect = None
        self.request.return_value = gog_page(['456'])
        self.assertIs(self.rating(second, refresh=True)['nsfw'], False)
        self.assertIs(self.rating(first)['nsfw'], True)
        self.assertEqual(self.request.call_count, 2)

    def test_missing_steam_products_wait_a_day_without_pausing_steam(self):
        delisted = self.game([('steam', '123')])
        self.request.side_effect = None
        self.request.return_value = steam_items()
        self.assertIsNone(self.rating(delisted)['nsfw'])
        self.assertFalse(self.worker._cooling(backend.CONTENT_PROVIDERS['steam'])[1])
        self.now += 3600
        self.rating(delisted)
        self.assertFalse(self.listing(delisted)['pending'])
        self.assertEqual(self.request.call_count, 1)
        self.now += 86400
        self.request.return_value = steam_items(steam_item())
        self.assertIs(self.rating(delisted)['nsfw'], False)
        self.assertEqual(self.request.call_count, 2)

    def test_steam_client_cache_labels_owned_apps_offline(self):
        path = self.root / '.steam/steam/appcache/appinfo.vdf'
        (self.root / '.steam/steam/steamapps').mkdir(parents=True)
        common = dict(name='Game', type='game')
        write_appinfo(
            path,
            {
                123: dict(common=dict(common, content_descriptors={'0': 3, '1': 5})),
                124: dict(common=dict(common, content_descriptors={'0': 2, '1': 5})),
                125: dict(common=common),
                126: dict(extended=dict(developer='Unknown')),
            },
        )
        games = {
            app: self.game([('steam', str(app))]) for app in (123, 124, 125, 126, 127)
        }
        self.assertIs(self.listing(games[123])['nsfw'], True)
        self.assertEqual(
            self.listing(games[124]),
            dict(supported=True, nsfw=False, pending=False, awaiting=False),
        )
        self.assertIs(self.listing(games[125])['nsfw'], False)
        self.assertIs(self.rating(games[123], refresh=True)['nsfw'], True)
        self.request.assert_not_called()
        # Apps the client has not cached, or cached without common data, use the store.
        self.assertTrue(self.listing(games[126])['awaiting'])
        self.assertTrue(self.listing(games[127])['awaiting'])
        self.request.side_effect = None
        self.request.return_value = steam_items(steam_item('127', [4]))
        self.assertIs(self.rating(games[127])['nsfw'], True)
        self.assertEqual(self.request.call_count, 1)
        # The client rewrites its cache; a changed file is read again.
        write_appinfo(
            path,
            {124: dict(common=dict(common, content_descriptors={'0': 4}))},
        )
        self.assertIs(self.listing(games[124])['nsfw'], True)

    def test_unsupported_or_corrupt_steam_client_cache_is_unknown(self):
        path = self.root / '.steam/steam/appcache/appinfo.vdf'
        (self.root / '.steam/steam/steamapps').mkdir(parents=True)
        game = self.game([('steam', '123')])
        common = dict(common=dict(type='game', content_descriptors={'0': 3}))
        write_appinfo(path, {123: common}, magic=0x07564428)
        self.assertIsNone(self.listing(game)['nsfw'])
        write_appinfo(path, {123: common})
        path.write_bytes(path.read_bytes()[:60])
        self.assertIsNone(self.listing(game)['nsfw'])
        self.request.assert_not_called()

    def test_listing_reads_labels_through_one_connection(self):
        games = [self.game([('gog', str(400 + index))]) for index in range(40)]
        opened = []
        connect = self.worker._db

        def counting():
            opened.append(True)
            return connect()

        self.worker._db = counting
        listed = self.worker._with_library_indicators(games)
        self.assertEqual(len(listed), 40)
        self.assertEqual(len(opened), 1)
        self.request.assert_not_called()

    def test_gog_slug_resolves_through_exact_heroic_product_match(self):
        game = self.game([('gog', 'same_title')])
        self.worker._library_snapshot = dict(
            gog=dict(
                items=[dict(externalId='456', title='Same title', slug='same_title')]
            )
        )
        self.request.side_effect = None
        self.request.return_value = gog_page(['456'])
        self.assertIs(self.rating(game)['nsfw'], True)
        self.assertTrue(
            self.request.call_args.args[0].startswith(backend.GOG_CATALOGUE)
        )


if __name__ == '__main__':
    unittest.main()
