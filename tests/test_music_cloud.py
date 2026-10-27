"""Nextcloud library records, account isolation, offline views and credential-free streams."""

import io
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs
from urllib.request import urlopen
from unittest.mock import MagicMock
import sys
import support

sys.path.insert(0, str(support.DESKTOP))
from integrations.subsonic import MusicError
from spaces.music.cloud import CloudLibrary, LibraryClient
from spaces.music.cloud_stream import StreamBroker


class Client:
    account_id = 'fixture-account'

    def __init__(self):
        self.calls = []
        self.offline = False

    def request(self, method, **args):
        self.calls.append((method, args))
        if self.offline:
            raise MusicError('Offline')
        song = dict(
            id='s1',
            title='Song',
            artist='Artist',
            album='Album',
            albumId='b1',
            artistId='a1',
            genre='Rock',
            duration=123,
        )
        album = dict(id='b1', name='Album', artist='Artist', artistId='a1', song=[song])
        artist = dict(
            id='a1',
            name='Artist',
            album=[dict(album, id='b' + str(i)) for i in range(5)],
        )
        return {
            'search3': {'searchResult3': {'song': [song]}},
            'getArtists': {'artists': {'index': [{'artist': [artist]}]}},
            'getAlbumList2': {'albumList2': {'album': [album]}},
            'getAlbum': {'album': dict(album, id=args.get('id', 'b1'))},
            'getArtist': {'artist': artist},
            'getStarred2': {'starred2': {'song': [dict(song, starred='date')]}},
            'getGenres': {'genres': {'genre': [{'value': 'Rock'}]}},
            'getSongsByGenre': {'songsByGenre': {'song': [song]}},
            'star': {},
            'unstar': {},
        }[method]


class CloudLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.client = Client()
        self.library = CloudLibrary(self.client, Path(self.tmp.name) / 'cache')
        self.library.index.start = lambda *args: None

    def test_library_search_categories_genres_and_starred_are_source_scoped(self):
        songs = self.library.browse({'category': 'songs', 'query': 'Song'})['items']
        self.assertEqual(songs[0]['source'], 'nextcloud')
        self.assertEqual(songs[0]['account'], self.client.account_id)
        self.assertEqual(songs[0]['albumId'], 'b1')
        self.assertEqual(songs[0]['artistIds'], ['a1'])
        self.assertEqual(
            self.client.calls[-1][1],
            dict(query='Song', artistCount=0, albumCount=0, songCount=50, songOffset=0),
        )
        self.assertEqual(
            self.library.browse({'category': 'albums'})['items'][0]['kind'], 'album'
        )
        self.assertEqual(
            self.library.browse({'category': 'artists'})['items'][0]['kind'], 'artist'
        )
        self.assertEqual(self.library.genres(), [dict(id='Rock', name='Rock')])
        self.assertTrue(self.library.browse({'starred': True})['items'][0]['starred'])
        self.assertEqual(len(self.library.browse({'genreName': 'Rock'})['items']), 1)
        self.assertEqual(self.client.calls[-1][0], 'getSongsByGenre')

    def test_artist_all_albums_and_progressive_tracks_and_album_drilldown(self):
        artist = self.library.browse({'category': 'artists'})['items'][0]
        result = self.library.artist(artist)
        self.assertEqual(len(result['albums']), 5)
        self.assertEqual(len(result['songs']), 2)
        self.assertTrue(result['songPaging']['hasMore'])
        page = self.library.artist_songs(result['songPaging'])
        self.assertEqual(page['offset'], 4)
        self.assertTrue(page['hasMore'])
        page = self.library.artist_songs(dict(artist=artist, offset=4))
        self.assertEqual(len(page['items']), 1)
        self.assertFalse(page['hasMore'])
        album = self.library.album(result['albums'][0])
        self.assertEqual(album['songs'][0]['title'], 'Song')

    def test_offline_cache_and_account_isolation_and_star_mutation(self):
        song = self.library.browse({})['items'][0]
        self.client.offline = True
        self.assertEqual(self.library.browse({'refresh': True})['items'][0], song)
        self.assertTrue(self.library.warning)
        with self.assertRaises(MusicError):
            self.library.album(dict(id='1', account='another'))
        self.client.offline = False
        self.assertTrue(self.library.favorite(song, True)['item']['starred'])
        self.assertEqual(self.client.calls[-1], ('star', {'id': 's1'}))
        self.assertEqual(list(self.library.cache.glob('*.json')), [])
        album = dict(song, kind='album')
        self.library.favorite(album, False)
        self.assertEqual(self.client.calls[-1], ('unstar', {'albumId': 's1'}))


class StreamTests(unittest.TestCase):
    def test_revocation_while_upstream_opens_cannot_start_a_late_stream(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        entered = threading.Event()
        resume = threading.Event()
        response = io.BytesIO(b'audio')
        response.headers = {'Content-Type': 'audio/flac'}
        response.status = 200

        class SlowClient:
            account_id = 'fixture'

            def open(self, *args):
                entered.set()
                resume.wait(2)
                return response

        broker = StreamBroker(SlowClient)
        self.addCleanup(broker.close)
        url = broker.url(dict(id='one', account='fixture'))
        broker.bind('fixture', url)

        def read():
            try:
                with urlopen(url, timeout=2) as reply:
                    return reply.status
            except URLError as error:
                code = error.code
                error.close()
                return code

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read)
            self.assertTrue(entered.wait(1))
            broker.release('fixture')
            resume.set()
            self.assertEqual(future.result(timeout=2), 404)
        self.assertTrue(response.closed)

    def test_gateway_forwards_range_and_auth_in_post_only_and_rejects_unknown_tickets(
        self,
    ):
        response = MagicMock()
        response.status = 206
        response.headers = {
            'Content-Type': 'audio/flac',
            'Content-Length': '5',
            'Content-Range': 'bytes 0-4/5',
        }
        response.read.side_effect = [b'audio', b'']
        opener = MagicMock()
        opener.open.return_value = response
        client = LibraryClient(
            dict(url='https://cloud.example/nc/', username='alice'),
            key='fixture-secret',
            opener=opener,
        )
        broker = StreamBroker(lambda: client)
        self.addCleanup(broker.close)
        url = broker.url(dict(id='s1', account=client.account_id))
        self.assertNotIn('fixture-secret', url)
        self.assertNotIn('cloud.example', url)
        from urllib.request import Request

        with urlopen(Request(url, headers={'Range': 'bytes=0-4'}), timeout=2) as reply:
            self.assertEqual(reply.status, 206)
            self.assertEqual(reply.read(), b'audio')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertNotIn('fixture-secret', request.full_url)
        self.assertEqual(parse_qs(request.data.decode())['p'], ['fixture-secret'])
        self.assertEqual(request.get_header('Range'), 'bytes=0-4')
        with self.assertRaises(URLError) as failure:
            urlopen(url.rsplit('/', 1)[0] + '/wrong', timeout=2)
        failure.exception.close()
        with self.assertRaises(MusicError):
            broker.url(dict(id='s1', account='another'))
        broker.bind('fixture-ipc', url)
        broker.release('fixture-ipc')
        with self.assertRaises(URLError) as failure:
            urlopen(url, timeout=1)
        failure.exception.close()
        broker.close()
        with self.assertRaises(URLError):
            urlopen(url, timeout=1)
